from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS
import hashlib
import mysql.connector
from mysql.connector import Error
from datetime import timedelta
import config
from config import DB_CONFIG, UPLOAD_FOLDER, ALLOWED_EXTENSIONS
import os
from werkzeug.utils import secure_filename
import json
from datetime import datetime
from cv_ai_extract import AICVResponseGroq as AICVResponse

# CVProcessor sınıfını import et
from extract_cv import CVProcessor

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.permanent_session_lifetime = timedelta(days=config.SESSION_LIFETIME_DAYS)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
CORS(app)


def get_db():
    """MySQL veritabanı bağlantısı oluştur"""
    try:
        conn = mysql.connector.connect(**config.DB_CONFIG)
        return conn
    except Error as e:
        print(f"Veritabanı bağlantı hatası: {e}")
        return None


def allowed_file(filename):
    """Dosya uzantısı kontrolü"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_links_to_database(user_id, links):
    """Kullanıcının linklerini veritabanına kaydet"""
    conn = get_db()
    if not conn:
        return False

    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE users 
            SET linkedin_url = %s, github_url = %s, portfolio_url = %s 
            WHERE user_id = %s
        """, (
            links.get('linkedin'),
            links.get('github'),
            links.get('portfolio'),
            user_id
        ))

        conn.commit()
        return True
    except Error as e:
        print(f"Link kaydetme hatası: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()


# Ana sayfa - index.html'i göster
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


# Giriş işlemi API'si
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    remember = data.get('remember', False)

    password_hash = hashlib.sha256(password.encode()).hexdigest()

    conn = get_db()
    if not conn:
        return jsonify({
            'success': False,
            'message': 'Veritabanı bağlantı hatası'
        }), 500

    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT user_id, username, name, surname FROM users WHERE username = %s AND password_hash = %s",
            (username, password_hash)
        )
        user = cursor.fetchone()

        if user:
            session.permanent = remember
            session['user_id'] = user['user_id']
            session['username'] = user['username']
            session['fullname'] = f"{user['name']} {user['surname']}"

            return jsonify({
                'success': True,
                'message': 'Giriş başarılı! Yönlendiriliyorsunuz...'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Kullanıcı adı veya şifre hatalı'
            }), 401

    except Error as e:
        return jsonify({
            'success': False,
            'message': f'Veritabanı hatası: {str(e)}'
        }), 500
    finally:
        cursor.close()
        conn.close()


# Kayıt ol API'si
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')

    password_hash = hashlib.sha256(password.encode()).hexdigest()

    conn = get_db()
    if not conn:
        return jsonify({
            'success': False,
            'message': 'Veritabanı bağlantı hatası'
        }), 500

    cursor = conn.cursor()

    try:
        name_parts = username.split()
        name = name_parts[0] if name_parts else username
        surname = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''

        cursor.execute(
            "INSERT INTO users (username, email, password_hash, name, surname) VALUES (%s, %s, %s, %s, %s)",
            (username, email, password_hash, name, surname)
        )
        conn.commit()

        return jsonify({
            'success': True,
            'message': 'Kayıt başarılı! Şimdi giriş yapabilirsiniz.'
        })

    except Error as e:
        if e.errno == 1062:
            return jsonify({
                'success': False,
                'message': 'Bu kullanıcı adı veya e-posta zaten kayıtlı'
            }), 400
        else:
            return jsonify({
                'success': False,
                'message': f'Kayıt sırasında hata: {str(e)}'
            }), 500
    finally:
        cursor.close()
        conn.close()


# Şifremi unuttum API'si
@app.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    data = request.json
    email = data.get('email')

    conn = get_db()
    if not conn:
        return jsonify({
            'success': False,
            'message': 'Veritabanı bağlantı hatası'
        }), 500

    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT user_id FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()

        if user:
            return jsonify({
                'success': True,
                'message': f'Şifre sıfırlama bağlantısı {email} adresine gönderildi'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Bu e-posta adresi sistemde kayıtlı değil'
            }), 404

    except Error as e:
        return jsonify({
            'success': False,
            'message': f'Veritabanı hatası: {str(e)}'
        }), 500
    finally:
        cursor.close()
        conn.close()


# Oturum kontrolü
@app.route('/api/check-session')
def check_session():
    if 'user_id' in session:
        return jsonify({
            'logged_in': True,
            'username': session['username'],
            'fullname': session.get('fullname', '')
        })
    return jsonify({
        'logged_in': False
    })


# Çıkış yap
@app.route('/api/logout')
def logout():
    session.clear()
    return jsonify({
        'success': True,
        'message': 'Çıkış yapıldı'
    })


# Dashboard - CV ve link yükleme sayfası
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    return render_template('cv_and_link_upload.html', session=session)


# CV ve linkleri yükleme API'si (GÜNCELLENDİ - yönlendirme eklendi)
@app.route('/api/upload-cv-links', methods=['POST'])
def upload_cv_links():
    if 'user_id' not in session:
        return jsonify({
            'success': False,
            'message': 'Oturum açmanız gerekiyor'
        }), 401

    user_id = session['user_id']

    try:
        linkedin_url = request.form.get('linkedin')
        github_url = request.form.get('github')
        portfolio_url = request.form.get('portfolio')
        notes = request.form.get('notes')

        links = {
            'linkedin': linkedin_url,
            'github': github_url,
            'portfolio': portfolio_url,
            'notes': notes
        }

        if 'cv' not in request.files:
            return jsonify({
                'success': False,
                'message': 'CV dosyası bulunamadı'
            }), 400

        file = request.files['cv']

        if file.filename == '':
            return jsonify({
                'success': False,
                'message': 'Dosya seçilmedi'
            }), 400

        if not allowed_file(file.filename):
            return jsonify({
                'success': False,
                'message': 'Desteklenmeyen dosya türü. Sadece PDF, DOC ve DOCX dosyaları yüklenebilir.'
            }), 400

        filename = secure_filename(file.filename)
        filename = f"user_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        processor = CVProcessor(DB_CONFIG)

        job_info = {
            'title': notes if notes else None,
            'url': linkedin_url,
            'location': None
        }

        cv_text_id = processor.save_cv_to_database(user_id, file_path, job_info)
        processor.disconnect_db()

        if cv_text_id:
            # BAŞARILI YÜKLEME - CV_TEXT_ID ile analiz sayfasına yönlendir
            return jsonify({
                'success': True,
                'message': 'CV ve linkler başarıyla yüklendi! Analiz sayfasına yönlendiriliyorsunuz...',
                'redirect': f'/cv-analysis?cv_id={cv_text_id}',
                'cv_text_id': cv_text_id
            })
        else:
            return jsonify({
                'success': False,
                'message': 'CV işlenirken bir hata oluştu'
            }), 500

    except Exception as e:
        print(f"CV yükleme hatası: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Bir hata oluştu: {str(e)}'
        }), 500


# Kullanıcının CV'lerini listeleme API'si
@app.route('/api/user-cvs', methods=['GET'])
def get_user_cvs():
    if 'user_id' not in session:
        return jsonify({
            'success': False,
            'message': 'Oturum açmanız gerekiyor'
        }), 401

    user_id = session['user_id']

    try:
        processor = CVProcessor(DB_CONFIG)
        cvs = processor.get_user_cvs(user_id)
        processor.disconnect_db()

        return jsonify({
            'success': True,
            'cvs': cvs
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'CV listesi alınırken hata: {str(e)}'
        }), 500


# CV detaylarını getirme API'si
@app.route('/api/cv-details/<int:cv_id>', methods=['GET'])
def get_cv_details(cv_id):
    if 'user_id' not in session:
        return jsonify({
            'success': False,
            'message': 'Oturum açmanız gerekiyor'
        }), 401

    user_id = session['user_id']

    conn = get_db()
    if not conn:
        return jsonify({
            'success': False,
            'message': 'Veritabanı bağlantı hatası'
        }), 500

    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT cv_id, cv_file_path, cv_text, cv_skills, cv_experience, 
                   cv_education, cv_languages, analyzed_at, job_title, job_url, job_location
            FROM cv_analyses 
            WHERE cv_id = %s AND user_id = %s
        """, (cv_id, user_id))

        cv = cursor.fetchone()

        if cv:
            if cv['cv_skills']:
                cv['cv_skills'] = json.loads(cv['cv_skills'])
            if cv['cv_experience']:
                cv['cv_experience'] = json.loads(cv['cv_experience'])
            if cv['cv_education']:
                cv['cv_education'] = json.loads(cv['cv_education'])
            if cv['cv_languages']:
                cv['cv_languages'] = json.loads(cv['cv_languages'])

            return jsonify({
                'success': True,
                'cv': cv
            })
        else:
            return jsonify({
                'success': False,
                'message': 'CV bulunamadı'
            }), 404

    except Error as e:
        return jsonify({
            'success': False,
            'message': f'Veritabanı hatası: {str(e)}'
        }), 500
    finally:
        cursor.close()
        conn.close()


# Users tablosuna link kolonlarını eklemek için SQL
@app.route('/api/setup-database', methods=['GET'])
def setup_database():
    if not app.debug:
        return jsonify({'success': False, 'message': 'Bu işlem sadece geliştirme modunda çalışır'}), 403

    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'message': 'Veritabanı bağlantı hatası'}), 500

    cursor = conn.cursor()

    try:
        cursor.execute("""
            ALTER TABLE users 
            ADD COLUMN IF NOT EXISTS linkedin_url VARCHAR(255),
            ADD COLUMN IF NOT EXISTS github_url VARCHAR(255),
            ADD COLUMN IF NOT EXISTS portfolio_url VARCHAR(255),
            ADD COLUMN IF NOT EXISTS notes TEXT
        """)
        conn.commit()

        return jsonify({
            'success': True,
            'message': 'Veritabanı başarıyla güncellendi'
        })

    except Error as e:
        return jsonify({
            'success': False,
            'message': f'Veritabanı hatası: {str(e)}'
        }), 500
    finally:
        cursor.close()
        conn.close()


# CV Analiz Sayfası
@app.route('/cv-analysis')
def cv_analysis():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    return render_template('cv_analysis.html', session=session)


# CV Analiz Sonucunu Kaydet
@app.route('/save-cv-analysis', methods=['POST'])
def save_cv_analysis():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'}), 401

    data = request.json
    user_id = data.get('user_id')
    cv_text_id = data.get('cv_text_id')  # Burada cv_text_id geliyor
    cv_data = data.get('cv_data')

    print(f"📥 Gelen veri: user_id={user_id}, cv_text_id={cv_text_id}, cv_data={cv_data}")

    ai_cv = AICVResponse(DB_CONFIG, config.api_key)

    try:
        # cv_text_id'yi mutlaka gönder!
        if ai_cv.SaveInDatabase(cv_data, user_id, cv_text_id):
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Veritabanına kaydedilemedi'})

    except Exception as e:
        print(f"❌ Hata: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        ai_cv.disconnect()
# Kullanıcının cv_text kayıtlarını getir
@app.route('/api/user-cv-texts', methods=['GET'])
def get_user_cv_texts():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'}), 401

    user_id = session['user_id']

    try:
        processor = CVProcessor(DB_CONFIG)
        cvs = processor.get_user_cvs(user_id)
        processor.disconnect_db()

        return jsonify({
            'success': True,
            'cvs': cvs
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# CV istatistiklerini getir
@app.route('/api/cv-stats', methods=['GET'])
def get_cv_stats():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'}), 401

    user_id = session['user_id']

    conn = get_db()
    if not conn:
        return jsonify({'success': False, 'error': 'Veritabanı bağlantı hatası'}), 500

    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT COUNT(*) as total FROM cv_text WHERE user_id = %s", (user_id,))
        total = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) as analyzed FROM cv_analyses WHERE user_id = %s", (user_id,))
        analyzed = cursor.fetchone()['analyzed']

        pending = total - analyzed

        return jsonify({
            'success': True,
            'stats': {
                'total': total,
                'analyzed': analyzed,
                'pending': max(0, pending)
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


# CV analiz API'si
@app.route('/analyze-cv', methods=['POST'])
def analyze_cv():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'}), 401

    data = request.json
    user_id = data.get('user_id')
    cv_text_id = data.get('cv_text_id')

    ai_cv = AICVResponse(DB_CONFIG, config.api_key)

    try:
        raw_text = ai_cv.Get_CV_Text(user_id, cv_text_id)

        if not raw_text:
            return jsonify({'success': False, 'error': 'CV metni bulunamadı'})

        cv_data = ai_cv.PromptingAI(raw_text)

        if cv_data:
            return jsonify({
                'success': True,
                'cv_data': cv_data,
                'raw_text': raw_text[:500] + '...' if len(raw_text) > 500 else raw_text
            })
        else:
            return jsonify({'success': False, 'error': 'AI analizi başarısız'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        ai_cv.disconnect()


if __name__ == '__main__':
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    app.run(debug=config.DEBUG, port=config.PORT)