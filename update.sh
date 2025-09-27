#!/bin/bash

# Быстрое обновление из GitHub
# Использование: ./update.sh

set -e  # Остановить при ошибке

BRANCH="main"

echo "⬇️  Быстрое обновление из GitHub"
echo "==============================="

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
if [[ -n $(git status --porcelain) ]]; then
    echo "⚠️  Найдены незакоммиченные изменения:"
    git status --short
    echo ""
    echo "🤔 Что делать с незакоммиченными изменениями?"
    echo "1) Сохранить в stash (рекомендуется)"
    echo "2) Закоммитить сейчас"
    echo "3) Отменить изменения (ОСТОРОЖНО!)"
    echo "4) Прервать обновление"
    echo ""
    read -p "Выберите опцию (1-4): " choice
    
    case $choice in
        1)
            echo "📦 Сохраняем изменения в stash..."
            git stash push -m "Auto stash before update $(date '+%Y-%m-%d %H:%M:%S')"
            ;;
        2)
            read -p "💬 Введите сообщение коммита: " commit_message
            if [ -z "$commit_message" ]; then
                commit_message="WIP: Auto commit before update $(date '+%Y-%m-%d %H:%M:%S')"
            fi
            echo "📝 Коммитим изменения..."
            git add .
            git commit -m "$commit_message"
            ;;
        3)
            echo "⚠️  Отменяем все изменения..."
            read -p "Вы уверены? Это действие нельзя отменить! (y/N): " confirm
            if [[ $confirm =~ ^[Yy]$ ]]; then
                git reset --hard HEAD
                git clean -fd
                echo "✅ Изменения отменены"
            else
                echo "❌ Операция прервана"
                exit 1
            fi
            ;;
        4)
            echo "❌ Обновление прервано"
            exit 1
            ;;
        *)
            echo "❌ Неверный выбор, прерываем"
            exit 1
            ;;
    esac
else
    echo "✅ Рабочая директория чистая"
fi

# Получить информацию о текущем состоянии
echo "📊 Текущее состояние:"
echo "   Текущая ветка: $(git branch --show-current)"
echo "   Последний коммит: $(git log -1 --oneline)"

# Стянуть изменения из GitHub
echo ""
echo "⬇️  Стягиваем изменения из GitHub..."
git fetch origin

# Проверить, есть ли новые изменения
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/$BRANCH)

if [ "$LOCAL" = "$REMOTE" ]; then
    echo "✅ Локальная ветка уже актуальна"
    echo "   Нет новых изменений для загрузки"
else
    echo "📥 Найдены новые изменения:"
    echo ""
    git log --oneline HEAD..origin/$BRANCH
    echo ""
    
    # Выполнить merge
    echo "🔄 Выполняем merge..."
    if git pull origin $BRANCH --no-edit; then
        echo "✅ Обновление успешно завершено!"
        echo ""
        echo "📊 Новое состояние:"
        echo "   Последний коммит: $(git log -1 --oneline)"
        
        # Предложить восстановить stash если он был создан
        if git stash list | grep -q "Auto stash before update"; then
            echo ""
            echo "📦 Найден автоматический stash"
            read -p "Восстановить сохраненные изменения? (y/N): " restore_stash
            if [[ $restore_stash =~ ^[Yy]$ ]]; then
                echo "📤 Восстанавливаем изменения из stash..."
                git stash pop
                echo "✅ Изменения восстановлены"
            fi
        fi
    else
        echo "❌ Ошибка при выполнении merge"
        echo "🔧 Возможно, есть конфликты. Разрешите их вручную:"
        echo "   git status"
        echo "   git mergetool  # или отредактируйте файлы вручную"
        echo "   git commit"
        exit 1
    fi
fi

echo ""
echo "🎉 Готово! Репозиторий обновлен до последней версии"
