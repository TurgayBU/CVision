import os
import mysql.connector
from mysql.connector import Error
import PyPDF2
from docx import Document
import pytesseract
from pdf2image import convert_from_path
import re
import json
from datetime import datetime
import config
from config import DB_CONFIG


class CVProcessor:
    def __init__(self, db_config):
        """
        db_config: Veritabanı bağlantı bilgileri (host, database, user, password)
        """
        self.db_config = db_config  # DB_CONFIG yerine parametre olarak gelen db_config
        self.connection = None

    def connect_db(self):
        """Veritabanı bağlantısı oluştur"""
        try:
            self.connection = mysql.connector.connect(**self.db_config)
            print("Connected to database successfully")
        except Error as e:
            print(f"Veritabanı bağlantı hatası: {e}")

    def disconnect_db(self):
        """Veritabanı bağlantısını kapat"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            print("Veritabanı bağlantısı kapatıldı")

    def extract_text_from_pdf(self, pdf_path):
        """PDF'den metin çıkar"""
        text = ""
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    text += page.extract_text()
        except Exception as e:
            print(f"PDF okuma hatası: {e}")

            # Eğer normal PDF okuma başarısız olursa OCR dene
            try:
                images = convert_from_path(pdf_path)
                for image in images:
                    text += pytesseract.image_to_string(image, lang='tur+eng')
            except Exception as ocr_error:
                print(f"OCR hatası: {ocr_error}")

        return text

    def extract_text_from_docx(self, docx_path):
        """DOCX'den metin çıkar"""
        text = ""
        try:
            doc = Document(docx_path)
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
        except Exception as e:
            print(f"DOCX okuma hatası: {e}")
        return text

    def extract_text_from_file(self, file_path):
        """Dosya türüne göre metin çıkar"""
        if not os.path.exists(file_path):
            print(f"Dosya bulunamadı: {file_path}")
            return None

        file_extension = os.path.splitext(file_path)[1].lower()

        if file_extension == '.pdf':
            return self.extract_text_from_pdf(file_path)
        elif file_extension == '.docx':
            return self.extract_text_from_docx(file_path)
        else:
            print(f"Desteklenmeyen dosya türü: {file_extension}")
            return None

    def parse_skills(self, text):
        """CV'den yetenekleri çıkar"""
        skills = []

        # Ortak yetenek listesi
        common_skills = [
            'python', 'java', 'javascript', 'c++', 'c#', 'php', 'ruby',
            'html', 'css', 'sql', 'mongodb', 'mysql', 'postgresql',
            'react', 'angular', 'vue', 'django', 'flask', 'spring',
            'aws', 'azure', 'docker', 'kubernetes', 'git', 'jenkins',
            'excel', 'word', 'powerpoint', 'photoshop', 'illustrator',
            'project management', 'agile', 'scrum', 'leadership',
            'communication', 'teamwork', 'problem solving', 'analytical'
        ]

        text_lower = text.lower()

        # Yetenekleri bul
        for skill in common_skills:
            if skill in text_lower:
                skills.append(skill)

        return list(set(skills))  # Tekrarları kaldır

    def parse_experience(self, text):
        """CV'den iş deneyimlerini çıkar (basit versiyon)"""
        experiences = []

        # Deneyim bölümünü bul
        experience_patterns = [
            r'deneyim(.*?)(?=eğitim|beceriler|yetenekler|$|eğitim|dil)',
            r'experience(.*?)(?=education|skills|$|languages)',
            r'iş deneyimi(.*?)(?=eğitim|beceriler|$|eğitim)'
        ]

        for pattern in experience_patterns:
            match = re.search(pattern, text.lower(), re.DOTALL | re.IGNORECASE)
            if match:
                exp_text = match.group(1).strip()
                # Basit bir deneyim listesi oluştur
                experiences.append(exp_text)
                break

        return experiences

    def parse_education(self, text):
        """CV'den eğitim bilgilerini çıkar"""
        education = []

        education_patterns = [
            r'eğitim(.*?)(?=deneyim|beceriler|yetenekler|$|experience|skills)',
            r'education(.*?)(?=experience|skills|$)',
            r'üniversite(.*?)(?=deneyim|beceriler|$)'
        ]

        for pattern in education_patterns:
            match = re.search(pattern, text.lower(), re.DOTALL | re.IGNORECASE)
            if match:
                edu_text = match.group(1).strip()
                education.append(edu_text)
                break

        return education

    def parse_languages(self, text):
        """CV'den dil bilgilerini çıkar"""
        languages = []

        language_patterns = [
            r'dil(.*?)(?=deneyim|eğitim|beceriler|$|experience|education|skills)',
            r'languages(.*?)(?=experience|education|skills|$)',
            r'yabancı dil(.*?)(?=deneyim|eğitim|beceriler|$)'
        ]

        for pattern in language_patterns:
            match = re.search(pattern, text.lower(), re.DOTALL | re.IGNORECASE)
            if match:
                lang_text = match.group(1).strip()
                languages.append(lang_text)
                break

        return languages

    def save_cv_to_database(self, user_id, file_path, job_info=None):
        """
        CV'yi veritabanına kaydet
        job_info: {'title': '...', 'url': '...', 'location': '...'} (opsiyonel)
        """
        if not self.connection or not self.connection.is_connected():
            self.connect_db()

        try:
            cursor = self.connection.cursor(dictionary=True)

            # CV'den metin çıkar
            cv_text = self.extract_text_from_file(file_path)

            if not cv_text:
                print("CV metni çıkarılamadı")
                return None

            # CV'den bilgileri parse et
            skills = self.parse_skills(cv_text)
            experience = self.parse_experience(cv_text)
            education = self.parse_education(cv_text)
            languages = self.parse_languages(cv_text)

            # Job info varsa al
            job_title = job_info.get('title') if job_info else None
            job_url = job_info.get('url') if job_info else None
            job_location = job_info.get('location') if job_info else None

            # Veritabanına kaydet
            insert_query = """
            INSERT INTO cv_analyses 
            (user_id, cv_file_path, cv_text, cv_skills, cv_experience, cv_education, cv_languages, 
             job_title, job_url, job_location, analyzed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """

            values = (
                user_id,
                file_path,
                cv_text[:5000],  # İlk 5000 karakter
                json.dumps(skills),
                json.dumps(experience),
                json.dumps(education),
                json.dumps(languages),
                job_title,
                job_url,
                job_location,
                datetime.now()
            )

            cursor.execute(insert_query, values)
            self.connection.commit()

            cv_id = cursor.lastrowid
            print(f"CV başarıyla kaydedildi. CV ID: {cv_id}")

            return cv_id

        except Error as e:
            print(f"Veritabanı hatası: {e}")
            if self.connection:
                self.connection.rollback()
            return None
        finally:
            if cursor:
                cursor.close()

    def process_multiple_cvs(self, user_id, cv_folder_path):
        """Bir klasördeki tüm CV'leri işle"""
        processed_cvs = []

        for filename in os.listdir(cv_folder_path):
            file_path = os.path.join(cv_folder_path, filename)

            if os.path.isfile(file_path):
                cv_id = self.save_cv_to_database(user_id, file_path)
                if cv_id:
                    processed_cvs.append({
                        'filename': filename,
                        'cv_id': cv_id,
                        'status': 'success'
                    })
                else:
                    processed_cvs.append({
                        'filename': filename,
                        'status': 'failed'
                    })

        return processed_cvs

    def get_user_cvs(self, user_id):
        """Kullanıcının tüm CV'lerini getir"""
        if not self.connection or not self.connection.is_connected():
            self.connect_db()

        try:
            cursor = self.connection.cursor(dictionary=True)

            query = """
            SELECT cv_id, cv_file_path, analyzed_at, job_title, job_location
            FROM cv_analyses
            WHERE user_id = %s
            ORDER BY analyzed_at DESC
            """

            cursor.execute(query, (user_id,))
            results = cursor.fetchall()

            return results

        except Error as e:
            print(f"Veritabanı hatası: {e}")
            return []
        finally:
            if cursor:
                cursor.close()
def main():
    processor = CVProcessor(DB_CONFIG)

    # Tek bir CV yükle
    user_id = 1  # Örnek kullanıcı ID
    cv_path = "path/to/your/cv.pdf"

    # İş başvurusu bilgileri (opsiyonel)
    job_info = {
        'title': 'Python Developer',
        'url': 'https://example.com/job/123',
        'location': 'İstanbul'
    }

    # CV'yi kaydet
    cv_id = processor.save_cv_to_database(user_id, cv_path, job_info)

    if cv_id:
        print(f"CV başarıyla kaydedildi. ID: {cv_id}")

    # Kullanıcının CV'lerini listele
    user_cvs = processor.get_user_cvs(user_id)
    print(f"\nKullanıcının {len(user_cvs)} CV'si bulundu:")
    for cv in user_cvs:
        print(f"- ID: {cv['cv_id']}, Tarih: {cv['analyzed_at']}")

    # Bağlantıyı kapat
    processor.disconnect_db()


if __name__ == "__main__":
    main()