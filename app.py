"""
app.py
Core Control and Orchestration Module.
The Flask entry point: wires together auth, database and the chatbot
engine, and exposes the web routes / JSON APIs the frontend calls.
"""
import os
from functools import wraps
from werkzeug.utils import secure_filename
import uuid
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, flash, send_file, abort
)

from config import Config
from database import FloxyDatabase
from auth import FloxyAuth
from chatbot import FloxyEngine
from datetime import timedelta
import datetime as dt
import io
from poster import make_poster, THEME_LIST, SIZE_LIST

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY
app.permanent_session_lifetime = timedelta(days=30)

SECURITY_QUESTIONS = [
    "What is your pet's name?",
    "What is your mother's maiden name?",
    "What was the name of your first school?",
    "What is your favorite teacher's name?",
    "What city were you born in?",
]


INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
    "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Delhi", "Jammu and Kashmir", "Ladakh", "Puducherry", "Chandigarh",
]

os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
GENERATED_DIR = os.path.join(Config.UPLOAD_FOLDER, "generated")
os.makedirs(GENERATED_DIR, exist_ok=True)


def _save_generated(data, download_name):
    """Saves a generated PDF/image/ZIP on the server and returns its stored name."""
    stored = f"{uuid.uuid4().hex[:8]}__{download_name}"
    with open(os.path.join(GENERATED_DIR, stored), "wb") as f:
        f.write(data)
    return stored


def _file_info(row):
    stored = row.get("attachment")
    if not stored:
        return None
    name = stored.split("__", 1)[-1]
    low = name.lower()
    return {
        "url": f"/files/{row['id']}",
        "name": name,
        "can_open": not low.endswith(".zip"),
        "is_image": low.endswith((".png", ".jpg", ".jpeg")),
    
    }

db = FloxyDatabase()
db.init_database()
auth_manager = FloxyAuth(db)
ai_engine = FloxyEngine(db)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in Config.ALLOWED_EXTENSIONS


# ----------------------------------------------------------------------
# Auth pages
# ----------------------------------------------------------------------
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("chat"))
    return redirect(url_for("login"))



@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        mobile = request.form.get("mobile", "").strip()
        state = request.form.get("state", "").strip()
        gmail = request.form.get("gmail", "").strip()
        password = request.form.get("password", "")
        security_question = request.form.get("security_question", "").strip()
        security_answer = request.form.get("security_answer", "").strip()

        success, message = auth_manager.register_user(
            name, username, mobile, gmail, password, security_question, security_answer, state
        )
        flash(message, "success" if success else "error")
        if success:
            return redirect(url_for("login"))
        return redirect(url_for("signup"))

    return render_template("signup.html", security_questions=SECURITY_QUESTIONS, states=INDIAN_STATES)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user, message = auth_manager.verify_login(username, password)
        if user:
            session.permanent = True
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["username"] = user["username"]
            return redirect(url_for("chat"))

        flash(message, "error")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        question = auth_manager.get_security_question(username)
        if not question:
            flash("No account found with that username.", "error")
            return redirect(url_for("forgot_password"))
        return render_template("forgot_password.html", username=username, question=question)
    return render_template("forgot_password.html")


@app.route("/reset-password", methods=["POST"])
def reset_password():
    username = request.form.get("username", "").strip()
    answer = request.form.get("security_answer", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    question = auth_manager.get_security_question(username)
    if not question:
        flash("No account found with that username.", "error")
        return redirect(url_for("forgot_password"))

    if not auth_manager.verify_security_answer(username, answer):
        flash("That answer doesn't match our records.", "error")
        return render_template("forgot_password.html", username=username, question=question)

    if new_password != confirm_password:
        flash("New password and confirmation don't match.", "error")
        return render_template("forgot_password.html", username=username, question=question)

    success, message = auth_manager.reset_password(username, new_password)
    flash(message, "success" if success else "error")
    if success:
        return redirect(url_for("login"))
    return render_template("forgot_password.html", username=username, question=question)


# ----------------------------------------------------------------------
# Chat page
# ----------------------------------------------------------------------
@app.route("/chat")
@login_required
def chat():
    history = ai_engine.get_chat_history(session["user_id"])  # today only
    chat_dates = ai_engine.get_chat_dates(session["user_id"])
    active_doc = ai_engine.get_active_document(session["user_id"])
    return render_template(
        "chat.html",
        name=session.get("name"),
        history=history,
        now_date=str(dt.date.today()),
        chat_dates=chat_dates,
        active_doc_name=active_doc["file_name"] if active_doc else None,
        poster_themes=THEME_LIST,
        poster_sizes=SIZE_LIST,
    )
# ----------------------------------------------------------------------
# API history
# ----------------------------------------------------------------------

def _music_links_for(text):
    m = ai_engine.detect_music_request(text)
    return ai_engine.build_music_links(m["query"]) if m and m["query"] else []


@app.route("/api/history")
@login_required
def api_history():
    date = request.args.get("date") or None
    history = ai_engine.get_chat_history(session["user_id"], date=date)
    serializable = [
        {
            "id": h["id"],
            "user_message": h["user_message"],
            "bot_response": h["bot_response"],
            "created_at": h["created_at"].strftime("%Y-%m-%dT%H:%M:%S"),
            "music_links": _music_links_for(h["user_message"]),
            "file": _file_info(h),
        }
        for h in history
    ]
    return jsonify({"history": serializable, "date": date})


@app.route("/files/<int:log_id>")
@login_required
def serve_attachment(log_id):
    stored = ai_engine.get_attachment(session["user_id"], log_id)
    if not stored:
        abort(404)
    path = os.path.join(GENERATED_DIR, os.path.basename(stored))
    if not os.path.isfile(path):
        abort(404)
    return send_file(
        path,
        as_attachment=(request.args.get("dl") == "1"),
        download_name=stored.split("__", 1)[-1],
    )



@app.route("/api/history/<date>", methods=["DELETE"])
@login_required
def api_delete_history(date):
    ai_engine.delete_chat_day(session["user_id"], date)
    return jsonify({"ok": True})


@app.route("/api/export-pdf")
@login_required
def api_export_pdf():
    date = request.args.get("date") or None
    history = ai_engine.get_chat_history(session["user_id"], date=date, limit=500)
    pdf_bytes = ai_engine.generate_chat_pdf(session.get("name", "User"), history, date)
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"floxy_chat_{date or 'today'}.pdf",
    )


@app.route("/api/bookmark", methods=["POST"])
@login_required
def api_add_bookmark():
    data = request.get_json(force=True)
    log_id = data.get("log_id")
    if not log_id:
        return jsonify({"error": "Missing log_id."}), 400
    ai_engine.add_bookmark(session["user_id"], log_id)
    return jsonify({"ok": True})


@app.route("/api/bookmark/<int:log_id>", methods=["DELETE"])
@login_required
def api_remove_bookmark(log_id):
    ai_engine.remove_bookmark(session["user_id"], log_id)
    return jsonify({"ok": True})


@app.route("/api/bookmarks")
@login_required
def api_get_bookmarks():
    bookmarks = ai_engine.get_bookmarks(session["user_id"])
    serializable = [
        {"id": b["id"], "user_message": b["user_message"], "bot_response": b["bot_response"]}
        for b in bookmarks
    ]
    return jsonify({"bookmarks": serializable})


@app.route("/api/bookmark/<int:log_id>/download")
@login_required
def api_download_bookmark(log_id):
    turn = ai_engine.get_log_by_id(session["user_id"], log_id)
    if not turn:
        return jsonify({"error": "Not found"}), 404
    pdf_bytes = ai_engine.generate_chat_pdf(session.get("name", "User"), [turn], date="Bookmark")
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"floxy_bookmark_{log_id}.pdf",
    )

@app.route("/api/bookmark-day", methods=["POST"])
@login_required
def api_bookmark_day():
    data = request.get_json(force=True)
    date = data.get("date")
    if not date:
        return jsonify({"error": "Missing date."}), 400
    bookmarked = ai_engine.toggle_day_bookmark(session["user_id"], date)
    return jsonify({"bookmarked": bookmarked})


@app.route("/api/bookmarked-days")
@login_required
def api_bookmarked_days():
    days = ai_engine.get_bookmarked_days(session["user_id"])
    serializable = [
        {"chat_date": str(d["chat_date"]), "msg_count": d["msg_count"], "title": d["title"]}
        for d in days
    ]
    return jsonify({"days": serializable})

# ----------------------------------------------------------------------
# JSON APIs used by chat.js
# ----------------------------------------------------------------------
@app.route("/api/send", methods=["POST"])
@login_required
def api_send():
    data = request.get_json(force=True)
    text = (data.get("message") or "").strip()
    mode = data.get("mode", "text")

    if not text:
        return jsonify({"error": "Empty message."}), 400

    # "Play a song" requests: show app options instead of asking Gemini
    music = ai_engine.detect_music_request(text)
    if music:
        if music["query"]:
            reply = f'🎵 "{music["query"]}" — kis app pe sunna hai? Neeche se choose karo, wahi app/website khul jayegi.'
            links = ai_engine.build_music_links(music["query"])
        else:
            reply = "Kaun sa gaana sunna hai? Gaane ka naam (aur chaho to singer ka naam) likh do, phir app ke options dikhaunga."
            links = []
        ai_engine.log_search_action(session["user_id"], text, mode)
        log_id = ai_engine.log_chat_interaction(session["user_id"], text, reply)
        return jsonify({"reply": reply, "log_id": log_id, "music_links": links})

    reply, log_id = ai_engine.send_message(session["user_id"], text, search_mode=mode)
    return jsonify({"reply": reply, "log_id": log_id})


@app.route("/api/upload", methods=["POST"])
@login_required
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file received."}), 400

    file = request.files["file"]
    prompt = request.form.get("prompt", "")

    if file.filename == "" or not allowed_file(file.filename):
        return jsonify({"error": "Unsupported file type."}), 400
    filename = secure_filename(file.filename)
    save_path = os.path.join(Config.UPLOAD_FOLDER, f"{session['user_id']}_{filename}")
    file.save(save_path)

    reply, log_id = ai_engine.process_file_upload(session["user_id"], save_path, prompt)
    doc = ai_engine.get_active_document(session["user_id"])
    return jsonify({
        "reply": reply,
        "file_name": filename,
        "active_document": doc["file_name"] if doc else None,
        "log_id": log_id,
    })

@app.route("/api/images-to-pdf", methods=["POST"])
@login_required
def api_images_to_pdf():
    files = request.files.getlist("images")
    if not files:
        return jsonify({"error": "Koi image nahi mili."}), 400
    try:
        pdf_bytes = ai_engine.images_to_pdf(files)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "Images ko PDF mein convert nahi kar paaye. Dusri image try karo."}), 500

    stored = _save_generated(pdf_bytes, "floxy_images.pdf")
    ai_engine.log_chat_interaction(
        session["user_id"],
        f"[Images to PDF: {len(files)} image(s)]",
        f"{len(files)} image(s) ka PDF ban gaya.",
        attachment=stored,
    )
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="floxy_images.pdf",
    )
@app.route("/api/pdf-to-images", methods=["POST"])
@login_required
def api_pdf_to_images():
    file = request.files.get("pdf")
    fmt = (request.form.get("format") or "png").lower()
    if not file or not (file.filename or "").lower().endswith(".pdf"):
        return jsonify({"error": "Sirf PDF file chalegi."}), 400

    try:
        data, mimetype, ext, pages = ai_engine.pdf_to_images(file, fmt)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "PDF ko image mein convert nahi kar paaye. Dusri PDF try karo."}), 500

    base = secure_filename(os.path.splitext(file.filename)[0]) or "floxy"
    download_name = f"{base}_images.zip" if ext == "zip" else f"{base}.{ext}"

    stored = _save_generated(data, download_name)
    ai_engine.log_chat_interaction(
        session["user_id"],
        f"[PDF to image: {file.filename}]",
        f"{pages} page(s) ki image ban gayi.",
        attachment=stored,
    )
    resp = send_file(io.BytesIO(data), mimetype=mimetype, as_attachment=True, download_name=download_name)
    resp.headers["X-Page-Count"] = str(pages)
    return resp

@app.route("/api/poster", methods=["POST"])
@login_required
def api_poster():
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "Poster ka title zaroori hai."}), 400

    fmt = "pdf" if data.get("format") == "pdf" else "png"
    try:
        file_bytes, ext = make_poster(data, fmt)
    except Exception:
        return jsonify({"error": "Poster nahi ban paya. Text thoda chhota karke dobara try karo."}), 500

    base = secure_filename(title)[:40] or "poster"
    stored = _save_generated(file_bytes, f"{base}_poster.{ext}")
    reply = f'🎨 "{title[:60]}" ka poster ready hai.'
    log_id = ai_engine.log_chat_interaction(
        session["user_id"], f"[Poster: {title[:80]}]", reply, attachment=stored
    )
    return jsonify({"reply": reply, "file": _file_info({"id": log_id, "attachment": stored})})

@app.route("/api/clear-document", methods=["POST"])
@login_required
def api_clear_document():
    ai_engine.clear_active_document(session["user_id"])
    return jsonify({"ok": True})


@app.route("/api/suggest", methods=["POST"])
@login_required
def api_suggest():
    data = request.get_json(force=True)
    partial = data.get("partial", "")
    suggestions = ai_engine.get_live_suggestions(partial)
    return jsonify({"suggestions": suggestions})


if __name__ == "__main__":
    app.run(debug=True, port=5000 , threaded=True)
