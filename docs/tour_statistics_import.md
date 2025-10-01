# Импорт турнирной статистики buzzer-игр

Этот документ описывает, как полностью очистить имеющиеся данные боёв, развернуть новую структуру БД и загрузить в неё результаты с листа `S01E02` Google-таблицы `https://docs.google.com/spreadsheets/d/1v7bkGlxtv_STTbqXIqx1oWwbKLguAvAMzRFWlBnKRNk/edit?usp=sharing`. Методика подходит для всех остальных листов сезона.

## 1. Цели и принципы
- Хранить в БД детализированную статистику боёв с точностью до каждого вопроса и игрока.
- Обеспечить повторяемый импорт из Google Sheets и внешних файлов.
- Нормализовать ФИО игроков на основе листа `PlayerList`, чтобы исключить дубликаты и опечатки.
- Упорядочить бои по коду `SxxEyyFzz`, где `xx` — сезон, `yy` — тур, `zz` — порядковый номер боя.

## 2. Очистка старых данных
Перед внедрением новой схемы нужно удалить все записи о боях и связанных сущностях, чтобы не мешали исторические данные. Рекомендуется выполнить транзакцию:
```sql
BEGIN;
TRUNCATE TABLE question_results CASCADE;
TRUNCATE TABLE questions CASCADE;
TRUNCATE TABLE fight_participants CASCADE;
TRUNCATE TABLE fights CASCADE;
TRUNCATE TABLE tours CASCADE;
TRUNCATE TABLE seasons CASCADE;
TRUNCATE TABLE imports CASCADE;
TRUNCATE TABLE players CASCADE;
TRUNCATE TABLE player_aliases CASCADE;
COMMIT;
```
> Примечание. Если таблиц ещё нет, команды `TRUNCATE` пропускаются.

## 3. Новая схема данных

### 3.1. Сущности и связи
| Таблица | Назначение |
| --- | --- |
| `seasons` | Сезоны (S01, S02 и т.д.). |
| `tours` | Тур внутри сезона. |
| `fights` | Отдельный бой (`fight_code` вида `S01E02F07`). |
| `imports` | Журнал импортов из листов/файлов. |
| `players` | Нормализованные ФИО игроков. |
| `player_aliases` | Все варианты написания ФИО (из PlayerList, переводов, опечаток). |
| `fight_participants` | Связка боя и игрока с итоговым счётом и позицией. |
| `themes` | Названия тем (например, «Цветная», «Бартез», «Блан»). |
| `questions` | Вопрос внутри боя c темой, номиналом и порядком. |
| `question_results` | Значение для конкретного игрока по вопросу (+/- номинал). |

### 3.2. SQL-описание
```sql
CREATE TABLE seasons (
    id SERIAL PRIMARY KEY,
    season_number SMALLINT NOT NULL UNIQUE,
    code TEXT GENERATED ALWAYS AS (format('S%02s', season_number)) STORED
);

CREATE TABLE tours (
    id SERIAL PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    tour_number SMALLINT NOT NULL,
    code TEXT GENERATED ALWAYS AS (format('%sE%02s', (SELECT code FROM seasons WHERE seasons.id = season_id), tour_number)) STORED,
    UNIQUE (season_id, tour_number)
);

CREATE TABLE imports (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,               -- "google_sheets"
    source_identifier TEXT NOT NULL,    -- URL или ID документа
    sheet_name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'pending',
    message TEXT
);

CREATE TABLE fights (
    id SERIAL PRIMARY KEY,
    tour_id INTEGER NOT NULL REFERENCES tours(id) ON DELETE CASCADE,
    fight_number SMALLINT NOT NULL,
    fight_code TEXT NOT NULL UNIQUE,
    sheet_column_range TEXT NOT NULL,   -- диапазон столбцов, использованных в листе
    question_row_start SMALLINT NOT NULL,
    question_row_end SMALLINT NOT NULL,
    import_id INTEGER NOT NULL REFERENCES imports(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tour_id, fight_number)
);

CREATE TABLE players (
    id SERIAL PRIMARY KEY,
    full_name TEXT NOT NULL UNIQUE,
    normalized_name TEXT NOT NULL UNIQUE,
    gender TEXT,
    city TEXT
);

CREATE TABLE player_aliases (
    id SERIAL PRIMARY KEY,
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    UNIQUE (player_id, normalized_alias),
    UNIQUE (alias)
);

CREATE TABLE themes (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL UNIQUE,
    external_code TEXT
);

CREATE TABLE fight_participants (
    id SERIAL PRIMARY KEY,
    fight_id INTEGER NOT NULL REFERENCES fights(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    seat_index SMALLINT NOT NULL,
    total_score INTEGER NOT NULL,
    finishing_place SMALLINT,
    UNIQUE (fight_id, player_id),
    UNIQUE (fight_id, seat_index)
);

CREATE TABLE questions (
    id SERIAL PRIMARY KEY,
    fight_id INTEGER NOT NULL REFERENCES fights(id) ON DELETE CASCADE,
    theme_id INTEGER NOT NULL REFERENCES themes(id),
    question_order SMALLINT NOT NULL,
    nominal SMALLINT NOT NULL,
    sheet_row SMALLINT NOT NULL,
    UNIQUE (fight_id, question_order)
);

CREATE TABLE question_results (
    id SERIAL PRIMARY KEY,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    participant_id INTEGER NOT NULL REFERENCES fight_participants(id) ON DELETE CASCADE,
    delta INTEGER NOT NULL,
    is_correct BOOLEAN NOT NULL,
    UNIQUE (question_id, participant_id)
);
```

### 3.3. Индексы и проверки
- Добавить индекс `idx_player_aliases_normalized` по `normalized_alias`.
- Добавить индекс `idx_question_results_participant` по `participant_id`.
- Проверка, что сумма `question_results.delta` по каждому участнику совпадает с `fight_participants.total_score` (realized триггером).

## 4. Подготовка справочников
1. **Темы**. Загрузить из существующей справочной таблицы тем. Каждой теме назначить `external_code`, если в другом листе уже есть идентификаторы.
2. **PlayerList**. Экспортировать лист `PlayerList` в CSV (`PlayerList!A1:D`). Для каждой строки:
   - Сформировать `normalized_name`: привести к нижнему регистру, удалить лишние пробелы, заменить `ё` → `е`.
   - Создать запись в `players` с официальным написанием (колонка `FullName`) и дополнительными атрибутами (город, пол, если есть).
   - Добавить запись в `player_aliases` для самого официального имени.
   - Для каждой альтернативной записи (например, латиница, «Ефименко Александр») добавлять alias в `player_aliases`.

## 5. Алгоритм импорта листа `S01E02`

### 5.1. Чтение листа
1. Зарегистрировать импорт:
   ```sql
   INSERT INTO imports (source, source_identifier, sheet_name, status)
   VALUES ('google_sheets', '1v7bkGlxtv_STTbqXIqx1oWwbKLguAvAMzRFWlBnKRNk', 'S01E02', 'pending')
   RETURNING id;
   ```
2. Использовать Google Sheets API `spreadsheets.values.get` с диапазоном `S01E02!A1:ZZ200`.
3. Представить данные как матрицу `rows[row_index][column_index]`.

### 5.2. Деление на бои
- В первой строке ищем ячейки с шаблоном `S\d{2}E\d{2}F\d{2}` — это заголовки боёв.
- Пустой столбец (все значения пустые) служит разделителем между боями.
- Для каждого блока фиксируем диапазон столбцов, например `B:G`.

### 5.3. Извлечение структуры боя
1. **Заголовок и метаданные**
   - Строка 1: `fight_code`. Разобрать на `season_number`, `tour_number`, `fight_number`.
   - Найти или создать `seasons` и `tours`, затем вставить запись в `fights`, указав диапазон столбцов и id импорта.
2. **Игроки**
   - Строка 2 (под заголовком) содержит ФИО участников. Их может быть 2–5.
   - Для каждого имени применить функцию нормализации (lowercase, trim, `ё` → `е`).
   - Найти игрока через `player_aliases.normalized_alias`. Если не найден, логировать ошибку для ручного разбора.
   - Вставить записи в `fight_participants` по порядку столбцов, сохраняя `seat_index`.
3. **Итоговые суммы**
   - Строка 3 под каждым игроком — `total_score`. Использовать как `fight_participants.total_score`.
4. **Темы и вопросы**
   - Строка 2 слева от имён (обычно несколько первых колонок) содержит названия тем по вертикали. В листе `S01E02` темы повторяются каждые пять строк (номиналы 10–50). Для каждого вопроса считываем тему из заголовка соответствующей колонки блока.
   - Колонка `F` листа содержит эталон номинала (`10`, `20`, `30`, `40`, `50`). Считаем строки, где `column_F` равно одному из этих значений. Эти строки определяют вопросы.
   - Для каждого вопроса фиксируем `question_order` (по порядку появления) и `nominal` (значение из колонки `F`).
   - Создаём запись в `questions` с `sheet_row` = индекс строки.
5. **Результаты по игрокам**
   - В ячейках пересечения `question_row` и столбца игрока содержится дельта (`+10`, `-20`, `0`).
   - Для каждого значения:
     - `delta = int(cell)`.
     - `is_correct = delta > 0`.
     - Создать запись в `question_results`.
6. **Контроль целостности**
   - Сумма `delta` по каждому игроку должна равняться `total_score`.
   - Количество вопросов кратно числу тем (обычно 5 номиналов на тему).

### 5.4. Завершение импорта
- После успешной вставки всех данных обновить `imports.status = 'success'` и `finished_at = now()`.
- При ошибке откатить транзакцию и записать `imports.status = 'failed'` с текстом ошибки.

## 6. Пример: бой `S01E02F01`

1. **Исходные данные**
   - Заголовок в строке 1: `S01E02F01`.
   - В строке 2 четыре игрока: `Александр Ефименко`, `Мария Тимохова`, `Денис Лавренюк`, `Евгений Капитульский`.
   - В строке 3 под именами — итоговые суммы (например, `70`, `-10`, `40`, `0`).
   - Колонка `F` в строках 5–9 содержит номиналы `10`, `20`, `30`, `40`, `50`.
   - Темы (рядом с номиналами) — `Цветная`, `Бартез`, `Блан`, …
2. **Нормализация имён**
   - Для каждого ФИО вычислить `normalized_alias`: `александр ефименко`, `мария тимохова`, `денис лавренюк`, `евгений капитульский`.
   - Найти соответствия в `player_aliases`. Если в листе была опечатка (например, «Ария Тимохова»), мы всё равно найдём игрока, так как alias «мария тимохова» присутствует в словаре.
3. **Создание боя**
   - `season_number = 1`, `tour_number = 2`, `fight_number = 1`.
   - Добавить записи в `seasons`, `tours` (если отсутствуют) и `fights` (`fight_code = 'S01E02F01'`, диапазон, например, `B:G`).
4. **Участники**
   - Вставить четыре строки в `fight_participants` с `seat_index` 1–4 и итоговыми суммами из строки 3.
5. **Вопросы**
   - Обнаружить пять строк с номиналами. Для каждой:
     - Найти тему в соответствующем столбце (например, «Цветная» для номинала 10).
     - Создать запись в `questions` с `question_order` 1–5.
6. **Результаты**
   - Для каждого вопроса собрать дельты, например:
     - Вопрос 1 (`nominal = 10`): `+10`, `0`, `-10`, `0` → создаём четыре записи в `question_results`.
     - Повторяем для всех номиналов.
7. **Валидация**
   - Сумма дельт каждого участника должна давать итоговую сумму (например, `+10 + 20 + 40 = 70`).
   - Если сумма не сходится, логируем ошибку и останавливаем импорт.
8. **Повтор для остальных боёв**
   - Двигаемся вправо к следующему заголовку (`S01E02F02`, `S01E02F03`, …) и повторяем шаги.

## 7. Автоматизация
- Реализовать Python-скрипт `scripts/import_fights.py`, который принимает аргументы `--sheet-id`, `--sheet-name`, `--range` и выполняет описанные шаги.
- Скрипт должен вести журнал (`imports`) и поддерживать режим dry-run (печать SQL без выполнения).
- Для повторного импорта того же боя выполнить:
  1. Обновить статус предыдущего импорта на `superseded`.
  2. Удалить записи из `fights` по `fight_code` (каскадно удалятся участники и вопросы).
  3. Запустить импорт заново.

## 8. Контроль качества
- Проверить, что количество боёв в БД совпадает с количеством заголовков на листе.
- Сравнить итоги игроков с оригинальным листом и с агрегированными отчётами.
- Убедиться, что все игроки из листа `S01E02` присутствуют в `PlayerList` и имеют alias.

## 9. Дальнейшие шаги
- Добавить unit-тесты на парсер Google Sheets (mock JSON-ответ).
- Расширить схему сезонными таблицами рейтингов, если потребуется (например, `player_tour_totals`).
- После обкатки импорта для `S01E02` повторить процедуру для остальных листов сезона.
