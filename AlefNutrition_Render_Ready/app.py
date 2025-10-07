import os
import sqlite3
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, abort, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# -------- Config --------
DATABASE = os.path.join(os.path.dirname(__file__), 'database.db')
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-this')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# -------- Helpers --------
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def current_user():
    uid = session.get('user_id')
    if not uid: return None
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
    conn.close()
    return user

def calculate_tdee(sex, age, height_cm, weight_kg, activity, goal):
    # Mifflin-St Jeor
    if sex == 'M':
        bmr = 10*weight_kg + 6.25*height_cm - 5*age + 5
    else:
        bmr = 10*weight_kg + 6.25*height_cm - 5*age - 161

    factors = {
        'sedentary': 1.2,
        'light': 1.375,
        'moderate': 1.55,
        'active': 1.725,
        'very_active': 1.9
    }
    tdee = bmr * factors.get(activity, 1.2)

    # goal adjustment
    if goal == 'lose': tdee -= 300
    elif goal == 'gain': tdee += 300

    # macros simple split: P 1.8 g/kg, F 30% kcal, rest CHO
    protein_g = round(1.8 * weight_kg, 1)
    fat_kcal = 0.30 * tdee
    fat_g = round(fat_kcal/9, 1)
    protein_kcal = protein_g * 4
    carbs_kcal = max(tdee - (fat_kcal + protein_kcal), 0)
    carbs_g = round(carbs_kcal/4, 1)

    return round(bmr), round(tdee), protein_g, fat_g, carbs_g

def _food_catalog():
    # catálogo simple (puedes ampliarlo luego)
    return {
        "desayuno": [
            {"name":"Avena con leche", "kcal":250, "prot":10, "carb":40, "fat":6},
            {"name":"Huevos revueltos + tortillas", "kcal":300, "prot":18, "carb":20, "fat":14},
            {"name":"Yogur griego + fruta", "kcal":220, "prot":18, "carb":28, "fat":4}
        ],
        "comida": [
            {"name":"Pollo a la plancha + arroz + ensalada", "kcal":600, "prot":40, "carb":65, "fat":16},
            {"name":"Pescado + puré + verduras", "kcal":550, "prot":35, "carb":50, "fat":18},
            {"name":"Carne magra + quinoa + ensalada", "kcal":650, "prot":42, "carb":60, "fat":20}
        ],
        "cena": [
            {"name":"Atún con tostadas + aguacate", "kcal":450, "prot":32, "carb":35, "fat":18},
            {"name":"Tostadas de pollo + pico de gallo", "kcal":420, "prot":30, "carb":40, "fat":12},
            {"name":"Ensalada grande + queso panela", "kcal":380, "prot":24, "carb":30, "fat":14}
        ],
        "snack": [
            {"name":"Fruta + nueces", "kcal":180, "prot":4, "carb":22, "fat":10},
            {"name":"Barra de proteína", "kcal":200, "prot":20, "carb":15, "fat":6},
            {"name":"Galletas de arroz + crema de cacahuate", "kcal":190, "prot":6, "carb":22, "fat":8}
        ]
    }

def build_week_plan(tdee, p_g, f_g, c_g):
    import random
    cat = _food_catalog()
    days = []
    # reparto aproximado de kcal por tiempo
    targets = {"desayuno":0.25, "comida":0.35, "cena":0.25, "snack":0.15}
    for d in range(7):
        day = {}
        for slot in ["desayuno","comida","cena","snack"]:
            target = tdee*targets[slot]
            # elige 1 item y ajusta porciones simple (1.0x, 1.5x, 0.75x)
            item = random.choice(cat[slot]).copy()
            # factor de porción
            factor = max(min(target / max(item["kcal"],1), 1.6), 0.7)
            factor = round(factor,2)
            item["portion"] = factor
            item["kcal"] = round(item["kcal"]*factor)
            item["prot"] = round(item["prot"]*factor)
            item["carb"] = round(item["carb"]*factor)
            item["fat"]  = round(item["fat"]*factor)
            day[slot] = item
        days.append(day)
    totals = {
        "kcal": sum(sum(d[slot]["kcal"] for slot in d) for d in days),
        "prot": sum(sum(d[slot]["prot"] for slot in d) for d in days),
        "carb": sum(sum(d[slot]["carb"] for slot in d) for d in days),
        "fat":  sum(sum(d[slot]["fat"] for slot in d) for d in days)
    }
    return {"days":days, "totals":totals, "tdee":tdee, "p_g":p_g, "f_g":f_g, "c_g":c_g}

# -------- DB Setup --------
def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'patient',
        name TEXT,
        age INTEGER,
        sex TEXT,
        height_cm REAL,
        weight_kg REAL,
        activity TEXT,
        goal TEXT,
        created_at TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS weights(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        weight_kg REAL,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS notes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        content TEXT,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS meals(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        image_path TEXT,
        comment TEXT,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS mealplans(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        plan_json TEXT,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""")
    # seed admin if not exists
    cur.execute("SELECT id FROM users WHERE email=?", ("admin@alefnutrition.com",))
    if not cur.fetchone():
        cur.execute("INSERT INTO users(email, password_hash, role, name, created_at) VALUES (?,?,?,?,?)",
                    ("admin@alefnutrition.com", generate_password_hash("12345"), "admin", "Nut. Jorge Ramos", datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

init_db()

# -------- Routes --------

@app.route('/admin/plan/<int:pid>', methods=['GET','POST'])
def admin_plan(pid):
    user = current_user()
    if not user or user['role'] != 'admin':
        return redirect(url_for('login'))
    conn = get_db()
    p = conn.execute('SELECT * FROM users WHERE id=?', (pid,)).fetchone()
    if not p:
        conn.close(); abort(404)
    # calcular macros actuales
    bmr, tdee, pr, fa, ca = calculate_tdee(p['sex'] or 'F', p['age'] or 0, p['height_cm'] or 0, p['weight_kg'] or 0, p['activity'] or 'sedentary', p['goal'] or 'maintain')
    # POST = generar y guardar
    if request.method == 'POST':
        plan = build_week_plan(tdee, pr, fa, ca)
        conn.execute('DELETE FROM mealplans WHERE user_id=?', (pid,))
        conn.execute('INSERT INTO mealplans(user_id, plan_json, created_at) VALUES (?,?,?)',
                     (pid, json.dumps(plan, ensure_ascii=False), datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()
        flash('Menú semanal generado.', 'ok')
        return redirect(url_for('admin_plan', pid=pid))
    # GET = mostrar si existe
    row = conn.execute('SELECT plan_json, created_at FROM mealplans WHERE user_id=? ORDER BY id DESC LIMIT 1', (pid,)).fetchone()
    conn.close()
    plan = json.loads(row['plan_json']) if row else None
    return render_template('plan.html', who='admin', patient=p, plan=plan, calc={'tdee':tdee,'p':pr,'f':fa,'c':ca})

@app.route('/plan')
def patient_plan():
    u = current_user()
    if not u or u['role']!='patient':
        return redirect(url_for('login'))
    conn = get_db()
    row = conn.execute('SELECT plan_json, created_at FROM mealplans WHERE user_id=? ORDER BY id DESC LIMIT 1', (u['id'],)).fetchone()
    conn.close()
    plan = json.loads(row['plan_json']) if row else None
    # calcular macros del paciente
    bmr, tdee, pr, fa, ca = calculate_tdee(u['sex'] or 'F', u['age'] or 0, u['height_cm'] or 0, u['weight_kg'] or 0, u['activity'] or 'sedentary', u['goal'] or 'maintain')
    return render_template('plan.html', who='patient', patient=u, plan=plan, calc={'tdee':tdee,'p':pr,'f':fa,'c':ca})

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower()
        password = request.form.get('password','')
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            if user['role'] == 'admin':
                return redirect(url_for('admin'))
            return redirect(url_for('dashboard'))
        flash('Credenciales inválidas', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        email = request.form.get('email','').strip().lower()
        password = request.form.get('password','')
        age = int(request.form.get('age') or 0)
        sex = request.form.get('sex','F')
        height_cm = float(request.form.get('height_cm') or 0)
        weight_kg = float(request.form.get('weight_kg') or 0)
        activity = request.form.get('activity','sedentary')
        goal = request.form.get('goal','maintain')
        created_at = datetime.utcnow().isoformat()

        conn = get_db()
        try:
            conn.execute('INSERT INTO users(email,password_hash,role,name,age,sex,height_cm,weight_kg,activity,goal,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                         (email, generate_password_hash(password), 'patient', name, age, sex, height_cm, weight_kg, activity, goal, created_at))
            conn.commit()
        except sqlite3.IntegrityError:
            flash('Ese correo ya está registrado.', 'error')
            conn.close()
            return render_template('register.html')
        # log in
        user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        conn.close()
        session['user_id'] = user['id']
        return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('landing'))

@app.route('/dashboard', methods=['GET','POST'])
def dashboard():
    user = current_user()
    if not user or user['role'] != 'patient':
        return redirect(url_for('login'))

    # weight input
    if request.method == 'POST' and 'weight_entry' in request.form:
        w = float(request.form.get('weight_entry') or 0)
        conn = get_db()
        conn.execute('INSERT INTO weights(user_id, weight_kg, created_at) VALUES (?,?,?)',
                     (user['id'], w, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()
        return redirect(url_for('dashboard'))

    # meals upload
    if request.method == 'POST' and 'meal_photo' in request.files:
        file = request.files['meal_photo']
        comment = request.form.get('meal_comment','')
        if file and allowed_file(file.filename):
            filename = datetime.utcnow().strftime('%Y%m%d%H%M%S') + '_' + secure_filename(file.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(path)
            rel = os.path.join('uploads', filename)
            conn = get_db()
            conn.execute('INSERT INTO meals(user_id, image_path, comment, created_at) VALUES (?,?,?,?)',
                         (user['id'], rel, comment, datetime.utcnow().isoformat()))
            conn.commit()
            conn.close()
            flash('Comida subida correctamente.', 'ok')
        else:
            flash('Archivo no permitido.', 'error')

    # pull data
    conn = get_db()
    weights = conn.execute('SELECT * FROM weights WHERE user_id=? ORDER BY created_at', (user['id'],)).fetchall()
    meals = conn.execute('SELECT * FROM meals WHERE user_id=? ORDER BY created_at DESC LIMIT 12', (user['id'],)).fetchall()
    conn.close()

    # compute tdee/macros
    bmr, tdee, p, f, c = calculate_tdee(user['sex'] or 'F', user['age'] or 0, user['height_cm'] or 0, user['weight_kg'] or 0, user['activity'] or 'sedentary', user['goal'] or 'maintain')

    return render_template('dashboard.html', user=user, weights=weights, meals=meals, calc={'bmr':bmr,'tdee':tdee,'p':p,'f':f,'c':c})

@app.route('/admin', methods=['GET','POST'])
def admin():
    user = current_user()
    if not user or user['role'] != 'admin':
        return redirect(url_for('login'))

    conn = get_db()
    patients = conn.execute("SELECT * FROM users WHERE role='patient' ORDER BY created_at DESC").fetchall()

    # notes add/update
    if request.method == 'POST' and request.form.get('action') == 'add_note':
        pid = int(request.form.get('patient_id'))
        content = request.form.get('content','').strip()
        if content:
            conn.execute('INSERT INTO notes(user_id, content, created_at) VALUES (?,?,?)',
                         (pid, content, datetime.utcnow().isoformat()))
            conn.commit()
        return redirect(url_for('admin'))

    # gather per-patient info
    data = []
    for p in patients:
        ws = conn.execute('SELECT weight_kg, created_at FROM weights WHERE user_id=? ORDER BY created_at', (p['id'],)).fetchall()
        last_w = ws[-1]['weight_kg'] if ws else p['weight_kg']
        notes = conn.execute('SELECT * FROM notes WHERE user_id=? ORDER BY created_at DESC LIMIT 3', (p['id'],)).fetchall()
        meals = conn.execute('SELECT * FROM meals WHERE user_id=? ORDER BY created_at DESC LIMIT 3', (p['id'],)).fetchall()
        bmr, tdee, pr, fa, ca = calculate_tdee(p['sex'] or 'F', p['age'] or 0, p['height_cm'] or 0, last_w or 0, p['activity'] or 'sedentary', p['goal'] or 'maintain')
        data.append({'patient':p, 'weights':ws, 'last_weight':last_w, 'notes':notes, 'meals':meals, 'calc':{'bmr':bmr,'tdee':tdee,'p':pr,'f':fa,'c':ca}})

    conn.close()
    return render_template('admin.html', data=data)

# ---- PDF Export (simple) ----
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm

@app.route('/admin/report/<int:pid>')
def admin_report(pid):
    user = current_user()
    if not user or user['role'] != 'admin':
        return redirect(url_for('login'))
    conn = get_db()
    p = conn.execute('SELECT * FROM users WHERE id=?', (pid,)).fetchone()
    if not p:
        abort(404)
    ws = conn.execute('SELECT weight_kg, created_at FROM weights WHERE user_id=? ORDER BY created_at DESC LIMIT 6', (pid,)).fetchall()
    conn.close()
    bmr, tdee, pr, fa, ca = calculate_tdee(p['sex'] or 'F', p['age'] or 0, p['height_cm'] or 0, p['weight_kg'] or 0, p['activity'] or 'sedentary', p['goal'] or 'maintain')

    filename = f"report_{pid}_{int(datetime.utcnow().timestamp())}.pdf"
    full = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    c = canvas.Canvas(full, pagesize=A4)
    c.setTitle("AlefNutrition Reporte")
    width, height = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(2*cm, height-2*cm, "AlefNutrition – Nut. Jorge Ramos")
    c.setFont("Helvetica", 11)
    c.drawString(2*cm, height-3*cm, f"Paciente: {p['name'] or p['email']}")
    c.drawString(2*cm, height-3.7*cm, f"Edad: {p['age'] or '-'}  Sexo: {p['sex'] or '-'}  Altura: {p['height_cm'] or '-'} cm  Peso: {p['weight_kg'] or '-'} kg")
    c.drawString(2*cm, height-4.4*cm, f"BMR: {bmr} kcal  TDEE: {tdee} kcal  Prot: {pr} g  Grasa: {fa} g  CHO: {ca} g")

    c.setFont("Helvetica-Bold", 12)
    c.drawString(2*cm, height-5.5*cm, "Últimos registros de peso:")
    c.setFont("Helvetica", 11)
    y = height-6.2*cm
    for w in ws:
        c.drawString(2.2*cm, y, f"{w['created_at'][:10]}  —  {w['weight_kg']} kg")
        y -= 0.6*cm

    c.setFont("Helvetica-Oblique", 10)
    c.drawString(2*cm, 2*cm, "Reporte generado automáticamente por AlefNutrition.")
    c.showPage()
    c.save()

    return send_file(full, as_attachment=True, download_name=f"AlefNutrition_{p['name'] or 'paciente'}_reporte.pdf")

# -------- Errors --------
@app.errorhandler(404)
def notfound(e):
    return render_template('404.html'), 404

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    app.run(host=host, port=port, debug=True)
