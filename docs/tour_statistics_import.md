# Импорт турнирной статистики buzzer-игр

## 1. Цели и общие принципы
- Централизованно хранить результаты боёв второго тура первого сезона и последующих туров.
- Поддерживать повторный импорт из Google Sheets и из исторических CSV/XLSX файлов.
- Сохранять связи между сезонами, турами, боями, игроками, темами и вопросами с их номиналами и исходами.
- Позволить аналитике строить отчёты по игрокам, темам и динамике раундов.

## 2. Предлагаемая схема базы данных

### 2.1. Основные сущности
| Таблица | Назначение |
| --- | --- |
| `seasons` | Справочник сезонов (S01, S02 и т.д.). |
| `tours` | Игровые туры внутри сезона. |
| `fights` | Отдельные бои внутри тура (код S01E02F07 и метаданные загрузки). |
| `players` | Уникальные игроки (нормализованные ФИО). |
| `fight_participants` | Связь игрока и боя, хранит итоговый счёт и позицию. |
| `themes` | Справочник тем вопросов (цветовая тема, «Бартез», «Блан» и т.д.). |
| `questions` | Вопросы внутри боя с указанием темы и номинала. |
| `question_results` | Результаты вопроса по игрокам (плюс/минус номинал, правильность). |
| `imports` | Журнал импортов из файлов/Google Sheets для воспроизводимости. |

### 2.2. SQL-описания таблиц
```sql
CREATE TABLE seasons (
    id SERIAL PRIMARY KEY,
    season_number INTEGER NOT NULL UNIQUE,
    slug TEXT GENERATED ALWAYS AS (LPAD(season_number::text, 2, '0')) STORED
);

CREATE TABLE tours (
    id SERIAL PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(id),
    tour_number INTEGER NOT NULL,
    UNIQUE (season_id, tour_number)
);

CREATE TABLE fights (
    id SERIAL PRIMARY KEY,
    tour_id INTEGER NOT NULL REFERENCES tours(id),
    fight_number INTEGER NOT NULL,
    fight_code TEXT NOT NULL UNIQUE, -- например S01E02F07
    sheet_id TEXT NOT NULL,          -- ID Google Sheet
    sheet_name TEXT NOT NULL,        -- вкладка, например "Tour2"
    imported_at TIMESTAMPTZ NOT NULL,
    import_id INTEGER NOT NULL REFERENCES imports(id),
    UNIQUE (tour_id, fight_number)
);

CREATE TABLE players (
    id SERIAL PRIMARY KEY,
    full_name TEXT NOT NULL UNIQUE,
    normalized_name TEXT NOT NULL UNIQUE
);

CREATE TABLE fight_participants (
    id SERIAL PRIMARY KEY,
    fight_id INTEGER NOT NULL REFERENCES fights(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    seat_index INTEGER NOT NULL,        -- порядок отображения в таблице
    total_score INTEGER NOT NULL,
    finishing_place INTEGER,
    UNIQUE (fight_id, player_id)
);

CREATE TABLE themes (
    id SERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,          -- короткий код темы
    title TEXT NOT NULL,
    description TEXT
);

CREATE TABLE questions (
    id SERIAL PRIMARY KEY,
    fight_id INTEGER NOT NULL REFERENCES fights(id) ON DELETE CASCADE,
    theme_id INTEGER NOT NULL REFERENCES themes(id),
    question_order INTEGER NOT NULL,
    nominal INTEGER NOT NULL,           -- 10, 20, 30, 40, 50
    sheet_row INTEGER,
    UNIQUE (fight_id, question_order)
);

CREATE TABLE question_results (
    id SERIAL PRIMARY KEY,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    participant_id INTEGER NOT NULL REFERENCES fight_participants(id) ON DELETE CASCADE,
    delta INTEGER NOT NULL,             -- +10, -20 и т.д.
    is_correct BOOLEAN NOT NULL,
    UNIQUE (question_id, participant_id)
);

CREATE TABLE imports (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,               -- например "google_sheets"
    source_identifier TEXT NOT NULL,    -- URL или имя файла
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    message TEXT
);
```

## 3. Стратегия импорта из Google Sheets

1. **Регистрация импорта**. Создать запись в `imports` со статусом `pending`, указав ID документа (`1ehQabU98lFzeInoJwvEIGpyZeuv2NFkPdnhoXYzDmT0`) и лист (`Tour2`).
2. **Получение данных**. Использовать Google Sheets API (метод `spreadsheets.values.get`) и запросить диапазон `Tour2!A1:ZZ200`.
3. **Разделение на блоки боёв**. Проходить по столбцам:
   - В первой строке ищем ячейки с шаблоном `SxxEyyFzz`.
   - Пустой столбец (все значения пусты) служит разделителем между боями.
4. **Парсинг блока боя**. Для каждого блока:
   - Строка 1: читаем `fight_code`.
   - Строка 2: названия тем по порядку вопросов.
   - Строка 3: итоговые суммы игроков.
   - Строка 4 и далее: в колонке `F` (общей для листа) указаны номиналы (10/20/30/40/50). Строки с этими номиналами соответствуют отдельным вопросам.
   - Для каждого игрока (столбец под именем): фиксируем имя, позицию (по порядку слева направо) и значения в строке 3 (итоговый счёт).
   - По строкам номиналов считываем дельты: положительное число — вопрос взят, отрицательное — не взят.
5. **Нормализация игроков**. Приводим ФИО к нижнему регистру, удаляем лишние пробелы, заменяем `ё` на `е`, чтобы сформировать `normalized_name`. Ищем/создаём запись в `players`.
6. **Создание записей боя**. На основе `fight_code` разбираем номера сезона, тура, боя. Вставляем/ищем сезон и тур, затем создаём запись в `fights` с ссылкой на `imports`.
7. **Связь участников**. Создаём записи в `fight_participants`, указывая итоговый счёт из строки 3 и индекс игрока.
8. **Создание вопросов**. Для каждой строки с номиналом:
   - Определяем тему из строки 2 соответствующего столбца (`themes` загружаются заранее из справочника).
   - Создаём запись в `questions` с порядком (номер строки по счёту) и номиналом.
9. **Результаты игроков**. Для каждой ячейки вопроса/игрока создаём запись в `question_results` с `delta` и вычисляем `is_correct = delta > 0`.
10. **Завершение импорта**. После успешной вставки меняем статус импорта на `success` и сохраняем временную метку завершения. При ошибках фиксируем статус `failed` и сообщение.

## 4. Пример импорта для тура "Tour2"

### 4.1. Исходные данные по бою S01E02F01
- Участники: Александр Ефименко, Мария Тимохова, Денис Лавренюк, Евгений Капитульский.
- Бой отделён пустой колонкой от последующих в листе `Tour2`.
- В строке 3 под именами игроков указаны итоги боя (например: `70`, `-10`, `40`, `0`).
- В строках с номиналами 10, 20, 30, 40, 50 указаны дельты по каждому игроку.

### 4.2. Шаги загрузки
1. **Разбор кода**. `S01E02F01` → сезон 1, тур 2, бой 1. Проверяем наличие `seasons.season_number = 1` и `tours.tour_number = 2`.
2. **Игроки**. После нормализации имен создаём/находим записи в `players`:
   - `александр ефименко`
   - `мария тимохова`
   - `денис лавренюк`
   - `евгений капитульский`
3. **Связь и итоговые счета**. Добавляем записи в `fight_participants` с `seat_index` 1-4 и итогами из строки 3.
4. **Темы и вопросы**.
   - Предположим, что в строке 2 стоят темы: `Цветная`, `Бартез`, `Блан`, `...`.
   - Для каждой строки номиналов (например, первая строка номинала `10`):
     - Создаём вопрос `question_order = 1`, `nominal = 10`, `theme = "Цветная"`.
     - По каждому игроку читаем значение (`+10`, `0`, `-10`, `0`) и добавляем записи в `question_results`.
   - Повторяем для номиналов `20`, `30`, `40`, `50`.
5. **Проверка суммы**. После загрузки пересчитываем суммы дельт по игрокам и сравниваем с итоговой строкой, чтобы убедиться в корректности парсинга.
6. **Финализация**. Обновляем `imports.status = 'success'` и сохраняем `finished_at`.

### 4.3. Повторение для остальных боёв листа
- Двигаемся вправо до пустой колонки, берём следующий заголовок `S01E02F02`, повторяем шаги.
- Таким образом импортируются все бои тура `Tour2`.

## 5. Дополнительные замечания
- **Восстановление тем**. Если тема не найдена в справочнике `themes`, логируем и добавляем в таблицу с временным кодом.
- **Журнал изменений**. Таблица `imports` позволяет повторно загружать данные: при повторном запуске можно помечать старые записи как архивные или обновлять их транзакционно.
- **Валидация данных**. Перед коммитом транзакции проверяем:
  - Все строки с номиналами соответствуют ожидаемым значениям.
  - Итоговые суммы совпадают с суммой дельт.
  - Количество игроков в бою 2-5.
- **Расширяемость**. Схема подходит для следующих сезонов и туров, достаточно добавлять новые листы и файлы в очередь импортов.
