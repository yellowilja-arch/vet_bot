import asyncio
import os
import shutil
from datetime import datetime
import boto3
from botocore.client import Config
from config import YC_ACCESS_KEY_ID, YC_SECRET_ACCESS_KEY, YC_BUCKET_NAME, YC_ENDPOINT, DB_PATH, ADMIN_IDS
from utils.helpers import safe_send_message

def upload_to_yandex(file_path: str, object_name: str) -> bool:
    """Загружает файл в Yandex Object Storage"""
    if not YC_ACCESS_KEY_ID or not YC_SECRET_ACCESS_KEY:
        print("⚠️ Yandex Cloud не настроен: пропускаем бэкап")
        return False
    
    session = boto3.session.Session()
    client = session.client(
        's3',
        endpoint_url=YC_ENDPOINT,
        aws_access_key_id=YC_ACCESS_KEY_ID,
        aws_secret_access_key=YC_SECRET_ACCESS_KEY,
        region_name='ru-central1',
        config=Config(signature_version='s3v4')
    )
    
    try:
        client.upload_file(file_path, YC_BUCKET_NAME, object_name)
        print(f"✅ Бэкап {object_name} загружен в Yandex Cloud!")
        return True
    except Exception as e:
        print(f"❌ Ошибка загрузки в Yandex Cloud: {e}")
        return False

async def clean_old_backups(max_files: int = 30):
    """Удаляет старые бэкапы из Yandex Cloud"""
    if not YC_ACCESS_KEY_ID or not YC_SECRET_ACCESS_KEY:
        return 0
    
    try:
        session = boto3.session.Session()
        client = session.client(
            's3',
            endpoint_url=YC_ENDPOINT,
            aws_access_key_id=YC_ACCESS_KEY_ID,
            aws_secret_access_key=YC_SECRET_ACCESS_KEY,
            region_name='ru-central1',
            config=Config(signature_version='s3v4')
        )
        
        response = client.list_objects_v2(Bucket=YC_BUCKET_NAME)
        if 'Contents' not in response:
            return 0
        
        objects = sorted(response['Contents'], key=lambda x: x['LastModified'], reverse=True)
        deleted_count = 0
        for obj in objects[max_files:]:
            client.delete_object(Bucket=YC_BUCKET_NAME, Key=obj['Key'])
            print(f"🗑️ Удалён старый бэкап: {obj['Key']}")
            deleted_count += 1
        
        return deleted_count
    except Exception as e:
        print(f"❌ Ошибка очистки бэкапов: {e}")
        return 0

async def create_backup():
    """Создаёт и загружает бэкап БД в Yandex Cloud"""
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"vet_bot_backup_{timestamp}.db"
        temp_path = f"/tmp/{backup_name}"
        
        shutil.copy2(DB_PATH, temp_path)
        success = upload_to_yandex(temp_path, backup_name)
        os.remove(temp_path)
        
        if success:
            deleted = await clean_old_backups(max_files=30)
            return f"✅ Бэкап создан и загружен\n📅 {timestamp}\n🗑️ Удалено старых: {deleted}"
        else:
            return f"❌ Ошибка загрузки бэкапа\n📅 {timestamp}"
    except Exception as e:
        print(f"❌ Ошибка бэкапа: {e}")
        return f"❌ Критическая ошибка бэкапа:\n{e}"

async def backup_worker():
    """Фоновая задача: раз в сутки бэкапим БД в Yandex Cloud"""
    while True:
        await asyncio.sleep(86400)  # 24 часа
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_name = f"vet_bot_backup_{timestamp}.db"
            temp_path = f"/tmp/{backup_name}"
            
            shutil.copy2(DB_PATH, temp_path)
            success = upload_to_yandex(temp_path, backup_name)
            os.remove(temp_path)
            
            if success:
                deleted = await clean_old_backups(max_files=30)
                for admin_id in ADMIN_IDS:
                    await safe_send_message(
                        admin_id,
                        f"✅ Бэкап БД создан и загружен в Yandex Cloud\n📅 {timestamp}\n🗑️ Удалено старых: {deleted}"
                    )
            else:
                for admin_id in ADMIN_IDS:
                    await safe_send_message(admin_id, f"❌ Ошибка загрузки бэкапа в Yandex Cloud\n📅 {timestamp}")
        except Exception as e:
            print(f"❌ Ошибка бэкапа: {e}")
            for admin_id in ADMIN_IDS:
                await safe_send_message(admin_id, f"❌ Критическая ошибка бэкапа:\n<pre>{e}</pre>", parse_mode="HTML")