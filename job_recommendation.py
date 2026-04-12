import mysql
from mysql.connector import Error
import config
def get_db():
    try:
        return mysql.connector.connect(**config.DB_CONFIG)
    except Error as e:
        print(f"Veritabanı bağlantı hatası: {e}")
        return None


class MinHeap:
    """
    (score, job_analysis_id) çiftlerini tutan min-heap.
    Heap'in tepesi her zaman en düşük skorlu ilanı gösterir.
    Böylece sabit boyutlu (k=3) heap'te en yüksek skorlu k ilanı tutulur.
    """

    def __init__(self, max_size=3):
        self.heap = []
        self.max_size = max_size

    def parent(self, index):
        return (index - 1) // 2

    def left_child(self, index):
        return 2 * index + 1

    def right_child(self, index):
        return 2 * index + 2

    def insert(self, score, job_analysis_id):
        """
        Yeni bir (score, job_id) çifti ekler.
        Heap max_size dolmamışsa direkt ekle.
        Doluysa: yeni skor heap tepesindeki (en küçük) skordan büyükse,
        tepedekini çıkar, yenisini ekle.
        """
        entry = (score, job_analysis_id)

        if len(self.heap) < self.max_size:
            self.heap.append(entry)
            self._heapify_up(len(self.heap) - 1)
        elif score > self.heap[0][0]:
            self.heap[0] = entry
            self._heapify_down(0)

    def _heapify_up(self, index):
        """Yeni eklenen elemanı yukarı taşır (heap özelliğini korur)."""
        while index > 0:
            p = self.parent(index)
            if self.heap[index][0] < self.heap[p][0]:
                self.heap[index], self.heap[p] = self.heap[p], self.heap[index]
                index = p
            else:
                break

    def _heapify_down(self, index):
        """Tepedeki elemanı aşağı taşır (heap özelliğini korur)."""
        size = len(self.heap)
        while True:
            smallest = index
            left = self.left_child(index)
            right = self.right_child(index)

            if left < size and self.heap[left][0] < self.heap[smallest][0]:
                smallest = left
            if right < size and self.heap[right][0] < self.heap[smallest][0]:
                smallest = right

            if smallest != index:
                self.heap[index], self.heap[smallest] = self.heap[smallest], self.heap[index]
                index = smallest
            else:
                break

    def peek_min(self):
        """En düşük skorlu elemanı döndürür (çıkarmaz)."""
        return self.heap[0] if self.heap else None

    def pop_min(self):
        """En düşük skorlu elemanı çıkarır ve döndürür."""
        if not self.heap:
            return None
        if len(self.heap) == 1:
            return self.heap.pop()
        min_val = self.heap[0]
        self.heap[0] = self.heap.pop()
        self._heapify_down(0)
        return min_val

    def get_sorted_desc(self):
        """Heap içeriğini en yüksek skordan en düşüğe sıralı döndürür."""
        return sorted(self.heap, key=lambda x: x[0], reverse=True)

    def size(self):
        return len(self.heap)

    def is_empty(self):
        return len(self.heap) == 0

    def __str__(self):
        return str(self.heap)


class JobRecommendation:
    def __init__(self, user_id, cv_text_id, top_n=3):
        self.user_id = user_id
        self.cv_text_id = cv_text_id
        self.top_n = top_n
        self.heap = MinHeap(max_size=top_n)

    # ──────────────────────────────────────────────────────────────
    # Veritabanı yardımcıları
    # ──────────────────────────────────────────────────────────────

    def get_cv_analysis_from_db(self):
        """CV analiz sonuçlarını döndürür: [address, skills, experience, education, languages]"""
        conn = get_db()
        if not conn:
            return None
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT cv_address, cv_skills, cv_experience, cv_education, cv_languages
                FROM cv_analyses
                WHERE user_id = %s AND cv_text_id = %s
                ORDER BY analyzed_at DESC
                LIMIT 1
            """, (self.user_id, self.cv_text_id))
            result = cursor.fetchone()
            if result:
                return result
            return None
        except Error as e:
            print(f"CV getirme hatası: {e}")
            return None
        finally:
            cursor.close()
            conn.close()

    def get_job_analysis_from_db(self, job_analysis_id):
        """Belirli bir iş ilanı analizini döndürür."""
        conn = get_db()
        if not conn:
            return None
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT job_analysis_id, job_title, company_name, source_url,
                       location_city, location_country,
                       required_skills, preferred_skills,
                       edu_min_level, edu_description, languages,
                       exp_min_years, exp_max_years
                FROM job_analyses
                WHERE job_analysis_id = %s
                LIMIT 1
            """, (job_analysis_id,))
            return cursor.fetchone()
        except Error as e:
            print(f"Job getirme hatası: {e}")
            return None
        finally:
            cursor.close()
            conn.close()

    def get_max_job_analysis_id(self):
        """Veritabanındaki en yüksek job_analysis_id değerini döndürür."""
        conn = get_db()
        if not conn:
            return 0
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT MAX(job_analysis_id) FROM job_analyses")
            result = cursor.fetchone()
            return result[0] if result and result[0] else 0
        except Error as e:
            print(f"Max ID getirme hatası: {e}")
            return 0
        finally:
            cursor.close()
            conn.close()

    # ──────────────────────────────────────────────────────────────
    # Puanlama
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_skills(raw):
        """JSON veya virgüllü string'den beceri listesi üretir."""
        import json
        if not raw:
            return []
        if isinstance(raw, list):
            return [str(s).strip().lower() for s in raw]
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                items = []
                for p in parsed:
                    if isinstance(p, dict):
                        items.append(str(p.get('skill', p.get('name', ''))).strip().lower())
                    else:
                        items.append(str(p).strip().lower())
                return [i for i in items if i]
        except (json.JSONDecodeError, TypeError):
            pass
        return [s.strip().lower() for s in str(raw).split(',') if s.strip()]

    def calculate_score(self, cv_data, job_data):
        """
        CV ile iş ilanını karşılaştırarak 0-100 arası puan döndürür.

        Ağırlıklar:
          - Zorunlu beceri eşleşmesi : 50 puan (max)
          - Tercih edilen beceri      : 20 puan (max)
          - Şehir eşleşmesi          : 15 puan
          - Dil eşleşmesi            : 10 puan
          - Eğitim eşleşmesi         :  5 puan
        """
        if not cv_data or not job_data:
            return 0

        score = 0

        # 1. Zorunlu beceriler (50 puan)
        cv_skills = self._parse_skills(cv_data.get('cv_skills'))
        req_skills = self._parse_skills(job_data.get('required_skills'))
        if req_skills:
            matched = sum(1 for s in req_skills if s in cv_skills)
            score += int((matched / len(req_skills)) * 50)

        # 2. Tercih edilen beceriler (20 puan)
        pref_skills = self._parse_skills(job_data.get('preferred_skills'))
        if pref_skills:
            matched_pref = sum(1 for s in pref_skills if s in cv_skills)
            score += int((matched_pref / len(pref_skills)) * 20)

        # 3. Şehir eşleşmesi (15 puan)
        # cv_address içinde iş şehrini arar
        cv_address = str(cv_data.get('cv_address', '')).lower()
        job_city = str(job_data.get('location_city', '')).lower()
        job_country = str(job_data.get('location_country', '')).lower()
        if job_city and job_city in cv_address:
            score += 15
        elif job_country and job_country in cv_address:
            score += 7  # Ülke eşleşmesi kısmi puan

        # 4. Dil eşleşmesi (10 puan)
        cv_langs = str(cv_data.get('cv_languages', '')).lower()
        job_langs = self._parse_skills(job_data.get('languages'))
        if job_langs:
            matched_lang = sum(1 for lang in job_langs if lang in cv_langs)
            score += int((matched_lang / len(job_langs)) * 10)

        # 5. Eğitim eşleşmesi (5 puan)
        edu_keywords = ['lisans', 'bachelor', 'master', 'yüksek lisans',
                        'doktora', 'phd', 'önlisans', 'associate']
        cv_edu = str(cv_data.get('cv_education', '')).lower()
        job_edu = str(job_data.get('edu_min_level', '') or
                      job_data.get('edu_description', '')).lower()
        for kw in edu_keywords:
            if kw in job_edu and kw in cv_edu:
                score += 5
                break

        return min(score, 100)

    # ──────────────────────────────────────────────────────────────
    # Ana analiz akışı
    # ──────────────────────────────────────────────────────────────

    def analyze_competitivity(self):
        """
        Tüm iş ilanlarını CV ile karşılaştırır.
        En yüksek skorlu top_n ilanı MinHeap'te tutar.
        Dönen değer: [(score, job_analysis_id), ...] yüksekten düşüğe sıralı
        """
        cv_data = self.get_cv_analysis_from_db()
        if not cv_data:
            print(f"Kullanıcı {self.user_id} için CV analizi bulunamadı.")
            return []

        max_id = self.get_max_job_analysis_id()
        if max_id == 0:
            print("Veritabanında iş ilanı bulunamadı.")
            return []

        for job_id in range(1, max_id + 1):
            job_data = self.get_job_analysis_from_db(job_id)
            if not job_data:
                continue  # Silinmiş / var olmayan kayıt, atla

            score = self.calculate_score(cv_data, job_data)
            self.heap.insert(score, job_id)

        return self.heap.get_sorted_desc()

    def recommend_jobs(self):
        """
        En uygun iş ilanlarının detaylarını döndürür.
        Format: [{'score': int, 'job': dict}, ...]
        """
        top_matches = self.analyze_competitivity()
        recommendations = []

        for score, job_id in top_matches:
            job_data = self.get_job_analysis_from_db(job_id)
            if job_data:
                recommendations.append({
                    'score': score,
                    'job': job_data
                })

        return recommendations