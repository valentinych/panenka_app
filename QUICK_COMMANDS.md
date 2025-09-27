# 🚀 Быстрые команды для разработки

## 📋 Основные скрипты

### 1. Быстрое обновление из GitHub
```bash
./update.sh
```
**Что делает:**
- Останавливает локальное приложение
- Проверяет незакоммиченные изменения
- Предлагает сохранить их в stash или закоммитить
- Стягивает последние изменения из GitHub
- Выполняет merge
- Предлагает восстановить stash

### 2. Быстрый деплой в Heroku
```bash
./deploy.sh "Описание изменений"
```
**Что делает:**
- Останавливает локальное приложение
- Коммитит незакоммиченные изменения
- Стягивает изменения из GitHub
- Деплоит в Heroku
- Показывает ссылки для мониторинга

## ⚡ Git aliases (уже настроены)

### Основные команды
```bash
git st          # git status
git co main     # git checkout main
git br          # git branch
git ci -m "msg" # git commit -m "msg"
```

### Продвинутые команды
```bash
git sync                    # Быстрая синхронизация с GitHub
git deploy                  # Быстрый деплой в Heroku
git quickcommit "message"   # Быстрый add + commit
git quickcommit             # Автоматическое сообщение с датой
```

## 🔄 Типичные рабочие процессы

### Обновиться и задеплоить
```bash
./update.sh && ./deploy.sh "Updated from GitHub"
```

### Быстро закоммитить и задеплоить
```bash
git quickcommit "Fix bug" && git deploy
```

### Синхронизация с GitHub одной командой
```bash
git sync
```

### Полный цикл: обновление → изменения → деплой
```bash
# 1. Обновиться из GitHub
./update.sh

# 2. Сделать изменения в коде
# ... редактируете файлы ...

# 3. Быстро задеплоить
./deploy.sh "My changes description"
```

## 🛠️ Heroku команды

### Просмотр логов
```bash
heroku logs --tail -a panenka-live
```

### Статус приложения
```bash
heroku ps -a panenka-live
```

### Переменные окружения
```bash
heroku config -a panenka-live
```

### Перезапуск приложения
```bash
heroku restart -a panenka-live
```

### Открыть приложение в браузере
```bash
heroku open -a panenka-live
```

## 🐛 Решение проблем

### Если git pull выдает ошибки
```bash
# Вариант 1: Использовать наш скрипт
./update.sh

# Вариант 2: Ручное решение
git stash                    # Сохранить изменения
git pull origin main         # Обновиться
git stash pop               # Восстановить изменения
```

### Если есть конфликты merge
```bash
git status                  # Посмотреть конфликтующие файлы
# Отредактировать файлы вручную, убрать маркеры <<<< ==== >>>>
git add .                   # Добавить решенные конфликты
git commit                  # Завершить merge
```

### Если деплой в Heroku не работает
```bash
# Проверить статус
heroku ps -a panenka-live

# Посмотреть логи
heroku logs --tail -a panenka-live

# Перезапустить
heroku restart -a panenka-live
```

### Откатить к предыдущей версии
```bash
# Посмотреть историю релизов
heroku releases -a panenka-live

# Откатиться к предыдущему релизу
heroku rollback -a panenka-live
```

## 📱 Мобильные команды (для быстрого набора)

Добавьте эти алиасы в ваш `.bashrc` или `.zshrc`:

```bash
# Добавить в ~/.bashrc или ~/.zshrc
alias gst='git st'
alias gco='git co'
alias gci='git quickcommit'
alias gsync='git sync'
alias gdeploy='git deploy'
alias update='./update.sh'
alias deploy='./deploy.sh'
alias hlogs='heroku logs --tail -a panenka-live'
alias hps='heroku ps -a panenka-live'
alias hconfig='heroku config -a panenka-live'
```

После добавления выполните:
```bash
source ~/.bashrc  # или source ~/.zshrc
```

## 🎯 Примеры использования

### Ежедневная работа
```bash
# Утром - обновиться
update

# В течение дня - быстрые коммиты
gci "Add new feature"
gci "Fix styling"

# Вечером - деплой
deploy "Daily updates"
```

### Срочное исправление
```bash
# Быстро исправить и задеплоить
gci "Hotfix: critical bug" && gdeploy
```

### Проверка статуса
```bash
gst              # Локальный статус
hps              # Статус на Heroku
hlogs            # Логи приложения
```
