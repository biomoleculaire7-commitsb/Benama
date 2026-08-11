import os
import json
import time
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, render_template

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Search several likely locations for the data file, since manual GitHub
# uploads sometimes drop files at repo root instead of inside data/.
_CANDIDATE_PATHS = [
    os.path.join(BASE_DIR, "data", "school_data.json"),
    os.path.join(BASE_DIR, "school_data.json"),
    os.path.join(BASE_DIR, "..", "school_data.json"),
    os.path.join(BASE_DIR, "..", "data", "school_data.json"),
]
DATA_FILE = next((p for p in _CANDIDATE_PATHS if os.path.exists(p)), None)
if DATA_FILE is None:
    raise FileNotFoundError(
        "تعذّر إيجاد school_data.json. تأكد من رفعه إلى المستودع "
        "(داخل مجلد data/ أو في الجذر مباشرة). تم البحث في: "
        + ", ".join(_CANDIDATE_PATHS)
    )

DOCS_FILE = os.path.join(os.path.dirname(DATA_FILE), "documents.json")
ANN_FILE = os.path.join(os.path.dirname(DATA_FILE), "announcements.json")
ABS_FILE = os.path.join(os.path.dirname(DATA_FILE), "absences.json")
GUID_FILE = os.path.join(os.path.dirname(DATA_FILE), "guidance.json")
LOGIN_LOG_FILE = os.path.join(os.path.dirname(DATA_FILE), "login_log.json")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
MAX_FILE_SIZE = 15 * 1024 * 1024  # 15MB - real server, no artifact-storage limit

os.makedirs(UPLOAD_DIR, exist_ok=True)

# Same resilience as the data file: find templates/ wherever it actually landed.
_TEMPLATE_CANDIDATES = [
    os.path.join(BASE_DIR, "templates"),
    BASE_DIR,
]
TEMPLATE_DIR = next(
    (p for p in _TEMPLATE_CANDIDATES if os.path.exists(os.path.join(p, "index.html"))),
    os.path.join(BASE_DIR, "templates"),
)

app = Flask(__name__, template_folder=TEMPLATE_DIR)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

with open(DATA_FILE, encoding="utf-8") as f:
    SCHOOL_DATA = json.load(f)

STUDENTS = SCHOOL_DATA["students"]
STAFF = SCHOOL_DATA["staff"]
ASSIGNMENTS = SCHOOL_DATA["assignments"]


def load_docs():
    if os.path.exists(DOCS_FILE):
        with open(DOCS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_docs(docs):
    with open(DOCS_FILE, "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)


def load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def log_login(role, uid, name):
    """Record every login (student/teacher/admin) for the director's daily report."""
    logs = load_json(LOGIN_LOG_FILE, [])
    logs.append({
        "role": role,
        "id": uid,
        "name": name,
        "date": today_str(),
        "time": datetime.now().strftime("%H:%M:%S"),
    })
    # keep the log from growing forever on the free tier's small disk
    logs = logs[-3000:]
    save_json(LOGIN_LOG_FILE, logs)


def classify_admin_role(role_text):
    role_text = role_text or ""
    if "مدير" in role_text and "مساعد" not in role_text:
        return "director"
    if "ناظر" in role_text:
        return "supervisor"
    if "مستشار" in role_text and "توجيه" in role_text:
        return "counselor"
    return None


# ---------------- Pages ----------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------- Auth ----------------

@app.route("/api/login/student", methods=["POST"])
def login_student():
    data = request.get_json(force=True)
    nid = str(data.get("national_id", "")).strip()
    if not nid:
        return jsonify({"ok": False, "error": "يرجى إدخال الرقم التعريف الوطني."}), 400
    stu = next((s for s in STUDENTS if str(s["national_id"]) == nid), None)
    if not stu:
        return jsonify({"ok": False, "error": "هذا الرقم غير مسجّل في قاعدة بياناتنا الحالية."}), 404
    log_login("student", nid, f"{stu['last_name']} {stu['first_name']} ({stu['class']})")
    return jsonify({"ok": True, "user": {**stu, "role": "student"}})


@app.route("/api/login/teacher", methods=["POST"])
def login_teacher():
    data = request.get_json(force=True)
    emp_id = str(data.get("employee_id", "")).strip()
    if not emp_id:
        return jsonify({"ok": False, "error": "يرجى إدخال الرقم التعريف الوظيفي."}), 400
    staff_row = next((s for s in STAFF if str(s["employee_id"]) == emp_id), None)
    if not staff_row:
        return jsonify({"ok": False, "error": "هذا الرقم الوظيفي غير مسجّل في قاعدة بياناتنا الحالية."}), 404
    my_classes = [a for a in ASSIGNMENTS if str(a["employee_id"]) == emp_id]
    if not my_classes:
        return jsonify({
            "ok": False,
            "error": "هذا الرقم مسجّل ضمن الطاقم، لكن لا يوجد له إسناد تربوي حالياً (قد يكون إدارياً)."
        }), 404
    log_login("teacher", emp_id, f"{staff_row['last_name']} {staff_row['first_name']} ({staff_row['subject']})")
    user = {**staff_row, "role": "teacher", "classes": my_classes}
    return jsonify({"ok": True, "user": user})


@app.route("/api/login/admin", methods=["POST"])
def login_admin():
    data = request.get_json(force=True)
    emp_id = str(data.get("employee_id", "")).strip()
    if not emp_id:
        return jsonify({"ok": False, "error": "يرجى إدخال الرقم التعريف الوظيفي."}), 400
    staff_row = next((s for s in STAFF if str(s["employee_id"]) == emp_id), None)
    if not staff_row:
        return jsonify({"ok": False, "error": "هذا الرقم الوظيفي غير مسجّل في قاعدة بياناتنا الحالية."}), 404
    admin_role = classify_admin_role(staff_row.get("role", ""))
    if not admin_role:
        return jsonify({
            "ok": False,
            "error": "هذا الرقم مسجّل ضمن الطاقم، لكنه ليس من فئة الإدارة (مدير / ناظر / مستشار توجيه)."
        }), 404
    log_login("admin", emp_id, f"{staff_row['last_name']} {staff_row['first_name']} ({staff_row['role']})")
    user = {**staff_row, "role": "admin", "admin_role": admin_role}
    return jsonify({"ok": True, "user": user})


# ---------------- Class rosters ----------------

@app.route("/api/roster/<class_name>")
def roster(class_name):
    rows = [s for s in STUDENTS if s["class"] == class_name]
    return jsonify({"class": class_name, "count": len(rows), "students": rows})


@app.route("/api/roster/<class_name>/export.xlsx")
def export_roster_csv(class_name):
    rows = [s for s in STUDENTS if s["class"] == class_name]

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from flask import Response
    from urllib.parse import quote
    import io

    wb = Workbook()
    ws = wb.active
    ws.title = class_name
    ws.sheet_view.rightToLeft = True

    GREEN = "0F4C3A"
    OCHRE = "C17817"
    thin = Side(style="thin", color="D8CFB8")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ncols = 5
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    ws["A1"] = f"متوسطة الشهيد بن نعمة مصطفى — قائمة تلاميذ قسم {class_name}"
    ws["A1"].font = Font(name="Arial", size=13, bold=True, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor=GREEN)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 26

    headers = ["الرقم", "اللقب", "الاسم", "الجنس", "الرقم التعريف الوطني"]
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=3, column=i, value=h)
        c.font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=OCHRE)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = border

    for idx, s in enumerate(rows, start=1):
        r = idx + 3
        values = [idx, s["last_name"], s["first_name"], s["gender"], s["national_id"]]
        for c_i, val in enumerate(values, start=1):
            cell = ws.cell(row=r, column=c_i, value=val)
            cell.font = Font(name="Arial", size=10.5)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = border
            if r % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="FBFAF6")

    widths = [7, 20, 20, 8, 20]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A4"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"قائمة_قسم_{class_name}.xlsx"
    encoded_filename = quote(filename)
    return Response(
        buf.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=roster.xlsx; filename*=UTF-8''{encoded_filename}",
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        }
    )


# ---------------- Documents (send/receive) ----------------

@app.route("/api/docs/<class_name>", methods=["GET"])
def get_docs(class_name):
    docs = load_docs()
    return jsonify(docs.get(class_name, []))


@app.route("/api/docs/<class_name>", methods=["POST"])
def post_doc(class_name):
    title = request.form.get("title", "").strip()
    body = request.form.get("body", "").strip()
    doctype = request.form.get("doctype", "درس")
    teacher_name = request.form.get("teacher_name", "")
    subject = request.form.get("subject", "")

    if not title:
        return jsonify({"ok": False, "error": "عنوان الوثيقة مطلوب."}), 400

    file_url = None
    file_name = None
    file_obj = request.files.get("file")
    if file_obj and file_obj.filename:
        safe_name = f"{int(time.time()*1000)}_{file_obj.filename}"
        file_obj.save(os.path.join(UPLOAD_DIR, safe_name))
        file_name = file_obj.filename
        file_url = f"/uploads/{safe_name}"

    docs = load_docs()
    docs.setdefault(class_name, [])
    docs[class_name].insert(0, {
        "title": title,
        "body": body,
        "doctype": doctype,
        "teacher": teacher_name,
        "subject": subject,
        "fileUrl": file_url,
        "fileName": file_name,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    save_docs(docs)
    return jsonify({"ok": True})


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=False)


# ---------------- Announcements (أمانة المدير) ----------------

@app.route("/api/announcements", methods=["GET"])
def list_announcements():
    return jsonify(load_json(ANN_FILE, []))


@app.route("/api/announcements", methods=["POST"])
def create_announcement():
    data = request.get_json(force=True)
    title = (data.get("title") or "").strip()
    body = (data.get("body") or "").strip()
    target = data.get("target") or "all"  # 'all' | 'students' | 'teachers' | 'class:<name>'
    author = data.get("author") or "إدارة المؤسسة"
    if not title:
        return jsonify({"ok": False, "error": "عنوان الإعلان مطلوب."}), 400
    anns = load_json(ANN_FILE, [])
    anns.insert(0, {
        "title": title, "body": body, "target": target, "author": author,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    save_json(ANN_FILE, anns)
    return jsonify({"ok": True})


@app.route("/api/announcements/for/<audience>")
def announcements_for(audience):
    """audience = 'students' | 'teachers' | a class name for a student's own class"""
    anns = load_json(ANN_FILE, [])
    if audience == "students":
        result = [a for a in anns if a["target"] in ("all", "students")]
    elif audience == "teachers":
        result = [a for a in anns if a["target"] in ("all", "teachers")]
    else:
        result = [a for a in anns if a["target"] in ("all", "students", f"class:{audience}")]
    return jsonify(result)


# ---------------- Absences (الناظر) ----------------

@app.route("/api/absences", methods=["POST"])
def mark_absences():
    data = request.get_json(force=True)
    class_name = data.get("class")
    date = data.get("date") or today_str()
    student_ids = data.get("national_ids", [])
    if not class_name:
        return jsonify({"ok": False, "error": "القسم مطلوب."}), 400

    roster = {str(s["national_id"]): s for s in STUDENTS if s["class"] == class_name}
    absences = load_json(ABS_FILE, [])
    # remove previous entries for this class/date, then add the new set (idempotent)
    absences = [a for a in absences if not (a["class"] == class_name and a["date"] == date)]
    for nid in student_ids:
        s = roster.get(str(nid))
        if s:
            absences.append({
                "national_id": str(nid), "last_name": s["last_name"], "first_name": s["first_name"],
                "class": class_name, "date": date,
            })
    save_json(ABS_FILE, absences)
    return jsonify({"ok": True, "count": len(student_ids)})


@app.route("/api/absences")
def get_absences():
    date = request.args.get("date") or today_str()
    class_name = request.args.get("class")
    absences = load_json(ABS_FILE, [])
    absences = [a for a in absences if a["date"] == date]
    if class_name:
        absences = [a for a in absences if a["class"] == class_name]
    return jsonify(absences)


# ---------------- Guidance (مستشار التوجيه) ----------------

@app.route("/api/guidance/<national_id>", methods=["GET"])
def get_guidance(national_id):
    guid = load_json(GUID_FILE, {})
    return jsonify(guid.get(str(national_id), []))


@app.route("/api/guidance/<national_id>", methods=["POST"])
def add_guidance(national_id):
    data = request.get_json(force=True)
    note = (data.get("note") or "").strip()
    author = data.get("author") or "مستشار التوجيه"
    if not note:
        return jsonify({"ok": False, "error": "نص المقابلة مطلوب."}), 400
    guid = load_json(GUID_FILE, {})
    guid.setdefault(str(national_id), [])
    guid[str(national_id)].insert(0, {
        "note": note, "author": author,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    save_json(GUID_FILE, guid)
    return jsonify({"ok": True})


@app.route("/api/guidance/recent")
def recent_guidance():
    """All interviews for a given date, across all students — for the director's report."""
    date = request.args.get("date") or today_str()
    guid = load_json(GUID_FILE, {})
    result = []
    for nid, notes in guid.items():
        stu = next((s for s in STUDENTS if str(s["national_id"]) == nid), None)
        for n in notes:
            if n["date"].startswith(date):
                result.append({
                    "national_id": nid,
                    "student_name": f"{stu['last_name']} {stu['first_name']}" if stu else nid,
                    "class": stu["class"] if stu else "—",
                    **n,
                })
    return jsonify(result)


# ---------------- Director's daily report ----------------

@app.route("/api/director/daily-report")
def daily_report():
    date = request.args.get("date") or today_str()

    logs = [l for l in load_json(LOGIN_LOG_FILE, []) if l["date"] == date]
    students_logged = [l for l in logs if l["role"] == "student"]
    teachers_logged = [l for l in logs if l["role"] == "teacher"]
    admins_logged = [l for l in logs if l["role"] == "admin"]

    absences = [a for a in load_json(ABS_FILE, []) if a["date"] == date]

    docs = load_docs()
    docs_today = []
    for class_name, items in docs.items():
        for d in items:
            if d["date"].startswith(date):
                docs_today.append({"class": class_name, **d})

    guid = load_json(GUID_FILE, {})
    guidance_today = []
    for nid, notes in guid.items():
        stu = next((s for s in STUDENTS if str(s["national_id"]) == nid), None)
        for n in notes:
            if n["date"].startswith(date):
                guidance_today.append({
                    "national_id": nid,
                    "student_name": f"{stu['last_name']} {stu['first_name']}" if stu else nid,
                    "class": stu["class"] if stu else "—",
                    **n,
                })

    return jsonify({
        "date": date,
        "logins": {
            "students": students_logged,
            "teachers": teachers_logged,
            "admins": admins_logged,
        },
        "absences": absences,
        "documents_sent": docs_today,
        "guidance_interviews": guidance_today,
        "totals": {
            "students_in_school": len(STUDENTS),
            "teachers_in_school": len({a["employee_id"] for a in ASSIGNMENTS}),
        }
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
