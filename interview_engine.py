"""
interview_engine.py
İş ilanı + CV verisi üzerinden mülakat soruları üretir,
kullanıcı cevaplarını değerlendirir ve DB'ye kaydeder.
"""

import json
import re
import requests
from datetime import datetime
import mysql.connector
from mysql.connector import Error


# ---------------------------------------------------------------------------
# Prompt şablonları
# ---------------------------------------------------------------------------

QUESTION_GEN_PROMPT = """
Sen deneyimli bir teknik işe alım uzmanısın.
Aşağıdaki iş ilanı ve aday CV bilgilerini kullanarak bu pozisyon için mülakat soruları hazırla.

İŞ İLANI BİLGİLERİ:
- Pozisyon: {job_title}
- Şirket: {company}
- Zorunlu Beceriler: {required_skills}
- Tercih Edilen Beceriler: {preferred_skills}
- Deneyim: {experience}
- Eğitim: {education}

ADAY CV BİLGİLERİ:
- Beceriler: {cv_skills}
- Deneyim: {cv_experience}
- Eğitim: {cv_education}
- Diller: {cv_languages}

YALNIZCA geçerli bir JSON nesnesi döndür, başka hiçbir şey yazma.

Şu kategorilerde toplam {total_count} soru üret:
- technical: {tech_count} soru (teknik/pozisyona özel)
- behavioral: {behav_count} soru (davranışsal, STAR metoduna uygun)
- situational: {sit_count} soru (senaryo tabanlı)
- cv_based: {cv_count} soru (CV'deki boşluklar/güçlü noktalar üzerine)

JSON formatı:
{{
  "questions": [
    {{
      "id": 1,
      "category": "technical|behavioral|situational|cv_based",
      "difficulty": "easy|medium|hard",
      "question": "Soru metni",
      "hint": "Değerlendirici için ipucu (kullanıcıya gösterilmez)",
      "ideal_answer_points": ["Beklenen cevap noktası 1", "Nokta 2"]
    }}
  ],
  "interview_focus": "Bu mülakatta odaklanılması gereken ana konu özeti"
}}
""".strip()


EVALUATE_PROMPT = """
Sen deneyimli bir teknik işe alım uzmanısın. Aşağıdaki mülakat sorusuna verilen cevabı değerlendir.

POZİSYON: {job_title} @ {company}

SORU: {question}
KATEGORİ: {category}
ZORLUK: {difficulty}

BEKLENEN CEVAP NOKTALARI:
{ideal_points}

ADAYIN CEVABI:
{answer}

YALNIZCA geçerli bir JSON nesnesi döndür:
{{
  "score": <0-100 arası sayı>,
  "grade": "A|B|C|D|F",
  "strengths": ["Güçlü yön 1", "Güçlü yön 2"],
  "improvements": ["Geliştirilmesi gereken 1", "Geliştirilmesi gereken 2"],
  "feedback": "Detaylı geri bildirim paragrafı (2-3 cümle)",
  "model_answer_hint": "Örnek iyi cevap yönlendirmesi"
}}
""".strip()


FINAL_REPORT_PROMPT = """
Sen deneyimli bir işe alım danışmanısın. Aşağıdaki mülakat oturumunu değerlendirip kapsamlı bir rapor hazırla.

POZİSYON: {job_title} @ {company}

MÜLAKAT SONUÇLARI:
{results_json}

YALNIZCA geçerli bir JSON nesnesi döndür:
{{
  "overall_score": <0-100>,
  "overall_grade": "A|B|C|D|F",
  "hiring_recommendation": "strong_yes|yes|maybe|no|strong_no",
  "recommendation_reason": "Tavsiye gerekçesi (2-3 cümle)",
  "category_scores": {{
    "technical": <0-100 veya null>,
    "behavioral": <0-100 veya null>,
    "situational": <0-100 veya null>,
    "cv_based": <0-100 veya null>
  }},
  "top_strengths": ["En güçlü yön 1", "2", "3"],
  "critical_gaps": ["Kritik eksik 1", "2"],
  "development_plan": ["Gelişim önerisi 1", "2", "3"],
  "interview_summary": "Genel mülakat özeti paragrafı"
}}
""".strip()


# ---------------------------------------------------------------------------
# Ana sınıf
# ---------------------------------------------------------------------------

class InterviewEngine:

    def __init__(self, db_config: dict, groq_api_key: str,
                 model: str = "llama-3.3-70b-versatile"):
        self.db_config = db_config
        self.groq_api_key = groq_api_key
        self.model = model
        self._conn = None
        self._connect_db()
        self._ensure_tables()

    # ------------------------------------------------------------------
    # DB
    # ------------------------------------------------------------------

    def _connect_db(self):
        try:
            self._conn = mysql.connector.connect(**self.db_config)
        except Error as e:
            print(f"[InterviewEngine] DB bağlantı hatası: {e}")
            self._conn = None

    def disconnect(self):
        if self._conn and self._conn.is_connected():
            self._conn.close()

    def _cursor(self):
        if not self._conn or not self._conn.is_connected():
            self._connect_db()
        return self._conn.cursor(dictionary=True)

    def _ensure_tables(self):
        """Gerekli tabloları oluştur."""
        cursor = self._cursor()
        try:
            # Mülakat oturumları
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS interview_sessions (
                    session_id        INT AUTO_INCREMENT PRIMARY KEY,
                    user_id           INT NOT NULL,
                    job_analysis_id   INT,
                    cv_text_id        INT,
                    job_title         VARCHAR(255),
                    company_name      VARCHAR(255),
                    total_questions   INT DEFAULT 0,
                    answered          INT DEFAULT 0,
                    overall_score     FLOAT,
                    overall_grade     VARCHAR(5),
                    hiring_recommendation VARCHAR(20),
                    final_report_json JSON,
                    status            ENUM('active','completed','abandoned') DEFAULT 'active',
                    started_at        DATETIME,
                    completed_at      DATETIME,
                    INDEX idx_user (user_id),
                    INDEX idx_job  (job_analysis_id)
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """)

            # Mülakat soruları
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS interview_questions (
                    question_id   INT AUTO_INCREMENT PRIMARY KEY,
                    session_id    INT NOT NULL,
                    question_order INT DEFAULT 0,
                    category      VARCHAR(30),
                    difficulty    VARCHAR(10),
                    question_text TEXT,
                    hint          TEXT,
                    ideal_points  JSON,
                    user_answer   TEXT,
                    score         FLOAT,
                    grade         VARCHAR(5),
                    strengths     JSON,
                    improvements  JSON,
                    feedback      TEXT,
                    model_answer_hint TEXT,
                    answered_at   DATETIME,
                    INDEX idx_session (session_id)
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """)

            self._conn.commit()
        except Error as e:
            print(f"[InterviewEngine] Tablo oluşturma hatası: {e}")
        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # Groq API yardımcısı
    # ------------------------------------------------------------------

    def _call_groq(self, prompt: str, max_tokens: int = 2000) -> dict:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload, headers=headers, timeout=60
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        # Markdown blokları temizle
        content = re.sub(r"^```[a-z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
        return json.loads(content)

    # ------------------------------------------------------------------
    # Soru üretimi
    # ------------------------------------------------------------------

    def generate_questions(self, job_data: dict, cv_data: dict,
                           total: int = 10) -> dict:
        """
        job_data: job_analyses satırı
        cv_data:  cv_analyses satırı  (None olabilir)
        """
        # Dağılım hesapla
        tech   = max(1, round(total * 0.35))
        behav  = max(1, round(total * 0.25))
        sit    = max(1, round(total * 0.20))
        cv_q   = total - tech - behav - sit

        def _arr(v):
            if not v: return "Belirtilmemiş"
            if isinstance(v, list): return ", ".join(str(x) for x in v)
            try: return ", ".join(json.loads(v))
            except: return str(v)

        prompt = QUESTION_GEN_PROMPT.format(
            job_title        = job_data.get("job_title", "Pozisyon"),
            company          = job_data.get("company_name", "Şirket"),
            required_skills  = _arr(job_data.get("required_skills")),
            preferred_skills = _arr(job_data.get("preferred_skills")),
            experience       = f"{job_data.get('exp_min_years','?')}–{job_data.get('exp_max_years','?')} yıl",
            education        = job_data.get("edu_min_level", "Belirtilmemiş"),
            cv_skills        = cv_data.get("cv_skills",    "Belirtilmemiş") if cv_data else "CV yok",
            cv_experience    = cv_data.get("cv_experience","Belirtilmemiş") if cv_data else "CV yok",
            cv_education     = cv_data.get("cv_education", "Belirtilmemiş") if cv_data else "CV yok",
            cv_languages     = cv_data.get("cv_languages", "Belirtilmemiş") if cv_data else "CV yok",
            total_count      = total,
            tech_count       = tech,
            behav_count      = behav,
            sit_count        = sit,
            cv_count         = cv_q,
        )
        return self._call_groq(prompt, max_tokens=3000)

    # ------------------------------------------------------------------
    # Oturum başlatma
    # ------------------------------------------------------------------

    def create_session(self, user_id: int, job_analysis_id: int,
                       cv_text_id: int | None, job_data: dict,
                       cv_data: dict | None, question_count: int = 10) -> dict:
        """
        Yeni mülakat oturumu oluştur, soruları üret ve DB'ye kaydet.
        Döner: { session_id, questions: [...] }
        """
        # Soruları üret
        gen = self.generate_questions(job_data, cv_data, question_count)
        questions = gen.get("questions", [])

        cursor = self._cursor()
        try:
            # Oturumu kaydet
            cursor.execute("""
                INSERT INTO interview_sessions
                (user_id, job_analysis_id, cv_text_id, job_title, company_name,
                 total_questions, status, started_at)
                VALUES (%s,%s,%s,%s,%s,%s,'active',NOW())
            """, (
                user_id, job_analysis_id, cv_text_id,
                job_data.get("job_title"), job_data.get("company_name"),
                len(questions)
            ))
            self._conn.commit()
            session_id = cursor.lastrowid

            # Soruları kaydet
            for i, q in enumerate(questions):
                cursor.execute("""
                    INSERT INTO interview_questions
                    (session_id, question_order, category, difficulty,
                     question_text, hint, ideal_points)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                """, (
                    session_id, i + 1,
                    q.get("category"), q.get("difficulty"),
                    q.get("question"),
                    q.get("hint"),
                    json.dumps(q.get("ideal_answer_points", []), ensure_ascii=False)
                ))
            self._conn.commit()

            # question_id'leri al
            cursor.execute("""
                SELECT question_id, question_order, category, difficulty, question_text
                FROM interview_questions WHERE session_id=%s ORDER BY question_order
            """, (session_id,))
            saved_qs = cursor.fetchall()

            return {
                "session_id": session_id,
                "questions": saved_qs,
                "interview_focus": gen.get("interview_focus", ""),
                "total": len(saved_qs)
            }
        except Error as e:
            print(f"[InterviewEngine] Oturum oluşturma hatası: {e}")
            raise
        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # Cevap değerlendirme
    # ------------------------------------------------------------------

    def evaluate_answer(self, question_id: int, user_answer: str,
                        job_title: str, company: str) -> dict:
        """Tek bir cevabı değerlendir, DB'ye kaydet."""
        cursor = self._cursor()
        try:
            cursor.execute(
                "SELECT * FROM interview_questions WHERE question_id=%s",
                (question_id,)
            )
            q = cursor.fetchone()
            if not q:
                raise ValueError(f"Soru bulunamadı: {question_id}")

            ideal = q.get("ideal_points") or "[]"
            if isinstance(ideal, str):
                ideal = json.loads(ideal)
            ideal_str = "\n".join(f"- {p}" for p in ideal)

            prompt = EVALUATE_PROMPT.format(
                job_title    = job_title,
                company      = company,
                question     = q["question_text"],
                category     = q["category"],
                difficulty   = q["difficulty"],
                ideal_points = ideal_str or "Genel beklentiler",
                answer       = user_answer[:2000]
            )
            result = self._call_groq(prompt, max_tokens=1000)

            # DB güncelle
            cursor.execute("""
                UPDATE interview_questions
                SET user_answer=%s, score=%s, grade=%s,
                    strengths=%s, improvements=%s,
                    feedback=%s, model_answer_hint=%s,
                    answered_at=NOW()
                WHERE question_id=%s
            """, (
                user_answer,
                result.get("score", 0),
                result.get("grade", "F"),
                json.dumps(result.get("strengths", []), ensure_ascii=False),
                json.dumps(result.get("improvements", []), ensure_ascii=False),
                result.get("feedback", ""),
                result.get("model_answer_hint", ""),
                question_id
            ))

            # Cevaplanan sayısını artır
            cursor.execute("""
                UPDATE interview_sessions
                SET answered = answered + 1
                WHERE session_id = (
                    SELECT session_id FROM interview_questions WHERE question_id=%s
                )
            """, (question_id,))

            self._conn.commit()
            return result
        except Error as e:
            print(f"[InterviewEngine] Değerlendirme hatası: {e}")
            raise
        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # Final rapor
    # ------------------------------------------------------------------

    def finalize_session(self, session_id: int) -> dict:
        """Tüm cevapları özetleyen final raporu üret ve kaydet."""
        cursor = self._cursor()
        try:
            cursor.execute(
                "SELECT * FROM interview_sessions WHERE session_id=%s",
                (session_id,)
            )
            session = cursor.fetchone()
            if not session:
                raise ValueError("Oturum bulunamadı")

            cursor.execute("""
                SELECT category, difficulty, question_text,
                       user_answer, score, grade, feedback
                FROM interview_questions
                WHERE session_id=%s AND user_answer IS NOT NULL
                ORDER BY question_order
            """, (session_id,))
            answered = cursor.fetchall()

            if not answered:
                raise ValueError("Cevaplanmış soru yok")

            results_json = json.dumps(answered, ensure_ascii=False, default=str)
            prompt = FINAL_REPORT_PROMPT.format(
                job_title    = session.get("job_title", ""),
                company      = session.get("company_name", ""),
                results_json = results_json[:5000]
            )
            report = self._call_groq(prompt, max_tokens=1500)

            # Oturumu güncelle
            cursor.execute("""
                UPDATE interview_sessions
                SET overall_score=%s, overall_grade=%s,
                    hiring_recommendation=%s,
                    final_report_json=%s,
                    status='completed', completed_at=NOW()
                WHERE session_id=%s
            """, (
                report.get("overall_score"),
                report.get("overall_grade"),
                report.get("hiring_recommendation"),
                json.dumps(report, ensure_ascii=False),
                session_id
            ))
            self._conn.commit()
            return report
        except Error as e:
            print(f"[InterviewEngine] Final rapor hatası: {e}")
            raise
        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # Sorgular
    # ------------------------------------------------------------------

    def get_session(self, session_id: int, user_id: int) -> dict | None:
        cursor = self._cursor()
        try:
            cursor.execute("""
                SELECT * FROM interview_sessions
                WHERE session_id=%s AND user_id=%s
            """, (session_id, user_id))
            s = cursor.fetchone()
            if s and isinstance(s.get("started_at"), datetime):
                s["started_at"] = s["started_at"].isoformat()
            if s and isinstance(s.get("completed_at"), datetime):
                s["completed_at"] = s["completed_at"].isoformat()
            return s
        finally:
            cursor.close()

    def get_session_questions(self, session_id: int) -> list:
        cursor = self._cursor()
        try:
            cursor.execute("""
                SELECT question_id, question_order, category, difficulty,
                       question_text, user_answer, score, grade, feedback,
                       strengths, improvements, model_answer_hint, answered_at
                FROM interview_questions
                WHERE session_id=%s ORDER BY question_order
            """, (session_id,))
            rows = cursor.fetchall()
            for r in rows:
                for f in ("strengths", "improvements"):
                    if isinstance(r.get(f), str):
                        try: r[f] = json.loads(r[f])
                        except: pass
                if isinstance(r.get("answered_at"), datetime):
                    r["answered_at"] = r["answered_at"].isoformat()
            return rows
        finally:
            cursor.close()

    def get_user_sessions(self, user_id: int) -> list:
        cursor = self._cursor()
        try:
            cursor.execute("""
                SELECT session_id, job_title, company_name,
                       total_questions, answered, overall_score,
                       overall_grade, hiring_recommendation,
                       status, started_at, completed_at
                FROM interview_sessions
                WHERE user_id=%s ORDER BY started_at DESC
            """, (user_id,))
            rows = cursor.fetchall()
            for r in rows:
                for f in ("started_at", "completed_at"):
                    if isinstance(r.get(f), datetime):
                        r[f] = r[f].isoformat()
            return rows
        finally:
            cursor.close()