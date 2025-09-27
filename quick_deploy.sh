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
git fetch origin && \
git pull origin main --no-edit && \
git push heroku main && \
echo "✅ Готово! Приложение обновлено на https://panenka-live-ae2234475edc.herokuapp.com/"
