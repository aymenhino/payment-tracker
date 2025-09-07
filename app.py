from flask import Flask, render_template, request, redirect, url_for, send_from_directory, Response, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.utils import secure_filename
import os, csv

app = Flask(__name__)
app.secret_key = "super-secret-key"   # ⚠️ change to something long/random
ACCESS_CODE = "2468"                  # 🔑 set your access code here

# --- Config ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "payments.db")

print(">>> Using database at:", DB_PATH)

app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, "uploads")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db = SQLAlchemy(app)

# --- Model ---
class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    recipient = db.Column(db.String(100), nullable=False)
    date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.String(300))
    receipt = db.Column(db.String(200))

# --- Auth Middleware ---
@app.before_request
def require_login():
    open_routes = ["login", "static"]
    if not session.get("authenticated") and request.endpoint not in open_routes:
        return redirect(url_for("login"))

# --- Login ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        code = request.form.get("code")
        if code == ACCESS_CODE:
            session["authenticated"] = True
            return redirect(url_for("index"))
        else:
            return render_template("login.html", error="❌ Wrong code")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# --- Helpers ---
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in {"png", "jpg", "jpeg", "gif", "pdf"}

def save_receipt(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        return None
    safe = secure_filename(file_storage.filename)
    filename = f"{int(datetime.utcnow().timestamp())}_{safe}"
    file_storage.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    return filename

@app.context_processor
def inject_year():
    return {"year": datetime.utcnow().year}

# --- Routes ---
@app.route("/")
def index():
    q = (request.args.get("q") or "").strip().lower()
    payments = Payment.query.order_by(Payment.date.desc(), Payment.id.desc()).all()
    if q:
        payments = [
            p for p in payments
            if q in p.recipient.lower()
            or q in (p.notes or "").lower()
            or q in p.date.isoformat()
        ]
    total = sum(p.amount for p in payments) if payments else 0
    return render_template("index.html", payments=payments, total=total, q=q)

@app.route("/add", methods=["POST"])
def add_payment():
    amount = float(request.form["amount"])
    recipient = request.form["recipient"].strip()
    date = datetime.strptime(request.form["date"], "%Y-%m-%d").date()
    notes = request.form.get("notes", "").strip()

    filename = None
    file = request.files.get("receipt")
    if file:
        filename = save_receipt(file)

    p = Payment(amount=amount, recipient=recipient, date=date, notes=notes, receipt=filename)
    db.session.add(p)
    db.session.commit()
    return redirect(url_for("index"))

@app.route("/edit/<int:pid>", methods=["GET", "POST"])
def edit_payment(pid):
    p = Payment.query.get_or_404(pid)
    if request.method == "POST":
        p.amount = float(request.form["amount"])
        p.recipient = request.form["recipient"].strip()
        p.date = datetime.strptime(request.form["date"], "%Y-%m-%d").date()
        p.notes = request.form.get("notes", "").strip()

        file = request.files.get("receipt")
        if file and file.filename:
            if p.receipt:
                try:
                    os.remove(os.path.join(app.config["UPLOAD_FOLDER"], p.receipt))
                except OSError:
                    pass
            new_name = save_receipt(file)
            if new_name:
                p.receipt = new_name

        db.session.commit()
        return redirect(url_for("index"))
    return render_template("edit.html", payment=p)

@app.route("/delete/<int:pid>", methods=["POST"])
def delete_payment(pid):
    p = Payment.query.get_or_404(pid)
    if p.receipt:
        try:
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"], p.receipt))
        except OSError:
            pass
    db.session.delete(p)
    db.session.commit()
    return redirect(url_for("index"))

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.route("/export/csv")
def export_csv():
    payments = Payment.query.order_by(Payment.date.desc(), Payment.id.desc()).all()
    def generate():
        yield "Amount,Recipient,Date,Notes,Receipt\n"
        for p in payments:
            row = [
                f"{p.amount:.2f}",
                p.recipient.replace(",", " "),
                p.date.isoformat(),
                (p.notes or "").replace(",", " "),
                p.receipt or ""
            ]
            yield ",".join(row) + "\n"
    return Response(generate(),
                    mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=payments.csv"})

# --- Run ---
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=5000)
