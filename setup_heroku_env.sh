#!/bin/bash

# Скрипт для настройки переменных окружения Heroku приложения
# Использование: ./setup_heroku_env.sh YOUR_APP_NAME

if [ $# -eq 0 ]; then
    echo "Ошибка: Не указано имя Heroku приложения"
    echo "Использование: $0 YOUR_APP_NAME"
    echo "Пример: $0 panenka-live"
    exit 1
fi

APP_NAME=$1

echo "Настройка переменных окружения для Heroku приложения: $APP_NAME"
echo "=================================================="

# AWS учетные данные
echo "Устанавливаем AWS учетные данные..."
heroku config:set AWS_ACCESS_KEY_ID=YOUR_AWS_ACCESS_KEY_ID -a $APP_NAME
heroku config:set AWS_SECRET_ACCESS_KEY=YOUR_AWS_SECRET_ACCESS_KEY -a $APP_NAME
heroku config:set AWS_DEFAULT_REGION=us-east-1 -a $APP_NAME

# S3 конфигурация для auth.json
echo "Устанавливаем S3 конфигурацию..."
heroku config:set AUTH_JSON_S3_BUCKET=val-draft-storage -a $APP_NAME
heroku config:set AUTH_JSON_S3_KEY=auth.json -a $APP_NAME

echo "=================================================="
echo "Переменные окружения установлены!"
echo ""
echo "Проверьте настройки:"
echo "heroku config -a $APP_NAME"
echo ""
echo "Для деплоя выполните:"
echo "git push heroku main"
echo ""
echo "Для проверки логов:"
echo "heroku logs --tail -a $APP_NAME"
