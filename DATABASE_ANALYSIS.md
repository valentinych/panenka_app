# 📊 Анализ базы данных и стоимости на Heroku

## 🗄️ Структура базы данных

### SQLite база данных (локальная)
Приложение использует **SQLite** для хранения данных о buzzer-лобби:

#### Таблица `lobbies`
```sql
CREATE TABLE lobbies (
    code TEXT PRIMARY KEY,           -- Код лобби (4 символа, например "ABCD")
    host_id TEXT NOT NULL,          -- UUID хоста
    host_name TEXT NOT NULL,        -- Имя хоста
    host_token TEXT NOT NULL,       -- Токен безопасности хоста
    created_at REAL NOT NULL,       -- Время создания (Unix timestamp)
    updated_at REAL NOT NULL,       -- Время последнего обновления
    host_seen REAL NOT NULL,        -- Время последней активности хоста
    locked INTEGER NOT NULL,        -- Заблокировано ли лобби (0/1)
    buzz_order TEXT NOT NULL        -- JSON массив порядка нажатий buzzer
)
```

#### Таблица `players`
```sql
CREATE TABLE players (
    id TEXT PRIMARY KEY,            -- UUID игрока
    lobby_code TEXT NOT NULL,       -- Код лобби (внешний ключ)
    name TEXT NOT NULL,             -- Имя игрока
    joined_at REAL NOT NULL,        -- Время присоединения
    last_seen REAL NOT NULL,        -- Время последней активности
    buzzed_at REAL,                 -- Время нажатия buzzer (может быть NULL)
    FOREIGN KEY(lobby_code) REFERENCES lobbies(code) ON DELETE CASCADE
)
```

### 📁 Расположение файла базы данных
- **Локально**: `app/lobbies.sqlite3`
- **На Heroku**: Ephemeral filesystem (временная файловая система)
- **Переменная окружения**: `PANENKA_LOBBY_DB` (опционально)

## 🔄 Как наполняются данные

### 1. Создание лобби
```python
lobby = {
    "code": "ABCD",                    # Генерируется случайно
    "host_id": str(uuid4()),           # UUID хоста
    "host_name": "Имя пользователя",   # Из session
    "host_token": secrets.token_urlsafe(16),
    "created_at": time.time(),
    "updated_at": time.time(),
    "host_seen": time.time(),
    "locked": False,
    "players": {},
    "buzz_order": []
}
```

### 2. Присоединение игроков
```python
player = {
    "id": str(uuid4()),
    "name": "Имя игрока",
    "joined_at": time.time(),
    "last_seen": time.time(),
    "buzzed_at": None  # Устанавливается при нажатии buzzer
}
```

### 3. Автоматическая очистка
- **Лобби истекают через**: 60 минут (3600 секунд)
- **Игроки истекают через**: 3 минуты (180 секунд) неактивности
- **Очистка происходит**: При каждом запросе к API

## 💰 Стоимость на Heroku

### 🆓 Текущая конфигурация (БЕСПЛАТНО)
```
Dyno: Eco (бесплатный)
- 1000 часов в месяц бесплатно
- Засыпает после 30 минут неактивности
- Просыпается при первом запросе (~10-30 секунд)
- Ограничение: 512 MB RAM

База данных: SQLite (файловая система)
- БЕСПЛАТНО
- НО: Данные теряются при перезапуске dyno!
```

### ⚠️ ПРОБЛЕМА: Потеря данных
**SQLite на Heroku НЕ персистентна!**
- При каждом деплое данные теряются
- При перезапуске dyno данные теряются
- При засыпании/пробуждении данные могут теряться

## 🔧 Рекомендации по улучшению

### 1. 💾 Персистентная база данных

#### Heroku Postgres (рекомендуется)
```bash
# Добавить бесплатный план Postgres
heroku addons:create heroku-postgresql:essential-0 -a panenka-live

# Стоимость: $5/месяц
# Включает: 1GB хранилища, 20 подключений
```

#### Heroku Redis (для временных данных)
```bash
# Для кэширования и временных данных лобби
heroku addons:create heroku-redis:mini -a panenka-live

# Стоимость: $3/месяц
# Включает: 25MB памяти
```

### 2. 🚀 Улучшение производительности

#### Basic Dyno (рекомендуется для продакшена)
```bash
heroku ps:scale web=1:basic -a panenka-live

# Стоимость: $7/месяц
# Преимущества:
# - Не засыпает
# - 512 MB RAM
# - Лучшая производительность
```

#### Standard-1X Dyno (для высокой нагрузки)
```bash
heroku ps:scale web=1:standard-1x -a panenka-live

# Стоимость: $25/месяц
# Преимущества:
# - 512 MB RAM
# - Автоскейлинг
# - Метрики производительности
```

## 📈 Сценарии стоимости

### 🆓 Минимальная конфигурация (текущая)
```
Eco Dyno: $0/месяц
SQLite: $0/месяц
ИТОГО: $0/месяц

⚠️ Ограничения:
- Потеря данных при перезапуске
- Засыпание через 30 минут
- Медленный старт после сна
```

### 💡 Рекомендуемая конфигурация
```
Basic Dyno: $7/месяц
Heroku Postgres Essential: $5/месяц
ИТОГО: $12/месяц

✅ Преимущества:
- Персистентные данные
- Не засыпает
- Стабильная работа
```

### 🚀 Продакшен конфигурация
```
Standard-1X Dyno: $25/месяц
Heroku Postgres Standard: $50/месяц
Heroku Redis Mini: $3/месяц
ИТОГО: $78/месяц

✅ Преимущества:
- Высокая производительность
- Автоскейлинг
- Мониторинг
- Бэкапы базы данных
```

## 🛠️ Миграция на Postgres

### 1. Установка аддона
```bash
heroku addons:create heroku-postgresql:essential-0 -a panenka-live
```

### 2. Обновление кода
Нужно будет:
- Добавить `psycopg2` в `requirements.txt`
- Изменить `lobby_store.py` для поддержки PostgreSQL
- Обновить SQL запросы (PostgreSQL синтаксис)

### 3. Переменные окружения
```bash
# Heroku автоматически установит DATABASE_URL
heroku config -a panenka-live | grep DATABASE_URL
```

## 📊 Мониторинг использования

### Текущее использование
```bash
# Проверить использование dyno часов
heroku ps -a panenka-live

# Проверить логи
heroku logs --tail -a panenka-live

# Проверить метрики (если доступны)
heroku logs --ps web -a panenka-live
```

### Рекомендуемые метрики
- Количество активных лобби
- Количество игроков онлайн
- Частота создания/удаления лобби
- Время отклика API

## 🎯 Выводы

### Для разработки/тестирования
- **Текущая конфигурация подходит** (Eco dyno + SQLite)
- **Стоимость**: $0/месяц
- **Ограничение**: Потеря данных при перезапуске

### Для продакшена
- **Рекомендуется**: Basic dyno + Postgres Essential
- **Стоимость**: $12/месяц
- **Преимущества**: Стабильность + персистентность данных

### Для высокой нагрузки
- **Рекомендуется**: Standard dyno + Postgres Standard + Redis
- **Стоимость**: $78/месяц
- **Преимущества**: Максимальная производительность
