"""
طبقة قاعدة البيانات — تُستعمل تلقائياً بمجرد وجود متغيّر البيئة DATABASE_URL
(رابط اتصال Supabase/PostgreSQL). إن لم يوجد هذا المتغيّر، يبقى DB_ENABLED=False
ويستمر app.py باستعمال ملفات JSON المحلية كما كان — لا يحدث أي عطل أثناء الانتقال.
"""
import os
import json
from datetime import datetime

DATABASE_URL = os.environ.get("DATABASE_URL")
DB_ENABLED = bool(DATABASE_URL)

if DB_ENABLED:
    import psycopg2
    import psycopg2.extras


def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


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
