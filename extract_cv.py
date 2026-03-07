import os
import mysql.connector
from mysql.connector import Error
import PyPDF2
from docx import Document
import pytesseract
from pdf2image import convert_from_path
import re
from datetime import datetime
import config
from config import DB_CONFIG

# cv_ai_extract'ten AICVResponse sınıfını import et
from cv_ai_extract import AICVResponseGroq


class CVProcessor:
    def __init__(self, db_config):
        """
        db_config: Veritabanı bağlantı bilgileri (host, database, user, password)
        """
        self.db_config = db_config
        self.connection = None

    def connect_db(self):
        """Veritabanı bağlantısı oluştur"""
        try:
            self.connection = mysql.connector.connect(**self.db_config)
            print("✅ Veritabanına başarıyla bağlanıldı")
        except Error as e:
            print(f"❌ Veritabanı bağlantı hatası: {e}")

    def disconnect_db(self):
        """Veritabanı bağlantısını kapat"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            print("🔌 Veritabanı bağlantısı kapatıldı")

    def extract_text_from_pdf(self, pdf_path):
        """PDF'den metin çıkar"""
        text = ""
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text
        except Exception as e:
            print(f"📄 PDF okuma hatası: {e}")

            # Eğer normal PDF okuma başarısız olursa OCR dene
            try:
                print("🔄 OCR deneniyor...")
                images = convert_from_path(pdf_path)
                for image in images:
                    text += pytesseract.image_to_string(image, lang='tur+eng')
                print("✅ OCR başarılı")
            except Exception as ocr_error:
                print(f"❌ OCR hatası: {ocr_error}")

        return text

    def extract_text_from_docx(self, docx_path):
        """DOCX'den metin çıkar"""
        text = ""
        try:
            doc = Document(docx_path)
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
        except Exception as e:
            print(f"📄 DOCX okuma hatası: {e}")
        return text

    def extract_text_from_file(self, file_path):
        """Dosya türüne göre metin çıkar"""
        if not os.path.exists(file_path):
            print(f"❌ Dosya bulunamadı: {file_path}")
            return None

        file_extension = os.path.splitext(file_path)[1].lower()

        if file_extension == '.pdf':
            return self.extract_text_from_pdf(file_path)
        elif file_extension == '.docx':
            return self.extract_text_from_docx(file_path)
        else:
            print(f"❌ Desteklenmeyen dosya türü: {file_extension}")
            return None

    def save_cv_to_database(self, user_id, file_path, job_info=None):
        """
        CV'yi veritabanına kaydet ve AI analizi için tetikle
        """
        if not self.connection or not self.connection.is_connected():
            self.connect_db()

        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True)

            # CV'den metin çıkar
            print(f"📄 CV'den metin çıkarılıyor: {file_path}")
            cv_text = self.extract_text_from_file(file_path)

            if not cv_text:
                print("❌ CV metni çıkarılamadı")
                return None

            # Metni temizle ve kısalt (çok uzunsa)
            cv_text_clean = cv_text.strip()[:10000]  # Maksimum 10000 karakter

            # SADECE cv_text tablosuna kaydet
            insert_query = """
            INSERT INTO cv_text 
            (user_id, raw_text)
            VALUES (%s, %s)
            """

            values = (user_id, cv_text_clean)

            cursor.execute(insert_query, values)
            self.connection.commit()

            cv_text_id = cursor.lastrowid
            print(f"✅ CV metni başarıyla kaydedildi. cv_text_id: {cv_text_id}")

            # OTOMATİK AI ANALİZİ - Yeni eklenen kısım
            print(f"🤖 AI analizi başlatılıyor...")
            self.analyze_cv_with_ai(user_id, cv_text_id, cv_text_clean)

            return cv_text_id

        except Error as e:
            print(f"❌ Veritabanı hatası: {e}")
            if self.connection:
                self.connection.rollback()
            return None
        finally:
            if cursor:
                cursor.close()

    def analyze_cv_with_ai(self, user_id, cv_text_id, raw_text):
        """
        Kaydedilen CV'yi AI ile analiz et
        """
        try:
            # AI analizcisini oluştur
            ai_analyzer = AICVResponseGroq(self.db_config, config.api_key)

            # Bağlantıyı kur
            if not ai_analyzer.connection:
                ai_analyzer.connect()

            # AI ile analiz et
            print(f"🔍 CV analiz ediliyor...")
            cv_data = ai_analyzer.PromptingAI(raw_text)

            if cv_data:
                print("✅ AI analizi tamamlandı")
                print(f"📊 Analiz sonuçları:")
                print(f"   📍 Adres: {cv_data[0][:50]}...")
                print(f"   💻 Yetenekler: {cv_data[1][:50]}...")
                print(f"   💼 Deneyim: {cv_data[2][:50]}...")
                print(f"   🎓 Eğitim: {cv_data[3][:50]}...")
                print(f"   🗣️ Diller: {cv_data[4][:50]}...")

                # Otomatik kaydetme (opsiyonel)
                # Eğer otomatik kaydetmek isterseniz:
                # ai_analyzer.SaveInDatabase(cv_data, user_id)

                return cv_data
            else:
                print("❌ AI analizi başarısız")
                return None

        except Exception as e:
            print(f"❌ AI analiz hatası: {e}")
            return None
        finally:
            if ai_analyzer:
                ai_analyzer.disconnect()

    def process_multiple_cvs(self, user_id, cv_folder_path):
        """Bir klasördeki tüm CV'leri işle"""
        processed_cvs = []

        for filename in os.listdir(cv_folder_path):
            file_path = os.path.join(cv_folder_path, filename)

            if os.path.isfile(file_path):
                print(f"\n📁 İşleniyor: {filename}")
                cv_id = self.save_cv_to_database(user_id, file_path)
                if cv_id:
                    processed_cvs.append({
                        'filename': filename,
                        'cv_text_id': cv_id,
                        'status': 'success'
                    })
                else:
                    processed_cvs.append({
                        'filename': filename,
                        'status': 'failed'
                    })

        return processed_cvs

    def get_user_cvs(self, user_id):
        """Kullanıcının tüm CV'lerini getir (cv_text tablosundan)"""
        if not self.connection or not self.connection.is_connected():
            self.connect_db()

        try:
            cursor = self.connection.cursor(dictionary=True)

            query = """
            SELECT cv_text_id, user_id, LEFT(raw_text, 200) as raw_text_preview, 
                   created_at 
            FROM cv_text
            WHERE user_id = %s
            ORDER BY created_at DESC
            """

            cursor.execute(query, (user_id,))
            results = cursor.fetchall()

            return results

        except Error as e:
            print(f"❌ Veritabanı hatası: {e}")
            return []
        finally:
            if cursor:
                cursor.close()

    def get_cv_text_by_id(self, cv_text_id):
        """Belirli bir cv_text_id'ye ait metni getir"""
        if not self.connection or not self.connection.is_connected():
            self.connect_db()

        try:
            cursor = self.connection.cursor(dictionary=True)

            query = "SELECT * FROM cv_text WHERE cv_text_id = %s"
            cursor.execute(query, (cv_text_id,))
            result = cursor.fetchone()

            return result

        except Error as e:
            print(f"❌ Veritabanı hatası: {e}")
            return None
        finally:
            if cursor:
                cursor.close()


def main():
    processor = CVProcessor(DB_CONFIG)

    # Tek bir CV yükle
    user_id = 4  # Turgay BOZOĞLU'nun user_id'si
    cv_path = "path/to/your/cv.pdf"  # Buraya gerçek dosya yolunu girin

    # CV'yi kaydet (AI analizi otomatik başlayacak)
    print("\n🚀 CV işleme başlatılıyor...")
    cv_text_id = processor.save_cv_to_database(user_id, cv_path)

    if cv_text_id:
        print(f"\n✅ İşlem tamamlandı! cv_text_id: {cv_text_id}")

    # Kullanıcının tüm CV'lerini listele
    print(f"\n📋 Kullanıcı ID {user_id} için CV listesi:")
    user_cvs = processor.get_user_cvs(user_id)
    for cv in user_cvs:
        print(f"   📄 cv_text_id: {cv['cv_text_id']}, Tarih: {cv['created_at']}")
        print(f"      Önizleme: {cv['raw_text_preview'][:100]}...")

    # Bağlantıyı kapat
    processor.disconnect_db()


if __name__ == "__main__":
    main()