"""
Aplikasi Web: Sistem Administrasi Klinik (Klinik SKEM)
Framework: Python Flask & Jinja2 Template Engine
Fitur:
  - Autentikasi Pengguna & Login Google Interaktif
  - Manajemen Profil Pasien Interaktif & Riwayat Pendaftaran
  - Resep Obat & Farmasi Terpadu
  - Alur Penyelesaian Kunjungan Pasien ("Selesai di Faskes Ini" & "Rujuk ke Faskes Selanjutnya / Faskes Tingkat 2")
  - Penyimpanan State Operasional Menggunakan Variabel List & Dictionary Python (In-Memory)
"""

import os
import json
import sqlite3
import urllib.parse
import re
from datetime import datetime
import requests
from flask import (
    Flask, render_template, request, redirect, url_for, flash, session, Blueprint
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'klinik-skem-secret-key-demo-2026'
# Dukung reverse proxy / ngrok (X-Forwarded-For, X-Forwarded-Proto, X-Forwarded-Host)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

# ==============================================================================
# KONFIGURASI PENYIMPANAN BERKAS & DOKUMEN DIGITAL (UPLOAD SYSTEM)
# ==============================================================================
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads', 'documents')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Maksimum 16MB

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'pdf', 'doc', 'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_uploaded_document(file_obj, prefix='doc'):
    """Menyimpan file dokumen/foto yang diunggah ke folder static/uploads/documents/ secara aman."""
    if not file_obj or not getattr(file_obj, 'filename', None):
        return None
    orig_name = file_obj.filename.strip()
    if not orig_name or not allowed_file(orig_name):
        return None
    ext = orig_name.rsplit('.', 1)[1].lower()
    raw_base = orig_name.rsplit('.', 1)[0]
    clean_base = secure_filename(raw_base) or 'berkas'
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_filename = f"{prefix}_{timestamp}_{clean_base}.{ext}"
    dest_path = os.path.join(UPLOAD_FOLDER, safe_filename)
    try:
        file_obj.save(dest_path)
        doc_type = 'image' if ext in ['png', 'jpg', 'jpeg', 'webp'] else ('pdf' if ext == 'pdf' else 'document')
        return {
            'document_url': f"/static/uploads/documents/{safe_filename}",
            'document_name': orig_name,
            'document_filename': safe_filename,
            'document_type': doc_type,
            'uploaded_at': datetime.now().strftime("%d %b %Y %H:%M")
        }
    except Exception as e:
        print(f"Error menyimpan file upload: {e}")
        return None

# ==============================================================================
# KONFIGURASI GOOGLE OAUTH 2.0 (GOOGLE IDENTITY SERVICES & OAUTH REDIRECT)
# ==============================================================================
GOOGLE_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'google_oauth_config.json')

def get_google_config():
    """Mengambil Google Client ID & Secret dari file konfigurasi atau environment variable."""
    config = {
        'client_id': os.environ.get('GOOGLE_CLIENT_ID', '').strip(),
        'client_secret': os.environ.get('GOOGLE_CLIENT_SECRET', '').strip()
    }
    if os.path.exists(GOOGLE_CONFIG_FILE):
        try:
            with open(GOOGLE_CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                if saved.get('client_id'):
                    config['client_id'] = saved['client_id'].strip()
                if saved.get('client_secret'):
                    config['client_secret'] = saved['client_secret'].strip()
        except Exception:
            pass
    return config

def save_google_config(client_id, client_secret):
    """Menyimpan Google Client ID & Secret ke file konfigurasi lokal."""
    data = {
        'client_id': (client_id or '').strip(),
        'client_secret': (client_secret or '').strip()
    }
    with open(GOOGLE_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def get_oauth_redirect_uri():
    """
    Menghasilkan Authorized Redirect URI yang presisi untuk Google OAuth.
    Mendeteksi protokol HTTPS saat berjalan di balik tunnel ngrok atau reverse proxy
    agar tidak terjadi error 'redirect_uri_mismatch' pada Google OAuth.
    """
    host = request.headers.get('X-Forwarded-Host') or request.headers.get('Host') or request.host
    proto = request.headers.get('X-Forwarded-Proto', request.scheme).lower()
    # Jika menggunakan tunnel ngrok atau domain publik non-localhost, Google mewajibkan protokol HTTPS
    if 'ngrok' in host.lower() or (not host.startswith(('localhost', '127.0.0.1'))):
        proto = 'https'
    return f"{proto}://{host}/auth/google/callback"

def get_app_origin():
    """Menghasilkan Authorized JavaScript origin yang presisi untuk Google Identity Services (GIS)."""
    host = request.headers.get('X-Forwarded-Host') or request.headers.get('Host') or request.host
    proto = request.headers.get('X-Forwarded-Proto', request.scheme).lower()
    if 'ngrok' in host.lower() or (not host.startswith(('localhost', '127.0.0.1'))):
        proto = 'https'
    return f"{proto}://{host}"

# ==============================================================================
# HELPER STANDARISASI TANGGAL INDONESIA (Mencegah Bug Tanggal Tidak Konsisten)
# ==============================================================================
ID_MONTHS = {
    1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'Mei', 6: 'Jun',
    7: 'Jul', 8: 'Agu', 9: 'Sep', 10: 'Okt', 11: 'Nov', 12: 'Des'
}

def format_indonesian_date(val=None):
    """Memformat tanggal ke standar Indonesia yang konsisten (contoh: '16 Okt 2026')."""
    if not val:
        d = datetime.now()
        return f"{d.day} {ID_MONTHS[d.month]} {d.year}"
    if isinstance(val, datetime):
        return f"{val.day} {ID_MONTHS[val.month]} {val.year}"
    val_str = str(val).strip()
    match_iso = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})', val_str)
    if match_iso:
        y, m, d = int(match_iso.group(1)), int(match_iso.group(2)), int(match_iso.group(3))
        return f"{d} {ID_MONTHS.get(m, 'Okt')} {y}"
    match_dmy = re.match(r'^(\d{1,2})-(\d{1,2})-(\d{4})', val_str)
    if match_dmy:
        d, m, y = int(match_dmy.group(1)), int(match_dmy.group(2)), int(match_dmy.group(3))
        return f"{d} {ID_MONTHS.get(m, 'Okt')} {y}"
    return val_str

# ==============================================================================
# DATASET IN-MEMORY: MITRA FASKES TINGKAT 2 & POLI SPESIALIS RUJUKAN
# ==============================================================================
FASKES2_PARTNERS = [
    {
        'id': 'FK2-01',
        'name': 'RSUD Dr. Soetomo',
        'type': 'Rumah Sakit Umum Daerah (Tipe A)',
        'city': 'Surabaya',
        'phone': '(031) 5501078',
        'status': 'Aktif',
        'status_class': 'green'
    },
    {
        'id': 'FK2-02',
        'name': 'RS Pusat Harapan',
        'type': 'Rumah Sakit Rujukan Nasional (Tipe A)',
        'city': 'Jakarta Pusat',
        'phone': '(021) 5684093',
        'status': 'Aktif',
        'status_class': 'green'
    },
    {
        'id': 'FK2-03',
        'name': 'RS Spesialis Sentosa Utama',
        'type': 'Rumah Sakit Khusus Spesialistik (Tipe B)',
        'city': 'Jakarta Barat',
        'phone': '(021) 5698200',
        'status': 'Aktif',
        'status_class': 'green'
    }
]

SPECIALTY_CLINICS = [
    'Poli Penyakit Dalam',
    'Poli Jantung & Pembuluh Darah',
    'Poli Bedah',
    'Poli Saraf',
    'Poli Onkologi',
    'Poli Mata Spesialistik',
    'Poli THT-KL Spesialistik',
    'Poli Anak & Subspesialis'
]

# ==============================================================================
# INTEGRASI BASIS DATA SQLITE (klinik_skem.db)
# ==============================================================================
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'klinik_skem.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

# Dataset In-Memory (Akan dimuat & disinkronkan otomatis dari SQLite klinik_skem.db)
REFERRALS = []
USERS_DB = {}
USERS_LIST = []
SAVED_PROFILES = {}
PATIENTS = []
QUEUE_LIST = []
REVIEW_LIST = []
ACTIVE_REGISTRATIONS = []
REGISTRATION_HISTORY = []
REQUIRED_ACTIONS = []
PRESCRIPTIONS = []
OPERATIONAL_HISTORY = []
REQUIREMENTS = [
    {
        'clinic': 'Poli Umum',
        'reqs': 'Identitas NIK dan profil pasien aktif',
        'mandatory': 'Ya',
        'status': 'Aktif',
        'status_class': 'green'
    },
    {
        'clinic': 'Poli Gigi',
        'reqs': 'Identitas dan kartu asuransi / penjamin',
        'mandatory': 'Ya',
        'status': 'Aktif',
        'status_class': 'green'
    },
    {
        'clinic': 'Poli Anak',
        'reqs': 'Kartu Identitas Anak (KIA) / Kartu Keluarga',
        'mandatory': 'Ya',
        'status': 'Aktif',
        'status_class': 'green'
    }
]

SERVICES_LIST = [
    {
        'name': 'Poli Umum',
        'hospital': 'Klinik SKEM',
        'requirements': 'Identitas, profil pasien aktif',
        'status': 'Aktif',
        'status_class': 'green'
    },
    {
        'name': 'Poli Gigi',
        'hospital': 'Klinik SKEM',
        'requirements': 'Identitas, kartu penjamin',
        'status': 'Aktif',
        'status_class': 'green'
    },
    {
        'name': 'Poli Anak',
        'hospital': 'Klinik SKEM',
        'requirements': 'Identitas anak / Kartu Keluarga',
        'status': 'Aktif',
        'status_class': 'green'
    },
    {
        'name': 'Laboratorium Sederhana',
        'hospital': 'Klinik SKEM',
        'requirements': 'Rujukan dokter pemeriksa',
        'status': 'Aktif',
        'status_class': 'green'
    },
    {
        'name': 'Farmasi & Obat',
        'hospital': 'Klinik SKEM',
        'requirements': 'Resep elektronik terdaftar',
        'status': 'Aktif',
        'status_class': 'green'
    }
]

SYSTEM_LOGS = []

QUEUE_STATE = {
    'prefix': 'A',
    'current_number': 0,
    'current_code': 'A-000',
    'daily_sequence': 0,
    'last_reset_date': datetime.now().strftime('%Y-%m-%d'),
    'counter_name': 'Loket 1 · Poli Umum',
    'total_called_today': 0
}

DEFAULT_SEED_USERS = [
    {
        'id': 'U001',
        'email': 'pasien@local',
        'password': 'password123',
        'name': 'Dinda Prameswari',
        'role': 'patient',
        'role_label': 'Pasien',
        'phone': '0812-0000-1182',
        'identity_number': 'DEMO-3173011182',
        'scope': 'Klinik SKEM',
        'status': 'Aktif',
        'auth_provider': 'local',
        'avatar_url': None
    },
    {
        'id': 'U002',
        'email': 'petugas@local',
        'password': 'password123',
        'name': 'Andi Pratama',
        'role': 'facility',
        'role_label': 'Petugas Klinik',
        'phone': '0812-0000-2233',
        'identity_number': 'STAFF-042',
        'scope': 'Klinik SKEM',
        'status': 'Aktif',
        'auth_provider': 'local',
        'avatar_url': None
    },
    {
        'id': 'U003',
        'email': 'admin@local',
        'password': 'password123',
        'name': 'Administrator Sistem',
        'role': 'system',
        'role_label': 'Admin Sistem',
        'phone': '0812-0000-9999',
        'identity_number': 'ADM-001',
        'scope': 'Pengaturan internal',
        'status': 'Aktif',
        'auth_provider': 'local',
        'avatar_url': None
    },
    {
        'id': 'U004',
        'email': 'dinda.skem@gmail.com',
        'password': None,
        'name': 'Dinda Prameswari',
        'role': 'patient',
        'role_label': 'Pasien',
        'phone': '0812-0000-1182',
        'identity_number': 'DEMO-3173011182',
        'scope': 'Klinik SKEM',
        'status': 'Aktif',
        'auth_provider': 'google',
        'avatar_url': 'https://lh3.googleusercontent.com/a/default-user'
    },
    {
        'id': 'U005',
        'email': 'andi.klinik@gmail.com',
        'password': None,
        'name': 'Andi Pratama',
        'role': 'facility',
        'role_label': 'Petugas Klinik',
        'phone': '0812-0000-2233',
        'identity_number': 'STAFF-042',
        'scope': 'Klinik SKEM',
        'status': 'Aktif',
        'auth_provider': 'google',
        'avatar_url': 'https://lh3.googleusercontent.com/a/default-user'
    }
]

DEFAULT_SEED_PROFILES = {
    'utama': {
        'key': 'utama',
        'user_email': 'pasien@local',
        'name': 'Dinda Prameswari',
        'id': 'DEMO-3173011182',
        'identity_number': 'DEMO-3173011182',
        'phone': '0812-0000-1182',
        'dob': '1998-05-12',
        'dob_text': '12 Mei 1998',
        'relationship': 'Utama',
        'badge': 'Profil utama · DEMO-NIK ••••1182'
    }
}

def parse_queue_number(queue_str):
    """Mengekstrak angka integer dari kode antrean seperti 'A-016' -> 16."""
    try:
        if not queue_str:
            return 0
        if '-' in str(queue_str):
            parts = str(queue_str).split('-')
            return int(parts[1])
        match = re.search(r'\d+', str(queue_str))
        if match:
            return int(match.group(0))
    except Exception:
        pass
    return 0

def init_sqlite_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password TEXT,
        name TEXT NOT NULL,
        role TEXT NOT NULL,
        role_label TEXT NOT NULL,
        phone TEXT,
        identity_number TEXT,
        scope TEXT DEFAULT 'Klinik SKEM',
        status TEXT DEFAULT 'Aktif',
        auth_provider TEXT DEFAULT 'local',
        google_id TEXT,
        avatar_url TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS profiles (
        key TEXT PRIMARY KEY,
        user_email TEXT NOT NULL,
        name TEXT NOT NULL,
        identity_number TEXT NOT NULL,
        phone TEXT,
        dob TEXT,
        dob_text TEXT,
        relationship TEXT,
        badge TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS patients (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        phone TEXT,
        date TEXT,
        service TEXT,
        finance TEXT,
        status TEXT,
        form TEXT,
        faskes2 TEXT,
        ref_id TEXT
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS registrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        user_email TEXT NOT NULL,
        patient_name TEXT NOT NULL,
        clinic TEXT NOT NULL,
        date TEXT NOT NULL,
        status TEXT NOT NULL,
        status_class TEXT,
        hospital TEXT DEFAULT 'Klinik SKEM',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS required_actions (
        code TEXT PRIMARY KEY,
        title TEXT,
        service TEXT,
        patient_name TEXT,
        patient_id TEXT,
        reason TEXT,
        user_email TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    try:
        col_names = [row[1] for row in c.execute("PRAGMA table_info(required_actions)").fetchall()]
        if 'user_email' not in col_names:
            c.execute("ALTER TABLE required_actions ADD COLUMN user_email TEXT")
    except Exception as e:
        print(f"Error migrasi tabel required_actions: {e}")
    c.execute("""
    CREATE TABLE IF NOT EXISTS queues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        queue_no TEXT UNIQUE NOT NULL,
        patient_id TEXT NOT NULL,
        patient_name TEXT NOT NULL,
        patient_email TEXT,
        source TEXT,
        service TEXT NOT NULL,
        status TEXT NOT NULL,
        status_class TEXT,
        can_call INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS queue_state (
        id INTEGER PRIMARY KEY,
        prefix TEXT DEFAULT 'A',
        current_number INTEGER DEFAULT 0,
        current_code TEXT DEFAULT 'A-000',
        daily_sequence INTEGER DEFAULT 0,
        last_reset_date TEXT,
        counter_name TEXT DEFAULT 'Loket 1 · Poli Umum',
        total_called_today INTEGER DEFAULT 0
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS reviews (
        id TEXT PRIMARY KEY,
        patient_id TEXT NOT NULL,
        patient_name TEXT NOT NULL,
        source TEXT DEFAULT 'Online',
        service TEXT NOT NULL,
        readiness TEXT NOT NULL,
        status_class TEXT,
        reason TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS prescriptions (
        id TEXT PRIMARY KEY,
        patient_id TEXT NOT NULL,
        patient_name TEXT NOT NULL,
        patient_email TEXT NOT NULL,
        doctor TEXT NOT NULL,
        clinic TEXT NOT NULL,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        queue_no TEXT,
        status TEXT NOT NULL,
        status_class TEXT,
        counter TEXT NOT NULL,
        notes TEXT,
        medications_json TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS referrals (
        id TEXT PRIMARY KEY,
        patient_id TEXT,
        patient_name TEXT,
        patient_email TEXT,
        source_faskes TEXT,
        target_faskes TEXT,
        target_clinic TEXT,
        notes TEXT,
        doctor TEXT,
        date TEXT,
        time TEXT,
        status TEXT,
        status_class TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS operational_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        desc TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS requirements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        clinic TEXT NOT NULL,
        reqs TEXT NOT NULL,
        mandatory TEXT NOT NULL,
        status TEXT NOT NULL,
        status_class TEXT
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        hospital TEXT NOT NULL,
        requirements TEXT NOT NULL,
        status TEXT NOT NULL,
        status_class TEXT
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS faskes2_partners (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        city TEXT NOT NULL,
        phone TEXT NOT NULL,
        status TEXT NOT NULL,
        status_class TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS system_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time TEXT NOT NULL,
        category TEXT NOT NULL,
        event TEXT NOT NULL,
        status TEXT NOT NULL,
        status_class TEXT
    )""")

    for sql in [
        "ALTER TABLE patients ADD COLUMN faskes2 TEXT",
        "ALTER TABLE patients ADD COLUMN ref_id TEXT",
        "ALTER TABLE patients ADD COLUMN document_url TEXT",
        "ALTER TABLE patients ADD COLUMN document_name TEXT",
        "ALTER TABLE patients ADD COLUMN document_type TEXT",
        "ALTER TABLE reviews ADD COLUMN reason TEXT",
        "ALTER TABLE reviews ADD COLUMN document_url TEXT",
        "ALTER TABLE reviews ADD COLUMN document_name TEXT",
        "ALTER TABLE reviews ADD COLUMN document_type TEXT",
        "ALTER TABLE registrations ADD COLUMN target_faskes TEXT",
        "ALTER TABLE registrations ADD COLUMN target_clinic TEXT",
        "ALTER TABLE registrations ADD COLUMN ref_id TEXT",
        "ALTER TABLE registrations ADD COLUMN patient_id TEXT",
        "ALTER TABLE registrations ADD COLUMN finance TEXT",
        "ALTER TABLE registrations ADD COLUMN document_url TEXT",
        "ALTER TABLE registrations ADD COLUMN document_name TEXT",
        "ALTER TABLE registrations ADD COLUMN document_type TEXT",
        "ALTER TABLE required_actions ADD COLUMN document_url TEXT",
        "ALTER TABLE required_actions ADD COLUMN document_name TEXT",
        "ALTER TABLE required_actions ADD COLUMN document_type TEXT"
    ]:
        try:
            c.execute(sql)
        except Exception:
            pass

    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        for u in DEFAULT_SEED_USERS:
            c.execute("""
            INSERT INTO users (id, email, password, name, role, role_label, phone, identity_number, scope, status, auth_provider, google_id, avatar_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (u['id'], u['email'], u['password'], u['name'], u['role'], u['role_label'], u['phone'], u['identity_number'], u['scope'], u['status'], u['auth_provider'], u.get('google_id'), u.get('avatar_url')))
        for k, p in DEFAULT_SEED_PROFILES.items():
            c.execute("""
            INSERT INTO profiles (key, user_email, name, identity_number, phone, dob, dob_text, relationship, badge)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (k, p['user_email'], p['name'], p['identity_number'], p['phone'], p['dob'], p['dob_text'], p['relationship'], p['badge']))

    c.execute("SELECT COUNT(*) FROM faskes2_partners")
    if c.fetchone()[0] == 0:
        for f in FASKES2_PARTNERS:
            c.execute("""
            INSERT INTO faskes2_partners (id, name, type, city, phone, status, status_class)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (f['id'], f['name'], f['type'], f['city'], f['phone'], f['status'], f.get('status_class', 'green')))

    c.execute("SELECT COUNT(*) FROM queue_state WHERE id = 1")
    if c.fetchone()[0] == 0:
        c.execute("""
        INSERT INTO queue_state (id, prefix, current_number, current_code, daily_sequence, last_reset_date, counter_name, total_called_today)
        VALUES (1, 'A', 0, 'A-000', 0, ?, 'Loket 1 · Poli Umum', 0)
        """, (datetime.now().strftime('%Y-%m-%d'),))

    conn.commit()
    conn.close()

def load_all_from_db():
    global USERS_DB, USERS_LIST, SAVED_PROFILES, PATIENTS, ACTIVE_REGISTRATIONS
    global REGISTRATION_HISTORY, REQUIRED_ACTIONS, QUEUE_LIST, QUEUE_STATE
    global REVIEW_LIST, PRESCRIPTIONS, REFERRALS, OPERATIONAL_HISTORY, SYSTEM_LOGS
    global FASKES2_PARTNERS, REQUIREMENTS, SERVICES_LIST

    try:
        conn = get_db()

        u_rows = conn.execute("SELECT * FROM users ORDER BY created_at ASC").fetchall()
        USERS_DB.clear()
        USERS_LIST.clear()
        for r in u_rows:
            d = dict(r)
            USERS_DB[d['email']] = d
            USERS_LIST.append({
                'username': d['email'],
                'name': d['name'],
                'role': d['role_label'],
                'scope': d.get('scope', 'Klinik SKEM'),
                'status': d.get('status', 'Aktif'),
                'status_class': 'green' if d.get('status') == 'Aktif' else 'amber'
            })

        p_rows = conn.execute("SELECT * FROM profiles ORDER BY created_at ASC").fetchall()
        SAVED_PROFILES.clear()
        for r in p_rows:
            SAVED_PROFILES[r['key']] = dict(r)

        pat_rows = conn.execute("SELECT * FROM patients ORDER BY id ASC").fetchall()
        PATIENTS.clear()
        for r in pat_rows:
            PATIENTS.append(dict(r))

        reg_rows = conn.execute("SELECT * FROM registrations ORDER BY id DESC").fetchall()
        REGISTRATION_HISTORY.clear()
        ACTIVE_REGISTRATIONS.clear()
        for r in reg_rows:
            item = dict(r)
            item['id'] = item['code']
            item['service'] = item.get('clinic', 'Poli Umum')
            if not item.get('patient_id'):
                item['patient_id'] = 'P-' + item['code'].replace('FF-', '')
            if not item.get('finance'):
                item['finance'] = 'Mandiri'
            REGISTRATION_HISTORY.append(item)
            if item.get('status') not in ('Selesai', 'Selesai di Faskes Ini'):
                ACTIVE_REGISTRATIONS.append(item)

        act_rows = conn.execute("SELECT * FROM required_actions ORDER BY created_at DESC").fetchall()
        REQUIRED_ACTIONS.clear()
        for r in act_rows:
            REQUIRED_ACTIONS.append(dict(r))

        q_rows = conn.execute("SELECT * FROM queues ORDER BY id ASC").fetchall()
        QUEUE_LIST.clear()
        for r in q_rows:
            d = dict(r)
            d['can_call'] = bool(d.get('can_call', 1))
            QUEUE_LIST.append(d)

        qs_row = conn.execute("SELECT * FROM queue_state WHERE id = 1").fetchone()
        if qs_row:
            QUEUE_STATE.update(dict(qs_row))

        rev_rows = conn.execute("SELECT * FROM reviews ORDER BY id ASC").fetchall()
        REVIEW_LIST.clear()
        for r in rev_rows:
            REVIEW_LIST.append(dict(r))

        rx_rows = conn.execute("SELECT * FROM prescriptions ORDER BY created_at DESC, id DESC").fetchall()
        PRESCRIPTIONS.clear()
        for r in rx_rows:
            d = dict(r)
            try:
                d['medications'] = json.loads(d.get('medications_json') or '[]')
            except Exception:
                d['medications'] = []
            PRESCRIPTIONS.append(d)

        ref_rows = conn.execute("SELECT * FROM referrals ORDER BY created_at DESC, id DESC").fetchall()
        REFERRALS.clear()
        for r in ref_rows:
            REFERRALS.append(dict(r))

        fk2_rows = conn.execute("SELECT * FROM faskes2_partners ORDER BY id ASC").fetchall()
        if fk2_rows:
            FASKES2_PARTNERS.clear()
            for r in fk2_rows:
                FASKES2_PARTNERS.append(dict(r))

        req_rows = conn.execute("SELECT * FROM requirements ORDER BY id ASC").fetchall()
        if req_rows:
            REQUIREMENTS.clear()
            for r in req_rows:
                REQUIREMENTS.append(dict(r))

        srv_rows = conn.execute("SELECT * FROM services ORDER BY id ASC").fetchall()
        if srv_rows:
            SERVICES_LIST.clear()
            for r in srv_rows:
                SERVICES_LIST.append(dict(r))

        op_rows = conn.execute("SELECT * FROM operational_history ORDER BY id DESC").fetchall()
        OPERATIONAL_HISTORY.clear()
        for r in op_rows:
            OPERATIONAL_HISTORY.append(dict(r))

        log_rows = conn.execute("SELECT * FROM system_logs ORDER BY id DESC").fetchall()
        if log_rows:
            SYSTEM_LOGS.clear()
            for r in log_rows:
                SYSTEM_LOGS.append(dict(r))

        conn.close()
    except Exception as e:
        print(f"Error memuat data SQLite: {e}")

def db_save_user(u):
    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO users (id, email, password, name, role, role_label, phone, identity_number, scope, status, auth_provider, google_id, avatar_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                password=excluded.password, name=excluded.name, role=excluded.role, role_label=excluded.role_label,
                phone=excluded.phone, identity_number=excluded.identity_number, scope=excluded.scope, status=excluded.status,
                auth_provider=excluded.auth_provider, google_id=excluded.google_id, avatar_url=excluded.avatar_url
        """, (
            u.get('id'), u.get('email', '').lower(), u.get('password'), u.get('name'), u.get('role'),
            u.get('role_label'), u.get('phone', ''), u.get('identity_number', ''), u.get('scope', 'Klinik SKEM'),
            u.get('status', 'Aktif'), u.get('auth_provider', 'local'), u.get('google_id'), u.get('avatar_url')
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_save_user: {e}")

def db_update_user_status(email, status):
    try:
        conn = get_db()
        conn.execute("UPDATE users SET status = ? WHERE LOWER(email) = LOWER(?)", (status, email))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_update_user_status: {e}")

def db_save_profile(p):
    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO profiles (key, user_email, name, identity_number, phone, dob, dob_text, relationship, badge)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                user_email=excluded.user_email, name=excluded.name, identity_number=excluded.identity_number,
                phone=excluded.phone, dob=excluded.dob, dob_text=excluded.dob_text, relationship=excluded.relationship, badge=excluded.badge
        """, (
            p.get('key'), p.get('user_email', '').lower(), p.get('name'), p.get('identity_number', ''),
            p.get('phone', ''), p.get('dob', ''), p.get('dob_text', ''), p.get('relationship', 'Keluarga'), p.get('badge', '')
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_save_profile: {e}")

def db_delete_profile(key):
    try:
        conn = get_db()
        conn.execute("DELETE FROM profiles WHERE key = ?", (key,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_delete_profile: {e}")

def db_save_patient(p):
    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO patients (id, name, phone, date, service, finance, status, form, faskes2, ref_id, document_url, document_name, document_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, phone=excluded.phone, date=excluded.date, service=excluded.service,
                finance=excluded.finance, status=excluded.status, form=excluded.form, faskes2=excluded.faskes2, ref_id=excluded.ref_id,
                document_url=excluded.document_url, document_name=excluded.document_name, document_type=excluded.document_type
        """, (
            p.get('id'), p.get('name'), p.get('phone', ''), p.get('date', ''), p.get('service', 'Poli Umum'),
            p.get('finance', 'Mandiri'), p.get('status', 'Terdaftar'), p.get('form', ''), p.get('faskes2'), p.get('ref_id'),
            p.get('document_url'), p.get('document_name'), p.get('document_type')
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_save_patient: {e}")

def db_save_registration(reg):
    try:
        code = reg.get('code') or reg.get('id')
        conn = get_db()
        conn.execute("""
            INSERT INTO registrations (code, user_email, patient_name, patient_id, clinic, date, finance, status, status_class, hospital, target_faskes, target_clinic, ref_id, document_url, document_name, document_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                patient_name=excluded.patient_name, patient_id=excluded.patient_id, clinic=excluded.clinic, date=excluded.date,
                finance=excluded.finance, status=excluded.status, status_class=excluded.status_class, hospital=excluded.hospital,
                target_faskes=excluded.target_faskes, target_clinic=excluded.target_clinic, ref_id=excluded.ref_id,
                document_url=excluded.document_url, document_name=excluded.document_name, document_type=excluded.document_type
        """, (
            code, reg.get('user_email', ''), reg.get('patient_name', ''), reg.get('patient_id', ''),
            reg.get('clinic') or reg.get('service', 'Poli Umum'), reg.get('date', ''),
            reg.get('finance', 'Mandiri'),
            reg.get('status', 'Menunggu verifikasi'), reg.get('status_class', 'blue'), reg.get('hospital', 'Klinik SKEM'),
            reg.get('target_faskes'), reg.get('target_clinic'), reg.get('ref_id'),
            reg.get('document_url'), reg.get('document_name'), reg.get('document_type')
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_save_registration: {e}")

def db_update_registration_status(code, status, status_class, hospital=None, target_faskes=None, target_clinic=None, ref_id=None):
    try:
        conn = get_db()
        query = "UPDATE registrations SET status = ?, status_class = ?"
        params = [status, status_class]
        if hospital is not None:
            query += ", hospital = ?"
            params.append(hospital)
        if target_faskes is not None:
            query += ", target_faskes = ?"
            params.append(target_faskes)
        if target_clinic is not None:
            query += ", target_clinic = ?"
            params.append(target_clinic)
        if ref_id is not None:
            query += ", ref_id = ?"
            params.append(ref_id)
        query += " WHERE code = ?"
        params.append(code)
        conn.execute(query, tuple(params))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_update_registration_status: {e}")

def db_save_required_action(action):
    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO required_actions (code, title, service, patient_name, patient_id, reason, user_email, document_url, document_name, document_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                title=excluded.title, service=excluded.service, patient_name=excluded.patient_name,
                patient_id=excluded.patient_id, reason=excluded.reason, user_email=excluded.user_email,
                document_url=excluded.document_url, document_name=excluded.document_name, document_type=excluded.document_type
        """, (
            action.get('code'), action.get('title'), action.get('service'), action.get('patient_name'),
            action.get('patient_id'), action.get('reason'), action.get('user_email', ''),
            action.get('document_url'), action.get('document_name'), action.get('document_type')
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_save_required_action: {e}")

def db_delete_required_action(code):
    try:
        conn = get_db()
        conn.execute("DELETE FROM required_actions WHERE code = ?", (code,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_delete_required_action: {e}")

def db_save_queue(q):
    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO queues (queue_no, patient_id, patient_name, patient_email, source, service, status, status_class, can_call)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(queue_no) DO UPDATE SET
                patient_id=excluded.patient_id, patient_name=excluded.patient_name, source=excluded.source,
                service=excluded.service, status=excluded.status, status_class=excluded.status_class, can_call=excluded.can_call
        """, (
            q.get('queue_no'), q.get('patient_id'), q.get('patient_name'), q.get('patient_email', ''),
            q.get('source', 'Online'), q.get('service', 'Poli Umum'), q.get('status', 'Menunggu'),
            q.get('status_class', 'blue'), 1 if q.get('can_call', True) else 0
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_save_queue: {e}")

def db_update_queue_status(queue_no, status, status_class='blue', can_call=1):
    try:
        conn = get_db()
        conn.execute("UPDATE queues SET status = ?, status_class = ?, can_call = ? WHERE queue_no = ?", (status, status_class, can_call, queue_no))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_update_queue_status: {e}")

def db_save_queue_state():
    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO queue_state (id, prefix, current_number, current_code, daily_sequence, last_reset_date, counter_name, total_called_today)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                prefix=excluded.prefix, current_number=excluded.current_number, current_code=excluded.current_code,
                daily_sequence=excluded.daily_sequence, last_reset_date=excluded.last_reset_date,
                counter_name=excluded.counter_name, total_called_today=excluded.total_called_today
        """, (
            QUEUE_STATE.get('prefix', 'A'), QUEUE_STATE.get('current_number', 0), QUEUE_STATE.get('current_code', 'A-000'),
            QUEUE_STATE.get('daily_sequence', 0), QUEUE_STATE.get('last_reset_date', ''), QUEUE_STATE.get('counter_name', 'Loket 1 · Poli Umum'),
            QUEUE_STATE.get('total_called_today', 0)
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_save_queue_state: {e}")

def db_save_review(r):
    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO reviews (id, patient_id, patient_name, source, service, readiness, status_class, reason, document_url, document_name, document_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                patient_id=excluded.patient_id, patient_name=excluded.patient_name, source=excluded.source,
                service=excluded.service, readiness=excluded.readiness, status_class=excluded.status_class, reason=excluded.reason,
                document_url=excluded.document_url, document_name=excluded.document_name, document_type=excluded.document_type
        """, (
            r.get('id'), r.get('patient_id'), r.get('patient_name'), r.get('source', 'Online'),
            r.get('service', 'Poli Umum'), r.get('readiness', 'Perlu diperiksa'), r.get('status_class', 'amber'), r.get('reason'),
            r.get('document_url'), r.get('document_name'), r.get('document_type')
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_save_review: {e}")

def db_update_review_status(review_id, readiness, status_class, reason=None):
    try:
        conn = get_db()
        if reason is not None:
            conn.execute("UPDATE reviews SET readiness = ?, status_class = ?, reason = ? WHERE id = ?", (readiness, status_class, reason, review_id))
        else:
            conn.execute("UPDATE reviews SET readiness = ?, status_class = ? WHERE id = ?", (readiness, status_class, review_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_update_review_status: {e}")

def db_save_prescription(rx):
    try:
        conn = get_db()
        meds_json = json.dumps(rx.get('medications', []))
        conn.execute("""
            INSERT INTO prescriptions (id, patient_id, patient_name, patient_email, doctor, clinic, date, time, queue_no, status, status_class, counter, notes, medications_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                patient_id=excluded.patient_id, patient_name=excluded.patient_name, patient_email=excluded.patient_email,
                doctor=excluded.doctor, clinic=excluded.clinic, date=excluded.date, time=excluded.time,
                queue_no=excluded.queue_no, status=excluded.status, status_class=excluded.status_class,
                counter=excluded.counter, notes=excluded.notes, medications_json=excluded.medications_json
        """, (
            rx.get('id'), rx.get('patient_id'), rx.get('patient_name'), rx.get('patient_email', ''),
            rx.get('doctor'), rx.get('clinic'), rx.get('date'), rx.get('time'), rx.get('queue_no'),
            rx.get('status'), rx.get('status_class'), rx.get('counter'), rx.get('notes'), meds_json
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_save_prescription: {e}")

def db_update_prescription_status(rx_id, status, status_class):
    try:
        conn = get_db()
        conn.execute("UPDATE prescriptions SET status = ?, status_class = ? WHERE id = ?", (status, status_class, rx_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_update_prescription_status: {e}")

def db_delete_prescription(rx_id):
    try:
        conn = get_db()
        conn.execute("DELETE FROM prescriptions WHERE id = ?", (rx_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_delete_prescription: {e}")

def db_save_referral(ref):
    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO referrals (id, patient_id, patient_name, patient_email, source_faskes, target_faskes, target_clinic, notes, doctor, date, time, status, status_class)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                patient_id=excluded.patient_id, patient_name=excluded.patient_name, patient_email=excluded.patient_email,
                source_faskes=excluded.source_faskes, target_faskes=excluded.target_faskes, target_clinic=excluded.target_clinic,
                notes=excluded.notes, doctor=excluded.doctor, date=excluded.date, time=excluded.time,
                status=excluded.status, status_class=excluded.status_class
        """, (
            ref.get('id'), ref.get('patient_id'), ref.get('patient_name'), ref.get('patient_email', ''),
            ref.get('source_faskes', 'Klinik SKEM'), ref.get('target_faskes'), ref.get('target_clinic'),
            ref.get('notes'), ref.get('doctor'), ref.get('date'), ref.get('time'), ref.get('status'), ref.get('status_class')
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_save_referral: {e}")

def db_save_operational_history(title, desc):
    try:
        conn = get_db()
        conn.execute("INSERT INTO operational_history (title, desc) VALUES (?, ?)", (title, desc))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_save_operational_history: {e}")

def db_save_system_log(category, event, status='Berhasil', status_class='green'):
    now_str = datetime.now().strftime("%d %b %Y %H:%M")
    try:
        conn = get_db()
        conn.execute("INSERT INTO system_logs (time, category, event, status, status_class) VALUES (?, ?, ?, ?, ?)", (now_str, category, event, status, status_class))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_save_system_log: {e}")

def db_save_faskes2_partner(p):
    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO faskes2_partners (id, name, type, city, phone, status, status_class)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, type=excluded.type, city=excluded.city,
                phone=excluded.phone, status=excluded.status, status_class=excluded.status_class
        """, (
            p.get('id'), p.get('name'), p.get('type'), p.get('city'), p.get('phone'),
            p.get('status', 'Aktif'), p.get('status_class', 'green')
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_save_faskes2_partner: {e}")

def db_delete_faskes2_partner(partner_id):
    try:
        conn = get_db()
        conn.execute("DELETE FROM faskes2_partners WHERE id = ?", (partner_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_delete_faskes2_partner: {e}")

def db_save_requirement(req, req_id=None):
    try:
        conn = get_db()
        if req_id:
            conn.execute("""
                UPDATE requirements SET clinic = ?, reqs = ?, mandatory = ?, status = ?, status_class = ?
                WHERE id = ?
            """, (req.get('clinic'), req.get('reqs'), req.get('mandatory', 'Ya'), req.get('status', 'Aktif'), req.get('status_class', 'green'), req_id))
        else:
            conn.execute("""
                INSERT INTO requirements (clinic, reqs, mandatory, status, status_class)
                VALUES (?, ?, ?, ?, ?)
            """, (req.get('clinic'), req.get('reqs'), req.get('mandatory', 'Ya'), req.get('status', 'Aktif'), req.get('status_class', 'green')))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_save_requirement: {e}")

def db_delete_requirement(clinic_name):
    try:
        conn = get_db()
        conn.execute("DELETE FROM requirements WHERE clinic = ?", (clinic_name,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_delete_requirement: {e}")

def db_save_service(srv, srv_id=None):
    try:
        conn = get_db()
        if srv_id:
            conn.execute("""
                UPDATE services SET name = ?, hospital = ?, requirements = ?, status = ?, status_class = ?
                WHERE id = ?
            """, (srv.get('name'), srv.get('hospital', 'Klinik SKEM'), srv.get('requirements', ''), srv.get('status', 'Aktif'), srv.get('status_class', 'green'), srv_id))
        else:
            conn.execute("""
                INSERT INTO services (name, hospital, requirements, status, status_class)
                VALUES (?, ?, ?, ?, ?)
            """, (srv.get('name'), srv.get('hospital', 'Klinik SKEM'), srv.get('requirements', ''), srv.get('status', 'Aktif'), srv.get('status_class', 'green')))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_save_service: {e}")

def db_delete_service(service_name):
    try:
        conn = get_db()
        conn.execute("DELETE FROM services WHERE name = ?", (service_name,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_delete_service: {e}")

def db_reset_all_except_users():
    try:
        conn = get_db()
        conn.execute("DELETE FROM registrations")
        conn.execute("DELETE FROM required_actions")
        conn.execute("DELETE FROM queues")
        conn.execute("DELETE FROM reviews")
        conn.execute("DELETE FROM prescriptions")
        conn.execute("DELETE FROM referrals")
        conn.execute("DELETE FROM operational_history")
        conn.execute("DELETE FROM patients")
        conn.execute("UPDATE queue_state SET current_number=0, current_code='A-000', daily_sequence=0, total_called_today=0 WHERE id=1")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error db_reset_all_except_users: {e}")

def check_daily_queue_reset():
    """Otomatis mereset nomor antrean setiap hari baru saat sistem diakses."""
    today_str = datetime.now().strftime('%Y-%m-%d')
    if QUEUE_STATE.get('last_reset_date') != today_str:
        old_code = QUEUE_STATE.get('current_code', 'A-000')
        prefix = QUEUE_STATE.get('prefix', 'A')
        QUEUE_STATE['current_number'] = 0
        QUEUE_STATE['current_code'] = f"{prefix}-000"
        QUEUE_STATE['daily_sequence'] = 0
        QUEUE_STATE['last_reset_date'] = today_str
        QUEUE_STATE['total_called_today'] = 0
        db_save_queue_state()
        
        log_event = f"Pergantian hari otomatis ({today_str}): Nomor antrean direset dari {old_code} menjadi {QUEUE_STATE['current_code']}"
        SYSTEM_LOGS.insert(0, {
            'time': datetime.now().strftime("%d %b %Y %H:%M"),
            'category': 'Reset Antrean Harian',
            'event': log_event,
            'status': 'Otomatis',
            'status_class': 'green'
        })
        db_save_system_log('Reset Antrean Harian', log_event, 'Otomatis', 'green')

# Inisialisasi dan muat seluruh data persisten dari SQLite klinik_skem.db saat aplikasi dimulai
init_sqlite_db()
load_all_from_db()

# ==============================================================================
# HELPER DATA ISOLATION & PRIVASI PASIEN
# ==============================================================================
def find_patient_email(patient_name=None, patient_id=None, form_id=None):
    """Mencari alamat email pemilik akun dari pendaftaran, antrean, profil keluarga, atau USERS_DB."""
    if form_id:
        for r in ACTIVE_REGISTRATIONS + REGISTRATION_HISTORY:
            if (r.get('code') == form_id or r.get('id') == form_id) and r.get('user_email'):
                return r.get('user_email').strip().lower()
    if patient_id:
        for q in QUEUE_LIST:
            if q.get('patient_id') == patient_id and q.get('patient_email'):
                return q.get('patient_email').strip().lower()
        for p in PATIENTS:
            if p.get('id') == patient_id and p.get('form'):
                for r in ACTIVE_REGISTRATIONS + REGISTRATION_HISTORY:
                    if (r.get('code') == p.get('form') or r.get('id') == p.get('form')) and r.get('user_email'):
                        return r.get('user_email').strip().lower()
    if patient_name:
        p_name_lower = patient_name.strip().lower()
        for p in SAVED_PROFILES.values():
            if p.get('name', '').strip().lower() == p_name_lower and p.get('user_email'):
                return p.get('user_email').strip().lower()
        for r in ACTIVE_REGISTRATIONS + REGISTRATION_HISTORY:
            if r.get('patient_name', '').strip().lower() == p_name_lower and r.get('user_email'):
                return r.get('user_email').strip().lower()
        for u in USERS_DB.values():
            if u.get('name', '').strip().lower() == p_name_lower and u.get('email'):
                return u.get('email').strip().lower()
    return ''

def get_current_patient_scope():
    """Mengembalikan user, user_email, user_name, accessible_names (set lowercase), my_profiles, dan my_reg_codes untuk akun pasien yang sedang login."""
    user = session.get('user', {})
    user_email = (user.get('email') or '').strip().lower()
    user_name = (user.get('name') or '').strip()

    my_profiles = {}
    if user_email:
        my_profiles = {k: v for k, v in SAVED_PROFILES.items() if (v.get('user_email') or '').strip().lower() == user_email}

    accessible_names = set()
    if user_name:
        accessible_names.add(user_name.lower())
    for prof in my_profiles.values():
        if prof.get('name'):
            accessible_names.add(prof['name'].strip().lower())

    my_reg_codes = set()
    for r in REGISTRATION_HISTORY + ACTIVE_REGISTRATIONS:
        r_email = (r.get('user_email') or '').strip().lower()
        r_name = (r.get('patient_name') or '').strip().lower()
        if (r_email and r_email == user_email) or (not r_email and r_name in accessible_names):
            if r.get('code'):
                my_reg_codes.add(r['code'])
            if r.get('id'):
                my_reg_codes.add(r['id'])
            if r.get('ref_id'):
                my_reg_codes.add(r['ref_id'])

    return user, user_email, user_name, accessible_names, my_profiles, my_reg_codes

def is_patient_record(item, user_email, accessible_names, my_reg_codes=None):
    """Memvalidasi dengan ketat apakah data milik pasien yang sedang login (mencegah data bocor ke akun lain)."""
    if not user_email:
        return False
    item_email = (item.get('user_email') or item.get('patient_email') or '').strip().lower()
    # 1. Jika item memiliki email, maka email HARUS cocok persis dengan akun pasien
    if item_email:
        return item_email == user_email
    # 2. Jika tidak ada email, cocokkan dengan kode pendaftaran yang dimiliki pasien
    if my_reg_codes:
        code = item.get('code') or item.get('id') or item.get('ref_id') or ''
        if code and code in my_reg_codes:
            return True
    # 3. Jika tidak ada email dan tidak ada kode, cocokkan dengan nama pasien / profil keluarga yang dikelola
    item_name = (item.get('patient_name') or item.get('name') or '').strip().lower()
    if item_name and item_name in accessible_names:
        return True
    return False

# ==============================================================================
# CONTEXT PROCESSOR (Injeksi global current_user, current_role, faskes2_partners ke template)
# ==============================================================================
@app.context_processor
def inject_user_context():
    check_daily_queue_reset()
    user = session.get('user')
    pending_actions = len(REQUIRED_ACTIONS)
    if user and user.get('role') == 'patient':
        _, u_email, _, acc_names, _, my_codes = get_current_patient_scope()
        pending_actions = sum(1 for a in REQUIRED_ACTIONS if is_patient_record(a, u_email, acc_names, my_codes))
    return {
        'current_user': user,
        'current_role': user.get('role') if user else None,
        'faskes2_partners': FASKES2_PARTNERS,
        'specialty_clinics': SPECIALTY_CLINICS,
        'queue_state': QUEUE_STATE,
        'pending_action_count': pending_actions
    }

# ==============================================================================
# HELPER FUNCTION: ROLE REDIRECT URL
# ==============================================================================
def get_role_home_url(role):
    if role == 'facility':
        return url_for('facility.dashboard')
    elif role == 'system':
        return url_for('system.dashboard')
    return url_for('patient.home')

# ==============================================================================
# BEFORE REQUEST: AUTHENTICATION & ROLE ACCESS GUARD
# ==============================================================================
@app.before_request
def auth_guard():
    public_endpoints = {
        'auth.login', 'auth.register', 'auth.logout',
        'auth.google_login', 'auth.google_direct', 'auth.google_callback',
        'auth.google_save_config', 'auth.google_reset_config',
        'login', 'register', 'logout', 'static', 'patient.api_queue_status'
    }
    endpoint = request.endpoint

    if not endpoint:
        return None

    if endpoint in public_endpoints or endpoint.startswith('auth.'):
        return None

    user = session.get('user')
    if not user:
        flash("Silakan masuk terlebih dahulu untuk melanjutkan.")
        return redirect(url_for('auth.login'))

    blueprint_name = endpoint.split('.')[0] if '.' in endpoint else None
    user_role = user.get('role')

    if blueprint_name in {'patient', 'facility', 'system'}:
        if blueprint_name != user_role:
            flash(f"Akses dialihkan ke portal Anda ({user.get('role_label')}).")
            return redirect(get_role_home_url(user_role))

    return None

# ==============================================================================
# BLUEPRINT 0: AUTENTIKASI (auth) & LOGIN GOOGLE
# ==============================================================================
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user'):
        return redirect(get_role_home_url(session['user']['role']))

    if request.method == 'POST':
        email_or_user = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()

        user_match = None
        for u in USERS_DB.values():
            if u['email'].lower() == email_or_user or u.get('identity_number', '').lower() == email_or_user:
                if u.get('password') == password:
                    user_match = u
                    break

        if user_match:
            if user_match.get('status') == 'Nonaktif':
                flash("Akun Anda saat ini dinonaktifkan oleh administrator.")
                return render_template('auth/login.html', email=email_or_user)

            session['user'] = {
                'id': user_match['id'],
                'email': user_match['email'],
                'name': user_match['name'],
                'role': user_match['role'],
                'role_label': user_match['role_label'],
                'phone': user_match.get('phone', ''),
                'identity_number': user_match.get('identity_number', ''),
                'auth_provider': user_match.get('auth_provider', 'local'),
                'avatar_url': user_match.get('avatar_url')
            }
            SYSTEM_LOGS.insert(0, {
                'time': datetime.now().strftime("%d %b %Y %H:%M"),
                'category': 'Autentikasi',
                'event': f"Masuk berhasil: {user_match['name']} ({user_match['role_label']})",
                'status': 'Berhasil',
                'status_class': 'green'
            })
            flash(f"Selamat datang kembali di Klinik SKEM, {user_match['name']}!")
            return redirect(get_role_home_url(user_match['role']))
        else:
            flash("Email atau kata sandi tidak valid. Coba gunakan akun demo atau Masuk dengan Google.")
            return render_template('auth/login.html', email=email_or_user)

    return render_template('auth/login.html')

@auth_bp.route('/demo/<role>', methods=['GET', 'POST'])
def demo_login(role):
    """Login 1-klik untuk pengujian demonstrasi berbagai role (Pasien, Petugas Klinik, Admin Sistem)."""
    role_map = {
        'pasien': 'pasien@local',
        'patient': 'pasien@local',
        'dinda': 'pasien@local',
        'petugas': 'petugas@local',
        'facility': 'petugas@local',
        'andi': 'petugas@local',
        'admin': 'admin@local',
        'system': 'admin@local'
    }
    target_email = role_map.get(role.lower())
    if not target_email or target_email not in USERS_DB:
        flash(f"Akun demo untuk role '{role}' tidak ditemukan.")
        return redirect(url_for('auth.login'))

    user_match = USERS_DB[target_email]
    session['user'] = {
        'id': user_match['id'],
        'email': user_match['email'],
        'name': user_match['name'],
        'role': user_match['role'],
        'role_label': user_match['role_label'],
        'phone': user_match.get('phone', ''),
        'identity_number': user_match.get('identity_number', ''),
        'auth_provider': user_match.get('auth_provider', 'local'),
        'avatar_url': user_match.get('avatar_url')
    }
    SYSTEM_LOGS.insert(0, {
        'time': datetime.now().strftime("%d %b %Y %H:%M"),
        'category': 'Autentikasi Demo',
        'event': f"Masuk cepat akun demo: {user_match['name']} ({user_match['role_label']})",
        'status': 'Berhasil',
        'status_class': 'green'
    })
    flash(f"Berhasil masuk sebagai {user_match['name']} ({user_match['role_label']}) [Mode Demo].")
    return redirect(get_role_home_url(user_match['role']))

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if session.get('user'):
        return redirect(get_role_home_url(session['user']['role']))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        identity_number = request.form.get('identity_number', '').strip()
        role = 'patient'
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        form_data = {
            'name': name, 'email': email, 'phone': phone,
            'identity_number': identity_number, 'role': role
        }

        if email in USERS_DB:
            flash("Alamat email sudah terdaftar. Silakan masuk.")
            return render_template('auth/register.html', form_data=form_data)

        if password != confirm_password:
            flash("Konfirmasi kata sandi tidak cocok.")
            return render_template('auth/register.html', form_data=form_data)

        if len(password) < 4:
            flash("Kata sandi terlalu pendek (minimal 4 karakter).")
            return render_template('auth/register.html', form_data=form_data)

        role_label = 'Pasien'
        new_id = f"U{len(USERS_DB) + 1:03d}"

        new_user = {
            'id': new_id,
            'email': email,
            'password': password,
            'name': name,
            'role': role,
            'role_label': role_label,
            'phone': phone,
            'identity_number': identity_number,
            'scope': 'Klinik SKEM',
            'status': 'Aktif',
            'auth_provider': 'local',
            'avatar_url': None
        }
        USERS_DB[email] = new_user
        db_save_user(new_user)

        USERS_LIST.append({
            'username': email,
            'name': name,
            'role': role_label,
            'scope': 'Klinik SKEM',
            'status': 'Aktif',
            'status_class': 'green'
        })

        # Buat profil utama pasien otomatis
        badge_suffix = f"••••{identity_number[-4:]}" if len(identity_number) >= 4 else identity_number
        SAVED_PROFILES['utama_' + new_id] = {
            'key': 'utama_' + new_id,
            'user_email': email,
            'name': name,
            'id': identity_number,
            'identity_number': identity_number,
            'phone': phone,
            'dob': '1998-01-01',
            'dob_text': '1 Januari 1998',
            'relationship': 'Utama',
            'badge': f"Pasien Utama · DEMO-NIK {badge_suffix}"
        }
        db_save_profile(SAVED_PROFILES['utama_' + new_id])

        session['user'] = {
            'id': new_user['id'],
            'email': new_user['email'],
            'name': new_user['name'],
            'role': new_user['role'],
            'role_label': new_user['role_label'],
            'phone': new_user['phone'],
            'identity_number': new_user['identity_number'],
            'auth_provider': 'local',
            'avatar_url': None
        }

        SYSTEM_LOGS.insert(0, {
            'time': datetime.now().strftime("%d %b %Y %H:%M"),
            'category': 'Autentikasi',
            'event': f"Pendaftaran akun pasien baru: {name}",
            'status': 'Berhasil',
            'status_class': 'green'
        })
        db_save_system_log('Autentikasi', f"Pendaftaran akun pasien baru: {name}", 'Berhasil', 'green')
        flash(f"Akun berhasil didaftarkan di Klinik SKEM! Selamat datang, {name}.")
        return redirect(get_role_home_url(role))

    return render_template('auth/register.html')

@auth_bp.route('/google')
def google_login():
    """Tampilkan antarmuka tunggal: Login dengan Google."""
    if session.get('user'):
        return redirect(get_role_home_url(session['user']['role']))
    
    cfg = get_google_config()
    client_id = cfg.get('client_id')
    client_secret = cfg.get('client_secret')
    is_configured = bool(client_id)
    
    redirect_uri = get_oauth_redirect_uri()
    app_origin = get_app_origin()
    show_setup = request.args.get('setup') == '1'
        
    return render_template(
        'auth/google_select.html',
        google_client_id=client_id,
        google_client_secret=client_secret,
        is_configured=is_configured,
        redirect_uri=redirect_uri,
        app_origin=app_origin,
        show_setup=show_setup
    )

@auth_bp.route('/google/direct')
def google_direct():
    """Redirect langsung browser pengguna ke halaman login Google resmi (accounts.google.com)."""
    if session.get('user'):
        return redirect(get_role_home_url(session['user']['role']))
    
    cfg = get_google_config()
    client_id = cfg.get('client_id')
    if not client_id:
        flash("Google Client ID belum dikonfigurasi. Masukkan Client ID terlebih dahulu.")
        return redirect(url_for('auth.google_login'))
    
    redirect_uri = get_oauth_redirect_uri()
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'access_type': 'online',
        'prompt': 'select_account'
    }
    google_auth_url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urllib.parse.urlencode(params)
    return redirect(google_auth_url)

@auth_bp.route('/google/config', methods=['POST'])
def google_save_config():
    """Simpan Client ID & Client Secret yang diinputkan pengguna."""
    client_id = request.form.get('client_id', '').strip()
    client_secret = request.form.get('client_secret', '').strip()
    
    if not client_id:
        flash("Google Client ID tidak boleh kosong.")
        return redirect(url_for('auth.google_login'))
        
    save_google_config(client_id, client_secret)
    flash("Kredensial Google OAuth 2.0 berhasil disimpan! Anda sekarang dapat masuk langsung dengan akun Google pribadi Anda.")
    return redirect(url_for('auth.google_login'))

@auth_bp.route('/google/reset-config', methods=['POST'])
def google_reset_config():
    """Reset konfigurasi Google Client ID."""
    save_google_config('', '')
    flash("Konfigurasi Google Client ID telah direset.")
    return redirect(url_for('auth.google_login'))

@auth_bp.route('/google/callback', methods=['GET', 'POST'])
def google_callback():
    """
    Menangani Callback Autentikasi Google:
    1. Google Identity Services (GIS) One-Tap / Button (POST 'credential' id_token).
    2. Google OAuth 2.0 Authorization Code (GET 'code' dari accounts.google.com).
    3. Simulasi Akun Demo (Fallback cepat jika belum mengonfigurasi Client ID).
    """
    email = None
    name = None
    avatar_url = None
    role = 'patient'
    role_label = 'Pasien'
    auth_source = 'Google'

    # 1. METODE GOOGLE IDENTITY SERVICES (GIS / ONE TAP)
    credential = request.form.get('credential')
    if credential:
        try:
            tokeninfo_url = f"https://oauth2.googleapis.com/tokeninfo?id_token={credential}"
            resp = requests.get(tokeninfo_url, timeout=10)
            if resp.status_code == 200:
                user_info = resp.json()
                email = user_info.get('email', '').strip().lower()
                name = user_info.get('name') or user_info.get('given_name') or email.split('@')[0]
                avatar_url = user_info.get('picture')
                auth_source = 'Google Identity Services (One Tap / Popup Akun Pribadi)'
            else:
                flash("Verifikasi ID Token Google gagal. Silakan coba kembali.")
                return redirect(url_for('auth.google_login'))
        except Exception as e:
            flash(f"Gagal memverifikasi token Google: {str(e)}")
            return redirect(url_for('auth.google_login'))

    # 2. METODE GOOGLE OAUTH 2.0 DIRECT REDIRECT (CODE EXCHANGE)
    code = request.args.get('code')
    oauth_error = request.args.get('error')
    if oauth_error:
        flash(f"Akses akun Google dibatalkan atau ditolak ({oauth_error}).")
        return redirect(url_for('auth.google_login'))

    if not email and code:
        cfg = get_google_config()
        client_id = cfg.get('client_id')
        client_secret = cfg.get('client_secret')
        redirect_uri = get_oauth_redirect_uri()

        token_url = "https://oauth2.googleapis.com/token"
        token_payload = {
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }
        try:
            token_resp = requests.post(token_url, data=token_payload, timeout=10)
            token_data = token_resp.json()
            access_token = token_data.get('access_token')

            if not access_token:
                err_detail = token_data.get('error_description') or token_data.get('error') or 'Token tidak ditemukan'
                flash(f"Gagal otorisasi token Google: {err_detail}. Pastikan Client Secret sesuai.")
                return redirect(url_for('auth.google_login'))

            userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
            userinfo_resp = requests.get(userinfo_url, headers={'Authorization': f'Bearer {access_token}'}, timeout=10)
            if userinfo_resp.status_code == 200:
                user_info = userinfo_resp.json()
                email = user_info.get('email', '').strip().lower()
                name = user_info.get('name') or user_info.get('given_name') or email.split('@')[0]
                avatar_url = user_info.get('picture')
                auth_source = 'Google OAuth 2.0 Resmi (accounts.google.com)'
            else:
                flash("Gagal mengambil profil akun dari Google API.")
                return redirect(url_for('auth.google_login'))
        except Exception as e:
            flash(f"Terjadi kesalahan saat otentikasi Google: {str(e)}")
            return redirect(url_for('auth.google_login'))

    # 3. METODE FALLBACK / SIMULASI AKUN
    if not email:
        account = request.args.get('account', '').strip().lower()
        if account == 'dinda':
            email = 'dinda.skem@gmail.com'
            name = 'Dinda Prameswari'
            avatar_url = 'https://lh3.googleusercontent.com/a/default-user'
            role = 'patient'
            role_label = 'Pasien'
            auth_source = 'Simulasi Google (Dinda)'
        elif account == 'andi':
            email = 'andi.klinik@gmail.com'
            name = 'Andi Pratama'
            avatar_url = 'https://lh3.googleusercontent.com/a/default-user'
            role = 'facility'
            role_label = 'Petugas Klinik'
            auth_source = 'Simulasi Google (Andi)'
        elif request.method == 'POST':
            form_email = (request.form.get('email') or request.form.get('custom_email') or '').strip().lower()
            form_name = (request.form.get('name') or request.form.get('custom_name') or '').strip()
            form_role = (request.form.get('role') or request.form.get('custom_role') or 'patient').strip()

            if form_email:
                email = form_email
                name = form_name or form_email.split('@')[0].capitalize()
                role = form_role
                role_labels = {
                    'patient': 'Pasien',
                    'facility': 'Petugas Klinik',
                    'system': 'Admin Sistem'
                }
                role_label = role_labels.get(role, 'Pasien')
                avatar_url = 'https://lh3.googleusercontent.com/a/default-user'
                auth_source = 'Simulasi Akun Google Kustom'

    if not email:
        flash("Sesi Google tidak valid atau dibatalkan.")
        return redirect(url_for('auth.google_login'))

    # PENDAFTARAN OTOMATIS & SINKRONISASI USER DARI GOOGLE
    user = USERS_DB.get(email)
    if not user:
        user_id = f"U{len(USERS_DB) + 1:03d}"
        dummy_nik = f"NIK-G{abs(hash(email)) % 10000000000:010d}"
        user = {
            'id': user_id,
            'email': email,
            'password': None,
            'name': name,
            'role': role,
            'role_label': role_label,
            'phone': '0812-Google-User',
            'identity_number': dummy_nik,
            'scope': 'Klinik SKEM',
            'status': 'Aktif',
            'auth_provider': 'google',
            'avatar_url': avatar_url or 'https://lh3.googleusercontent.com/a/default-user'
        }
        USERS_DB[email] = user
        db_save_user(user)
        USERS_LIST.append({
            'username': email,
            'name': name,
            'role': role_label,
            'scope': 'Klinik SKEM',
            'status': 'Aktif',
            'status_class': 'green'
        })

        if role == 'patient':
            SAVED_PROFILES['g_' + user_id] = {
                'key': 'g_' + user_id,
                'user_email': email,
                'name': name,
                'id': dummy_nik,
                'identity_number': dummy_nik,
                'phone': '0812-Google-User',
                'dob': '1998-05-12',
                'dob_text': '12 Mei 1998',
                'relationship': 'Utama',
                'badge': f"Pasien Utama (Google) · {dummy_nik}"
            }
            db_save_profile(SAVED_PROFILES['g_' + user_id])
    else:
        # Perbarui profil dengan nama & foto terbaru dari Google jika tersedia
        if name:
            user['name'] = name
        if avatar_url:
            user['avatar_url'] = avatar_url
        user['auth_provider'] = 'google'
        db_save_user(user)

    session['user'] = {
        'id': user['id'],
        'email': user['email'],
        'name': user['name'],
        'role': user['role'],
        'role_label': user['role_label'],
        'phone': user.get('phone', ''),
        'identity_number': user.get('identity_number', ''),
        'auth_provider': 'google',
        'avatar_url': user.get('avatar_url') or 'https://lh3.googleusercontent.com/a/default-user'
    }

    SYSTEM_LOGS.insert(0, {
        'time': datetime.now().strftime("%d %b %Y %H:%M"),
        'category': 'Autentikasi Google',
        'event': f"Masuk via Akun Google ({auth_source}): {user['name']} ({user['email']})",
        'status': 'Berhasil',
        'status_class': 'green'
    })
    db_save_system_log('Autentikasi Google', f"Masuk via Akun Google ({auth_source}): {user['name']} ({user['email']})", 'Berhasil', 'green')

    flash(f"Berhasil masuk dengan akun Google: {user['name']} ({user['email']})!")
    return redirect(get_role_home_url(user['role']))

@auth_bp.route('/logout')
def logout():
    user = session.get('user')
    if user:
        SYSTEM_LOGS.insert(0, {
            'time': datetime.now().strftime("%d %b %Y %H:%M"),
            'category': 'Autentikasi',
            'event': f"Pengguna keluar: {user.get('name')}",
            'status': 'Selesai',
            'status_class': 'green'
        })
    session.pop('user', None)
    flash("Anda telah berhasil keluar dari sistem Klinik SKEM.")
    return redirect(url_for('auth.login'))

# ==============================================================================
# BLUEPRINT 1: ROLE PASIEN (patient)
# ==============================================================================
patient_bp = Blueprint('patient', __name__, url_prefix='/patient')

@patient_bp.route('/')
@patient_bp.route('/home')
def home():
    user, user_email, user_name, accessible_names, my_profiles, my_reg_codes = get_current_patient_scope()

    # Cek rujukan aktif untuk pasien ini
    active_referral = next((
        r for r in REFERRALS
        if is_patient_record(r, user_email, accessible_names, my_reg_codes)
    ), None)

    # Cek resep siap diambil
    my_rx = [
        rx for rx in PRESCRIPTIONS
        if is_patient_record(rx, user_email, accessible_names, my_reg_codes)
    ]
    ready_rx = next((rx for rx in my_rx if rx.get('status') == 'Siap Diambil'), None)

    # Filter pendaftaran aktif & tindakan yang diperlukan hanya untuk akun ini
    my_active_registrations = [
        r for r in ACTIVE_REGISTRATIONS
        if is_patient_record(r, user_email, accessible_names, my_reg_codes)
    ]
    my_required_actions = [
        a for a in REQUIRED_ACTIONS
        if is_patient_record(a, user_email, accessible_names, my_reg_codes)
    ]

    # Cari nomor antrean pengguna yang aktif
    check_daily_queue_reset()
    my_q_item = next((
        q for q in QUEUE_LIST
        if is_patient_record(q, user_email, accessible_names, my_reg_codes) and q.get('status') not in ('Selesai di Faskes Ini', 'Dirujuk ke Faskes 2')
    ), None)
    run_code = QUEUE_STATE['current_code']
    run_num = QUEUE_STATE['current_number']

    if my_q_item:
        my_queue_no = my_q_item['queue_no']
        my_num = parse_queue_number(my_queue_no)
        gap = my_num - run_num

        if my_q_item.get('status') == 'Dipanggil ke Loket 1' or gap == 0:
            gap_text = f"🔔 Giliran Anda sekarang! Silakan menuju {QUEUE_STATE['counter_name']}"
            gap_status = "calling"
            gap = 0
        elif gap > 1:
            gap_text = f"{gap} antrean lagi sebelum giliran Anda"
            gap_status = "waiting"
        elif gap == 1:
            gap_text = "1 antrean lagi sebelum giliran Anda (Silakan bersiap)"
            gap_status = "ready"
        else:
            gap_text = f"Nomor Anda ({my_queue_no}) telah terlewati. Silakan konfirmasi ke loket."
            gap_status = "passed"
    else:
        # Cek apakah kunjungan hari ini sudah selesai atau sedang menunggu verifikasi berkas
        completed_q = next((
            q for q in QUEUE_LIST
            if is_patient_record(q, user_email, accessible_names, my_reg_codes) and q.get('status') in ('Selesai di Faskes Ini', 'Dirujuk ke Faskes 2')
        ), None)
        pending_reg = next((
            r for r in my_active_registrations
            if r.get('status') in ('Menunggu verifikasi', 'Menunggu verifikasi ulang', 'Perlu dilengkapi')
        ), None)

        if completed_q:
            my_queue_no = completed_q['queue_no']
            gap = None
            if completed_q['status'] == 'Dirujuk ke Faskes 2':
                gap_text = "Pelayanan selesai: Anda telah dirujuk ke Faskes Tingkat 2."
                gap_status = "referred"
            else:
                gap_text = "Pelayanan Anda di faskes ini telah tuntas."
                gap_status = "completed"
        elif pending_reg:
            my_queue_no = "Menunggu Verifikasi"
            gap = None
            if pending_reg.get('status') == 'Perlu dilengkapi':
                gap_text = "Berkas pendaftaran perlu dilengkapi. Silakan buka menu Tindakan."
                gap_status = "need_action"
            else:
                gap_text = "Pendaftaran sedang diperiksa petugas. Nomor antrean terbit setelah disetujui."
                gap_status = "pending_verification"
        else:
            my_queue_no = "-"
            gap = None
            gap_text = "Belum ada nomor antrean aktif hari ini."
            gap_status = "none"

    patient_metrics = {
        'active_registrations': len(my_active_registrations),
        'need_action': len(my_required_actions),
        'my_queue': my_queue_no,
        'saved_profiles': len(my_profiles)
    }

    action_notice = None
    if my_required_actions:
        action_notice = f"{my_required_actions[0].get('title')} ({my_required_actions[0].get('code')}): {my_required_actions[0].get('reason')}"

    return render_template(
        'patient/home.html',
        active_page='home',
        metrics=patient_metrics,
        queue_running=run_code,
        my_queue=my_queue_no,
        queue_gap_text=gap_text,
        gap_status=gap_status,
        queue_state=QUEUE_STATE,
        active_registrations=my_active_registrations,
        action_notice=action_notice,
        ready_rx=ready_rx,
        active_referral=active_referral,
        patients=PATIENTS
    )

@patient_bp.route('/api/queue-status')
def api_queue_status():
    """API untuk pembaruan realtime nomor antrean di portal pasien."""
    check_daily_queue_reset()
    user, user_email, user_name, accessible_names, my_profiles, my_reg_codes = get_current_patient_scope()

    my_q_item = next((
        q for q in QUEUE_LIST
        if is_patient_record(q, user_email, accessible_names, my_reg_codes) and q.get('status') not in ('Selesai di Faskes Ini', 'Dirujuk ke Faskes 2')
    ), None)
    run_code = QUEUE_STATE['current_code']
    run_num = QUEUE_STATE['current_number']

    if my_q_item:
        my_queue_no = my_q_item['queue_no']
        my_num = parse_queue_number(my_queue_no)
        gap = my_num - run_num

        if my_q_item.get('status') == 'Dipanggil ke Loket 1' or gap == 0:
            gap_text = f"🔔 Giliran Anda sekarang! Silakan menuju {QUEUE_STATE['counter_name']}"
            gap_status = "calling"
            gap = 0
        elif gap > 1:
            gap_text = f"{gap} antrean lagi sebelum giliran Anda"
            gap_status = "waiting"
        elif gap == 1:
            gap_text = "1 antrean lagi sebelum giliran Anda (Silakan bersiap)"
            gap_status = "ready"
        else:
            gap_text = f"Nomor Anda ({my_queue_no}) telah terlewati. Silakan konfirmasi ke loket."
            gap_status = "passed"
    else:
        completed_q = next((
            q for q in QUEUE_LIST
            if is_patient_record(q, user_email, accessible_names, my_reg_codes) and q.get('status') in ('Selesai di Faskes Ini', 'Dirujuk ke Faskes 2')
        ), None)
        pending_reg = next((
            r for r in ACTIVE_REGISTRATIONS
            if is_patient_record(r, user_email, accessible_names, my_reg_codes) and r.get('status') in ('Menunggu verifikasi', 'Menunggu verifikasi ulang', 'Perlu dilengkapi')
        ), None)

        if completed_q:
            my_queue_no = completed_q['queue_no']
            gap = None
            if completed_q['status'] == 'Dirujuk ke Faskes 2':
                gap_text = "Pelayanan selesai: Anda telah dirujuk ke Faskes Tingkat 2."
                gap_status = "referred"
            else:
                gap_text = "Pelayanan Anda di faskes ini telah tuntas."
                gap_status = "completed"
        elif pending_reg:
            my_queue_no = "Menunggu Verifikasi"
            gap = None
            if pending_reg.get('status') == 'Perlu dilengkapi':
                gap_text = "Berkas pendaftaran perlu dilengkapi. Silakan buka menu Tindakan."
                gap_status = "need_action"
            else:
                gap_text = "Pendaftaran sedang diperiksa petugas. Nomor antrean terbit setelah disetujui."
                gap_status = "pending_verification"
        else:
            my_queue_no = "-"
            gap = None
            gap_text = "Belum ada nomor antrean aktif hari ini."
            gap_status = "none"

    return {
        'running_queue': run_code,
        'my_queue': my_queue_no,
        'gap': gap,
        'gap_text': gap_text,
        'gap_status': gap_status,
        'counter': QUEUE_STATE['counter_name'],
        'time': datetime.now().strftime("%H:%M:%S")
    }

@patient_bp.route('/register', methods=['GET', 'POST'])
def register():
    user, user_email, user_name, accessible_names, my_profiles, my_reg_codes = get_current_patient_scope()

    if request.method == 'POST':
        patient_name = request.form.get('name', user_name or 'Pasien').strip()
        service = request.form.get('service', 'Poli Umum').strip()
        raw_visit_date = request.form.get('visit_date', '')
        visit_date = format_indonesian_date(raw_visit_date)

        new_code = f"FF-{len(REGISTRATION_HISTORY) + 155}"

        # Simpan berkas dokumen pendukung jika ada
        doc_info = None
        if 'supporting_document' in request.files:
            file_obj = request.files['supporting_document']
            if file_obj and file_obj.filename:
                doc_info = save_uploaded_document(file_obj, prefix=new_code.replace('-', ''))

        doc_url = doc_info['document_url'] if doc_info else None
        doc_name = doc_info['document_name'] if doc_info else None
        doc_type = doc_info['document_type'] if doc_info else None

        patient_id = f"P{len(PATIENTS) + 1:03d}"
        finance_choice = request.form.get('payment_method', 'Mandiri')

        new_reg = {
            'clinic': service,
            'date': visit_date,
            'code': new_code,
            'status': 'Menunggu verifikasi',
            'status_class': 'blue',
            'hospital': 'Klinik SKEM',
            'patient_name': patient_name,
            'patient_id': patient_id,
            'finance': finance_choice,
            'user_email': user_email,
            'document_url': doc_url,
            'document_name': doc_name,
            'document_type': doc_type
        }
        ACTIVE_REGISTRATIONS.insert(0, new_reg)
        REGISTRATION_HISTORY.insert(0, {
            'id': new_code,
            'code': new_code,
            'date': visit_date,
            'service': service,
            'hospital': 'Klinik SKEM',
            'patient_name': patient_name,
            'patient_id': patient_id,
            'finance': finance_choice,
            'status': 'Menunggu verifikasi',
            'status_class': 'blue',
            'user_email': user_email,
            'document_url': doc_url,
            'document_name': doc_name,
            'document_type': doc_type
        })
        new_rev = {
            'id': new_code,
            'patient_id': patient_id,
            'patient_name': patient_name,
            'source': 'Online',
            'service': service,
            'readiness': 'Perlu diperiksa',
            'status_class': 'amber',
            'document_url': doc_url,
            'document_name': doc_name,
            'document_type': doc_type
        }
        REVIEW_LIST.insert(0, new_rev)
        new_pat = {
            'id': patient_id,
            'name': patient_name,
            'phone': user.get('phone', '0812-0000-1182'),
            'date': visit_date,
            'service': service,
            'finance': request.form.get('payment_method', 'Mandiri'),
            'status': 'Menunggu verifikasi',
            'form': new_code,
            'document_url': doc_url,
            'document_name': doc_name,
            'document_type': doc_type
        }
        PATIENTS.insert(0, new_pat)

        db_save_registration(new_reg)
        db_save_review(new_rev)
        db_save_patient(new_pat)

        SYSTEM_LOGS.insert(0, {
            'time': datetime.now().strftime("%d %b %Y %H:%M"),
            'category': 'Pendaftaran',
            'event': f"Pendaftaran {new_code} untuk {patient_name} ({service}) diajukan ke Klinik SKEM" + (f" [Berkas: {doc_name}]" if doc_name else ""),
            'status': 'Berhasil',
            'status_class': 'green'
        })
        db_save_system_log('Pendaftaran', f"Pendaftaran {new_code} untuk {patient_name} ({service}) diajukan ke Klinik SKEM", 'Berhasil', 'green')

        flash(f"Pendaftaran {patient_name} untuk {service} di Klinik SKEM berhasil diajukan!" + (" Dokumen pendukung berhasil diunggah." if doc_name else ""))
        return redirect(url_for('patient.home'))

    if not my_profiles:
        id_num = user.get('identity_number', '3171000000000001')
        badge_suffix = f"••••{id_num[-4:]}" if len(id_num) >= 4 else id_num
        my_profiles = {
            'utama': {
                'key': 'utama',
                'user_email': user_email,
                'name': user_name or 'Pasien',
                'identity_number': id_num,
                'phone': user.get('phone', '0812-0000-0000'),
                'relationship': 'Utama',
                'badge': f"Pasien Utama · DEMO-NIK {badge_suffix}"
            }
        }

    return render_template(
        'patient/register.html',
        active_page='register',
        saved_profiles=my_profiles,
        visit_date=datetime.now().strftime("%Y-%m-%d"),
        patients=PATIENTS
    )

@patient_bp.route('/actions')
def actions():
    _, user_email, _, accessible_names, _, my_reg_codes = get_current_patient_scope()
    my_actions = [a for a in REQUIRED_ACTIONS if is_patient_record(a, user_email, accessible_names, my_reg_codes)]
    return render_template(
        'patient/actions.html',
        active_page='actions',
        required_actions=my_actions,
        patients=PATIENTS
    )

@patient_bp.route('/actions/upload', methods=['POST'])
def upload_action():
    code = request.form.get('code', 'FF-0148').strip()
    notes = request.form.get('notes', '').strip()

    # Simpan berkas perbaikan jika diunggah
    doc_info = None
    if 'document_file' in request.files:
        file_obj = request.files['document_file']
        if file_obj and file_obj.filename:
            doc_info = save_uploaded_document(file_obj, prefix=f"fix_{code.replace('-', '')}")

    doc_url = doc_info['document_url'] if doc_info else None
    doc_name = doc_info['document_name'] if doc_info else None
    doc_type = doc_info['document_type'] if doc_info else None

    # 1. Hapus dari REQUIRED_ACTIONS pasien
    REQUIRED_ACTIONS[:] = [a for a in REQUIRED_ACTIONS if a.get('code') != code]
    db_delete_required_action(code)

    # 2. Update status di ACTIVE_REGISTRATIONS pasien
    for reg in ACTIVE_REGISTRATIONS:
        if reg.get('code') == code:
            reg['status'] = 'Menunggu verifikasi ulang'
            reg['status_class'] = 'blue'
            if doc_url:
                reg['document_url'] = doc_url
                reg['document_name'] = doc_name
                reg['document_type'] = doc_type
            db_save_registration(reg)

    # 3. Update status di REVIEW_LIST petugas klinik
    for r in REVIEW_LIST:
        if r.get('id') == code:
            r['readiness'] = 'Menunggu verifikasi ulang'
            r['status_class'] = 'blue'
            if doc_url:
                r['document_url'] = doc_url
                r['document_name'] = doc_name
                r['document_type'] = doc_type
            db_save_review(r)

    # 4. Update status di PATIENTS
    for p in PATIENTS:
        if p.get('form') == code:
            p['status'] = 'Menunggu verifikasi ulang'
            if doc_url:
                p['document_url'] = doc_url
                p['document_name'] = doc_name
                p['document_type'] = doc_type
            db_save_patient(p)

    # 5. Update di REGISTRATION_HISTORY
    for h in REGISTRATION_HISTORY:
        if h.get('id') == code:
            h['status'] = 'Menunggu verifikasi ulang'
            h['status_class'] = 'blue'
            if doc_url:
                h['document_url'] = doc_url
                h['document_name'] = doc_name
                h['document_type'] = doc_type
            db_save_registration(h)

    db_update_registration_status(code, 'Menunggu verifikasi ulang', 'blue')
    db_update_review_status(code, 'Menunggu verifikasi ulang', 'blue')

    op_desc = f"Pasien telah mengunggah perbaikan dokumen untuk verifikasi petugas Klinik SKEM." + (f" Berkas: {doc_name}." if doc_name else "") + (f" Catatan: {notes}" if notes else "")
    OPERATIONAL_HISTORY.insert(0, {
        'title': f"Dokumen {code} diunggah ulang",
        'desc': op_desc
    })
    db_save_operational_history(f"Dokumen {code} diunggah ulang", op_desc)
    flash(f"Berkas perbaikan untuk {code} berhasil disimpan dan dikirim untuk diverifikasi ulang oleh petugas.")
    return redirect(url_for('patient.actions'))

@patient_bp.route('/history')
def history():
    _, user_email, _, accessible_names, _, my_reg_codes = get_current_patient_scope()
    my_history = [h for h in REGISTRATION_HISTORY if is_patient_record(h, user_email, accessible_names, my_reg_codes)]
    return render_template(
        'patient/history.html',
        active_page='history',
        registration_history=my_history,
        patients=PATIENTS
    )

@patient_bp.route('/profiles')
def profiles():
    _, user_email, _, _, my_profiles, _ = get_current_patient_scope()
    profiles_list = [
        {
            'key': k,
            'name': v['name'],
            'desc': v.get('badge', f"{v.get('relationship', 'Keluarga')} · DEMO-NIK {v.get('identity_number', '')[-4:]}"),
            'id': v.get('identity_number', ''),
            'phone': v.get('phone', ''),
            'dob': v.get('dob', ''),
            'dob_text': v.get('dob_text', v.get('dob', '')),
            'relationship': v.get('relationship', 'Keluarga')
        }
        for k, v in my_profiles.items()
    ]

    return render_template(
        'patient/profiles.html',
        active_page='profiles',
        patient_profiles=profiles_list,
        patients=PATIENTS
    )

@patient_bp.route('/profiles/add', methods=['POST'])
def add_profile():
    user = session.get('user', {})
    user_email = user.get('email', 'pasien@local')

    name = request.form.get('name', '').strip()
    identity_number = request.form.get('identity_number', '').strip()
    relationship = request.form.get('relationship', 'Keluarga').strip()
    dob = request.form.get('dob', '').strip()
    phone = request.form.get('phone', '').strip()

    if not name or not identity_number:
        flash("Nama lengkap dan nomor identitas wajib diisi.")
        return redirect(url_for('patient.profiles'))

    base_key = re.sub(r'[^a-zA-Z0-9]', '', name.lower())[:8] or 'pasien'
    key = base_key
    counter = 1
    while key in SAVED_PROFILES:
        key = f"{base_key}_{counter}"
        counter += 1

    badge_suffix = f"••••{identity_number[-4:]}" if len(identity_number) >= 4 else identity_number
    badge = f"{relationship} · DEMO-NIK {badge_suffix}"

    SAVED_PROFILES[key] = {
        'key': key,
        'user_email': user_email,
        'name': name,
        'id': identity_number,
        'identity_number': identity_number,
        'phone': phone,
        'dob': dob,
        'dob_text': dob,
        'relationship': relationship,
        'badge': badge
    }
    db_save_profile(SAVED_PROFILES[key])

    flash(f"Profil {name} ({relationship}) berhasil ditambahkan ke daftar profil Anda.")
    return redirect(url_for('patient.profiles'))

@patient_bp.route('/profiles/edit/<profile_key>', methods=['POST'])
def edit_profile(profile_key):
    if profile_key in SAVED_PROFILES:
        name = request.form.get('name', '').strip()
        identity_number = request.form.get('identity_number', '').strip()
        relationship = request.form.get('relationship', 'Keluarga').strip()
        dob = request.form.get('dob', '').strip()
        phone = request.form.get('phone', '').strip()

        badge_suffix = f"••••{identity_number[-4:]}" if len(identity_number) >= 4 else identity_number
        badge = f"{relationship} · DEMO-NIK {badge_suffix}"

        SAVED_PROFILES[profile_key].update({
            'name': name,
            'id': identity_number,
            'identity_number': identity_number,
            'phone': phone,
            'dob': dob,
            'dob_text': dob,
            'relationship': relationship,
            'badge': badge
        })
        db_save_profile(SAVED_PROFILES[profile_key])
        flash(f"Profil {name} berhasil diperbarui.")
    else:
        flash("Profil tidak ditemukan.")
    return redirect(url_for('patient.profiles'))

@patient_bp.route('/profiles/delete/<profile_key>', methods=['POST'])
def delete_profile(profile_key):
    if profile_key in SAVED_PROFILES:
        deleted = SAVED_PROFILES.pop(profile_key)
        db_delete_profile(profile_key)
        flash(f"Profil {deleted.get('name', '')} berhasil dihapus.")
    else:
        flash("Profil tidak ditemukan.")
    return redirect(url_for('patient.profiles'))

@patient_bp.route('/prescriptions')
def prescriptions():
    _, user_email, _, accessible_names, _, my_reg_codes = get_current_patient_scope()
    my_prescriptions = [
        rx for rx in PRESCRIPTIONS
        if is_patient_record(rx, user_email, accessible_names, my_reg_codes)
    ]

    ready_count = sum(1 for rx in my_prescriptions if rx.get('status') == 'Siap Diambil')
    prep_count = sum(1 for rx in my_prescriptions if rx.get('status') == 'Sedang Diracik')
    done_count = sum(1 for rx in my_prescriptions if rx.get('status') == 'Sudah Diambil')
    ready_rx = next((rx for rx in my_prescriptions if rx.get('status') == 'Siap Diambil'), None)

    return render_template(
        'patient/prescriptions.html',
        active_page='prescriptions',
        prescriptions=my_prescriptions,
        ready_count=ready_count,
        prep_count=prep_count,
        done_count=done_count,
        ready_rx=ready_rx,
        patients=PATIENTS
    )

@patient_bp.route('/prescriptions/confirm/<rx_id>', methods=['POST'])
def confirm_prescription(rx_id):
    user = session.get('user', {})
    user_name = user.get('name', 'Pasien')

    matched = next((rx for rx in PRESCRIPTIONS if rx['id'] == rx_id), None)
    if matched:
        matched['status'] = 'Sudah Diambil'
        matched['status_class'] = 'blue'
        db_update_prescription_status(rx_id, 'Sudah Diambil', 'blue')
        op_desc = f'Pasien {user_name} mengonfirmasi pengambilan obat di Loket Farmasi Klinik SKEM.'
        OPERATIONAL_HISTORY.insert(0, {
            'title': f'{rx_id} diambil pasien',
            'desc': op_desc
        })
        db_save_operational_history(f'{rx_id} diambil pasien', op_desc)
        flash(f"Konfirmasi berhasil! Resep {rx_id} telah dicatat sudah Anda ambil.")
    else:
        flash("Resep tidak ditemukan.")
    return redirect(url_for('patient.prescriptions'))

# ==============================================================================
# BLUEPRINT 2: ROLE PETUGAS KLINIK (facility)
# ==============================================================================
facility_bp = Blueprint('facility', __name__, url_prefix='/facility')

@facility_bp.route('/')
@facility_bp.route('/dashboard')
def dashboard():
    needs_review = sum(1 for r in REVIEW_LIST if r.get('readiness') not in ('Terverifikasi', 'Dirujuk ke Faskes 2', 'Selesai di Faskes Ini'))

    facility_metrics = {
        'incoming': QUEUE_STATE.get('daily_sequence', 0) + len(QUEUE_LIST),
        'needs_review': needs_review,
        'in_queue': len(QUEUE_LIST),
        'completed': sum(1 for p in PATIENTS if p.get('status') in ('Selesai', 'Selesai di Faskes Ini', 'Dirujuk ke Faskes 2'))
    }

    return render_template(
        'facility/dashboard.html',
        active_page='dashboard',
        metrics=facility_metrics,
        pending_review_count=needs_review,
        ready_queue_count=len(QUEUE_LIST),
        patients=PATIENTS
    )

@facility_bp.route('/review')
def review():
    return render_template(
        'facility/review.html',
        active_page='review',
        review_list=REVIEW_LIST,
        patients=PATIENTS
    )

@facility_bp.route('/review/confirm/<form_id>', methods=['POST'])
def confirm_review(form_id):
    matched = next((r for r in REVIEW_LIST if r['id'] == form_id), None)

    if matched:
        matched['readiness'] = 'Terverifikasi'
        matched['status_class'] = 'green'
        db_update_review_status(form_id, 'Terverifikasi', 'green')

        existing_q = any(q['patient_id'] == matched['patient_id'] for q in QUEUE_LIST)
        new_q_no = None
        if not existing_q:
            check_daily_queue_reset()
            QUEUE_STATE['daily_sequence'] += 1
            new_q_no = f"{QUEUE_STATE['prefix']}-{QUEUE_STATE['daily_sequence']:03d}"
            target_email = find_patient_email(patient_name=matched['patient_name'], patient_id=matched['patient_id'], form_id=form_id)
            q_item = {
                'queue_no': new_q_no,
                'patient_id': matched['patient_id'],
                'patient_name': matched['patient_name'],
                'patient_email': target_email,
                'source': matched.get('source', 'Online'),
                'service': matched.get('service', 'Poli Umum'),
                'status': 'Menunggu',
                'status_class': 'blue',
                'can_call': True
            }
            QUEUE_LIST.append(q_item)
            db_save_queue(q_item)
            db_save_queue_state()

        # 1. Update status di ACTIVE_REGISTRATIONS pasien
        for reg in ACTIVE_REGISTRATIONS:
            if reg.get('code') == form_id:
                reg['status'] = 'Terverifikasi (Masuk Antrean)'
                reg['status_class'] = 'green'

        # 2. Update status di PATIENTS
        for p in PATIENTS:
            if p.get('form') == form_id or p.get('id') == matched['patient_id']:
                p['status'] = 'Terverifikasi'
                db_save_patient(p)

        # 3. Update status di REGISTRATION_HISTORY
        for h in REGISTRATION_HISTORY:
            if h.get('id') == form_id:
                h['status'] = 'Terverifikasi (Masuk Antrean)'
                h['status_class'] = 'green'

        db_update_registration_status(form_id, 'Terverifikasi (Masuk Antrean)', 'green')

        # 4. Hapus dari REQUIRED_ACTIONS jika ada
        REQUIRED_ACTIONS[:] = [a for a in REQUIRED_ACTIONS if a.get('code') != form_id]
        db_delete_required_action(form_id)

        op_desc = f'Kelengkapan administrasi {matched["patient_name"]} dinyatakan lengkap oleh petugas Klinik SKEM.'
        OPERATIONAL_HISTORY.insert(0, {
            'title': f'{form_id} dikonfirmasi',
            'desc': op_desc
        })
        db_save_operational_history(f'{form_id} dikonfirmasi', op_desc)
        flash(f"Formulir {form_id} ({matched['patient_name']}) berhasil diverifikasi & masuk ke antrean!")
    else:
        flash(f"Formulir {form_id} tidak ditemukan.")

    return redirect(url_for('facility.review'))

@facility_bp.route('/review/request_fix/<form_id>', methods=['POST'])
def request_fix(form_id):
    matched = next((r for r in REVIEW_LIST if r['id'] == form_id), None)
    fix_reason = request.form.get('reason', '').strip() or 'Foto dokumen/identitas kurang jelas atau berkas pendukung belum lengkap'
    patient_name = matched.get('patient_name', 'Pasien') if matched else 'Pasien'
    patient_id = matched.get('patient_id', 'P001') if matched else 'P001'
    service = matched.get('service', 'Poli Umum') if matched else 'Poli Umum'

    if matched:
        matched['readiness'] = 'Perlu perbaikan'
        matched['status_class'] = 'amber'
        matched['reason'] = fix_reason
        db_update_review_status(form_id, 'Perlu perbaikan', 'amber', reason=fix_reason)

    doc_url = matched.get('document_url') if matched else None
    doc_name = matched.get('document_name') if matched else None
    doc_type = matched.get('document_type') if matched else None

    # 1. Tambahkan atau update di REQUIRED_ACTIONS agar muncul di portal pasien
    target_email = find_patient_email(patient_name=patient_name, patient_id=patient_id, form_id=form_id)
    action_item = next((a for a in REQUIRED_ACTIONS if a.get('code') == form_id), None)
    if not action_item:
        new_act = {
            'code': form_id,
            'title': 'Unggah Ulang Berkas / Identitas',
            'service': service,
            'patient_name': patient_name,
            'patient_id': patient_id,
            'reason': fix_reason,
            'user_email': target_email,
            'document_url': doc_url,
            'document_name': doc_name,
            'document_type': doc_type
        }
        REQUIRED_ACTIONS.insert(0, new_act)
        db_save_required_action(new_act)
    else:
        action_item['reason'] = fix_reason
        if target_email:
            action_item['user_email'] = target_email
        if doc_url and not action_item.get('document_url'):
            action_item['document_url'] = doc_url
            action_item['document_name'] = doc_name
            action_item['document_type'] = doc_type
        db_save_required_action(action_item)

    # 2. Update status di ACTIVE_REGISTRATIONS pasien
    for reg in ACTIVE_REGISTRATIONS:
        if reg.get('code') == form_id:
            reg['status'] = 'Perlu dilengkapi'
            reg['status_class'] = 'amber'

    # 3. Update status di PATIENTS
    for p in PATIENTS:
        if p.get('form') == form_id or p.get('id') == patient_id:
            p['status'] = 'Perlu perbaikan berkas'
            db_save_patient(p)

    # 4. Update status di REGISTRATION_HISTORY
    for h in REGISTRATION_HISTORY:
        if h.get('id') == form_id:
            h['status'] = 'Perlu dilengkapi'
            h['status_class'] = 'amber'

    db_update_registration_status(form_id, 'Perlu dilengkapi', 'amber')

    op_desc = f'Petugas meminta perbaikan dokumen untuk {patient_name}: {fix_reason}'
    OPERATIONAL_HISTORY.insert(0, {
        'title': f'Permintaan perbaikan berkas {form_id}',
        'desc': op_desc
    })
    db_save_operational_history(f'Permintaan perbaikan berkas {form_id}', op_desc)

    log_evt = f"Permintaan perbaikan berkas {form_id} untuk {patient_name}"
    SYSTEM_LOGS.insert(0, {
        'time': datetime.now().strftime("%d %b %Y %H:%M"),
        'category': 'Verifikasi Berkas',
        'event': log_evt,
        'status': 'Perlu Perbaikan',
        'status_class': 'amber'
    })
    db_save_system_log('Verifikasi Berkas', log_evt, 'Perlu Perbaikan', 'amber')

    flash(f"Permintaan perbaikan berkas untuk {form_id} ({patient_name}) telah dikirimkan ke pasien.")
    return redirect(url_for('facility.review'))

@facility_bp.route('/queue')
def queue():
    check_daily_queue_reset()
    return render_template(
        'facility/queue.html',
        active_page='queue',
        running_queue=QUEUE_STATE['current_code'],
        queue_state=QUEUE_STATE,
        queue_list=QUEUE_LIST,
        patients=PATIENTS
    )

@facility_bp.route('/queue/next', methods=['POST'])
def next_queue():
    """Panggil nomor antrean berikutnya (Prioritaskan pasien yang sedang menunggu di antrean)."""
    check_daily_queue_reset()

    # Cari pasien berikutnya yang sedang menunggu di antrean
    waiting_items = [q for q in QUEUE_LIST if q.get('status') in ('Menunggu', 'Terdaftar') and q.get('can_call')]
    if waiting_items:
        target_item = waiting_items[0]
        target_item['status'] = 'Dipanggil ke Loket 1'
        target_item['status_class'] = 'green'
        new_code = target_item['queue_no']
        num = parse_queue_number(new_code)
        QUEUE_STATE['current_code'] = new_code
        QUEUE_STATE['current_number'] = num
        QUEUE_STATE['total_called_today'] += 1
        matched_patient = target_item['patient_name']
        db_update_queue_status(new_code, 'Dipanggil ke Loket 1', 'green', can_call=1)
    else:
        QUEUE_STATE['current_number'] += 1
        new_code = f"{QUEUE_STATE['prefix']}-{QUEUE_STATE['current_number']:03d}"
        QUEUE_STATE['current_code'] = new_code
        QUEUE_STATE['total_called_today'] += 1
        matched_patient = None
        for q in QUEUE_LIST:
            if q['queue_no'] == new_code:
                q['status'] = 'Dipanggil ke Loket 1'
                q['status_class'] = 'green'
                matched_patient = q['patient_name']
                db_update_queue_status(new_code, 'Dipanggil ke Loket 1', 'green', can_call=1)
                break

    db_save_queue_state()

    desc = f"Nomor antrean {new_code} dipanggil ke {QUEUE_STATE['counter_name']}"
    if matched_patient:
        desc += f" (Pasien: {matched_patient})"

    OPERATIONAL_HISTORY.insert(0, {
        'title': f'{new_code} dipanggil',
        'desc': desc
    })
    db_save_operational_history(f'{new_code} dipanggil', desc)

    SYSTEM_LOGS.insert(0, {
        'time': datetime.now().strftime("%d %b %Y %H:%M"),
        'category': 'Panggilan Antrean',
        'event': desc,
        'status': 'Dipanggil',
        'status_class': 'green'
    })
    db_save_system_log('Panggilan Antrean', desc, 'Dipanggil', 'green')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return {
            'success': True,
            'running_queue': new_code,
            'matched_patient': matched_patient,
            'message': f"Nomor {new_code} berhasil dipanggil ke Loket."
        }

    flash(f"Nomor antrean berikutnya ({new_code}) dipanggil ke Loket.")
    return redirect(url_for('facility.queue'))

@facility_bp.route('/queue/call/<queue_no>', methods=['POST'])
def call_queue(queue_no):
    """Panggil nomor antrean tertentu."""
    check_daily_queue_reset()
    QUEUE_STATE['current_code'] = queue_no
    num = parse_queue_number(queue_no)
    if num > 0:
        QUEUE_STATE['current_number'] = num
    QUEUE_STATE['total_called_today'] += 1
    db_save_queue_state()

    matched_patient = None
    for q in QUEUE_LIST:
        if q['queue_no'] == queue_no:
            q['status'] = 'Dipanggil ke Loket 1'
            q['status_class'] = 'green'
            matched_patient = q['patient_name']
            db_update_queue_status(queue_no, 'Dipanggil ke Loket 1', 'green', can_call=1)
            break

    desc = f"Nomor antrean {queue_no} dipanggil ke {QUEUE_STATE['counter_name']}"
    if matched_patient:
        desc += f" (Pasien: {matched_patient})"

    OPERATIONAL_HISTORY.insert(0, {
        'title': f'{queue_no} dipanggil',
        'desc': desc
    })
    db_save_operational_history(f'{queue_no} dipanggil', desc)

    SYSTEM_LOGS.insert(0, {
        'time': datetime.now().strftime("%d %b %Y %H:%M"),
        'category': 'Panggilan Antrean',
        'event': desc,
        'status': 'Dipanggil',
        'status_class': 'green'
    })
    db_save_system_log('Panggilan Antrean', desc, 'Dipanggil', 'green')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return {
            'success': True,
            'running_queue': queue_no,
            'matched_patient': matched_patient,
            'message': f"Nomor {queue_no} sedang dipanggil ke Loket."
        }

    flash(f"Nomor antrean {queue_no} sedang dipanggil ke Loket.")
    return redirect(url_for('facility.queue'))

@facility_bp.route('/queue/admit/<queue_no>', methods=['POST'])
def admit_queue(queue_no):
    for q in QUEUE_LIST:
        if q['queue_no'] == queue_no:
            q['status'] = 'Menunggu'
            q['status_class'] = 'blue'
            q['can_call'] = True
            db_update_queue_status(queue_no, 'Menunggu', 'blue', can_call=1)
            op_desc = f'Nomor antrean {queue_no} ({q["patient_name"]}) siap dipanggil di loket Klinik SKEM.'
            OPERATIONAL_HISTORY.insert(0, {
                'title': f'{queue_no} dimasukkan ke antrean aktif',
                'desc': op_desc
            })
            db_save_operational_history(f'{queue_no} dimasukkan ke antrean aktif', op_desc)
            flash(f"Nomor antrean {queue_no} siap dipanggil.")
            break
    return redirect(url_for('facility.queue'))

# ------------------------------------------------------------------------------
# FITUR BARU: SELESAI DI FASKES INI
# ------------------------------------------------------------------------------
@facility_bp.route('/visit/complete', methods=['POST'])
def complete_visit():
    patient_id = request.form.get('patient_id', '').strip()
    patient_name = request.form.get('patient_name', '').strip()
    queue_no = request.form.get('queue_no', '').strip()
    form_id = request.form.get('form_id', '').strip()

    # 1. Update pada Antrean (QUEUE_LIST)
    for q in QUEUE_LIST:
        if (queue_no and q['queue_no'] == queue_no) or (patient_id and q['patient_id'] == patient_id):
            q['status'] = 'Selesai di Faskes Ini'
            q['status_class'] = 'green'
            q['can_call'] = False
            db_update_queue_status(q['queue_no'], 'Selesai di Faskes Ini', 'green', can_call=0)
            if not patient_name:
                patient_name = q['patient_name']

    # 2. Update pada Data Pasien (PATIENTS)
    for p in PATIENTS:
        if p['id'] == patient_id or (patient_name and p['name'].lower() == patient_name.lower()):
            p['status'] = 'Selesai di Faskes Ini'
            db_save_patient(p)
            if not patient_name:
                patient_name = p['name']

    # 3. Update pada Review (REVIEW_LIST)
    for r in REVIEW_LIST:
        if (form_id and r['id'] == form_id) or (patient_id and r['patient_id'] == patient_id):
            r['readiness'] = 'Selesai di Faskes Ini'
            r['status_class'] = 'green'
            db_update_review_status(r['id'], 'Selesai di Faskes Ini', 'green')

    # 4. Update pada Pendaftaran Aktif & Riwayat (Cegah duplikat 2x)
    now_date = format_indonesian_date(datetime.now())
    for reg in ACTIVE_REGISTRATIONS:
        if reg.get('code') == form_id or (patient_name and reg.get('patient_name', '').lower() == patient_name.lower()):
            reg['status'] = 'Selesai di Faskes Ini'
            reg['status_class'] = 'green'

    # Update status di REGISTRATION_HISTORY yang sudah ada
    matched_h = None
    for h in REGISTRATION_HISTORY:
        if (form_id and h.get('id') == form_id) or (patient_name and h.get('patient_name', '').lower() == patient_name.lower()):
            matched_h = h
            break
    if matched_h:
        matched_h['status'] = 'Selesai di Faskes Ini'
        matched_h['status_class'] = 'green'
        matched_h['date'] = now_date
        db_update_registration_status(matched_h.get('code') or matched_h.get('id'), 'Selesai di Faskes Ini', 'green')
    else:
        new_h_code = form_id or f"FF-{len(REGISTRATION_HISTORY)+155}"
        target_email = find_patient_email(patient_name=patient_name, patient_id=patient_id, form_id=form_id)
        new_h = {
            'id': new_h_code,
            'code': new_h_code,
            'date': now_date,
            'service': 'Poli Umum',
            'hospital': 'Klinik SKEM',
            'patient_name': patient_name,
            'status': 'Selesai di Faskes Ini',
            'status_class': 'green',
            'user_email': target_email
        }
        REGISTRATION_HISTORY.insert(0, new_h)
        db_save_registration(new_h)

    # 5. Catat ke Riwayat Operasional & Log Sistem
    op_desc = f'Kunjungan pasien {patient_name} dinyatakan Selesai di Faskes Ini oleh petugas Klinik SKEM.'
    OPERATIONAL_HISTORY.insert(0, {
        'title': f'Kunjungan {patient_name or "Pasien"} diselesaikan',
        'desc': op_desc
    })
    db_save_operational_history(f'Kunjungan {patient_name or "Pasien"} diselesaikan', op_desc)

    log_evt = f"Kunjungan pasien {patient_name} selesai di Faskes ini"
    SYSTEM_LOGS.insert(0, {
        'time': datetime.now().strftime("%d %b %Y %H:%M"),
        'category': 'Pelayanan Pasien',
        'event': log_evt,
        'status': 'Selesai',
        'status_class': 'green'
    })
    db_save_system_log('Pelayanan Pasien', log_evt, 'Selesai', 'green')

    flash(f"Status kunjungan pasien {patient_name} berhasil diubah menjadi: Selesai di Faskes Ini.")
    return redirect(request.referrer or url_for('facility.queue'))

# ------------------------------------------------------------------------------
# FITUR BARU: RUJUK KE FASKES LANJUTAN (FASKES TINGKAT 2)
# ------------------------------------------------------------------------------
@facility_bp.route('/visit/refer', methods=['POST'])
def refer_visit():
    patient_id = request.form.get('patient_id', '').strip() or 'P001'
    patient_name = request.form.get('patient_name', '').strip() or 'Dinda Prameswari'
    target_faskes = request.form.get('target_faskes', '').strip() or 'RSUD Dr. Soetomo'
    target_clinic = request.form.get('target_clinic', '').strip() or 'Poli Penyakit Dalam'
    notes = request.form.get('notes', '').strip()
    queue_no = request.form.get('queue_no', '').strip()
    form_id = request.form.get('form_id', '').strip()

    # Cari email pasien yang sebenarnya (bukan hardcoded pasien@local)
    target_email = find_patient_email(patient_name=patient_name, patient_id=patient_id, form_id=form_id)

    # Buat nomor rujukan otomatis
    ref_id = f"SRJ-2026-{len(REFERRALS) + 1:03d}"
    now_date = format_indonesian_date(datetime.now())
    now_time = datetime.now().strftime("%H:%M")

    # 1. Tambahkan ke data in-memory REFERRALS & DB
    new_referral = {
        'id': ref_id,
        'patient_id': patient_id,
        'patient_name': patient_name,
        'patient_email': target_email,
        'source_faskes': 'Klinik SKEM',
        'target_faskes': target_faskes,
        'target_clinic': target_clinic,
        'notes': notes or 'Pasien memerlukan rujukan lanjutan ke Faskes Tingkat 2 untuk konsultasi dokter spesialis.',
        'doctor': 'dr. Hendra Pratama, Sp.PD',
        'date': now_date,
        'time': now_time,
        'status': 'Terkirim ke Faskes 2',
        'status_class': 'purple'
    }
    REFERRALS.insert(0, new_referral)
    db_save_referral(new_referral)

    # 2. Update status pada Antrean (QUEUE_LIST)
    for q in QUEUE_LIST:
        if (queue_no and q['queue_no'] == queue_no) or (patient_id and q['patient_id'] == patient_id):
            q['status'] = 'Dirujuk ke Faskes 2'
            q['status_class'] = 'purple'
            q['can_call'] = False
            db_update_queue_status(q['queue_no'], 'Dirujuk ke Faskes 2', 'purple', can_call=0)

    # 3. Update status pada Data Pasien (PATIENTS)
    for p in PATIENTS:
        if p['id'] == patient_id or p['name'].lower() == patient_name.lower():
            p['status'] = 'Dirujuk ke Faskes 2'
            p['faskes2'] = target_faskes
            p['ref_id'] = ref_id
            db_save_patient(p)

    # 4. Update status pada Review (REVIEW_LIST)
    for r in REVIEW_LIST:
        if (form_id and r['id'] == form_id) or (patient_id and r['patient_id'] == patient_id):
            r['readiness'] = 'Dirujuk ke Faskes 2'
            r['status_class'] = 'purple'
            db_update_review_status(r['id'], 'Dirujuk ke Faskes 2', 'purple')

    # 5. Update pada Pendaftaran Aktif Pasien (Cegah duplikat)
    found_active = False
    for reg in ACTIVE_REGISTRATIONS:
        if (form_id and reg.get('code') == form_id) or (patient_name and reg.get('patient_name', '').lower() == patient_name.lower()):
            reg['status'] = 'Dirujuk ke Faskes 2'
            reg['status_class'] = 'purple'
            reg['hospital'] = target_faskes
            reg['target_faskes'] = target_faskes
            reg['target_clinic'] = target_clinic
            reg['ref_id'] = ref_id
            found_active = True
            db_save_registration(reg)
            break
    if not found_active:
        active_item = {
            'clinic': target_clinic,
            'date': now_date,
            'code': ref_id,
            'status': 'Dirujuk ke Faskes 2',
            'status_class': 'purple',
            'hospital': target_faskes,
            'target_faskes': target_faskes,
            'target_clinic': target_clinic,
            'patient_name': patient_name,
            'ref_id': ref_id,
            'user_email': target_email
        }
        ACTIVE_REGISTRATIONS.insert(0, active_item)
        db_save_registration(active_item)

    # 6. Update pada Riwayat Pendaftaran Pasien (Cegah duplikat 2x)
    matched_h = None
    for h in REGISTRATION_HISTORY:
        if (form_id and h.get('id') == form_id) or (patient_name and h.get('patient_name', '').lower() == patient_name.lower()):
            matched_h = h
            break
    if matched_h:
        matched_h['status'] = 'Dirujuk ke Faskes 2'
        matched_h['status_class'] = 'purple'
        matched_h['hospital'] = f"{target_faskes} (Rujukan)"
        matched_h['service'] = target_clinic
        matched_h['target_faskes'] = target_faskes
        matched_h['target_clinic'] = target_clinic
        matched_h['ref_id'] = ref_id
        matched_h['date'] = now_date
        if target_email and not matched_h.get('user_email'):
            matched_h['user_email'] = target_email
        db_save_registration(matched_h)
    else:
        new_h = {
            'id': ref_id,
            'code': ref_id,
            'date': now_date,
            'service': target_clinic,
            'hospital': f"{target_faskes} (Rujukan)",
            'status': 'Dirujuk ke Faskes 2',
            'status_class': 'purple',
            'target_faskes': target_faskes,
            'target_clinic': target_clinic,
            'patient_name': patient_name,
            'ref_id': ref_id,
            'user_email': target_email
        }
        REGISTRATION_HISTORY.insert(0, new_h)
        db_save_registration(new_h)

    # 7. Tambahkan ke Timeline Riwayat Operasional
    op_desc = f'Pasien {patient_name} dirujuk ke {target_faskes} ({target_clinic}). Catatan: {notes[:80]}'
    OPERATIONAL_HISTORY.insert(0, {
        'title': f'Rujukan {ref_id} diterbitkan',
        'desc': op_desc
    })
    db_save_operational_history(f'Rujukan {ref_id} diterbitkan', op_desc)

    # 8. Catat aktivitas ke Log Sistem (sesuai format Requirement 3)
    log_evt = f"Data rujukan pasien {patient_name} berhasil dikirim ke {target_faskes}"
    SYSTEM_LOGS.insert(0, {
        'time': datetime.now().strftime("%d %b %Y %H:%M"),
        'category': 'Rujukan Faskes 2',
        'event': log_evt,
        'status': 'Terkirim',
        'status_class': 'green'
    })
    db_save_system_log('Rujukan Faskes 2', log_evt, 'Terkirim', 'green')

    flash(f"Data & berkas rujukan {patient_name} berhasil dikirim ke {target_faskes} ({target_clinic}) - No. Rujukan: {ref_id}!")
    return redirect(request.referrer or url_for('facility.queue'))

@facility_bp.route('/walkin', methods=['GET', 'POST'])
def walkin():
    if request.method == 'POST':
        patient_name = request.form.get('patient_name', '').strip()
        service = request.form.get('service', 'Poli Umum').strip()

        check_daily_queue_reset()
        QUEUE_STATE['daily_sequence'] += 1
        new_queue_num = f"{QUEUE_STATE['prefix']}-{QUEUE_STATE['daily_sequence']:03d}"
        p_id = f"P{len(PATIENTS) + 1:03d}"

        new_pat = {
            'id': p_id,
            'name': patient_name,
            'phone': '0812-0000-0000',
            'date': datetime.now().strftime("%d %b %Y"),
            'service': service,
            'finance': 'Mandiri',
            'status': 'Terdaftar',
            'form': new_queue_num
        }
        PATIENTS.append(new_pat)
        db_save_patient(new_pat)

        new_q = {
            'queue_no': new_queue_num,
            'patient_id': p_id,
            'patient_name': patient_name,
            'source': 'Walk-in',
            'service': service,
            'status': 'Terdaftar',
            'status_class': '',
            'can_call': True
        }
        QUEUE_LIST.append(new_q)
        db_save_queue(new_q)
        db_save_queue_state()

        op_desc = f'Pasien walk-in {patient_name} mendaftar di {service} Klinik SKEM.'
        OPERATIONAL_HISTORY.insert(0, {
            'title': f'{new_queue_num} walk-in didaftarkan',
            'desc': op_desc
        })
        db_save_operational_history(f'{new_queue_num} walk-in didaftarkan', op_desc)

        flash(f"Pasien walk-in {patient_name} berhasil didaftarkan ke antrean {new_queue_num} Klinik SKEM.")
        return redirect(url_for('facility.queue'))

    return render_template(
        'facility/walkin.html',
        active_page='walkin',
        patients=PATIENTS
    )

@facility_bp.route('/patients')
def patients():
    return render_template(
        'facility/patients.html',
        active_page='patients',
        patients=PATIENTS
    )

@facility_bp.route('/history')
def history():
    return render_template(
        'facility/history.html',
        active_page='history',
        operational_history=OPERATIONAL_HISTORY,
        patients=PATIENTS
    )

@facility_bp.route('/prescriptions')
def prescriptions():
    ready_count = sum(1 for rx in PRESCRIPTIONS if rx.get('status') == 'Siap Diambil')
    prep_count = sum(1 for rx in PRESCRIPTIONS if rx.get('status') == 'Sedang Diracik')
    done_count = sum(1 for rx in PRESCRIPTIONS if rx.get('status') == 'Sudah Diambil')

    return render_template(
        'facility/prescriptions.html',
        active_page='prescriptions',
        prescriptions=PRESCRIPTIONS,
        total_rx=len(PRESCRIPTIONS),
        ready_count=ready_count,
        prep_count=prep_count,
        done_count=done_count,
        patients=PATIENTS,
        saved_profiles=SAVED_PROFILES
    )

@facility_bp.route('/prescriptions/create', methods=['POST'])
def create_prescription():
    patient_choice = request.form.get('patient_info', '').strip()
    custom_patient_name = request.form.get('custom_patient_name', '').strip()
    doctor = request.form.get('doctor', 'dr. Hendra Pratama, Sp.PD').strip()
    clinic = request.form.get('clinic', 'Poli Umum').strip()
    counter = request.form.get('counter', 'Loket Farmasi 2').strip()
    status = request.form.get('status', 'Sedang Diracik').strip()
    notes = request.form.get('notes', '').strip()

    patient_id = "P001"
    patient_name = "Dinda Prameswari"
    patient_email = ""

    if custom_patient_name:
        patient_name = custom_patient_name
        patient_id = f"P{abs(hash(patient_name)) % 900 + 100:03d}"
        patient_email = find_patient_email(patient_name=patient_name, patient_id=patient_id)
    elif '|' in patient_choice:
        parts = patient_choice.split('|')
        patient_id = parts[0]
        patient_name = parts[1]
        patient_email = parts[2] if len(parts) > 2 and parts[2].strip() else find_patient_email(patient_name=patient_name, patient_id=patient_id)
    elif patient_choice:
        patient_name = patient_choice
        for p in PATIENTS:
            if p['name'].lower() == patient_name.lower():
                patient_id = p['id']
                break
        patient_email = find_patient_email(patient_name=patient_name, patient_id=patient_id)

    if not patient_email:
        patient_email = find_patient_email(patient_name=patient_name, patient_id=patient_id)

    med_names = request.form.getlist('med_name[]')
    med_dosages = request.form.getlist('med_dosage[]')
    med_qtys = request.form.getlist('med_qty[]')
    med_timings = request.form.getlist('med_timing[]')

    medications = []
    for i in range(len(med_names)):
        m_name = med_names[i].strip() if i < len(med_names) else ''
        if m_name:
            m_dosage = med_dosages[i].strip() if i < len(med_dosages) else '1 x 1 sehari'
            m_qty = med_qtys[i].strip() if i < len(med_qtys) else '10 pcs'
            m_timing = med_timings[i].strip() if i < len(med_timings) else 'Sesudah makan'
            medications.append({
                'name': m_name,
                'form': 'Obat',
                'qty': m_qty,
                'dosage': m_dosage,
                'timing': m_timing
            })

    if not medications:
        medications.append({
            'name': 'Paracetamol 500mg',
            'form': 'Tablet',
            'qty': '10 tablet',
            'dosage': '3 x 1 sehari',
            'timing': 'Sesudah makan'
        })

    status_class = 'green' if status == 'Siap Diambil' else ('amber' if status == 'Sedang Diracik' else 'blue')
    new_rx_id = f"RX-{len(PRESCRIPTIONS) + 8802}"

    new_rx = {
        'id': new_rx_id,
        'patient_id': patient_id,
        'patient_name': patient_name,
        'patient_email': patient_email,
        'doctor': doctor,
        'clinic': clinic,
        'date': format_indonesian_date(datetime.now()),
        'time': datetime.now().strftime("%H:%M"),
        'queue_no': f"A-{len(PRESCRIPTIONS) + 18:03d}",
        'status': status,
        'status_class': status_class,
        'counter': counter,
        'notes': notes or 'Minum obat sesuai anjuran dan jadwal yang tertera pada etiket.',
        'medications': medications
    }
    PRESCRIPTIONS.insert(0, new_rx)
    db_save_prescription(new_rx)

    op_desc = f'Petugas Klinik menginput resep {new_rx_id} untuk pasien {patient_name} ({clinic}) - status: {status}.'
    OPERATIONAL_HISTORY.insert(0, {
        'title': f'{new_rx_id} diterbitkan',
        'desc': op_desc
    })
    db_save_operational_history(f'{new_rx_id} diterbitkan', op_desc)

    flash(f"Resep {new_rx_id} untuk {patient_name} berhasil diterbitkan ke farmasi & akun pasien!")
    return redirect(url_for('facility.prescriptions'))

@facility_bp.route('/prescriptions/status/<rx_id>/<new_status>', methods=['POST'])
def update_prescription_status(rx_id, new_status):
    matched = next((rx for rx in PRESCRIPTIONS if rx['id'] == rx_id), None)

    if matched:
        if new_status == 'ready':
            matched['status'] = 'Siap Diambil'
            matched['status_class'] = 'green'
            flash(f"Resep {rx_id} ({matched['patient_name']}) telah ditandai Siap Diambil di {matched['counter']}!")
            op_desc = f'Obat untuk {matched["patient_name"]} telah selesai diracik dan siap diambil di {matched["counter"]}.'
            OPERATIONAL_HISTORY.insert(0, {
                'title': f'{rx_id} siap diambil',
                'desc': op_desc
            })
            db_save_operational_history(f'{rx_id} siap diambil', op_desc)
        elif new_status == 'dispensed':
            matched['status'] = 'Sudah Diambil'
            matched['status_class'] = 'blue'
            flash(f"Resep {rx_id} ({matched['patient_name']}) telah diserahkan ke pasien!")
            op_desc = f'Obat {rx_id} telah diserahkan ke {matched["patient_name"]}.'
            OPERATIONAL_HISTORY.insert(0, {
                'title': f'{rx_id} diserahkan',
                'desc': op_desc
            })
            db_save_operational_history(f'{rx_id} diserahkan', op_desc)
        elif new_status == 'prep':
            matched['status'] = 'Sedang Diracik'
            matched['status_class'] = 'amber'
            flash(f"Resep {rx_id} dikembalikan ke status Sedang Diracik.")

        db_update_prescription_status(rx_id, matched['status'], matched['status_class'])
    else:
        flash(f"Resep {rx_id} tidak ditemukan.")

    return redirect(url_for('facility.prescriptions'))

@facility_bp.route('/prescriptions/delete/<rx_id>', methods=['POST'])
def delete_prescription(rx_id):
    """Menghapus resep obat dari sistem farmasi Klinik SKEM."""
    global PRESCRIPTIONS
    matched = next((rx for rx in PRESCRIPTIONS if rx['id'] == rx_id), None)

    if matched:
        p_name = matched.get('patient_name', 'Pasien')
        PRESCRIPTIONS[:] = [rx for rx in PRESCRIPTIONS if rx['id'] != rx_id]
        db_delete_prescription(rx_id)

        op_desc = f'Resep {rx_id} untuk {p_name} telah dihapus dari sistem oleh petugas farmasi.'
        OPERATIONAL_HISTORY.insert(0, {
            'title': f'{rx_id} dihapus',
            'desc': op_desc
        })
        db_save_operational_history(f'{rx_id} dihapus', op_desc)

        log_evt = f"Penghapusan resep {rx_id} ({p_name})"
        SYSTEM_LOGS.insert(0, {
            'time': datetime.now().strftime("%d %b %Y %H:%M"),
            'category': 'Resep Obat',
            'event': log_evt,
            'status': 'Dihapus',
            'status_class': 'amber'
        })
        db_save_system_log('Resep Obat', log_evt, 'Dihapus', 'amber')

        flash(f"Resep {rx_id} untuk {p_name} berhasil dihapus dari daftar farmasi.")
    else:
        flash(f"Resep {rx_id} tidak ditemukan.")

    return redirect(url_for('facility.prescriptions'))

# ==============================================================================
# BLUEPRINT 3: ROLE ADMIN SISTEM (system)
# ==============================================================================
system_bp = Blueprint('system', __name__, url_prefix='/system')

@system_bp.route('/')
@system_bp.route('/dashboard')
def dashboard():
    staff_count = sum(1 for u in USERS_LIST if u.get('role') == 'Petugas Klinik')
    referred_count = sum(1 for p in PATIENTS if p.get('status') == 'Dirujuk ke Faskes 2') or len(REFERRALS)

    system_metrics = {
        'active_clinics': len(SERVICES_LIST),
        'staff_accounts': staff_count or 12,
        'active_counters': 3,
        'open_issues': 1,
        'referred_faskes2': referred_count
    }

    system_activities = [
        {'title': 'Rujukan Faskes 2 tercatat', 'desc': f'Total {referred_count} pasien berhasil dirujuk ke Faskes Tingkat 2.'},
        {'title': 'Konfigurasi persyaratan diperbarui', 'desc': 'Poli Gigi · Klinik SKEM'},
        {'title': 'Akun petugas diaktifkan', 'desc': 'Akses dibatasi ke Klinik SKEM.'}
    ]

    return render_template(
        'system/dashboard.html',
        active_page='dashboard',
        metrics=system_metrics,
        system_activities=system_activities,
        patients=PATIENTS,
        faskes2_partners=FASKES2_PARTNERS,
        queue_state=QUEUE_STATE
    )

@system_bp.route('/queue/edit', methods=['POST'])
def edit_queue():
    """Admin Sistem mengubah nomor antrean berjalan."""
    check_daily_queue_reset()
    new_code = request.form.get('queue_code', '').strip().upper()
    counter_name = request.form.get('counter_name', '').strip()

    if not new_code:
        flash("Nomor antrean tidak boleh kosong.")
        return redirect(url_for('system.dashboard'))

    old_code = QUEUE_STATE['current_code']
    num = parse_queue_number(new_code)
    prefix_match = re.match(r'^([A-Z]+)', new_code)
    if prefix_match:
        QUEUE_STATE['prefix'] = prefix_match.group(1)
    QUEUE_STATE['current_code'] = new_code
    QUEUE_STATE['current_number'] = num
    if counter_name:
        QUEUE_STATE['counter_name'] = counter_name
    db_save_queue_state()

    log_evt = f"Admin Sistem mengubah nomor antrean berjalan dari {old_code} menjadi {new_code}"
    SYSTEM_LOGS.insert(0, {
        'time': datetime.now().strftime("%d %b %Y %H:%M"),
        'category': 'Manajemen Antrean',
        'event': log_evt,
        'status': 'Diperbarui',
        'status_class': 'green'
    })
    db_save_system_log('Manajemen Antrean', log_evt, 'Diperbarui', 'green')
    flash(f"Nomor antrean berjalan klinik berhasil diubah menjadi {new_code}!")
    return redirect(url_for('system.dashboard'))

@system_bp.route('/queue/reset', methods=['POST'])
def reset_queue():
    """Admin Sistem mereset nomor antrean klinik."""
    prefix = request.form.get('prefix', 'A').strip().upper() or 'A'
    try:
        start_num = int(request.form.get('start_num', 0))
    except Exception:
        start_num = 0

    old_code = QUEUE_STATE['current_code']
    QUEUE_STATE['prefix'] = prefix
    QUEUE_STATE['current_number'] = start_num
    QUEUE_STATE['current_code'] = f"{prefix}-{start_num:03d}"
    QUEUE_STATE['daily_sequence'] = start_num
    QUEUE_STATE['last_reset_date'] = datetime.now().strftime('%Y-%m-%d')
    QUEUE_STATE['total_called_today'] = 0
    db_save_queue_state()

    log_evt = f"Admin Sistem mereset nomor antrean klinik hari ini menjadi {QUEUE_STATE['current_code']} (sebelumnya {old_code})"
    SYSTEM_LOGS.insert(0, {
        'time': datetime.now().strftime("%d %b %Y %H:%M"),
        'category': 'Manajemen Antrean',
        'event': log_evt,
        'status': 'Direset',
        'status_class': 'green'
    })
    db_save_system_log('Manajemen Antrean', log_evt, 'Direset', 'green')
    flash(f"Nomor antrean klinik berhasil direset ke {QUEUE_STATE['current_code']} untuk hari ini.")
    return redirect(url_for('system.dashboard'))

@system_bp.route('/facilities')
def facilities():
    return render_template(
        'system/facilities.html',
        active_page='facilities',
        requirements=REQUIREMENTS,
        patients=PATIENTS
    )

@system_bp.route('/partners')
def partners():
    return render_template(
        'system/partners.html',
        active_page='partners',
        faskes2_partners=FASKES2_PARTNERS,
        patients=PATIENTS
    )

@system_bp.route('/faskes2')
def faskes2_alias():
    return redirect(url_for('system.partners'))

# ------------------------------------------------------------------------------
# FITUR MANAJEMEN MITRA FASKES TINGKAT 2
# ------------------------------------------------------------------------------
@system_bp.route('/faskes2/add', methods=['POST'])
def add_faskes2():
    name = request.form.get('name', '').strip()
    f_type = request.form.get('type', 'Rumah Sakit Rujukan').strip()
    city = request.form.get('city', '').strip()
    phone = request.form.get('phone', '').strip()
    status = request.form.get('status', 'Aktif').strip()

    if name:
        new_id = f"FK2-{len(FASKES2_PARTNERS) + 1:02d}"
        new_partner = {
            'id': new_id,
            'name': name,
            'type': f_type,
            'city': city,
            'phone': phone,
            'status': status,
            'status_class': 'green' if status == 'Aktif' else 'amber'
        }
        FASKES2_PARTNERS.append(new_partner)
        db_save_faskes2_partner(new_partner)

        log_evt = f"Mitra Faskes Tingkat 2 baru ditambahkan: {name} ({city})"
        SYSTEM_LOGS.insert(0, {
            'time': datetime.now().strftime("%d %b %Y %H:%M"),
            'category': 'Konfigurasi Faskes 2',
            'event': log_evt,
            'status': 'Berhasil',
            'status_class': 'green'
        })
        db_save_system_log('Konfigurasi Faskes 2', log_evt, 'Berhasil', 'green')

        flash(f"Mitra Faskes Rujukan {name} ({new_id}) berhasil ditambahkan ke sistem!")
    return redirect(url_for('system.partners'))

@system_bp.route('/faskes2/edit/<partner_id>', methods=['POST'])
def edit_faskes2(partner_id):
    p = next((x for x in FASKES2_PARTNERS if x['id'] == partner_id), None)
    if p:
        p['name'] = request.form.get('name', p['name']).strip()
        p['type'] = request.form.get('type', p['type']).strip()
        p['city'] = request.form.get('city', p['city']).strip()
        p['phone'] = request.form.get('phone', p['phone']).strip()
        status = request.form.get('status', p['status']).strip()
        p['status'] = status
        p['status_class'] = 'green' if status == 'Aktif' else 'amber'

        db_save_faskes2_partner(p)
        flash(f"Data mitra faskes {p['name']} ({partner_id}) berhasil diperbarui!")
    return redirect(url_for('system.partners'))

@system_bp.route('/faskes2/delete/<partner_id>', methods=['POST'])
def delete_faskes2(partner_id):
    p = next((x for x in FASKES2_PARTNERS if x['id'] == partner_id), None)
    name = p['name'] if p else partner_id
    FASKES2_PARTNERS[:] = [x for x in FASKES2_PARTNERS if x['id'] != partner_id]
    db_delete_faskes2_partner(partner_id)
    flash(f"Mitra Faskes Rujukan {name} ({partner_id}) berhasil dihapus!")
    return redirect(url_for('system.partners'))

@system_bp.route('/facilities/add', methods=['POST'])
def add_facility_req():
    clinic = request.form.get('clinic', '').strip()
    reqs = request.form.get('reqs', '').strip()
    mandatory = request.form.get('mandatory', 'Ya').strip()
    status = request.form.get('status', 'Aktif').strip()

    if clinic and reqs:
        new_req = {
            'clinic': clinic,
            'reqs': reqs,
            'mandatory': mandatory,
            'status': status,
            'status_class': 'green' if status == 'Aktif' else 'amber'
        }
        REQUIREMENTS.append(new_req)
        db_save_requirement(new_req)

        log_evt = f"Persyaratan administrasi {clinic} berhasil ditambahkan di Klinik SKEM"
        SYSTEM_LOGS.insert(0, {
            'time': datetime.now().strftime("%d %b %Y %H:%M"),
            'category': 'Konfigurasi',
            'event': log_evt,
            'status': 'Berhasil',
            'status_class': 'green'
        })
        db_save_system_log('Konfigurasi', log_evt, 'Berhasil', 'green')
        flash(f"Persyaratan administrasi untuk {clinic} berhasil ditambahkan.")
    return redirect(url_for('system.facilities'))

@system_bp.route('/facilities/edit/<int:index>', methods=['POST'])
def edit_facility_req(index):
    clinic = request.form.get('clinic', '').strip()
    reqs = request.form.get('reqs', '').strip()
    mandatory = request.form.get('mandatory', 'Ya').strip()
    status = request.form.get('status', 'Aktif').strip()

    if 0 <= index < len(REQUIREMENTS):
        REQUIREMENTS[index].update({
            'clinic': clinic,
            'reqs': reqs,
            'mandatory': mandatory,
            'status': status,
            'status_class': 'green' if status == 'Aktif' else 'amber'
        })
        db_save_requirement(REQUIREMENTS[index], req_id=REQUIREMENTS[index].get('id'))
        flash(f"Persyaratan {clinic} berhasil diperbarui.")
    return redirect(url_for('system.facilities'))

@system_bp.route('/facilities/delete/<int:index>', methods=['POST'])
def delete_facility_req(index):
    if 0 <= index < len(REQUIREMENTS):
        removed = REQUIREMENTS.pop(index)
        db_delete_requirement(removed['clinic'])
        flash(f"Persyaratan untuk {removed['clinic']} berhasil dihapus.")
    return redirect(url_for('system.facilities'))

@system_bp.route('/users')
def users():
    return render_template(
        'system/users.html',
        active_page='users',
        users_list=USERS_LIST,
        patients=PATIENTS
    )

@system_bp.route('/users/add', methods=['POST'])
def add_user():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    role = request.form.get('role', 'facility').strip()
    scope = request.form.get('scope', 'Klinik SKEM').strip()
    password = request.form.get('password', 'password123').strip()

    role_labels = {
        'facility': 'Petugas Klinik',
        'system': 'Admin Sistem',
        'patient': 'Pasien'
    }
    role_label = role_labels.get(role, 'Petugas Klinik')
    new_id = f"U{len(USERS_DB) + 1:03d}"

    new_user = {
        'id': new_id,
        'email': email,
        'password': password,
        'name': name,
        'role': role,
        'role_label': role_label,
        'phone': '0812-0000-0000',
        'identity_number': f"STF-{len(USERS_DB) + 1:03d}",
        'scope': scope,
        'status': 'Aktif',
        'auth_provider': 'local',
        'avatar_url': None
    }
    USERS_DB[email] = new_user
    db_save_user(new_user)

    USERS_LIST.append({
        'username': email,
        'name': name,
        'role': role_label,
        'scope': scope,
        'status': 'Aktif',
        'status_class': 'green'
    })

    log_evt = f"Akun pengguna baru dibuat: {name} ({email})"
    SYSTEM_LOGS.insert(0, {
        'time': datetime.now().strftime("%d %b %Y %H:%M"),
        'category': 'Akun',
        'event': log_evt,
        'status': 'Berhasil',
        'status_class': 'green'
    })
    db_save_system_log('Akun', log_evt, 'Berhasil', 'green')
    flash(f"Akun pengguna {name} ({email}) berhasil dibuat.")
    return redirect(url_for('system.users'))

@system_bp.route('/users/toggle/<username>', methods=['POST'])
def toggle_user(username):
    for u in USERS_LIST:
        if u['username'] == username:
            u['status'] = 'Nonaktif' if u['status'] == 'Aktif' else 'Aktif'
            new_status = u['status']
            if username in USERS_DB:
                USERS_DB[username]['status'] = new_status
            db_update_user_status(username, new_status)
            log_evt = f"Status akun {username} diubah menjadi {new_status}"
            SYSTEM_LOGS.insert(0, {
                'time': datetime.now().strftime("%d %b %Y %H:%M"),
                'category': 'Akun',
                'event': log_evt,
                'status': 'Berhasil',
                'status_class': 'green'
            })
            db_save_system_log('Akun', log_evt, 'Berhasil', 'green')
            flash(f"Status akun {username} diubah menjadi {new_status}.")
            break
    return redirect(url_for('system.users'))

@system_bp.route('/services')
def services():
    return render_template(
        'system/services.html',
        active_page='services',
        services_list=SERVICES_LIST,
        patients=PATIENTS
    )

@system_bp.route('/services/add', methods=['POST'])
def add_service():
    name = request.form.get('name', '').strip()
    hospital = request.form.get('hospital', 'Klinik SKEM').strip()
    requirements = request.form.get('requirements', '').strip()
    status = request.form.get('status', 'Aktif').strip()

    if name:
        new_srv = {
            'name': name,
            'hospital': hospital or 'Klinik SKEM',
            'requirements': requirements,
            'status': status,
            'status_class': 'green' if status == 'Aktif' else 'amber'
        }
        SERVICES_LIST.append(new_srv)
        db_save_service(new_srv)

        log_evt = f"Layanan baru {name} ditambahkan di Klinik SKEM"
        SYSTEM_LOGS.insert(0, {
            'time': datetime.now().strftime("%d %b %Y %H:%M"),
            'category': 'Konfigurasi',
            'event': log_evt,
            'status': 'Berhasil',
            'status_class': 'green'
        })
        db_save_system_log('Konfigurasi', log_evt, 'Berhasil', 'green')
        flash(f"Layanan {name} berhasil ditambahkan.")
    return redirect(url_for('system.services'))

@system_bp.route('/services/edit/<int:index>', methods=['POST'])
def edit_service(index):
    name = request.form.get('name', '').strip()
    hospital = request.form.get('hospital', 'Klinik SKEM').strip()
    requirements = request.form.get('requirements', '').strip()
    status = request.form.get('status', 'Aktif').strip()

    if 0 <= index < len(SERVICES_LIST):
        SERVICES_LIST[index].update({
            'name': name,
            'hospital': hospital or 'Klinik SKEM',
            'requirements': requirements,
            'status': status,
            'status_class': 'green' if status == 'Aktif' else 'amber'
        })
        db_save_service(SERVICES_LIST[index], srv_id=SERVICES_LIST[index].get('id'))
        flash(f"Layanan {name} berhasil diperbarui.")
    return redirect(url_for('system.services'))

@system_bp.route('/services/delete/<int:index>', methods=['POST'])
def delete_service(index):
    if 0 <= index < len(SERVICES_LIST):
        removed = SERVICES_LIST.pop(index)
        db_delete_service(removed['name'])
        flash(f"Layanan {removed['name']} berhasil dihapus.")
    return redirect(url_for('system.services'))

@system_bp.route('/logs')
def logs():
    return render_template(
        'system/logs.html',
        active_page='logs',
        system_logs=SYSTEM_LOGS,
        patients=PATIENTS
    )

# ==============================================================================
# REGISTRASI BLUEPRINT & TOP-LEVEL SHORTCUT ROUTES
# ==============================================================================
app.register_blueprint(auth_bp)
app.register_blueprint(patient_bp)
app.register_blueprint(facility_bp)
app.register_blueprint(system_bp)

@app.route('/')
def index():
    user = session.get('user')
    if user:
        return redirect(get_role_home_url(user.get('role')))
    return redirect(url_for('auth.login'))

@app.route('/login')
def login_shortcut():
    return redirect(url_for('auth.login'))

@app.route('/register')
def register_shortcut():
    return redirect(url_for('auth.register'))

@app.route('/logout')
def logout_shortcut():
    return redirect(url_for('auth.logout'))

if __name__ == '__main__':
    app.run(debug=True, port=5001)
