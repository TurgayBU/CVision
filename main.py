"""
DÜZELTME ÖZET:
1. CV analizi sonrası database'e otomatik kaydediliyor
2. Job matching sırasında DB'den CV bilgileri çekiliyor
3. CV ve Job match sonuçları birlikte gösteriliyor
4. Session cleanup yapılıyor
"""
import app
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS
import hashlib
import mysql.connector
from mysql.connector import Error
from datetime import timedelta, datetime
import config
from config import DB_CONFIG, UPLOAD_FOLDER, ALLOWED_EXTENSIONS
import os
from werkzeug.utils import secure_filename
import json
from cv_ai_extract import AICVResponseGroq as AICVResponse
from extract_cv import CVProcessor
from interview_routes import interview_bp


# ── Flask uygulaması oluştur ──────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.permanent_session_lifetime = timedelta(days=config.SESSION_LIFETIME_DAYS)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
app.register_blueprint(interview_bp)
CORS(app)

from job_routes import job_bp

app.register_blueprint(job_bp)


# ─────────────────────────────────────────────────────────────────────────────
# Yardımcı fonksiyonlar
# ─────────────────────────────────────────────────────────────────────────────

def get_db():
    try:
        return mysql.connector.connect(**config.DB_CONFIG)
    except Error as e:
        print(f"Veritabanı bağlantı hatası: {e}")
        return None


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ═══════════════════════════════════════════════════════════════════════════════
# DÜZELTME 1: Analiz sonuçlarını DB'ye kaydetme işlevini geliştirelim
# ═══════════════════════════════════════════════════════════════════════════════

def save_cv_analysis_to_db(user_id, cv_text_id, cv_data):
    """
    CV analiz sonuçlarını veritabanına kaydeder.
    cv_data = [address, skills, experience, education, languages]
    """
    conn = get_db()
    if not conn:
        return False, "Veritabanı bağlantı hatası"

    cursor = conn.cursor()
    try:
        # cv_analyses tablosuna kayıt yap
        cursor.execute("""
            INSERT INTO cv_analyses (
                user_id, cv_text_id, cv_address, cv_skills,
                cv_experience, cv_education, cv_languages, analyzed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                cv_address = VALUES(cv_address),
                cv_skills = VALUES(cv_skills),
                cv_experience = VALUES(cv_experience),
                cv_education = VALUES(cv_education),
                cv_languages = VALUES(cv_languages),
                analyzed_at = NOW()
        """, (
            user_id,
            cv_text_id,
            cv_data[0] or "",  # address
            cv_data[1] or "",  # skills
            cv_data[2] or "",  # experience
            cv_data[3] or "",  # education
            cv_data[4] or "",  # languages
        ))
        conn.commit()
        return True, "CV analizi kaydedildi"
    except Error as e:
        print(f"CV kayıt hatası: {e}")
        return False, f"Kayıt hatası: {e}"
    finally:
        cursor.close()
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# app.py'e EKLENECEK ENDPOINT: /api/job-detail/<job_id>
# Bu endpoint job_detail.html sayfasının ihtiyacı olan tüm veriyi döndürür:
#   - job_analyses tablosundan iş ilanı bilgileri
#   - cv_analyses tablosundan CV bilgileri (aynı user_id ile)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/api/job-detail/<int:job_id>', methods=['GET'])
def get_job_detail(job_id):
    """
    job_detail.html için tek endpoint.

    Döndürdüğü yapı:
    {
        "success": True,
        "job": { ...job_analyses satırı... },
        "cv":  { ...cv_analyses satırı (en son analiz)... }  # None olabilir
    }
    """
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'}), 401

    user_id = session['user_id']
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'error': 'Veritabanı bağlantı hatası'}), 500

    cursor = conn.cursor(dictionary=True)
    try:
        # ── 1. İş analizi ──────────────────────────────────────────────────
        cursor.execute("""
            SELECT
                job_analysis_id, user_id, source_url, raw_text,
                job_title, department, employment_type, company_name,
                location_city, location_district, location_country,
                is_remote, work_type,
                required_skills, preferred_skills,
                exp_min_years, exp_max_years, exp_description,
                edu_min_level, edu_preferred_fields, edu_description,
                languages,
                salary_min, salary_max, salary_currency, salary_negotiable,
                benefits, completeness_score, missing_fields,
                full_analysis_json, analyzed_at
            FROM job_analyses
            WHERE job_analysis_id = %s AND user_id = %s
            LIMIT 1
        """, (job_id, user_id))

        job = cursor.fetchone()
        if not job:
            return jsonify({'success': False, 'error': 'İş analizi bulunamadı veya erişim izniniz yok'}), 404

        # datetime → string
        if job.get('analyzed_at'):
            job['analyzed_at'] = job['analyzed_at'].isoformat()

        # ── 2. CV analizi (en son) ──────────────────────────────────────────
        cursor.execute("""
            SELECT
                cv_id, cv_text_id,
                cv_address, cv_skills, cv_experience,
                cv_education, cv_languages,
                analyzed_at
            FROM cv_analyses
            WHERE user_id = %s
            ORDER BY analyzed_at DESC
            LIMIT 1
        """, (user_id,))

        cv = cursor.fetchone()
        if cv and cv.get('analyzed_at'):
            cv['analyzed_at'] = cv['analyzed_at'].isoformat()

        return jsonify({
            'success': True,
            'job': job,
            'cv': cv,  # None ise frontend "CV bulunamadı" gösterir
            'match': None  # İleride matching sonucu buraya eklenebilir
        })

    except Error as e:
        print(f"job-detail hatası: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


# ───────────────────────────────────────────────────────────────────────────────
# AYRICA: cv_analysis sayfasında analyzeJob() fonksiyonu
# /api/cv-analysis-check endpoint'i çağırıyor — bunu da ekleyin:
# ───────────────────────────────────────────────────────────────────────────────

@app.route('/api/cv-analysis-check', methods=['GET'])
def cv_analysis_check():
    """
    Belirli bir CV'nin analiz edilip edilmediğini kontrol eder.
    cv_analysis.html'deki analyzeJob() fonksiyonu bunu kullanıyor.
    """
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'}), 401

    user_id = request.args.get('user_id', type=int)
    cv_text_id = request.args.get('cv_text_id', type=int)

    if not user_id or not cv_text_id:
        return jsonify({'success': False, 'error': 'user_id ve cv_text_id gerekli'}), 400

    result = get_cv_analysis_from_db(user_id, cv_text_id)
    if result:
        return jsonify({'success': True, 'analyzed': True})
    return jsonify({'success': False, 'analyzed': False,
                    'error': 'CV analizi bulunamadı. Lütfen önce CV analiz edin.'})

def get_cv_analysis_from_db(user_id, cv_text_id):
    """
    Veritabanından CV analiz sonuçlarını getirir.
    """
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
        """, (user_id, cv_text_id))
        result = cursor.fetchone()
        if result:
            return [
                result['cv_address'],
                result['cv_skills'],
                result['cv_experience'],
                result['cv_education'],
                result['cv_languages']
            ]
        return None
    except Error as e:
        print(f"CV getirme hatası: {e}")
        return None
    finally:
        cursor.close()
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Diğer route'lar (değişmemiş)
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    remember = data.get('remember', False)
    password_hash = hashlib.sha256(password.encode()).hexdigest()

    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Veritabanı bağlantı hatası'}), 500

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT user_id, username, name, surname FROM users WHERE username=%s AND password_hash=%s",
            (username, password_hash)
        )
        user = cursor.fetchone()
        if user:
            session.permanent = remember
            session['user_id'] = user['user_id']
            session['username'] = user['username']
            session['fullname'] = f"{user['name']} {user['surname']}"
            return jsonify({'success': True, 'message': 'Giriş başarılı!'})
        return jsonify({'success': False, 'message': 'Kullanıcı adı veya şifre hatalı'}), 401
    except Error as e:
        return jsonify({'success': False, 'message': f'Veritabanı hatası: {e}'}), 500
    finally:
        cursor.close();
        conn.close()


@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')
    password_hash = hashlib.sha256(password.encode()).hexdigest()

    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Veritabanı bağlantı hatası'}), 500

    cursor = conn.cursor()
    try:
        parts = username.split()
        name = parts[0]
        surname = ' '.join(parts[1:]) if len(parts) > 1 else ''
        cursor.execute(
            "INSERT INTO users (username, email, password_hash, name, surname) VALUES (%s,%s,%s,%s,%s)",
            (username, email, password_hash, name, surname)
        )
        conn.commit()
        return jsonify({'success': True, 'message': 'Kayıt başarılı!'})
    except Error as e:
        if e.errno == 1062:
            return jsonify({'success': False, 'message': 'Bu kullanıcı adı veya e-posta zaten kayıtlı'}), 400
        return jsonify({'success': False, 'message': f'Kayıt sırasında hata: {e}'}), 500
    finally:
        cursor.close();
        conn.close()


@app.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    email = (request.json or {}).get('email')
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Veritabanı bağlantı hatası'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT user_id FROM users WHERE email=%s", (email,))
        if cursor.fetchone():
            return jsonify({'success': True, 'message': f'Şifre sıfırlama bağlantısı {email} adresine gönderildi'})
        return jsonify({'success': False, 'message': 'Bu e-posta sistemde kayıtlı değil'}), 404
    except Error as e:
        return jsonify({'success': False, 'message': f'Veritabanı hatası: {e}'}), 500
    finally:
        cursor.close();
        conn.close()


@app.route('/api/check-session')
def check_session():
    if 'user_id' in session:
        return jsonify({'logged_in': True, 'username': session['username'], 'fullname': session.get('fullname', '')})
    return jsonify({'logged_in': False})


@app.route('/api/logout')
def logout():
    session.clear()
    return jsonify({'success': True, 'message': 'Çıkış yapıldı'})


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    return render_template('cv_and_link_upload.html', session=session)


@app.route('/api/upload-cv-links', methods=['POST'])
def upload_cv_links():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Oturum açmanız gerekiyor'}), 401

    user_id = session['user_id']
    try:
        links = {
            'linkedin': request.form.get('linkedin'),
            'github': request.form.get('github'),
            'portfolio': request.form.get('portfolio'),
            'notes': request.form.get('notes'),
        }

        if 'cv' not in request.files:
            return jsonify({'success': False, 'message': 'CV dosyası bulunamadı'}), 400

        file = request.files['cv']
        if file.filename == '':
            return jsonify({'success': False, 'message': 'Dosya seçilmedi'}), 400
        if not allowed_file(file.filename):
            return jsonify({'success': False, 'message': 'Sadece PDF, DOC ve DOCX desteklenir'}), 400

        filename = secure_filename(file.filename)
        filename = f"user_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        processor = CVProcessor(DB_CONFIG)
        job_info = {'title': links['notes'], 'url': links['linkedin'], 'location': None}
        cv_text_id = processor.save_cv_to_database(user_id, file_path, job_info)
        processor.disconnect_db()

        if cv_text_id:
            return jsonify({
                'success': True,
                'message': 'CV başarıyla yüklendi!',
                'cv_text_id': cv_text_id,
            })
        return jsonify({'success': False, 'message': 'CV işlenirken hata oluştu'}), 500

    except Exception as e:
        print(f"CV yükleme hatası: {e}")
        return jsonify({'success': False, 'message': f'Hata: {e}'}), 500


@app.route('/api/user-cvs', methods=['GET'])
def get_user_cvs():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Oturum açmanız gerekiyor'}), 401
    try:
        processor = CVProcessor(DB_CONFIG)
        cvs = processor.get_user_cvs(session['user_id'])
        processor.disconnect_db()
        return jsonify({'success': True, 'cvs': cvs})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/cv-details/<int:cv_id>', methods=['GET'])
def get_cv_details(cv_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Oturum açmanız gerekiyor'}), 401

    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Veritabanı bağlantı hatası'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT cv_id, cv_file_path, cv_text, cv_skills, cv_experience,
                   cv_education, cv_languages, analyzed_at, job_title, job_url, job_location
            FROM cv_analyses WHERE cv_id=%s AND user_id=%s
        """, (cv_id, session['user_id']))
        cv = cursor.fetchone()
        if not cv:
            return jsonify({'success': False, 'message': 'CV bulunamadı'}), 404
        for key in ('cv_skills', 'cv_experience', 'cv_education', 'cv_languages'):
            if cv.get(key):
                cv[key] = json.loads(cv[key])
        return jsonify({'success': True, 'cv': cv})
    except Error as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        cursor.close();
        conn.close()


@app.route('/cv-analysis')
def cv_analysis():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    return render_template('cv_analysis.html', session=session)


# ═══════════════════════════════════════════════════════════════════════════════
# DÜZELTME 2: CV Analiz Endpoint'ini Güncelleyelim
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/analyze-cv', methods=['POST'])
def analyze_cv():
    """
    CV'yi AI ile analiz eder ve OTOMATIK olarak DB'ye kaydeder.
    """
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'}), 401

    data = request.json
    user_id = data.get('user_id')
    cv_text_id = data.get('cv_text_id')

    if not user_id or not cv_text_id:
        return jsonify({'success': False, 'error': 'user_id ve cv_text_id gerekli'}), 400

    ai_cv = AICVResponse(DB_CONFIG, config.api_key)
    try:
        # 1. CV metnini getir
        raw_text = ai_cv.Get_CV_Text(user_id, cv_text_id)
        if not raw_text:
            return jsonify({'success': False, 'error': 'CV metni bulunamadı'})

        # 2. AI ile analiz yap
        cv_data = ai_cv.PromptingAI(raw_text)
        if not cv_data:
            return jsonify({'success': False, 'error': 'AI analizi başarısız'})

        # 3. ⭐ OTOMATIK DB'ye kaydet
        success, message = save_cv_analysis_to_db(user_id, cv_text_id, cv_data)
        if not success:
            print(f"⚠️ Uyarı: CV analizi yapıldı ancak kaydedilemedi: {message}")

        # 4. Sonuç döndür
        preview = raw_text[:500] + '...' if len(raw_text) > 500 else raw_text
        return jsonify({
            'success': True,
            'cv_data': cv_data,
            'raw_text': preview,
            'saved_to_db': success,
            'message': message
        })

    except Exception as e:
        print(f"❌ Analiz hatası: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        ai_cv.disconnect()


# ═══════════════════════════════════════════════════════════════════════════════
# DÜZELTME 3: Job Analysis Endpoint'ini Güncelleyelim
# ═══════════════════════════════════════════════════════════════════════════════



@app.route('/save-cv-analysis', methods=['POST'])
def save_cv_analysis():
    """
    Bu endpoint artık gerekli değil çünkü analyze-cv'de otomatik kaydediliyor.
    Backward compatibility için tutuldu.
    """
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'}), 401

    data = request.json
    success, message = save_cv_analysis_to_db(
        data.get('user_id'),
        data.get('cv_text_id'),
        data.get('cv_data')
    )

    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'error': message})


@app.route('/api/user-cv-texts', methods=['GET'])
def get_user_cv_texts():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'}), 401
    try:
        processor = CVProcessor(DB_CONFIG)
        cvs = processor.get_user_cvs(session['user_id'])
        processor.disconnect_db()
        return jsonify({'success': True, 'cvs': cvs})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/cv-stats', methods=['GET'])
def get_cv_stats():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'}), 401
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'error': 'Veritabanı bağlantı hatası'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT COUNT(*) as total FROM cv_text WHERE user_id=%s", (session['user_id'],))
        total = cursor.fetchone()['total']
        cursor.execute("SELECT COUNT(*) as analyzed FROM cv_analyses WHERE user_id=%s", (session['user_id'],))
        analyzed = cursor.fetchone()['analyzed']
        return jsonify(
            {'success': True, 'stats': {'total': total, 'analyzed': analyzed, 'pending': max(0, total - analyzed)}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close();
        conn.close()


@app.route('/job-detail')
def job_detail_page():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    return render_template('job_detail.html')


@app.route('/api/job-analyses')
def get_job_analyses():
    if not session.get('user_id'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    user_id = session['user_id']

    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT job_analysis_id, job_title, company_name, department,
                   employment_type, is_remote, work_type, completeness_score,
                   analyzed_at, required_skills, preferred_skills, exp_min_years,
                   exp_max_years, edu_min_level, edu_preferred_fields, languages,
                   salary_min, salary_max, salary_currency, source_url,
                   location_city, location_district, location_country
            FROM job_analyses
            WHERE user_id = %s
            ORDER BY analyzed_at DESC
        """, (user_id,))

        jobs = cursor.fetchall()
        cursor.close()
        conn.close()

        return jsonify({'success': True, 'jobs': jobs})

    except mysql.connector.Error as err:
        print(f"MySQL Hatası: {err}")
        return jsonify({'success': False, 'error': f'Database error: {str(err)}'}), 500
    except Exception as e:
        print(f"Genel hata: {e}")
        return jsonify({'success': False, 'error': f'Server error: {str(e)}'}), 500


@app.route('/api/cv-analysis', methods=['GET'])
def get_cv_analysis():
    """
    job_detail.html'in CV verisini çekmek için kullandığı endpoint.

    Query params:
        cv_text_id: int  (zorunlu)

    Döner:
        { "success": true, "cv": { cv_address, cv_skills, cv_experience, cv_education, cv_languages } }
    """
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'}), 401

    cv_text_id = request.args.get('cv_text_id', type=int)
    if not cv_text_id:
        return jsonify({'success': False, 'error': 'cv_text_id gerekli'}), 400

    user_id = session['user_id']
    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'error': 'Veritabanı bağlantı hatası'}), 500

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT cv_address, cv_skills, cv_experience, cv_education, cv_languages
            FROM cv_analyses
            WHERE user_id = %s AND cv_text_id = %s
            ORDER BY analyzed_at DESC
            LIMIT 1
        """, (user_id, cv_text_id))
        cv = cursor.fetchone()

        if cv:
            return jsonify({'success': True, 'cv': cv})
        return jsonify({'success': False, 'error': 'CV analizi bulunamadı'}), 404

    except Error as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/interview')
def interview_page():
    """Mülakat simülatörü sayfası"""
    if 'user_id' not in session:
        return redirect(url_for('index'))
    return render_template('interview.html')

# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    app.run(debug=config.DEBUG, port=config.PORT)