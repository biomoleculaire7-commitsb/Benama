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
    user = {**staff_row, "role": "teacher", "classes": my_classes}
    return jsonify({"ok": True, "user": user})


# ---------------- Class rosters ----------------

@app.route("/api/roster/<class_name>")
def roster(class_name):
    rows = [s for s in STUDENTS if s["class"] == class_name]
    return jsonify({"class": class_name, "count": len(rows), "students": rows})


@app.route("/api/roster/<class_name>/export.csv")
def export_roster_csv(class_name):
    rows = [s for s in STUDENTS if s["class"] == class_name]
    lines = ["الرقم,اللقب,الاسم,الجنس,الرقم التعريف الوطني,القسم"]
    for i, s in enumerate(rows, 1):
        lines.append(f'{i},{s["last_name"]},{s["first_name"]},{s["gender"]},{s["national_id"]},{s["class"]}')
    csv_content = "\ufeff" + "\n".join(lines)
    from flask import Response
    from urllib.parse import quote
    filename = f"قائمة_قسم_{class_name}.csv"
    encoded_filename = quote(filename)
    return Response(
        csv_content,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=roster.csv; filename*=UTF-8''{encoded_filename}"
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
