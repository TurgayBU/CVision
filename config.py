# Veritabanı konfigürasyonu
import os

DB_CONFIG = {
    'host': 'localhost',
    'database': 'cvision',
    'user': 'root',
    'password': 'Yeni0000',  # MySQL şifreni buraya yaz
    'port': 3306
}

# Flask konfigürasyonu
SECRET_KEY = 'cvision_gizli_anahtar_2024'
SESSION_LIFETIME_DAYS = 7

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB

# Upload klasörünü oluştur
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

api_key="REDACTED"

# Uygulama ayarları
DEBUG = True
PORT = 5000