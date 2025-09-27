#!/bin/bash

# Супер быстрый деплой одной командой
# Использование: ./quick_deploy.sh [commit-message]

set -e

echo "🚀 Супер быстрый деплой"
echo "======================"

# Коммитим изменения если есть
if [[ -n $(git status --porcelain) ]]; then
    echo "📝 Коммитим изменения..."
    git add .
    git commit -m "${1:-Quick deploy $(date '+%Y-%m-%d %H:%M:%S')}"
fi

# Fetch + Pull + Deploy одной цепочкой
echo "⚡ Выполняем: fetch → pull → deploy..."
git fetch origin
git pull origin main --no-edit

if git push heroku main; then
    echo "✅ Готово! Приложение обновлено на https://panenka-live-ae2234475edc.herokuapp.com/"
else
    echo "❌ Не удалось запушить изменения в Heroku"

    if git remote get-url heroku >/dev/null 2>&1; then
        if git fetch heroku main >/dev/null 2>&1; then
            if git merge-base --is-ancestor heroku/main HEAD; then
                echo "ℹ️  Локальная ветка отстаёт от Heroku. Сначала обновите её:"
                echo "   git fetch heroku"
                echo "   git merge heroku/main"
            elif git merge-base --is-ancestor HEAD heroku/main; then
                echo "ℹ️  Heroku содержит коммиты, которых нет локально."
                echo "   Если это ожидаемо, можно перезаписать Heroku:"
                echo "   git push heroku main --force-with-lease"
            else
                echo "ℹ️  Ветки разошлись. Сравните изменения перед деплоем:"
                echo "   git log --oneline heroku/main..HEAD"
                echo "   git log --oneline HEAD..heroku/main"
            fi
        else
            echo "⚠️  Не удалось получить состояние ветки Heroku"
        fi
    else
        echo "⚠️  Удалённый репозиторий 'heroku' не настроен"
    fi

    exit 1
fi
