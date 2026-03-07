import mysql.connector
from config import DB_CONFIG, api_key  # config.py'da groq_api_key tanımlı olmalı
from groq import Groq  # Groq kütüphanesini import et
import time
from functools import wraps

class AICVResponseGroq:  # Sınıf adını değiştirelim (isteğe bağlı)
    def __init__(self, db_config, api_key):
        self.db_config = db_config
        self.connection = None
        self.api_key = api_key

        # Groq istemcisini oluştur
        self.client = Groq(api_key=api_key)
        # Kullanılacak model (ücretsiz ve güçlü)
        self.model = "llama-3.3-70b-versatile"  # veya "mixtral-8x7b-32768", "gemma2-9b-it"

    def connect(self):
        try:
            self.connection = mysql.connector.connect(**self.db_config)
            print("✅ MySQL bağlantısı başarılı")
            return True
        except Exception as e:
            print(f"❌ MySQL bağlantı hatası: {e}")
            return False

    def disconnect(self):
        if self.connection and self.connection.is_connected():
            self.connection.close()
            print("🔌 MySQL bağlantısı kapatıldı")

    def Get_CV_Text(self, user_id, cv_text_id):
        try:
            if not self.connection or not self.connection.is_connected():
                self.connect()

            query = "SELECT raw_text FROM cv_text WHERE user_id = %s AND cv_text_id = %s"
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute(query, (user_id, cv_text_id))
            result = cursor.fetchone()
            cursor.close()

            if result:
                return result['raw_text']
            print(f"❌ CV metni bulunamadı: user_id={user_id}, cv_text_id={cv_text_id}")
            return None

        except Exception as e:
            print(f"❌ Veritabanı sorgu hatası: {e}")
            return None

    def rate_limit(max_per_minute=30):
        """Dakikada maksimum istek sayısını sınırla"""
        min_interval = 60.0 / max_per_minute
        last_called = [0.0]

        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                elapsed = time.time() - last_called[0]
                left_to_wait = min_interval - elapsed
                if left_to_wait > 0:
                    time.sleep(left_to_wait)
                ret = func(*args, **kwargs)
                last_called[0] = time.time()
                return ret

            return wrapper

        return decorator

    # PromptingAI metodunun üstüne @rate_limit() ekle
    @rate_limit(max_per_minute=25)
    def PromptingAI(self, raw_text):
        if not self.api_key:
            print("❌ API anahtarı bulunamadı")
            return None

        try:
            prompt = f"""In this mission you have to categorize the following CV raw text to following schema of database:
`user_id`,`cv_address`,`cv_skills`,`cv_experience`,`cv_education`,`cv_languages`

Here are the rules:
1) cv_address should be coming from this cv
2) cv_skills should be relevant to programming skills or IT job's skills
3) cv_experience is what written in CV don't need to do anything extra
4) cv_education should be translated to English even if it written in any other language rather than English
5) cv_language should be understood as language that people communicate, not like any coding language
6) Coding language's should be under the cv_skills part

Finally here is the raw text of cv:
{raw_text}

Give the answers exactly in this format (each on new line):
cv_address='Answer is here'
cv_skills='Answer is here'
cv_experience='Answer is here'
cv_education='Answer is here'
cv_languages='Answer is here'
"""

            print("🔄 Groq API'ye istek gönderiliyor...")

            # Groq API çağrısı
            chat_completion = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a CV analysis expert that extracts structured information from CV texts."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                model=self.model,
                temperature=0.3,
                max_tokens=1000,
                top_p=0.9,
                stream=False
            )

            if chat_completion and chat_completion.choices:
                ai_response = chat_completion.choices[0].message.content
                print("✅ Groq API yanıtı alındı")
                return self.ParseResponse(ai_response)
            else:
                print("❌ API yanıtı boş")
                return None

        except Exception as e:
            print(f"❌ AI sorgulama hatası: {e}")
            return None

    def ParseResponse(self, response):
        cv_address = ""
        cv_skills = ""
        cv_experience = ""
        cv_education = ""
        cv_languages = ""

        try:
            lines = response.strip().split('\n')
            for line in lines:
                if '=' in line:
                    parts = line.split('=', 1)
                    key = parts[0].strip()
                    value = parts[1].strip().strip("'\"")

                    if 'address' in key:
                        cv_address = value
                    elif 'skills' in key:
                        cv_skills = value
                    elif 'experience' in key:
                        cv_experience = value
                    elif 'education' in key:
                        cv_education = value
                    elif 'languages' in key or 'language' in key:
                        cv_languages = value

            print("✅ API yanıtı parse edildi")
            return [cv_address, cv_skills, cv_experience, cv_education, cv_languages]

        except Exception as e:
            print(f"❌ Parse hatası: {e}")
            return [cv_address, cv_skills, cv_experience, cv_education, cv_languages]

    def CheckMechanism(self, CV):
        try:
            print("\n📋 Lütfen CV bilgilerini onaylayın:")
            print(f"📍 Adres: {CV[0]}")
            print(f"💻 Yetenekler: {CV[1]}")
            print(f"💼 Deneyim: {CV[2]}")
            print(f"🎓 Eğitim: {CV[3]}")
            print(f"🗣️ Diller: {CV[4]}")

            while True:
                confirm = input("\n✅ Bu bilgiler doğru mu? (evet/hayır): ").strip().lower()
                if confirm in ['evet', 'e', 'yes', 'y']:
                    return True
                elif confirm in ['hayır', 'h', 'hayir', 'no', 'n']:
                    return False
                else:
                    print("Lütfen 'evet' veya 'hayır' yazın")

        except Exception as e:
            print(f"❌ Onay hatası: {e}")
            return False

    def SaveInDatabase(self, CV, user_id=None, cv_text_id=None):
        try:
            if not self.connection or not self.connection.is_connected():
                self.connect()

            if cv_text_id is None:
                print("❌ cv_text_id zorunlu!")
                return False

            cursor = self.connection.cursor()

            import json

            def parse_to_json_array(text):
                if not text:
                    return json.dumps([])
                if text.strip().startswith('[') and text.strip().endswith(']'):
                    return text
                lines = [line.strip() for line in text.split('\n') if line.strip()]
                if lines:
                    return json.dumps(lines)
                items = [item.strip() for item in text.split(',') if item.strip()]
                if items:
                    return json.dumps(items)
                return json.dumps([text])

            cv_skills_json = parse_to_json_array(CV[1])
            cv_experience_json = parse_to_json_array(CV[2])
            cv_education_json = parse_to_json_array(CV[3])
            cv_languages_json = parse_to_json_array(CV[4])

            cv_address = CV[0][:200] if CV[0] else ''

            # Sorguda 7 değer olmalı: user_id, cv_text_id, cv_address, cv_skills, cv_experience, cv_education, cv_languages
            query = """
            INSERT INTO cv_analyses 
            (user_id, cv_text_id, cv_address, cv_skills, cv_experience, cv_education, cv_languages) 
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """

            values = (
                user_id,
                cv_text_id,  # BU SATIR EKLENMİŞ OLMALI!
                cv_address,
                cv_skills_json,
                cv_experience_json,
                cv_education_json,
                cv_languages_json
            )

            print(f"📝 Kaydedilecek veri: {values}")
            print(f"📝 Sorgu: {query}")

            cursor.execute(query, values)
            self.connection.commit()

            print("✅ Veritabanına kaydedildi")
            cursor.close()
            return True

        except Exception as e:
            print(f"❌ Veritabanı kayıt hatası: {e}")
            return False
# Test fonksiyonu
def test_analysis():
    """Belirli bir cv_text_id'yi analiz et"""
    user_id = 4
    cv_text_id = 1  # Turgay'ın CV'si

    # config.py'dan groq_api_key'i al
    ai = AICVResponseGroq(DB_CONFIG, api_key)

    try:
        # CV metnini al
        raw_text = ai.Get_CV_Text(user_id, cv_text_id)

        if raw_text:
            print(f"📄 CV metni alındı ({len(raw_text)} karakter)")

            # AI ile analiz et
            cv_data = ai.PromptingAI(raw_text)

            if cv_data:
                print("\n📊 ANALİZ SONUÇLARI:")
                print(f"📍 Adres: {cv_data[0]}")
                print(f"💻 Yetenekler: {cv_data[1]}")
                print(f"💼 Deneyim: {cv_data[2]}")
                print(f"🎓 Eğitim: {cv_data[3]}")
                print(f"🗣️ Diller: {cv_data[4]}")

                # Onay iste
                if ai.CheckMechanism(cv_data):
                    ai.SaveInDatabase(cv_data, user_id)
                else:
                    print("❌ İşlem iptal edildi")
            else:
                print("❌ Analiz başarısız")
        else:
            print("❌ CV metni bulunamadı")

    finally:
        ai.disconnect()


if __name__ == "__main__":
    test_analysis()