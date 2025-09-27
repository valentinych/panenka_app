# Настройка приложения на Heroku с AWS S3

## Проблема
Пользователи не могут залогиниться в приложение на Heroku, потому что файл `auth.json` не загружается из AWS S3.

## Решение

### 1. Установка переменных окружения на Heroku

Выполните следующие команды, заменив `YOUR_APP_NAME` на имя вашего Heroku приложения:

```bash
# AWS учетные данные
heroku config:set AWS_ACCESS_KEY_ID=YOUR_AWS_ACCESS_KEY_ID -a YOUR_APP_NAME
heroku config:set AWS_SECRET_ACCESS_KEY=YOUR_AWS_SECRET_ACCESS_KEY -a YOUR_APP_NAME
heroku config:set AWS_DEFAULT_REGION=us-east-1 -a YOUR_APP_NAME

# S3 конфигурация для auth.json
heroku config:set AUTH_JSON_S3_BUCKET=val-draft-storage -a YOUR_APP_NAME
heroku config:set AUTH_JSON_S3_KEY=auth.json -a YOUR_APP_NAME
```

### 2. Проверка переменных окружения

```bash
heroku config -a YOUR_APP_NAME
```

Должны быть установлены следующие переменные:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY` 
- `AWS_DEFAULT_REGION`
- `AUTH_JSON_S3_BUCKET`
- `AUTH_JSON_S3_KEY`

### 3. Деплой приложения

```bash
git push heroku main
```

### 4. Проверка логов

```bash
heroku logs --tail -a YOUR_APP_NAME
```

## Тестирование S3 подключения

### Локальное тестирование

Создайте файл `test_s3_connection.py` (уже существует в проекте):

```python
import boto3
import os
from botocore.exceptions import ClientError, NoCredentialsError

def test_s3_connection():
    try:
        # Получаем параметры из переменных окружения
        bucket_name = os.getenv('AUTH_JSON_S3_BUCKET', 'val-draft-storage')
        key_name = os.getenv('AUTH_JSON_S3_KEY', 'auth.json')
        
        print(f"Тестируем подключение к S3...")
        print(f"Bucket: {bucket_name}")
        print(f"Key: {key_name}")
        
        # Создаем S3 клиент
        s3_client = boto3.client('s3')
        
        # Пытаемся получить объект
        response = s3_client.get_object(Bucket=bucket_name, Key=key_name)
        
        print("✅ Успешно подключились к S3!")
        print(f"Размер файла: {response['ContentLength']} байт")
        print(f"Последнее изменение: {response['LastModified']}")
        
        return True
        
    except NoCredentialsError:
        print("❌ Ошибка: AWS учетные данные не найдены")
        print("Убедитесь, что установлены переменные AWS_ACCESS_KEY_ID и AWS_SECRET_ACCESS_KEY")
        return False
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'NoSuchBucket':
            print(f"❌ Ошибка: Bucket '{bucket_name}' не найден")
        elif error_code == 'NoSuchKey':
            print(f"❌ Ошибка: Файл '{key_name}' не найден в bucket '{bucket_name}'")
        elif error_code == 'AccessDenied':
            print(f"❌ Ошибка: Нет доступа к bucket '{bucket_name}' или файлу '{key_name}'")
        else:
            print(f"❌ Ошибка AWS: {e}")
        return False
        
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        return False

if __name__ == "__main__":
    test_s3_connection()
```

Используйте тестовый скрипт:

```bash
# Установите переменные окружения
export AWS_ACCESS_KEY_ID=YOUR_AWS_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY=YOUR_AWS_SECRET_ACCESS_KEY
export AWS_DEFAULT_REGION=us-east-1
export AUTH_JSON_S3_BUCKET=val-draft-storage
export AUTH_JSON_S3_KEY=auth.json

# Запустите тест
python test_s3_connection.py
```

### Тестирование на Heroku

```bash
heroku run python test_s3_connection.py -a YOUR_APP_NAME
```

## Возможные проблемы и решения

### 1. Ошибка "NoCredentialsError"
**Проблема**: AWS учетные данные не установлены или неверные.
**Решение**: Проверьте переменные окружения `AWS_ACCESS_KEY_ID` и `AWS_SECRET_ACCESS_KEY`.

### 2. Ошибка "AccessDenied" 
**Проблема**: У пользователя AWS нет прав доступа к S3 bucket.
**Решение**: Убедитесь, что у пользователя есть права `s3:GetObject` для bucket `val-draft-storage`.

### 3. Ошибка "NoSuchBucket"
**Проблема**: Bucket не существует или указано неверное имя.
**Решение**: Проверьте имя bucket в переменной `AUTH_JSON_S3_BUCKET`.

### 4. Ошибка "NoSuchKey"
**Проблема**: Файл `auth.json` не найден в bucket.
**Решение**: Убедитесь, что файл загружен в S3 bucket с правильным именем.

## Автоматическая настройка

Используйте скрипт `setup_heroku_env.sh` для автоматической настройки:

```bash
chmod +x setup_heroku_env.sh
./setup_heroku_env.sh YOUR_APP_NAME
```

## Проверка работы приложения

После настройки:

1. Откройте приложение в браузере
2. Попробуйте залогиниться с любыми учетными данными из `auth.json`
3. Проверьте логи Heroku на наличие ошибок

Если все настроено правильно, пользователи смогут успешно логиниться в приложение.