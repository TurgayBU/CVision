import mysql.connector
from config import DB_CONFIG, api_key
from groq import Groq
import time
from functools import wraps
import json
import re

class AICVResponseGroq:
    def __init__(self, db_config, api_key):
        self.db_config = db_config
        self.connection = None
        self.api_key = api_key

        # Create Groq client
        self.client = Groq(api_key=api_key)
        # Model to use
        self.model = "llama-3.3-70b-versatile"

    def connect(self):
        try:
            self.connection = mysql.connector.connect(**self.db_config)
            print("✅ MySQL connection successful")
            return True
        except Exception as e:
            print(f"❌ MySQL connection error: {e}")
            return False

    def disconnect(self):
        if self.connection and self.connection.is_connected():
            self.connection.close()
            print("🔌 MySQL connection closed")

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
            print(f"❌ CV text not found: user_id={user_id}, cv_text_id={cv_text_id}")
            return None

        except Exception as e:
            print(f"❌ Database query error: {e}")
            return None

    def rate_limit(max_per_minute=30):
        """Limit maximum number of requests per minute"""
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

    @rate_limit(max_per_minute=25)
    def PromptingAI(self, raw_text):
        if not self.api_key:
            print("❌ API key not found")
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

            print("🔄 Sending request to Groq API...")

            # Groq API call
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
                print("✅ Groq API response received")
                return self.ParseResponse(ai_response)
            else:
                print("❌ API response is empty")
                return None

        except Exception as e:
            print(f"❌ AI query error: {e}")
            return None

    @rate_limit(max_per_minute=20)
    def GenerateCVEnhancements(self, raw_text, cv_data):
        """
        CV'ye göre eksik yetenekler, öğrenme yol haritası ve CV iyileştirme önerileri üretir.
        """

        if not self.api_key:
            print("❌ API key not found")
            return None

        try:
            prompt = f"""
    You are a professional IT recruiter and career coach.

    Analyze this CV and generate:
    1. Missing technical skills
    2. Learning roadmap for missing skills
    3. CV improvement suggestions

    CV Raw Text:
    {raw_text[:6000]}

    Extracted CV Data:
    Address: {cv_data[0] if len(cv_data) > 0 else ""}
    Skills: {cv_data[1] if len(cv_data) > 1 else ""}
    Experience: {cv_data[2] if len(cv_data) > 2 else ""}
    Education: {cv_data[3] if len(cv_data) > 3 else ""}
    Languages: {cv_data[4] if len(cv_data) > 4 else ""}

    Return ONLY valid JSON. Do not write markdown. Do not use ```.

    JSON format:
    {{
      "missing_skills": [
        {{
          "skill": "Docker",
          "priority": "high",
          "reason": "Docker is commonly expected in backend and DevOps-related IT roles.",
          "roadmap": [
            "Learn containers and images",
            "Create a Dockerfile for a simple Flask app",
            "Run Flask and MySQL using Docker Compose",
            "Add the Dockerized project to your CV"
          ],
          "estimated_time": "1 week"
        }}
      ],
      "cv_improvements": [
        {{
          "section": "Experience",
          "problem": "The experience description is too general.",
          "original": "Worked on backend development.",
          "improved": "Developed REST APIs using Flask and MySQL, implemented authentication, and improved database-driven workflows."
        }}
      ],
      "general_advice": [
        "Add measurable achievements where possible.",
        "Mention technologies used in each project.",
        "Use action verbs such as developed, implemented, optimized, designed."
      ]
    }}
    """

            print("🔄 Sending CV enhancement request to Groq API...")

            chat_completion = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert CV reviewer, IT recruiter, and career advisor."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                model=self.model,
                temperature=0.4,
                max_tokens=1800,
                top_p=0.9,
                stream=False
            )

            content = chat_completion.choices[0].message.content.strip()

            # Bazen model ```json bloğu döndürebilir, temizliyoruz.
            content = re.sub(r"^```json\s*", "", content)
            content = re.sub(r"^```\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

            return json.loads(content)

        except Exception as e:
            print(f"❌ CV enhancement error: {e}")
            return {
                "missing_skills": [],
                "cv_improvements": [],
                "general_advice": [
                    "CV improvement analysis could not be generated."
                ]
            }

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

            print("✅ API response parsed")
            return [cv_address, cv_skills, cv_experience, cv_education, cv_languages]

        except Exception as e:
            print(f"❌ Parse error: {e}")
            return [cv_address, cv_skills, cv_experience, cv_education, cv_languages]

    def CheckMechanism(self, CV):
        try:
            print("\n📋 Please confirm the CV information:")
            print(f"📍 Address: {CV[0]}")
            print(f"💻 Skills: {CV[1]}")
            print(f"💼 Experience: {CV[2]}")
            print(f"🎓 Education: {CV[3]}")
            print(f"🗣️ Languages: {CV[4]}")

            while True:
                confirm = input("\n✅ Is this information correct? (yes/no): ").strip().lower()
                if confirm in ['yes', 'y']:
                    return True
                elif confirm in ['no', 'n']:
                    return False
                else:
                    print("Please type 'yes' or 'no'")

        except Exception as e:
            print(f"❌ Confirmation error: {e}")
            return False

    def SaveInDatabase(self, CV, user_id=None, cv_text_id=None):
        try:
            if not self.connection or not self.connection.is_connected():
                self.connect()

            if cv_text_id is None:
                print("❌ cv_text_id is required!")
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

            query = """
            INSERT INTO cv_analyses 
            (user_id, cv_text_id, cv_address, cv_skills, cv_experience, cv_education, cv_languages) 
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """

            values = (
                user_id,
                cv_text_id,
                cv_address,
                cv_skills_json,
                cv_experience_json,
                cv_education_json,
                cv_languages_json
            )

            print(f"📝 Data to be saved: {values}")
            print(f"📝 Query: {query}")

            cursor.execute(query, values)
            self.connection.commit()

            print("✅ Saved to database")
            cursor.close()
            return True

        except Exception as e:
            print(f"❌ Database save error: {e}")
            return False

# Test function
def test_analysis():
    """Analyze a specific cv_text_id"""
    user_id = 4
    cv_text_id = 1

    ai = AICVResponseGroq(DB_CONFIG, api_key)

    try:
        # Get CV text
        raw_text = ai.Get_CV_Text(user_id, cv_text_id)

        if raw_text:
            print(f"📄 CV text retrieved ({len(raw_text)} characters)")

            # Analyze with AI
            cv_data = ai.PromptingAI(raw_text)

            if cv_data:
                print("\n📊 ANALYSIS RESULTS:")
                print(f"📍 Address: {cv_data[0]}")
                print(f"💻 Skills: {cv_data[1]}")
                print(f"💼 Experience: {cv_data[2]}")
                print(f"🎓 Education: {cv_data[3]}")
                print(f"🗣️ Languages: {cv_data[4]}")

                # Ask for confirmation
                if ai.CheckMechanism(cv_data):
                    ai.SaveInDatabase(cv_data, user_id)
                else:
                    print("❌ Operation cancelled")
            else:
                print("❌ Analysis failed")
        else:
            print("❌ CV text not found")

    finally:
        ai.disconnect()


if __name__ == "__main__":
    test_analysis()