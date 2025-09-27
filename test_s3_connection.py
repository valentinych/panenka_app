#!/usr/bin/env python3
"""
Скрипт для тестирования подключения к S3 и загрузки auth.json
"""

import os
import sys
import json
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_s3_connection():
    """Тестирует подключение к S3 и загрузку auth.json"""
    
    # Проверяем переменные окружения
    required_vars = ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_DEFAULT_REGION']
    s3_vars = ['AUTH_JSON_S3_BUCKET', 'AUTH_JSON_S3_KEY']
    
    logger.info("Проверяем переменные окружения...")
    
    missing_vars = []
    for var in required_vars + s3_vars:
        value = os.getenv(var)
        if value:
            if 'KEY' in var or 'SECRET' in var:
                logger.info(f"✓ {var}: {'*' * len(value)}")
            else:
                logger.info(f"✓ {var}: {value}")
        else:
            logger.error(f"✗ {var}: НЕ УСТАНОВЛЕНА")
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"Отсутствуют переменные окружения: {missing_vars}")
        return False
    
    # Тестируем boto3
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
        logger.info("✓ boto3 импортирован успешно")
    except ImportError as e:
        logger.error(f"✗ Ошибка импорта boto3: {e}")
        return False
    
    # Тестируем S3 клиент
    try:
        logger.info("Создаем S3 клиент...")
        s3_client = boto3.client('s3')
        logger.info("✓ S3 клиент создан успешно")
    except Exception as e:
        logger.error(f"✗ Ошибка создания S3 клиента: {e}")
        return False
    
    # Тестируем доступ к bucket
    bucket_name = os.getenv('AUTH_JSON_S3_BUCKET')
    try:
        logger.info(f"Проверяем доступ к bucket: {bucket_name}")
        s3_client.head_bucket(Bucket=bucket_name)
        logger.info("✓ Bucket доступен")
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '404':
            logger.error(f"✗ Bucket {bucket_name} не найден")
        elif error_code == '403':
            logger.error(f"✗ Нет доступа к bucket {bucket_name}")
        else:
            logger.error(f"✗ Ошибка доступа к bucket: {e}")
        return False
    except Exception as e:
        logger.error(f"✗ Неожиданная ошибка при проверке bucket: {e}")
        return False
    
    # Тестируем загрузку файла
    object_key = os.getenv('AUTH_JSON_S3_KEY', 'auth.json')
    try:
        logger.info(f"Загружаем файл: s3://{bucket_name}/{object_key}")
        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
        
        body = response.get('Body')
        if not body:
            logger.error("✗ Пустой ответ от S3")
            return False
        
        content = body.read()
        if isinstance(content, bytes):
            content = content.decode('utf-8')
        
        logger.info(f"✓ Файл загружен, размер: {len(content)} символов")
        
        # Парсим JSON
        try:
            data = json.loads(content)
            users = data.get('users', [])
            active_users = [u for u in users if not u.get('inactive', False)]
            
            logger.info(f"✓ JSON валиден")
            logger.info(f"✓ Всего пользователей: {len(users)}")
            logger.info(f"✓ Активных пользователей: {len(active_users)}")
            
            # Показываем первых нескольких пользователей
            if active_users:
                logger.info("Первые 3 активных пользователя:")
                for i, user in enumerate(active_users[:3]):
                    logger.info(f"  {i+1}. {user.get('name', 'Неизвестно')} (логин: {user.get('login', 'N/A')})")
            
            return True
            
        except json.JSONDecodeError as e:
            logger.error(f"✗ Ошибка парсинга JSON: {e}")
            return False
            
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'NoSuchKey':
            logger.error(f"✗ Файл {object_key} не найден в bucket {bucket_name}")
        else:
            logger.error(f"✗ Ошибка загрузки файла: {e}")
        return False
    except Exception as e:
        logger.error(f"✗ Неожиданная ошибка при загрузке файла: {e}")
        return False

if __name__ == "__main__":
    logger.info("Начинаем тестирование S3 подключения...")
    logger.info("=" * 50)
    
    success = test_s3_connection()
    
    logger.info("=" * 50)
    if success:
        logger.info("🎉 Все тесты прошли успешно!")
        sys.exit(0)
    else:
        logger.error("❌ Тесты не прошли. Проверьте конфигурацию.")
        sys.exit(1)
