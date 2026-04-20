import mysql
from mysql.connector import Error
import config
def get_db():
    try:
        return mysql.connector.connect(**config.DB_CONFIG)
    except Error as e:
        print(f"Database connection error: {e}")
        return None


class MinHeap:
    """
    Min-heap holding (score, job_analysis_id) pairs.
    The top of the heap always points to the lowest-scored listing.
    This way, the fixed-size (k=3) heap keeps the top-k highest scored listings.
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
        Inserts a new (score, job_id) pair.
        If heap is not full, insert directly.
        If full: if new score is greater than heap top (minimum),
        remove the top and insert the new one.
        """
        entry = (score, job_analysis_id)

        if len(self.heap) < self.max_size:
            self.heap.append(entry)
            self._heapify_up(len(self.heap) - 1)
        elif score > self.heap[0][0]:
            self.heap[0] = entry
            self._heapify_down(0)

    def _heapify_up(self, index):
        """Moves newly added element up (maintains heap property)."""
        while index > 0:
            p = self.parent(index)
            if self.heap[index][0] < self.heap[p][0]:
                self.heap[index], self.heap[p] = self.heap[p], self.heap[index]
                index = p
            else:
                break

    def _heapify_down(self, index):
        """Moves top element down (maintains heap property)."""
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
        """Returns the lowest-scored element (does not remove)."""
        return self.heap[0] if self.heap else None

    def pop_min(self):
        """Removes and returns the lowest-scored element."""
        if not self.heap:
            return None
        if len(self.heap) == 1:
            return self.heap.pop()
        min_val = self.heap[0]
        self.heap[0] = self.heap.pop()
        self._heapify_down(0)
        return min_val

    def get_sorted_desc(self):
        """Returns heap content sorted from highest to lowest score."""
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
    # Database helpers
    # ──────────────────────────────────────────────────────────────

    def get_cv_analysis_from_db(self):
        """Returns CV analysis results: [address, skills, experience, education, languages]"""
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
            print(f"CV fetch error: {e}")
            return None
        finally:
            cursor.close()
            conn.close()

    def get_job_analysis_from_db(self, job_analysis_id):
        """Returns a specific job listing analysis."""
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
            print(f"Job fetch error: {e}")
            return None
        finally:
            cursor.close()
            conn.close()

    def get_max_job_analysis_id(self):
        """Returns the highest job_analysis_id in the database."""
        conn = get_db()
        if not conn:
            return 0
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT MAX(job_analysis_id) FROM job_analyses")
            result = cursor.fetchone()
            return result[0] if result and result[0] else 0
        except Error as e:
            print(f"Max ID fetch error: {e}")
            return 0
        finally:
            cursor.close()
            conn.close()

    # ──────────────────────────────────────────────────────────────
    # Scoring
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_skills(raw):
        """Generates skill list from JSON or comma-separated string."""
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
        Compares CV with job listing and returns a score between 0-100.

        Weights:
          - Required skill match : 50 points (max)
          - Preferred skill match : 20 points (max)
          - City match            : 15 points
          - Language match        : 10 points
          - Education match       :  5 points
        """
        if not cv_data or not job_data:
            return 0

        score = 0

        # 1. Required skills (50 points)
        cv_skills = self._parse_skills(cv_data.get('cv_skills'))
        req_skills = self._parse_skills(job_data.get('required_skills'))
        if req_skills:
            matched = sum(1 for s in req_skills if s in cv_skills)
            score += int((matched / len(req_skills)) * 50)

        # 2. Preferred skills (20 points)
        pref_skills = self._parse_skills(job_data.get('preferred_skills'))
        if pref_skills:
            matched_pref = sum(1 for s in pref_skills if s in cv_skills)
            score += int((matched_pref / len(pref_skills)) * 20)

        # 3. City match (15 points)
        cv_address = str(cv_data.get('cv_address', '')).lower()
        job_city = str(job_data.get('location_city', '')).lower()
        job_country = str(job_data.get('location_country', '')).lower()
        if job_city and job_city in cv_address:
            score += 15
        elif job_country and job_country in cv_address:
            score += 7  # Partial points for country match

        # 4. Language match (10 points)
        cv_langs = str(cv_data.get('cv_languages', '')).lower()
        job_langs = self._parse_skills(job_data.get('languages'))
        if job_langs:
            matched_lang = sum(1 for lang in job_langs if lang in cv_langs)
            score += int((matched_lang / len(job_langs)) * 10)

        # 5. Education match (5 points)
        edu_keywords = ['bachelor', 'master', 'associate', 'phd', 'doctorate',
                        'high school', 'undergraduate', 'postgraduate']
        cv_edu = str(cv_data.get('cv_education', '')).lower()
        job_edu = str(job_data.get('edu_min_level', '') or
                      job_data.get('edu_description', '')).lower()
        for kw in edu_keywords:
            if kw in job_edu and kw in cv_edu:
                score += 5
                break

        return min(score, 100)

    # ──────────────────────────────────────────────────────────────
    # Main analysis flow
    # ──────────────────────────────────────────────────────────────

    def analyze_competitivity(self):
        """
        Compares all job listings with the CV.
        Keeps top_n highest-scored listings in MinHeap.
        Returns: [(score, job_analysis_id), ...] sorted high to low
        """
        cv_data = self.get_cv_analysis_from_db()
        if not cv_data:
            print(f"CV analysis not found for user {self.user_id}.")
            return []

        max_id = self.get_max_job_analysis_id()
        if max_id == 0:
            print("No job listings found in database.")
            return []

        for job_id in range(1, max_id + 1):
            job_data = self.get_job_analysis_from_db(job_id)
            if not job_data:
                continue  # Deleted / non-existent record, skip

            score = self.calculate_score(cv_data, job_data)
            self.heap.insert(score, job_id)

        return self.heap.get_sorted_desc()

    def recommend_jobs(self):
        """
        Returns details of the most suitable job listings.
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