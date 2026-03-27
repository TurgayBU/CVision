"""
job_analyzer.py
İş ilanı URL'sinden metin çeker ve Groq AI ile analiz eder.
"""

import re
import json
import requests
from datetime import datetime
from bs4 import BeautifulSoup
import mysql.connector
from mysql.connector import Error


# ---------------------------------------------------------------------------
# Metin çekme yardımcıları
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def fetch_text_from_url(url: str, timeout: int = 15) -> str:
    """
    Verilen URL'den ham metni çeker.
    LinkedIn / Kariyer.net / Indeed gibi sitelerde çalışır;
    JS render gerektiren sayfalar için metin kısmen gelebilir.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Gereksiz tag'leri kaldır
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # Önce iş ilanı içerik alanlarını dene
        selectors = [
            # LinkedIn
            "div.description__text",
            # Indeed
            "div#jobDescriptionText",
            # Kariyer.net
            "div.job-description",
            "div.position-detail-text",
            # Genel
            "article",
            "main",
            "div[class*='job']",
            "div[class*='description']",
        ]
        for sel in selectors:
            el = soup.select_one(sel)
            if el and len(el.get_text(strip=True)) > 200:
                return _clean(el.get_text(separator="\n"))

        # Hiçbiri yoksa tüm body
        return _clean(soup.get_text(separator="\n"))

    except Exception as exc:
        raise RuntimeError(f"URL'den metin çekilemedi: {exc}") from exc


def _clean(text: str) -> str:
    """Gereksiz boşlukları ve tekrarlayan satırları temizler."""
    lines = [ln.strip() for ln in text.splitlines()]
    seen, result = set(), []
    for ln in lines:
        if ln and ln not in seen:
            seen.add(ln)
            result.append(ln)
    return "\n".join(result)


# ---------------------------------------------------------------------------
# AI Prompt
# ---------------------------------------------------------------------------

JOB_ANALYSIS_PROMPT = """
Sen bir işe alım uzmanı ve metin analistisin.
Verilen iş ilanı metnini detaylıca analiz edip YALNIZCA geçerli bir JSON nesnesi döndür.
Başka hiçbir şey yazma — ne açıklama, ne markdown, ne ``` bloğu.

İş İlanı Metni:
{raw_text}

Döndüreceğin JSON şeması (bilinmeyenleri null bırak):
{{
  "job_title": "string",
  "department": "string|null",
  "employment_type": "full_time|part_time|contract|internship|freelance|null",
  "location": {{
    "city": "string|null",
    "district": "string|null",
    "country": "string",
    "is_remote": true/false,
    "work_type": "onsite|hybrid|remote"
  }},
  "skills": {{
    "required": ["string"],
    "preferred": ["string"]
  }},
  "experience": {{
    "min_years": number|null,
    "max_years": number|null,
    "description": "string|null"
  }},
  "education": {{
    "min_level": "none|primary|high_school|associate|bachelor|master|phd",
    "preferred_fields": ["string"],
    "description": "string|null"
  }},
  "languages": [
    {{
      "language": "string",
      "level": "a1|a2|b1|b2|c1|c2|ana_dil",
      "is_required": true/false
    }}
  ],
  "salary": {{
    "min": number|null,
    "max": number|null,
    "currency": "TRY|USD|EUR|null",
    "is_negotiable": true/false
  }},
  "benefits": ["string"],
  "company_name": "string|null",
  "analysis_metadata": {{
    "completeness_score": number,
    "missing_fields": ["string"]
  }}
}}
""".strip()


# ---------------------------------------------------------------------------
# Ana sınıf
# ---------------------------------------------------------------------------

class JobAnalyzer:
    """
    İş ilanı analizi:
      - URL veya ham metin kabul eder
      - Groq API ile JSON analizi yapar
      - MySQL'e kaydeder
    """

    def __init__(self, db_config: dict, groq_api_key: str,
                 model: str = "llama-3.3-70b-versatile"):
        self.db_config = db_config
        self.groq_api_key = groq_api_key
        self.model = model
        self._conn = None
        self._connect_db()

    # ------------------------------------------------------------------
    # DB
    # ------------------------------------------------------------------

    def _connect_db(self):
        try:
            self._conn = mysql.connector.connect(**self.db_config)
        except Error as e:
            print(f"[JobAnalyzer] DB bağlantı hatası: {e}")
            self._conn = None

    def disconnect(self):
        if self._conn and self._conn.is_connected():
            self._conn.close()

    def _cursor(self):
        if not self._conn or not self._conn.is_connected():
            self._connect_db()
        return self._conn.cursor(dictionary=True)

    # ------------------------------------------------------------------
    # Metin alma
    # ------------------------------------------------------------------

    def get_raw_text(self, source: str) -> tuple[str, str]:
        """
        source: URL ya da düz metin.
        Döner: (raw_text, source_url_or_empty)
        """
        if source.startswith("http://") or source.startswith("https://"):
            return fetch_text_from_url(source), source
        return source, ""

    # ------------------------------------------------------------------
    # AI analizi
    # ------------------------------------------------------------------

    def analyze_with_ai(self, raw_text: str) -> dict:
        """Groq API'ye istek atar, JSON parse eder."""
        prompt = JOB_ANALYSIS_PROMPT.format(raw_text=raw_text[:6000])

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 2000,
        }
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }

        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()

        # Bazen model ``` bloğuna sarabilir; temizle
        content = re.sub(r"^```[a-z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)

        return json.loads(content)

    # ------------------------------------------------------------------
    # DB kayıt
    # ------------------------------------------------------------------

    def save_to_db(self, user_id: int, raw_text: str,
                   analysis: dict, source_url: str = "") -> int | None:
        """
        job_analyses tablosuna kaydeder.
        Tablo yoksa otomatik oluşturur.
        Döner: job_analysis_id
        """
        self._ensure_table()
        cursor = self._cursor()
        try:
            loc = analysis.get("location", {})
            skills = analysis.get("skills", {})
            exp = analysis.get("experience", {})
            edu = analysis.get("education", {})
            sal = analysis.get("salary", {})
            meta = analysis.get("analysis_metadata", {})

            cursor.execute("""
                INSERT INTO job_analyses (
                    user_id, source_url, raw_text,
                    job_title, department, employment_type, company_name,
                    location_city, location_district, location_country,
                    is_remote, work_type,
                    required_skills, preferred_skills,
                    exp_min_years, exp_max_years, exp_description,
                    edu_min_level, edu_preferred_fields, edu_description,
                    languages, salary_min, salary_max, salary_currency,
                    salary_negotiable, benefits,
                    completeness_score, missing_fields,
                    full_analysis_json, analyzed_at
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s
                )
            """, (
                user_id,
                source_url,
                raw_text[:5000],
                analysis.get("job_title"),
                analysis.get("department"),
                analysis.get("employment_type"),
                analysis.get("company_name"),
                loc.get("city"),
                loc.get("district"),
                loc.get("country"),
                loc.get("is_remote", False),
                loc.get("work_type"),
                json.dumps(skills.get("required", []), ensure_ascii=False),
                json.dumps(skills.get("preferred", []), ensure_ascii=False),
                exp.get("min_years"),
                exp.get("max_years"),
                exp.get("description"),
                edu.get("min_level"),
                json.dumps(edu.get("preferred_fields", []), ensure_ascii=False),
                edu.get("description"),
                json.dumps(analysis.get("languages", []), ensure_ascii=False),
                sal.get("min"),
                sal.get("max"),
                sal.get("currency"),
                sal.get("is_negotiable", False),
                json.dumps(analysis.get("benefits", []), ensure_ascii=False),
                meta.get("completeness_score", 0),
                json.dumps(meta.get("missing_fields", []), ensure_ascii=False),
                json.dumps(analysis, ensure_ascii=False),
                datetime.now(),
            ))
            self._conn.commit()
            return cursor.lastrowid
        except Error as e:
            print(f"[JobAnalyzer] DB kayıt hatası: {e}")
            self._conn.rollback()
            return None
        finally:
            cursor.close()

    def _ensure_table(self):
        """job_analyses tablosunu yoksa oluşturur."""
        cursor = self._cursor()
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS job_analyses (
                    job_analysis_id   INT AUTO_INCREMENT PRIMARY KEY,
                    user_id           INT NOT NULL,
                    source_url        VARCHAR(1000),
                    raw_text          TEXT,
                    job_title         VARCHAR(255),
                    department        VARCHAR(255),
                    employment_type   VARCHAR(50),
                    company_name      VARCHAR(255),
                    location_city     VARCHAR(100),
                    location_district VARCHAR(100),
                    location_country  VARCHAR(100),
                    is_remote         TINYINT(1) DEFAULT 0,
                    work_type         VARCHAR(20),
                    required_skills   JSON,
                    preferred_skills  JSON,
                    exp_min_years     FLOAT,
                    exp_max_years     FLOAT,
                    exp_description   TEXT,
                    edu_min_level     VARCHAR(50),
                    edu_preferred_fields JSON,
                    edu_description   TEXT,
                    languages         JSON,
                    salary_min        FLOAT,
                    salary_max        FLOAT,
                    salary_currency   VARCHAR(10),
                    salary_negotiable TINYINT(1) DEFAULT 0,
                    benefits          JSON,
                    completeness_score FLOAT DEFAULT 0,
                    missing_fields    JSON,
                    full_analysis_json JSON,
                    analyzed_at       DATETIME,
                    INDEX idx_user (user_id),
                    INDEX idx_title (job_title)
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """)
            self._conn.commit()
        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # Kullanıcının ilanlarını listele
    # ------------------------------------------------------------------

    def get_user_jobs(self, user_id: int) -> list[dict]:
        cursor = self._cursor()
        try:
            cursor.execute("""
                SELECT job_analysis_id, job_title, company_name,
                       location_city, work_type, employment_type,
                       completeness_score, analyzed_at, source_url
                FROM job_analyses
                WHERE user_id = %s
                ORDER BY analyzed_at DESC
            """, (user_id,))
            rows = cursor.fetchall()
            for r in rows:
                if isinstance(r.get("analyzed_at"), datetime):
                    r["analyzed_at"] = r["analyzed_at"].isoformat()
            return rows
        finally:
            cursor.close()

    def get_job_detail(self, job_analysis_id: int, user_id: int) -> dict | None:
        cursor = self._cursor()
        try:
            cursor.execute("""
                SELECT * FROM job_analyses
                WHERE job_analysis_id = %s AND user_id = %s
            """, (job_analysis_id, user_id))
            row = cursor.fetchone()
            if row:
                for key in ("required_skills", "preferred_skills", "languages",
                            "edu_preferred_fields", "benefits",
                            "missing_fields", "full_analysis_json"):
                    if isinstance(row.get(key), str):
                        row[key] = json.loads(row[key])
                if isinstance(row.get("analyzed_at"), datetime):
                    row["analyzed_at"] = row["analyzed_at"].isoformat()
            return row
        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # Ana akış (tek çağrı)
    # ------------------------------------------------------------------

    def run(self, user_id: int, source: str) -> dict:
        """
        source: URL ya da ham metin
        Döner: {
            'job_analysis_id': int,
            'analysis': dict,
            'needs_more_info': bool,
            'missing_fields': list
        }
        """
        raw_text, source_url = self.get_raw_text(source)
        if len(raw_text.strip()) < 50:
            raise ValueError("İş ilanı metni çok kısa veya okunamadı.")

        analysis = self.analyze_with_ai(raw_text)
        job_id = self.save_to_db(user_id, raw_text, analysis, source_url)
        missing = analysis.get("analysis_metadata", {}).get("missing_fields", [])

        return {
            "job_analysis_id": job_id,
            "analysis": analysis,
            "needs_more_info": bool(missing),
            "missing_fields": missing,
        }