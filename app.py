from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from fpdf import FPDF
from dotenv import load_dotenv
from io import BytesIO

# -------------------------
# Load environment
# -------------------------
load_dotenv()

# -------------------------
# Flask Setup
# -------------------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersecretkey")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_DIR = os.path.join(BASE_DIR, "instance")
DB_PATH = os.path.join(DB_DIR, "notes.db")
os.makedirs(DB_DIR, exist_ok=True)

# -------------------------
# Optional OpenAI / OpenRouter client
# -------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")

try:
    # New OpenAI python client exposes OpenAI class
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except Exception:
    OpenAI = None
    OPENAI_AVAILABLE = False

client = None
if OPENAI_AVAILABLE and OPENAI_API_KEY:
    # Some OpenAI client constructors do not accept api_base as a constructor arg.
    # Set the base URL via environment variable first (OpenRouter compatibility),
    # then instantiate the client with the API key only.
    os.environ.setdefault("OPENAI_API_BASE", OPENAI_BASE_URL)
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
    except TypeError:
        # Fallback: try without named arg (older/newer client variations)
        try:
            client = OpenAI(OPENAI_API_KEY)
        except Exception:
            client = None

# -------------------------
# Database helpers
# -------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL
                )""")
    c.execute("""CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    pinned INTEGER DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )""")
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

init_db()

# -------------------------
# AI Helper (OpenAI/OpenRouter with fallback)
# -------------------------
def _rule_based_suggestion(text: str) -> str:
    t = (text or "").lower()
    if "exam" in t or "study" in t:
        return "📘 Suggestion: Break your study into a timetable and focus on key topics."
    if "important" in t or "urgent" in t:
        return "📌 Suggestion: Mark this note as important and pin it for quick access."
    if len(t) > 300:
        return "✂️ Suggestion: This note is long — consider splitting into headings or bullet points."
    if "meeting" in t or "call" in t:
        return "🕒 Suggestion: Add date/time and action items for the meeting."
    if "task" in t or "todo" in t or "to-do" in t:
        return "✅ Suggestion: Convert this into a checklist to track progress."
    return "💡 Suggestion: Keep your notes concise and add clear next steps."

def ai_generate_suggestion(note_content: str) -> str:
    """
    Try to get a suggestion from OpenAI/OpenRouter. If that fails (no key, client error, quota),
    fall back to a simple rule-based suggestion.
    """
    if not note_content:
        return "💡 Suggestion: Add some content to get tailored suggestions."

    if client:
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that gives concise, actionable suggestions for user notes."},
                    {"role": "user", "content": f"Analyze this note and provide 1-2 concise suggestions or actions the user can take:\n\n{note_content}"}
                ],
                max_tokens=150,
                temperature=0.6
            )
            # Parse common response shapes
            if hasattr(resp, "choices") and len(resp.choices) > 0:
                choice = resp.choices[0]
                # OpenAI-style: choice.message.content
                if hasattr(choice, "message") and getattr(choice.message, "content", None):
                    return choice.message.content.strip()
                # Some clients return dict-like structures
                if isinstance(choice, dict):
                    if "message" in choice and isinstance(choice["message"], dict) and "content" in choice["message"]:
                        return choice["message"]["content"].strip()
                    if "text" in choice:
                        return choice["text"].strip()
                # Fallback to string attributes
                if hasattr(choice, "text"):
                    return choice.text.strip()
        except Exception as e:
            # Return rule-based suggestion with a short note (keeps UX friendly)
            fallback = _rule_based_suggestion(note_content)
            return f"{fallback} (AI unavailable: {str(e)})"

    return _rule_based_suggestion(note_content)

# -------------------------
# Routes
# -------------------------
@app.route("/")
def home():
    return render_template("home.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password_raw = request.form.get("password", "")
        if not username or not email or not password_raw:
            flash("Please fill all fields.", "danger")
            return redirect(url_for("register"))

        password = generate_password_hash(password_raw)
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                (username, email, password)
            )
            conn.commit()
            flash("Registration successful! Please login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username or Email already exists!", "danger")
        finally:
            conn.close()
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            flash("Logged in successfully.", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid credentials!", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for("home"))

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db()
    notes = conn.execute(
        "SELECT * FROM notes WHERE user_id=? ORDER BY pinned DESC, created_at DESC",
        (session["user_id"],)
    ).fetchall()
    conn.close()
    return render_template("dashboard.html", notes=notes)

@app.route("/note/add", methods=["GET", "POST"])
def add_note():
    if "user_id" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        title = request.form.get("title", "").strip() or "Untitled"
        content = request.form.get("content", "").strip()
        pinned = 1 if request.form.get("pinned") else 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db()
        conn.execute(
            "INSERT INTO notes (user_id, title, content, pinned, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (session["user_id"], title, content, pinned, now, now)
        )
        conn.commit()
        conn.close()
        flash("Note added successfully!", "success")
        return redirect(url_for("dashboard"))
    return render_template("note_form.html", action="Add", note=None, ai_suggestion=None)

@app.route("/note/edit/<int:id>", methods=["GET", "POST"])
def edit_note(id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    note = conn.execute("SELECT * FROM notes WHERE id=? AND user_id=?", (id, session["user_id"])).fetchone()
    if not note:
        conn.close()
        flash("Note not found!", "danger")
        return redirect(url_for("dashboard"))

    ai_suggestion = None

    if request.method == "POST":
        title = request.form.get("title", "").strip() or "Untitled"
        content = request.form.get("content", "").strip()
        pinned = 1 if request.form.get("pinned") else 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE notes SET title=?, content=?, pinned=?, updated_at=? WHERE id=?",
            (title, content, pinned, now, id)
        )
        conn.commit()
        conn.close()

        ai_suggestion = ai_generate_suggestion(content)
        updated_note = (id, session["user_id"], title, content, pinned, now, now)
        return render_template("note_form.html", action="Edit", note=updated_note, ai_suggestion=ai_suggestion)

    conn.close()
    ai_suggestion = ai_generate_suggestion(note["content"])
    return render_template("note_form.html", action="Edit", note=note, ai_suggestion=ai_suggestion)

@app.route("/note/delete/<int:id>", methods=["POST", "GET"])
def delete_note(id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db()
    conn.execute("DELETE FROM notes WHERE id=? AND user_id=?", (id, session["user_id"]))
    conn.commit()
    conn.close()
    flash("Note deleted successfully!", "info")
    return redirect(url_for("dashboard"))

@app.route("/note/download/<int:id>")
def download_note(id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db()
    note = conn.execute("SELECT * FROM notes WHERE id=? AND user_id=?", (id, session["user_id"])).fetchone()
    conn.close()
    if not note:
        flash("Note not found!", "danger")
        return redirect(url_for("dashboard"))

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, txt=note["title"], ln=True, align="C")
    pdf.ln(4)
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(0, 8, txt=note["content"])

    pdf_bytes = pdf.output(dest="S").encode("latin-1")
    buffer = BytesIO(pdf_bytes)
    buffer.seek(0)
    filename = f"note_{note['id']}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")

@app.route("/analytics")
def analytics():
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db()
    total_notes = conn.execute("SELECT COUNT(*) FROM notes WHERE user_id=?", (session["user_id"],)).fetchone()[0]
    pinned_notes = conn.execute("SELECT COUNT(*) FROM notes WHERE user_id=? AND pinned=1", (session["user_id"],)).fetchone()[0]
    conn.close()
    return render_template("analytics.html", total_notes=total_notes, pinned_notes=pinned_notes)

@app.route("/settings", methods=["GET", "POST"])
def settings():
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    if request.method == "POST":
        username = request.form.get("username", user["username"]).strip()
        email = request.form.get("email", user["email"]).strip()
        password = request.form.get("password", None)
        theme = request.form.get("theme", None)

        if password:
            hashed = generate_password_hash(password)
        else:
            hashed = user["password"]

        try:
            conn.execute(
                "UPDATE users SET username=?, email=?, password=? WHERE id=?",
                (username, email, hashed, session["user_id"])
            )
            conn.commit()
            flash("Account updated successfully!", "success")
        except sqlite3.IntegrityError:
            flash("Username or Email already in use.", "danger")

        if theme:
            session["theme"] = theme
            flash(f"Theme changed to {theme}", "success")

        conn.close()
        return redirect(url_for("settings"))

    conn.close()
    return render_template("settings.html", user=user)

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    app.run(debug=True)
