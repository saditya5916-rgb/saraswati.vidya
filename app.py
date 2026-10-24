from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3, os, shutil, csv, io, calendar, uuid
from datetime import date, datetime
from functools import wraps

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "school.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SCHOOL_SECRET_KEY", "change-this-secret-key-before-public-deployment")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    # Make a timestamped safety copy before applying additive schema migrations.
    if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0:
        try:
            probe = sqlite3.connect(DB_PATH)
            tables = {r[0] for r in probe.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            cols = {r[1] for r in probe.execute("PRAGMA table_info(fee_payments)")} if 'fee_payments' in tables else set()
            needs_migration = 'fee_allocations' not in tables or not {'payment_method','transaction_reference','remarks'}.issubset(cols)
            probe.close()
            if needs_migration:
                stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                shutil.copy2(DB_PATH, DB_PATH + '.backup_' + stamp)
        except Exception:
            pass
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        subject TEXT DEFAULT '',
        role TEXT DEFAULT 'Teacher',
        phone TEXT DEFAULT '',
        photo TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS notices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        body TEXT DEFAULT '',
        date TEXT DEFAULT CURRENT_DATE
    );
    CREATE TABLE IF NOT EXISTS admissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_name TEXT NOT NULL,
        dob TEXT DEFAULT '',
        class_name TEXT DEFAULT '',
        parent_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        email TEXT DEFAULT '',
        address TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_uid TEXT UNIQUE,
        student_name TEXT NOT NULL,
        class_name TEXT DEFAULT '',
        parent_name TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        address TEXT DEFAULT '',
        monthly_fee REAL NOT NULL DEFAULT 0,
        admission_date TEXT DEFAULT CURRENT_DATE,
        active INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS fee_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_no TEXT UNIQUE,
        student_id INTEGER NOT NULL,
        fee_month TEXT NOT NULL,
        amount REAL NOT NULL,
        paid_on TEXT DEFAULT CURRENT_DATE,
        note TEXT DEFAULT '',
        FOREIGN KEY(student_id) REFERENCES students(id)
    );
    CREATE TABLE IF NOT EXISTS fee_allocations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_id INTEGER NOT NULL,
        fee_month TEXT NOT NULL,
        amount REAL NOT NULL,
        allocation_type TEXT NOT NULL DEFAULT 'payment',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(payment_id) REFERENCES fee_payments(id)
    );
    CREATE TABLE IF NOT EXISTS gallery (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT DEFAULT '',
        image_path TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS vans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_no TEXT NOT NULL,
        driver_name TEXT DEFAULT '',
        driver_phone TEXT DEFAULT '',
        route_name TEXT DEFAULT '',
        capacity INTEGER DEFAULT 0,
        notes TEXT DEFAULT ''
    );
    """)
    # Safe additive migration: existing tables and records are never dropped.
    pay_cols = {r["name"] for r in con.execute("PRAGMA table_info(fee_payments)")}
    for col, definition in [("payment_method", "TEXT DEFAULT 'Cash'"), ("transaction_reference", "TEXT DEFAULT ''"), ("remarks", "TEXT DEFAULT ''"), ("idempotency_key", "TEXT DEFAULT ''")]:
        if col not in pay_cols:
            con.execute(f"ALTER TABLE fee_payments ADD COLUMN {col} {definition}")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_fee_payment_idempotency ON fee_payments(idempotency_key) WHERE idempotency_key <> ''")
    cols = {r["name"] for r in con.execute("PRAGMA table_info(students)")}
    if "student_uid" not in cols:
        con.execute("ALTER TABLE students ADD COLUMN student_uid TEXT")
    for row in con.execute("SELECT id FROM students WHERE student_uid IS NULL OR student_uid=''").fetchall():
        con.execute("UPDATE students SET student_uid=? WHERE id=?", (f"SVM-{row['id']:05d}", row["id"]))
    if not con.execute("SELECT id FROM admins LIMIT 1").fetchone():
        con.execute("INSERT INTO admins(username,password_hash) VALUES(?,?)",
                    ("admin", generate_password_hash("Admin@12345")))
    defaults = {
        "school_name": "Saraswati Vidya Mandir Public School, Semla",
        "tagline": "Learning Today... Leading Tomorrow...",
        "principal": "Smita Singh",
        "director": "Neekesh Singh",
        "phone": "+91 98765 43210",
        "email": "info@svmsemla.in",
        "address": "Semla, Bihar, India",
        "hero_title": "Welcome to Saraswati Vidya Mandir Public School, Semla",
        "hero_text": "Quality education, moral values and a bright future for every child.",
        "about": "We are committed to providing quality education with a blend of traditional values and modern learning techniques. We aim to nurture confident, creative and responsible citizens of tomorrow.",
        "academic_year_start": "2026",
        "academic_year_end": "2027"
    }
    for k, v in defaults.items():
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k,v))
    if not con.execute("SELECT id FROM teachers LIMIT 1").fetchone():
        con.executemany("INSERT INTO teachers(name,subject,role) VALUES(?,?,?)", [
            ("Sanju", "General Studies", "Teacher"), ("Nisha", "General Studies", "Teacher")
        ])
    if not con.execute("SELECT id FROM notices LIMIT 1").fetchone():
        con.executemany("INSERT INTO notices(title,body,date) VALUES(?,?,?)", [
            ("Welcome to Our School", "Admissions and school updates will appear here.", "2026-10-23"),
            ("Admission Enquiry Open", "Submit the online enquiry form to contact the school.", "2026-10-23")
        ])
    con.commit()
    con.close()

def settings():
    con = db()
    data = {r["key"]: r["value"] for r in con.execute("SELECT key,value FROM settings")}
    con.close()
    return data

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapped

@app.context_processor
def common_data():
    return {"school": settings(), "admin_logged_in": bool(session.get("admin_id"))}

@app.route("/")
def home():
    con = db()
    teachers = con.execute("SELECT * FROM teachers ORDER BY id DESC").fetchall()
    notices = con.execute("SELECT * FROM notices ORDER BY date DESC, id DESC LIMIT 5").fetchall()
    gallery_photos = con.execute("SELECT * FROM gallery ORDER BY id DESC LIMIT 12").fetchall()
    con.close()
    return render_template("index.html", teachers=teachers, notices=notices, gallery_photos=gallery_photos)

@app.route("/admission", methods=["POST"])
def admission():
    fields = ["student_name", "dob", "class_name", "parent_name", "phone", "email", "address"]
    data = {f: request.form.get(f, "").strip() for f in fields}
    if not data["student_name"] or not data["parent_name"] or not data["phone"]:
        flash("Please fill in student name, parent name and phone number.", "error")
        return redirect(url_for("home") + "#admission")
    con = db()
    con.execute("""INSERT INTO admissions(student_name,dob,class_name,parent_name,phone,email,address)
                   VALUES(:student_name,:dob,:class_name,:parent_name,:phone,:email,:address)""", data)
    con.commit()
    con.close()
    flash("Your admission enquiry was submitted successfully. The school will contact you.", "success")
    return redirect(url_for("home") + "#admission")

@app.route("/admin")
def admin_home():
    if not session.get("admin_id"):
        return redirect(url_for("admin_login"))
    con = db()
    counts = {
        "teachers": con.execute("SELECT COUNT(*) FROM teachers").fetchone()[0],
        "notices": con.execute("SELECT COUNT(*) FROM notices").fetchone()[0],
        "admissions": con.execute("SELECT COUNT(*) FROM admissions").fetchone()[0],
        "students": con.execute("SELECT COUNT(*) FROM students WHERE active=1").fetchone()[0],
        "fees": con.execute("SELECT COALESCE(SUM(amount),0) FROM fee_payments").fetchone()[0],
        "vans": con.execute("SELECT COUNT(*) FROM vans").fetchone()[0]
    }
    con.close()
    return render_template("admin.html", page="dashboard", counts=counts)

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        con = db()
        user = con.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
        con.close()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["admin_id"] = user["id"]
            session["admin_username"] = user["username"]
            return redirect(url_for("admin_home"))
        flash("Incorrect username or password.", "error")
    return render_template("login.html")

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
def admin_settings():
    if request.method == "POST":
        keys = ["school_name","tagline","principal","director","phone","email","address","hero_title","hero_text","about","academic_year_start","academic_year_end"]
        con = db()
        for key in keys:
            con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, request.form.get(key, "").strip()))
        con.commit()
        con.close()
        flash("School details updated.", "success")
        return redirect(url_for("admin_settings"))
    return render_template("admin.html", page="settings", data=settings())

@app.route("/admin/teachers", methods=["GET", "POST"])
@login_required
def admin_teachers():
    con = db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "achived":
            con.execute("DELETE FROM teachers WHERE id=?", (request.form.get("id"),))
        else:
            name = request.form.get("name", "").strip()
            if name:
                photo = request.form.get("existing_photo", "")
                upload = request.files.get("photo")
                if upload and upload.filename and allowed_file(upload.filename):
                    filename = secure_filename(upload.filename)
                    filename = str(os.urandom(4).hex()) + "_" + filename
                    upload.save(os.path.join(UPLOAD_DIR, filename))
                    photo = "uploads/" + filename
                values = (name, request.form.get("subject","").strip(),
                          request.form.get("role","Teacher").strip(),
                          request.form.get("phone","").strip(), photo)
                tid = request.form.get("id", "").strip()
                if tid:
                    con.execute("UPDATE teachers SET name=?,subject=?,role=?,phone=?,photo=? WHERE id=?", values + (tid,))
                else:
                    con.execute("INSERT INTO teachers(name,subject,role,phone,photo) VALUES(?,?,?,?,?)", values)
        con.commit()
        con.close()
        flash("Teacher information saved.", "success")
        return redirect(url_for("admin_teachers"))
    teachers = con.execute("SELECT * FROM teachers ORDER BY id DESC").fetchall()
    con.close()
    return render_template("admin.html", page="teachers", teachers=teachers)

@app.route("/admin/notices", methods=["GET", "POST"])
@login_required
def admin_notices():
    con = db()
    if request.method == "POST":
        if request.form.get("action") == "delete":
            con.execute("DELETE FROM notices WHERE id=?", (request.form.get("id"),))
        else:
            title = request.form.get("title", "").strip()
            body = request.form.get("body", "").strip()
            date = request.form.get("date", "").strip() or "2026-10-23"
            nid = request.form.get("id", "").strip()
            if title:
                if nid:
                    con.execute("UPDATE notices SET title=?,body=?,date=? WHERE id=?", (title,body,date,nid))
                else:
                    con.execute("INSERT INTO notices(title,body,date) VALUES(?,?,?)", (title,body,date))
        con.commit()
        con.close()
        flash("Notice saved.", "success")
        return redirect(url_for("admin_notices"))
    notices = con.execute("SELECT * FROM notices ORDER BY date DESC,id DESC").fetchall()
    con.close()
    return render_template("admin.html", page="notices", notices=notices)

@app.route("/admin/admissions")
@login_required
def admin_admissions():
    con = db()
    admissions = con.execute("SELECT * FROM admissions ORDER BY created_at DESC").fetchall()
    con.close()
    return render_template("admin.html", page="admissions", admissions=admissions)

@app.route("/admin/password", methods=["GET", "POST"])
@login_required
def admin_password():
    if request.method == "POST":
        old = request.form.get("old_password", "")
        new = request.form.get("new_password", "")
        if len(new) < 10:
            flash("New password must be at least 10 characters.", "error")
        else:
            con = db()
            user = con.execute("SELECT * FROM admins WHERE id=?", (session["admin_id"],)).fetchone()
            if user and check_password_hash(user["password_hash"], old):
                con.execute("UPDATE admins SET password_hash=? WHERE id=?",
                            (generate_password_hash(new), session["admin_id"]))
                con.commit()
                flash("Password changed successfully.", "success")
            else:
                flash("Current password is incorrect.", "error")
            con.close()
        return redirect(url_for("admin_password"))
    return render_template("admin.html", page="password")


def feature_page(page, **kwargs):
    return render_template("admin_feature.html", page=page, **kwargs)

@app.route("/admin/students", methods=["GET", "POST"])
@login_required
def admin_students():
    con = db()
    if request.method == "POST":
        action = request.form.get("action", "save")
        sid = request.form.get("id", "").strip()
        if action == "delete" and sid:
            # Keep payment history: mark inactive instead of deleting the student.
            con.execute("UPDATE students SET active=0 WHERE id=?", (sid,))
            con.commit(); con.close()
            flash("Student Delete; fee history has been preserved.", "success")
            return redirect(url_for("admin_students"))
        name = request.form.get("student_name", "").strip()
        if not name:
            con.close(); flash("Student name is required.", "error")
            return redirect(url_for("admin_students"))
        vals = (name, request.form.get("class_name","").strip(),
                request.form.get("parent_name","").strip(), request.form.get("phone","").strip(),
                request.form.get("address","").strip(), max(0, float(request.form.get("monthly_fee") or 0)),
                request.form.get("admission_date","").strip() or "2026-04-01")
        if sid:
            con.execute("""UPDATE students SET student_name=?,class_name=?,parent_name=?,phone=?,address=?,monthly_fee=?,admission_date=?,active=1 WHERE id=?""", vals+(sid,))
        else:
            cur = con.execute("""INSERT INTO students(student_name,class_name,parent_name,phone,address,monthly_fee,admission_date) VALUES(?,?,?,?,?,?,?)""", vals)
            con.execute("UPDATE students SET student_uid=? WHERE id=?", (f"SVM-{cur.lastrowid:05d}", cur.lastrowid))
        con.commit(); con.close()
        flash("Student record saved.", "success")
        return redirect(url_for("admin_students"))
    students = con.execute("SELECT * FROM students WHERE active=1 ORDER BY id DESC").fetchall()
    editing = con.execute("SELECT * FROM students WHERE id=? AND active=1", (request.args.get("edit", type=int),)).fetchone() if request.args.get("edit", type=int) else None
    con.close()
    return feature_page("students", students=students, editing=editing)

def month_range(start_key, end_key):
    sy, sm = map(int, start_key.split('-')); ey, em = map(int, end_key.split('-'))
    out=[]; y,m=sy,sm
    while (y,m) <= (ey,em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13: y,m=y+1,1
    return out

def academic_months(student, end_month=None):
    start_date = (student['admission_date'] or '2026-04-01')[:7]
    today = date.today()
    end_month = end_month or f"{today.year}-{today.month:02d}"
    if start_date > end_month: return []
    return month_range(start_date, end_month)

def fee_ledger(con, student, end_month=None):
    months = academic_months(student, end_month)
    rows=[]
    for key in months:
        # Legacy records without allocation rows remain assigned to their recorded month.
        legacy = con.execute('''SELECT COALESCE(SUM(p.amount),0) FROM fee_payments p
            WHERE p.student_id=? AND p.fee_month=? AND NOT EXISTS
            (SELECT 1 FROM fee_allocations a WHERE a.payment_id=p.id)''', (student['id'],key)).fetchone()[0]
        allocated = con.execute("SELECT COALESCE(SUM(a.amount),0) FROM fee_allocations a JOIN fee_payments p ON p.id=a.payment_id WHERE p.student_id=? AND a.fee_month=?", (student['id'],key)).fetchone()[0]
        paid = round(float(legacy or 0)+float(allocated or 0),2)
        fee = round(float(student['monthly_fee'] or 0),2)
        rows.append({'key':key,'label':calendar.month_name[int(key[5:7])]+' '+key[:4], 'fee':fee,'paid':paid,'due':max(0,round(fee-paid,2)), 'overpaid':max(0,round(paid-fee,2)),'status':'Paid' if paid>=fee and fee>0 else ('Partially Paid' if paid>0 else 'Unpaid')})
    total_received = con.execute("SELECT COALESCE(SUM(amount),0) FROM fee_payments WHERE student_id=?",(student['id'],)).fetchone()[0]
    allocated_total = con.execute("SELECT COALESCE(SUM(a.amount),0) FROM fee_allocations a JOIN fee_payments p ON p.id=a.payment_id WHERE p.student_id=?",(student['id'],)).fetchone()[0]
    legacy_total = con.execute("SELECT COALESCE(SUM(p.amount),0) FROM fee_payments p WHERE p.student_id=? AND NOT EXISTS (SELECT 1 FROM fee_allocations a WHERE a.payment_id=p.id)",(student['id'],)).fetchone()[0]
    advance = max(0,round(float(total_received or 0)-float(allocated_total or 0)-float(legacy_total or 0),2))
    current_key=f"{date.today().year}-{date.today().month:02d}"
    due_total=sum(x['due'] for x in rows if x['key'] <= current_key)
    return {'months':rows,'total_received':round(float(total_received or 0),2),'due_total':round(due_total,2),'advance':advance,'total_charged':round(sum(x['fee'] for x in rows if x['key'] <= current_key),2)}

@app.route("/admin/fees", methods=["GET", "POST"])
@login_required
def admin_fees():
    con=db()
    if request.method == 'POST':
        try:
            sid=int(request.form.get('student_id','0')); month=request.form.get('fee_month','').strip()
            amount=round(float(request.form.get('amount','0')),2)
            paid_on=request.form.get('paid_on','').strip() or date.today().isoformat()
            method=request.form.get('payment_method','Cash').strip()
            ref=request.form.get('transaction_reference','').strip(); remarks=request.form.get('remarks','').strip()
            st=con.execute('SELECT * FROM students WHERE id=? AND active=1',(sid,)).fetchone()
            if not st or len(month)!=7 or amount<=0 or method not in ('Cash','UPI','Bank Transfer','Other'):
                raise ValueError()
            # Idempotency token stops double-click/replay of the same submitted form.
            token=request.form.get('idempotency_key','').strip()
            if token and con.execute('SELECT id FROM fee_payments WHERE idempotency_key=?',(token,)).fetchone():
                existing=con.execute('SELECT id FROM fee_payments WHERE idempotency_key=?',(token,)).fetchone(); con.close()
                return redirect(url_for('fee_receipt',payment_id=existing['id']))
            con.execute('BEGIN IMMEDIATE')
            end_month=f"{int(settings().get('academic_year_end','2027'))}-03"
            ledger=fee_ledger(con,st,end_month)
            cur=con.execute("INSERT INTO fee_payments(receipt_no,student_id,fee_month,amount,paid_on,note,payment_method,transaction_reference,remarks,idempotency_key) VALUES(NULL,?,?,?,?,?,?,?,?,?)",(sid,month,amount,paid_on,method+' — '+remarks if remarks else method,method,ref,remarks,token))
            pid=cur.lastrowid; receipt=f"FEE-{paid_on.replace('-','')}-{pid:05d}"
            con.execute('UPDATE fee_payments SET receipt_no=? WHERE id=?',(receipt,pid))
            # Apply the new money to oldest outstanding months first; any remainder is advance.
            remaining=amount
            for row in ledger['months']:
                if row['due'] <= 0: continue
                take=min(remaining,row['due'])
                if take>0:
                    con.execute("INSERT INTO fee_allocations(payment_id,fee_month,amount,allocation_type) VALUES(?,?,?,?)",(pid,row['key'],take,'advance_adjustment' if row['key'] > f"{date.today().year}-{date.today().month:02d}" else 'payment'))
                    remaining=round(remaining-take,2)
                if remaining<=0: break
            # If payment month is beyond current computed months, charge months through it.
            if remaining>0:
                existing_months={r['key'] for r in ledger['months']}
                for key in month_range((ledger['months'][-1]['key'] if ledger['months'] else (st['admission_date'] or '2026-04-01')[:7]), month):
                    if key in existing_months: continue
                    fee=round(float(st['monthly_fee'] or 0),2)
                    take=min(remaining,fee)
                    if take>0:
                        con.execute("INSERT INTO fee_allocations(payment_id,fee_month,amount,allocation_type) VALUES(?,?,?,?)",(pid,key,take,'advance_adjustment' if key > f"{date.today().year}-{date.today().month:02d}" else 'payment'))
                        remaining=round(remaining-take,2)
                    if remaining<=0: break
            con.commit(); con.close()
            return redirect(url_for('fee_receipt',payment_id=pid))
        except (ValueError,TypeError,sqlite3.IntegrityError):
            con.rollback(); con.close(); flash('Please select a student and enter a valid amount, date, month and payment method. Duplicate submissions are blocked.','error')
            return redirect(url_for('admin_fees'))
    students=con.execute('SELECT * FROM students WHERE active=1 ORDER BY student_name').fetchall()
    payments=con.execute("SELECT p.*,s.student_name,s.student_uid,s.class_name,s.phone FROM fee_payments p JOIN students s ON s.id=p.student_id ORDER BY p.id DESC LIMIT 200").fetchall()
    end_month=f"{int(settings().get('academic_year_end','2027'))}-03"
    balances=[]
    for st in students:
        led=fee_ledger(con,st,end_month)
        balances.append({'student':st,**led})
    class_totals={}
    for b in balances:
        cls=b['student']['class_name'] or 'Unassigned'
        class_totals[cls]=round(class_totals.get(cls,0)+b['due_total'],2)
    totals={'collected':round(float(con.execute('SELECT COALESCE(SUM(amount),0) FROM fee_payments WHERE amount>0').fetchone()[0]),2),'due':round(sum(b['due_total'] for b in balances),2),'advance':round(sum(b['advance'] for b in balances),2)}
    con.close()
    return feature_page('fees',students=students,payments=payments,balances=balances,totals=totals,class_totals=class_totals,today=date.today().isoformat(),request_token=uuid.uuid4().hex,months=[(f'{y}-{m:02d}',calendar.month_name[m]+' '+str(y)) for y in range(date.today().year-2,date.today().year+3) for m in range(1,13)])

@app.route('/admin/fees/ledger/<int:student_id>')
@login_required
def fee_ledger_page(student_id):
    con=db(); st=con.execute('SELECT * FROM students WHERE id=?',(student_id,)).fetchone()
    if not st:
        con.close(); flash('Student not found.','error'); return redirect(url_for('admin_fees'))
    led=fee_ledger(con,st,f"{int(settings().get('academic_year_end','2027'))}-03")
    payments=con.execute('SELECT * FROM fee_payments WHERE student_id=? ORDER BY paid_on,id',(student_id,)).fetchall()
    allocations=con.execute('SELECT a.*,p.receipt_no,p.paid_on,p.payment_method FROM fee_allocations a JOIN fee_payments p ON p.id=a.payment_id WHERE p.student_id=? ORDER BY a.id',(student_id,)).fetchall()
    con.close(); return feature_page('ledger',student=st,ledger=led,payments=payments,allocations=allocations)

@app.route('/admin/fees/export.csv')
@login_required
def fee_export_csv():
    con=db(); students=con.execute('SELECT * FROM students ORDER BY class_name,student_name').fetchall()
    output=io.StringIO(); writer=csv.writer(output)
    writer.writerow(['Student ID','Student Name','Class','Monthly Fee','Total Received','Total Outstanding','Unused Advance'])
    for st in students:
        led=fee_ledger(con,st,f"{int(settings().get('academic_year_end','2027'))}-03")
        writer.writerow([st['student_uid'],st['student_name'],st['class_name'],st['monthly_fee'],led['total_received'],led['due_total'],led['advance']])
    con.close(); from flask import Response
    return Response('﻿'+output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=school_fee_report.csv'})

@app.route("/admin/fees/receipt/<int:payment_id>")
@login_required
def fee_receipt(payment_id):
    con=db()
    payment=con.execute("""SELECT p.*,s.student_name,s.student_uid,s.class_name,s.parent_name,s.phone FROM fee_payments p JOIN students s ON s.id=p.student_id WHERE p.id=?""",(payment_id,)).fetchone()
    con.close()
    if not payment:
        flash("Receipt not found.", "error"); return redirect(url_for("admin_fees"))
    from urllib.parse import quote
    message=f"Fee receipt {payment['receipt_no']} | {payment['student_name']} ({payment['student_uid']}) | Month: {payment['fee_month']} | Paid: Rs. {payment['amount']:.2f}. Thank you."
    whatsapp="https://wa.me/"+''.join(c for c in (payment["phone"] or "") if c.isdigit())+"?text="+quote(message)
    return feature_page("receipt", payment=payment, whatsapp=whatsapp)

@app.route("/admin/fees/reminders")
@login_required
def fee_reminders():
    con=db(); students=con.execute("SELECT * FROM students WHERE active=1 ORDER BY student_name").fetchall(); rows=[]
    from urllib.parse import quote
    end_month=f"{int(settings().get('academic_year_end','2027'))}-03"
    for st in students:
        led=fee_ledger(con,st,end_month); due=led['due_total']
        msg=f"Dear {st['parent_name'] or 'Parent'}, school fee reminder for {st['student_name']} ({st['student_uid']}). Outstanding fees: Rs. {due:.2f}. Please contact the school office if already paid."
        rows.append({'student':st,'due':due,'wa':'https://wa.me/'+''.join(c for c in (st['phone'] or '') if c.isdigit())+'?text='+quote(msg)})
    con.close(); return feature_page('reminders',reminders=rows)

@app.route("/admin/gallery", methods=["GET","POST"])
@login_required
def admin_gallery():
    con=db()
    if request.method=="POST":
        if request.form.get("action")=="delete":
            con.execute("DELETE FROM gallery WHERE id=?",(request.form.get("id"),))
        else:
            title=request.form.get("title","").strip()
            upload=request.files.get("photo")
            if upload and upload.filename and allowed_file(upload.filename):
                filename=os.urandom(4).hex()+"_"+secure_filename(upload.filename)
                upload.save(os.path.join(UPLOAD_DIR,filename))
                con.execute("INSERT INTO gallery(title,image_path) VALUES(?,?)",(title,"uploads/"+filename))
            else:
                flash("Choose a JPG, PNG, GIF or WEBP image.", "error")
                con.close(); return redirect(url_for("admin_gallery"))
        con.commit(); con.close()
        flash("Gallery updated.", "success"); return redirect(url_for("admin_gallery"))
    photos=con.execute("SELECT * FROM gallery ORDER BY id DESC").fetchall(); con.close()
    return feature_page("gallery", photos=photos)

@app.route("/admin/vans", methods=["GET","POST"])
@login_required
def admin_vans():
    con=db()
    if request.method=="POST":
        if request.form.get("action")=="delete":
            con.execute("DELETE FROM vans WHERE id=?",(request.form.get("id"),))
        else:
            vid=request.form.get("id","").strip()
            vals=(request.form.get("vehicle_no","").strip(),request.form.get("driver_name","").strip(),request.form.get("driver_phone","").strip(),request.form.get("route_name","").strip(),int(request.form.get("capacity") or 0),request.form.get("notes","").strip())
            if vals[0]:
                if vid: con.execute("UPDATE vans SET vehicle_no=?,driver_name=?,driver_phone=?,route_name=?,capacity=?,notes=? WHERE id=?",vals+(vid,))
                else: con.execute("INSERT INTO vans(vehicle_no,driver_name,driver_phone,route_name,capacity,notes) VALUES(?,?,?,?,?,?)",vals)
        con.commit(); con.close(); flash("Van information saved.", "success"); return redirect(url_for("admin_vans"))
    vans=con.execute("SELECT * FROM vans ORDER BY id DESC").fetchall()
    editing=con.execute("SELECT * FROM vans WHERE id=?", (request.args.get("edit", type=int),)).fetchone() if request.args.get("edit", type=int) else None
    con.close()
    return feature_page("vans", vans=vans, editing=editing)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
