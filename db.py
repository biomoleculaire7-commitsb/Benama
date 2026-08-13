"""
طبقة قاعدة البيانات — تُستعمل تلقائياً بمجرد وجود متغيّر البيئة DATABASE_URL
(رابط اتصال Supabase/PostgreSQL). إن لم يوجد هذا المتغيّر، يبقى DB_ENABLED=False
ويستمر app.py باستعمال ملفات JSON المحلية كما كان — لا يحدث أي عطل أثناء الانتقال.

يستعمل pg8000 (سائق PostgreSQL مكتوب بلغة بايثون خالصة، بلا أي كود C مُصرَّف)
لتفادي مشاكل التوافق مع إصدارات بايثون الحديثة التي يستعملها Render أحياناً.
"""
import os
import ssl
from urllib.parse import urlparse, unquote

DATABASE_URL = os.environ.get("DATABASE_URL")
DB_ENABLED = bool(DATABASE_URL)

_DB_HOST = _DB_PORT = _DB_USER = _DB_PASSWORD = _DB_NAME = None
_INIT_ERROR = None

if DB_ENABLED:
    try:
        import pg8000.dbapi

        _parsed = urlparse(DATABASE_URL.strip())
        _DB_HOST = _parsed.hostname
        _DB_PORT = _parsed.port or 5432
        _DB_USER = unquote(_parsed.username) if _parsed.username else None
        _DB_PASSWORD = unquote(_parsed.password) if _parsed.password else None
        _DB_NAME = (_parsed.path or "/postgres").lstrip("/") or "postgres"

        missing = [name for name, val in [
            ("اسم المستخدم (user)", _DB_USER),
            ("كلمة المرور (password)", _DB_PASSWORD),
            ("العنوان (host)", _DB_HOST),
        ] if not val]
        if missing:
            raise ValueError(
                "DATABASE_URL غير صالح — تعذّر استخراج: " + "، ".join(missing) + ". "
                "تأكد أن الرابط بصيغة: postgresql://USER:PASSWORD@HOST:PORT/DBNAME "
                "وأن كلمة المرور استُبدلت فعلياً بدل [YOUR-PASSWORD]، وأنها لا تحتوي "
                "على مسافات أو أسطر إضافية عند اللصق في Render."
            )
    except Exception as e:
        # Never let a bad DATABASE_URL crash the whole platform at import time.
        # Fall back to local JSON storage; app.py's own try/except is a second
        # safety net around init_db() for errors that only surface at connect-time.
        print(f"[WARNING] DATABASE_URL misconfigured, using JSON files instead: {e}")
        DB_ENABLED = False
        _INIT_ERROR = str(e)


def get_conn():
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    return pg8000.dbapi.connect(
        user=_DB_USER, password=_DB_PASSWORD, host=_DB_HOST,
        port=_DB_PORT, database=_DB_NAME, ssl_context=ssl_context,
    )


def init_db():
    """Create all tables if they don't exist yet. Safe to call on every startup."""
    if not DB_ENABLED:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id SERIAL PRIMARY KEY,
            class_name TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT,
            doctype TEXT,
            teacher TEXT,
            subject TEXT,
            file_url TEXT,
            file_name TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT,
            target TEXT,
            author TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS absences (
            id SERIAL PRIMARY KEY,
            national_id TEXT NOT NULL,
            last_name TEXT,
            first_name TEXT,
            class_name TEXT,
            absence_date DATE NOT NULL,
            reason TEXT,
            hours NUMERIC DEFAULT 0,
            UNIQUE(national_id, absence_date)
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff_absences (
            id SERIAL PRIMARY KEY,
            employee_id TEXT NOT NULL,
            last_name TEXT,
            first_name TEXT,
            role TEXT,
            absence_date DATE NOT NULL,
            reason TEXT,
            hours NUMERIC DEFAULT 0,
            UNIQUE(employee_id, absence_date)
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS parent_phones (
            national_id TEXT PRIMARY KEY,
            phone TEXT
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS guidance (
            id SERIAL PRIMARY KEY,
            national_id TEXT NOT NULL,
            reason TEXT,
            actions TEXT,
            author TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS login_log (
            id SERIAL PRIMARY KEY,
            role TEXT,
            uid TEXT,
            name TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()


def _dictify(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------------- Documents ----------------

def get_documents(class_name):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""SELECT title, body, doctype, teacher, subject, file_url AS "fileUrl",
                    file_name AS "fileName", to_char(created_at,'YYYY-MM-DD HH24:MI') AS date
                    FROM documents WHERE class_name=%s ORDER BY created_at DESC""", (class_name,))
    rows = _dictify(cur)
    cur.close(); conn.close()
    return rows


def get_documents_for_date(date):
    """All documents sent on a given date, across all classes — for the director's report."""
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""SELECT class_name AS "class", title, doctype, teacher, subject
                    FROM documents WHERE created_at::date=%s ORDER BY created_at DESC""", (date,))
    rows = _dictify(cur)
    cur.close(); conn.close()
    return rows


def add_document(class_name, title, body, doctype, teacher, subject, file_url, file_name):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""INSERT INTO documents (class_name, title, body, doctype, teacher, subject, file_url, file_name)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (class_name, title, body, doctype, teacher, subject, file_url, file_name))
    conn.commit(); cur.close(); conn.close()


# ---------------- Announcements ----------------

def get_announcements():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""SELECT title, body, target, author, to_char(created_at,'YYYY-MM-DD HH24:MI') AS date
                    FROM announcements ORDER BY created_at DESC""")
    rows = _dictify(cur)
    cur.close(); conn.close()
    return rows


def add_announcement(title, body, target, author):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""INSERT INTO announcements (title, body, target, author) VALUES (%s,%s,%s,%s)""",
                (title, body, target, author))
    conn.commit(); cur.close(); conn.close()


# ---------------- Absences — students ----------------

def save_student_absences(class_name, date, records):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM absences WHERE class_name=%s AND absence_date=%s", (class_name, date))
    for r in records:
        cur.execute("""INSERT INTO absences (national_id, last_name, first_name, class_name, absence_date, reason, hours)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (r["national_id"], r["last_name"], r["first_name"], class_name, date, r.get("reason", ""), r.get("hours", 0)))
    conn.commit(); cur.close(); conn.close()


def get_student_absences(date, class_name=None):
    conn = get_conn(); cur = conn.cursor()
    if class_name:
        cur.execute("""SELECT national_id, last_name, first_name, class_name AS "class",
                        to_char(absence_date,'YYYY-MM-DD') AS date, reason, hours
                        FROM absences WHERE absence_date=%s AND class_name=%s""", (date, class_name))
    else:
        cur.execute("""SELECT national_id, last_name, first_name, class_name AS "class",
                        to_char(absence_date,'YYYY-MM-DD') AS date, reason, hours
                        FROM absences WHERE absence_date=%s""", (date,))
    rows = _dictify(cur)
    cur.close(); conn.close()
    return rows


# ---------------- Absences — staff ----------------

def save_staff_absences(date, records):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM staff_absences WHERE absence_date=%s", (date,))
    for r in records:
        cur.execute("""INSERT INTO staff_absences (employee_id, last_name, first_name, role, absence_date, reason, hours)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (r["employee_id"], r["last_name"], r["first_name"], r["role"], date, r.get("reason", ""), r.get("hours", 0)))
    conn.commit(); cur.close(); conn.close()


def get_staff_absences(date):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""SELECT employee_id, last_name, first_name, role,
                    to_char(absence_date,'YYYY-MM-DD') AS date, reason, hours
                    FROM staff_absences WHERE absence_date=%s""", (date,))
    rows = _dictify(cur)
    cur.close(); conn.close()
    return rows


# ---------------- Parent phones ----------------

def get_parent_phone(national_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT phone FROM parent_phones WHERE national_id=%s", (national_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row[0] if row else ""


def get_parent_phones_bulk():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT national_id, phone FROM parent_phones")
    result = {r[0]: r[1] for r in cur.fetchall()}
    cur.close(); conn.close()
    return result


def set_parent_phone(national_id, phone):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""INSERT INTO parent_phones (national_id, phone) VALUES (%s,%s)
                    ON CONFLICT (national_id) DO UPDATE SET phone=EXCLUDED.phone""", (national_id, phone))
    conn.commit(); cur.close(); conn.close()


# ---------------- Guidance ----------------

def add_guidance(national_id, reason, actions, author):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""INSERT INTO guidance (national_id, reason, actions, author) VALUES (%s,%s,%s,%s)""",
                (national_id, reason, actions, author))
    conn.commit(); cur.close(); conn.close()


def get_guidance(national_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""SELECT reason, actions, author, to_char(created_at,'YYYY-MM-DD HH24:MI') AS date
                    FROM guidance WHERE national_id=%s ORDER BY created_at DESC""", (national_id,))
    rows = _dictify(cur)
    cur.close(); conn.close()
    return rows


def get_guidance_for_date(date):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""SELECT national_id, reason, actions, author,
                    to_char(created_at,'YYYY-MM-DD HH24:MI') AS date
                    FROM guidance WHERE created_at::date=%s ORDER BY created_at DESC""", (date,))
    rows = _dictify(cur)
    cur.close(); conn.close()
    return rows


# ---------------- Login log ----------------

def log_login(role, uid, name):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT INTO login_log (role, uid, name) VALUES (%s,%s,%s)", (role, uid, name))
    conn.commit(); cur.close(); conn.close()


def get_logins_for_date(date):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""SELECT role, uid AS id, name, to_char(created_at,'HH24:MI:SS') AS time
                    FROM login_log WHERE created_at::date=%s ORDER BY created_at""", (date,))
    rows = _dictify(cur)
    cur.close(); conn.close()
    return rows
