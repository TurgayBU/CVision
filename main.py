from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS
import hashlib
import mysql.connector
from mysql.connector import Error
from datetime import timedelta
import config  # config.py dosyasını import et

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.permanent_session_lifetime = timedelta(days=config.SESSION_LIFETIME_DAYS)
CORS(app)


def get_db():
    """MySQL veritabanı bağlantısı oluştur"""
    try:
        conn = mysql.connector.connect(**config.DB_CONFIG)
        return conn
    except Error as e:
        print(f"Veritabanı bağlantı hatası: {e}")
        return None


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

    # Şifreyi hashle
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
        # name ve surname alanlarını username'den ayır
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


# Dashboard
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index'))

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Dashboard - CVision</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
                font-family: 'Segoe UI', sans-serif;
            }}
            body {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                padding: 20px;
            }}
            .container {{
                background: white;
                border-radius: 20px;
                box-shadow: 0 15px 35px rgba(0,0,0,0.2);
                width: 100%;
                max-width: 500px;
                padding: 40px;
            }}
            .header {{
                text-align: center;
                margin-bottom: 30px;
            }}
            .header h1 {{
                color: #333;
                font-size: 28px;
            }}
            .welcome-box {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                padding: 25px;
                border-radius: 10px;
                color: white;
                text-align: center;
                margin-bottom: 25px;
            }}
            .info-card {{
                background: #f8f9fa;
                padding: 20px;
                border-radius: 10px;
                margin-bottom: 20px;
            }}
            .info-card p {{
                margin: 10px 0;
                color: #555;
            }}
            .btn {{
                width: 100%;
                padding: 14px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                border: none;
                border-radius: 10px;
                color: white;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
            }}
            .btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(102,126,234,0.4);
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>CVision</h1>
            </div>

            <div class="welcome-box">
                <h2>Hoş Geldiniz, {session.get('fullname', session['username'])}!</h2>
                <p>Başarıyla giriş yaptınız.</p>
            </div>

            <div class="info-card">
                <p><strong>Kullanıcı ID:</strong> {session['user_id']}</p>
                <p><strong>Kullanıcı Adı:</strong> {session['username']}</p>
            </div>

            <button class="btn" onclick="logout()">Çıkış Yap</button>
        </div>

        <script>
            function logout() {{
                fetch('/api/logout')
                    .then(response => response.json())
                    .then(data => {{
                        if(data.success) window.location.href = '/';
                    }});
            }}
        </script>
    </body>
    </html>
    """


if __name__ == '__main__':
    app.run(debug=config.DEBUG, port=config.PORT)