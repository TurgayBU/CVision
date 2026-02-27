from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS
import hashlib
import sqlite3
from datetime import timedelta

app = Flask(__name__)
app.secret_key = "gizli_anahtar_buraya"
app.permanent_session_lifetime = timedelta(days=7)
CORS(app)


# Veritabanı bağlantısı
def get_db():
    conn = sqlite3.connect('users.db')
    conn.row_factory = sqlite3.Row
    return conn


# Veritabanını oluştur
def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Örnek kullanıcı ekle (şifre: 12345)
    password_hash = hashlib.sha256('12345'.encode()).hexdigest()
    try:
        conn.execute('INSERT INTO users (username, password, email) VALUES (?, ?, ?)',
                     ('admin', password_hash, 'admin@example.com'))
        conn.commit()
    except:
        pass  # Kullanıcı zaten varsa hata verme

    conn.close()


# Ana sayfa - templates/index.html'den alır
@app.route('/')
def index():
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
    user = conn.execute('SELECT * FROM users WHERE username = ? AND password = ?',
                        (username, password_hash)).fetchone()
    conn.close()

    if user:
        session.permanent = remember
        session['user_id'] = user['id']
        session['username'] = user['username']

        return jsonify({
            'success': True,
            'message': 'Giriş başarılı',
            'username': user['username']
        })
    else:
        return jsonify({
            'success': False,
            'message': 'Kullanıcı adı veya şifre hatalı'
        }), 401


# Şifremi unuttum API'si
@app.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    data = request.json
    email = data.get('email')

    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    conn.close()

    if user:
        return jsonify({
            'success': True,
            'message': 'Şifre sıfırlama bağlantısı e-posta adresinize gönderildi'
        })
    else:
        return jsonify({
            'success': False,
            'message': 'Bu e-posta adresi sistemde kayıtlı değil'
        }), 404


# Kayıt ol API'si
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')

    password_hash = hashlib.sha256(password.encode()).hexdigest()

    conn = get_db()
    try:
        conn.execute('INSERT INTO users (username, password, email) VALUES (?, ?, ?)',
                     (username, password_hash, email))
        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'message': 'Kayıt başarılı! Giriş yapabilirsiniz.'
        })
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({
            'success': False,
            'message': 'Bu kullanıcı adı veya e-posta zaten kayıtlı'
        }), 400


# Oturum kontrolü
@app.route('/api/check-session')
def check_session():
    if 'user_id' in session:
        return jsonify({
            'logged_in': True,
            'username': session['username']
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


# Dashboard sayfası
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    return "<h1>Hoş Geldiniz!</h1><p>Başarıyla giriş yaptınız.</p><a href='/api/logout'>Çıkış Yap</a>"


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)