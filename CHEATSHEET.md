# 🚀 Шпаргалка быстрых команд

## ⚡ Самые частые команды

```bash
# 🔥 СУПЕР БЫСТРЫЙ ДЕПЛОЙ (fetch + pull + deploy)
./quick_deploy.sh "сообщение"
# или
git fulldeploy
# или  
git smartdeploy "сообщение"

# Обновиться из GitHub
./update.sh

# Быстрый деплой
./deploy.sh "описание изменений"

# Статус git
git st

# Быстрый коммит
git quickcommit "сообщение"

# Синхронизация с GitHub
git sync

# Деплой в Heroku
git deploy
```

## 🔄 Типичные сценарии

### Утренняя синхронизация
```bash
./update.sh
```

### Быстрые изменения и деплой
```bash
git quickcommit "fix bug" && git deploy
```

### Полный цикл
```bash
./update.sh                    # Обновиться
# ... делаем изменения ...
./deploy.sh "my changes"       # Деплоим
```

## 🛠️ Heroku мониторинг

```bash
heroku logs --tail -a panenka-live    # Логи
heroku ps -a panenka-live             # Статус
heroku restart -a panenka-live        # Перезапуск
```

## 🆘 Если что-то сломалось

```bash
git st                         # Проверить статус
heroku logs -a panenka-live    # Посмотреть ошибки
heroku rollback -a panenka-live # Откатиться
```
