#!/bin/bash

# Быстрый деплой в Heroku
# Использование: ./deploy.sh [commit-message]

set -e  # Остановить при ошибке

APP_NAME="panenka-live"
BRANCH="main"

echo "🚀 Быстрый деплой в Heroku"
echo "=========================="

# Проверить, что мы в git репозитории
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "❌ Ошибка: Не git репозиторий"
    exit 1
fi

# Остановить локальное приложение если запущено
echo "🛑 Останавливаем локальное приложение..."
pkill -f "python run.py" 2>/dev/null || echo "   Локальное приложение не запущено"

# Проверить статус git
echo "📋 Проверяем статус git..."
git status --porcelain

# Если есть незакоммиченные изменения
if [[ -n $(git status --porcelain) ]]; then
    echo "📝 Найдены незакоммиченные изменения"
    
    # Получить сообщение коммита
    if [ -z "$1" ]; then
        echo "💬 Введите сообщение коммита (или нажмите Enter для автоматического):"
        read -r commit_message
        if [ -z "$commit_message" ]; then
            commit_message="Auto deploy $(date '+%Y-%m-%d %H:%M:%S')"
        fi
    else
        commit_message="$1"
    fi
    
    echo "   Коммитим изменения: '$commit_message'"
    git add .
    git commit -m "$commit_message"
else
    echo "   Нет незакоммиченных изменений"
fi

# Стянуть последние изменения из GitHub
echo "⬇️  Стягиваем изменения из GitHub..."
if git fetch origin; then
    # Проверить, есть ли новые коммиты
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/$BRANCH)
    
    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "   Найдены новые изменения, выполняем merge..."
        git pull origin $BRANCH --no-edit
    else
        echo "   Локальная ветка актуальна"
    fi
else
    echo "⚠️  Не удалось подключиться к GitHub, продолжаем с локальными изменениями"
fi

# Деплой в Heroku
echo "🚀 Деплоим в Heroku ($APP_NAME)..."
if git push heroku $BRANCH; then
    echo "✅ Деплой успешно завершен!"
    echo ""
    echo "🌐 Приложение доступно по адресу:"
    echo "   https://panenka-live-ae2234475edc.herokuapp.com/"
    echo ""
    echo "📊 Для просмотра логов используйте:"
    echo "   heroku logs --tail -a $APP_NAME"
    echo ""
    echo "⚙️  Для просмотра статуса приложения:"
    echo "   heroku ps -a $APP_NAME"
else
    echo "❌ Ошибка деплоя в Heroku"

    if git remote get-url heroku >/dev/null 2>&1; then
        if git fetch heroku $BRANCH >/dev/null 2>&1; then
            if git merge-base --is-ancestor heroku/$BRANCH HEAD; then
                echo "ℹ️  Локальная ветка отстаёт от Heroku. Сначала обновите её:"
                echo "   git fetch heroku"
                echo "   git merge heroku/$BRANCH"
            elif git merge-base --is-ancestor HEAD heroku/$BRANCH; then
                echo "ℹ️  Heroku содержит коммиты, которых нет локально."
                echo "   Если всё верно, можно перезаписать Heroku:"
                echo "   git push heroku $BRANCH --force-with-lease"
            else
                echo "ℹ️  Ветки разошлись. Сравните изменения перед деплоем:"
                echo "   git log --oneline heroku/$BRANCH..HEAD"
                echo "   git log --oneline HEAD..heroku/$BRANCH"
            fi
        else
            echo "⚠️  Не удалось получить состояние ветки Heroku"
        fi
    else
        echo "⚠️  Удалённый репозиторий 'heroku' не настроен"
    fi

    exit 1
fi
