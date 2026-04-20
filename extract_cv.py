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

from cv_ai_extract import AICVResponseGroq


class CVProcessor:
    def __init__(self, db_config):
        """
        db_config: Database connection info (host, database, user, password)
        """
        self.db_config = db_config
        self.connection = None

    def connect_db(self):
        """Create database connection"""
        try:
            self.connection = mysql.connector.connect(**self.db_config)
            print("✅ Successfully connected to database")
        except Error as e:
            print(f"❌ Database connection error: {e}")

    def disconnect_db(self):
        """Close database connection"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            print("🔌 Database connection closed")

    def extract_text_from_pdf(self, pdf_path):
        """Extract text from PDF"""
        text = ""
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text
        except Exception as e:
            print(f"📄 PDF read error: {e}")

            # Try OCR if normal PDF reading fails
            try:
                print("🔄 Attempting OCR...")
                images = convert_from_path(pdf_path)
                for image in images:
                    text += pytesseract.image_to_string(image, lang='tur+eng')
                print("✅ OCR successful")
            except Exception as ocr_error:
                print(f"❌ OCR error: {ocr_error}")

        return text

    def extract_text_from_docx(self, docx_path):
        """Extract text from DOCX"""
        text = ""
        try:
            doc = Document(docx_path)
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
        except Exception as e:
            print(f"📄 DOCX read error: {e}")
        return text

    def extract_text_from_file(self, file_path):
        """Extract text based on file type"""
        if not os.path.exists(file_path):
            print(f"❌ File not found: {file_path}")
            return None

        file_extension = os.path.splitext(file_path)[1].lower()

        if file_extension == '.pdf':
            return self.extract_text_from_pdf(file_path)
        elif file_extension == '.docx':
            return self.extract_text_from_docx(file_path)
        else:
            print(f"❌ Unsupported file type: {file_extension}")
            return None

    def save_cv_to_database(self, user_id, file_path, job_info=None):
        """
        Save CV to database and trigger AI analysis
        """
        if not self.connection or not self.connection.is_connected():
            self.connect_db()

        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True)

            # Extract text from CV
            print(f"📄 Extracting text from CV: {file_path}")
            cv_text = self.extract_text_from_file(file_path)

            if not cv_text:
                print("❌ Could not extract CV text")
                return None

            # Clean and truncate text
            cv_text_clean = cv_text.strip()[:10000]  # Maximum 10000 characters

            # Save only to cv_text table
            insert_query = """
            INSERT INTO cv_text 
            (user_id, raw_text)
            VALUES (%s, %s)
            """

            values = (user_id, cv_text_clean)

            cursor.execute(insert_query, values)
            self.connection.commit()

            cv_text_id = cursor.lastrowid
            print(f"✅ CV text saved successfully. cv_text_id: {cv_text_id}")

            # AUTOMATIC AI ANALYSIS
            print(f"🤖 Starting AI analysis...")
            self.analyze_cv_with_ai(user_id, cv_text_id, cv_text_clean)

            return cv_text_id

        except Error as e:
            print(f"❌ Database error: {e}")
            if self.connection:
                self.connection.rollback()
            return None
        finally:
            if cursor:
                cursor.close()

    def analyze_cv_with_ai(self, user_id, cv_text_id, raw_text):
        """
        Analyze saved CV with AI
        """
        try:
            # Create AI analyzer
            ai_analyzer = AICVResponseGroq(self.db_config, config.api_key)

            # Establish connection
            if not ai_analyzer.connection:
                ai_analyzer.connect()

            # Analyze with AI
            print(f"🔍 Analyzing CV...")
            cv_data = ai_analyzer.PromptingAI(raw_text)

            if cv_data:
                print("✅ AI analysis complete")
                print(f"📊 Analysis results:")
                print(f"   📍 Address: {cv_data[0][:50]}...")
                print(f"   💻 Skills: {cv_data[1][:50]}...")
                print(f"   💼 Experience: {cv_data[2][:50]}...")
                print(f"   🎓 Education: {cv_data[3][:50]}...")
                print(f"   🗣️ Languages: {cv_data[4][:50]}...")

                return cv_data
            else:
                print("❌ AI analysis failed")
                return None

        except Exception as e:
            print(f"❌ AI analysis error: {e}")
            return None
        finally:
            if ai_analyzer:
                ai_analyzer.disconnect()

    def process_multiple_cvs(self, user_id, cv_folder_path):
        """Process all CVs in a folder"""
        processed_cvs = []

        for filename in os.listdir(cv_folder_path):
            file_path = os.path.join(cv_folder_path, filename)

            if os.path.isfile(file_path):
                print(f"\n📁 Processing: {filename}")
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
        """Get all CVs for a user (from cv_text table)"""
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
            print(f"❌ Database error: {e}")
            return []
        finally:
            if cursor:
                cursor.close()

    def get_cv_text_by_id(self, cv_text_id):
        """Get text for a specific cv_text_id"""
        if not self.connection or not self.connection.is_connected():
            self.connect_db()

        try:
            cursor = self.connection.cursor(dictionary=True)

            query = "SELECT * FROM cv_text WHERE cv_text_id = %s"
            cursor.execute(query, (cv_text_id,))
            result = cursor.fetchone()

            return result

        except Error as e:
            print(f"❌ Database error: {e}")
            return None
        finally:
            if cursor:
                cursor.close()


def main():
    processor = CVProcessor(DB_CONFIG)

    # Upload a single CV
    user_id = 4
    cv_path = "path/to/your/cv.pdf"  # Enter the actual file path here

    # Save CV (AI analysis will start automatically)
    print("\n🚀 Starting CV processing...")
    cv_text_id = processor.save_cv_to_database(user_id, cv_path)

    if cv_text_id:
        print(f"\n✅ Processing complete! cv_text_id: {cv_text_id}")

    # List all CVs for user
    print(f"\n📋 CV list for user ID {user_id}:")
    user_cvs = processor.get_user_cvs(user_id)
    for cv in user_cvs:
        print(f"   📄 cv_text_id: {cv['cv_text_id']}, Date: {cv['created_at']}")
        print(f"      Preview: {cv['raw_text_preview'][:100]}...")

    # Close connection
    processor.disconnect_db()


if __name__ == "__main__":
    main()