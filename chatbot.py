"""
chatbot.py
Multi-Modal Intelligence and Synthesis Module.
Talks to the Gemini API, extracts text from uploaded PDFs/DOCX/images,
enforces a daily call quota per user, and logs every turn to MySQL.
"""
import os
import re
import io
import datetime
import docx2txt
from pypdf import PdfReader
import google.generativeai as genai
from PIL import Image
from PIL import Image, ImageOps

from config import Config
from psycopg2.extras import RealDictCursor

class FloxyEngine:
    def __init__(self, db_instance):
        self.db = db_instance
        genai.configure(api_key=Config.GEMINI_API_KEY, transport="rest")
        self.model = genai.GenerativeModel(
        Config.GEMINI_MODEL,
        generation_config={"max_output_tokens": 1024},
        )

    # ------------------------------------------------------------------
    # Daily quota
    # ------------------------------------------------------------------
    def check_and_increment_quota(self, user_id):
        """Returns (allowed: bool, calls_used_today: int)."""
        today = datetime.date.today()
        conn = self.db.get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM api_logs WHERE user_id = %s", (user_id,))
        row = cur.fetchone()

        if row is None:
            cur.execute(
                "INSERT INTO api_logs (user_id, api_calls_count, last_call_date) "
                "VALUES (%s, 1, %s)",
                (user_id, today),
            )
            conn.commit()
            cur.close(); conn.close()
            return True, 1

        if row["last_call_date"] != today:
            # new day -> reset counter
            cur.execute(
                "UPDATE api_logs SET api_calls_count = 1, last_call_date = %s "
                "WHERE user_id = %s",
                (today, user_id),
            )
            conn.commit()
            cur.close(); conn.close()
            return True, 1

        if row["api_calls_count"] >= Config.DAILY_API_LIMIT:
            cur.close(); conn.close()
            return False, row["api_calls_count"]

        cur.execute(
            "UPDATE api_logs SET api_calls_count = api_calls_count + 1 WHERE user_id = %s",
            (user_id,),
        )
        conn.commit()
        cur.close(); conn.close()
        return True, row["api_calls_count"] + 1

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------
    def log_search_action(self, user_id, text, mode="text"):
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO search_history (user_id, search_text, search_mode) VALUES (%s, %s, %s)",
            (user_id, text, mode),
        )
        conn.commit(); cur.close(); conn.close()


    def log_chat_interaction(self, user_id, user_message, bot_response, attachment=None):
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO chatbot_logs (user_id, user_message, bot_response, attachment) "
            "VALUES (%s, %s, %s, %s)",
            (user_id, user_message, bot_response, attachment),
        )
        conn.commit()
        new_id = cur.lastrowid
        cur.close(); conn.close()
        return new_id
    
    def get_chat_history(self, user_id, limit=50, date=None):
        conn = self.db.get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if date:
            cur.execute(
                "SELECT id, user_message, bot_response, attachment, created_at FROM chatbot_logs "
                "WHERE user_id = %s AND DATE(created_at) = %s ORDER BY id ASC LIMIT %s",
                (user_id, date, limit),
            )
        else:
            cur.execute(
                "SELECT id, user_message, bot_response, attachment, created_at FROM chatbot_logs "
                "WHERE user_id = %s AND DATE(created_at) = CURDATE() ORDER BY id ASC LIMIT %s",
                (user_id, limit),
            )
        rows = cur.fetchall()
        cur.close(); conn.close()
        return rows
    
    _TRIVIAL = {"hi", "hii", "hiii", "hello", "hey", "hlo", "hola", "ok", "okay", "thanks", "thank you",
                "thik hai", "theek hai", "good", "yes", "no", "namaste", "test", "testing"}

    @staticmethod
    def _shorten(s, n=30):
        s = s.strip()
        if len(s) <= n:
            return s
        cut = s[:n]
        if " " in cut[15:]:
            cut = cut[:cut.rfind(" ")]
        return cut.rstrip(" ,.-:;") + "…"

    @classmethod
    def _make_title(cls, msg):
        """Short heading for a chat message (no AI used, so no quota)."""
        text = " ".join((msg or "").split())
        if not text:
            return ""
        m = re.match(r"^\[Uploaded file: (.+?)\]", text)
        if m:
            name = re.sub(r"^\d+_", "", m.group(1)).replace("_", " ")
            return "📎 " + cls._shorten(name)
        m = re.match(r"^\[Poster: (.+?)\]$", text)
        if m:
            return "🎨 " + cls._shorten(m.group(1))
        if text.startswith("[Images to PDF"):
            return "🖼️ Images to PDF"
        if re.match(r"^\[PDF to image: (.+?)\]$", text):
            return "📄 PDF to image"
        return cls._shorten(text[0].upper() + text[1:])

    @classmethod
    def _is_trivial(cls, msg):
        t = re.sub(r"[^\w\s]", "", (msg or "").lower()).strip()
        return len(t) < 4 or t in cls._TRIVIAL

    def _day_titles(self, user_id):
        """{date: heading} for every day this user has chatted. The heading comes from the
        first real question of that day (greetings like 'hi' are skipped)."""
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT DATE(created_at), LEFT(user_message, 200) FROM chatbot_logs "
            "WHERE user_id = %s ORDER BY id ASC",
            (user_id,),
        )
        first_any, good = {}, {}
        for day, msg in cur.fetchall():
            if not (msg or "").strip():
                continue
            first_any.setdefault(day, msg)
            if day not in good and not self._is_trivial(msg):
                good[day] = msg
        cur.close(); conn.close()
        return {day: (self._make_title(good.get(day) or first_any[day]) or "Chat") for day in first_any}

    def get_chat_dates(self, user_id):
        """Every date this user has chatted on (newest first) with a heading, message count
        and whether that day is bookmarked."""
        conn = self.db.get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT DATE(c.created_at) AS chat_date, COUNT(*) AS msg_count, "
            "MAX(CASE WHEN bd.id IS NOT NULL THEN 1 ELSE 0 END) AS is_bookmarked "
            "FROM chatbot_logs c "
            "LEFT JOIN bookmarked_days bd ON bd.user_id = c.user_id AND bd.chat_date = DATE(c.created_at) "
            "WHERE c.user_id = %s "
            "GROUP BY DATE(c.created_at) ORDER BY chat_date DESC",
            (user_id,),
        )
        rows = cur.fetchall()
        cur.close(); conn.close()
        titles = self._day_titles(user_id)
        for r in rows:
            r["title"] = titles.get(r["chat_date"], "Chat")
        return rows



    def delete_chat_day(self, user_id, date):
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT attachment FROM chatbot_logs "
            "WHERE user_id = %s AND DATE(created_at) = %s AND attachment IS NOT NULL",
            (user_id, date),
        )
        for (stored,) in cur.fetchall():
            try:
                os.remove(os.path.join(Config.UPLOAD_FOLDER, "generated", os.path.basename(stored)))
            except OSError:
                pass
        cur.execute("DELETE FROM chatbot_logs WHERE user_id = %s AND DATE(created_at) = %s", (user_id, date))
        cur.execute("DELETE FROM search_history WHERE user_id = %s AND DATE(created_at) = %s", (user_id, date))
        cur.execute("DELETE FROM bookmarked_days WHERE user_id = %s AND chat_date = %s", (user_id, date))
        conn.commit(); cur.close(); conn.close()

    def get_attachment(self, user_id, log_id):
        """Stored file name for this user's chat message, or None."""
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT attachment FROM chatbot_logs WHERE id = %s AND user_id = %s",
            (log_id, user_id),
        )
        row = cur.fetchone()
        cur.close(); conn.close()
        return row[0] if row and row[0] else None
    
    def add_bookmark(self, user_id, log_id):
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT IGNORE INTO bookmarked_chats (user_id, log_id) VALUES (%s, %s)",
            (user_id, log_id),
        )
        conn.commit(); cur.close(); conn.close()

    def remove_bookmark(self, user_id, log_id):
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM bookmarked_chats WHERE user_id = %s AND log_id = %s", (user_id, log_id))
        conn.commit(); cur.close(); conn.close()

    def get_bookmarks(self, user_id):
        conn = self.db.get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT c.id, c.user_message, c.bot_response FROM bookmarked_chats b "
            "JOIN chatbot_logs c ON b.log_id = c.id "
            "WHERE b.user_id = %s ORDER BY b.saved_at DESC",
            (user_id,),
        )
        rows = cur.fetchall()
        cur.close(); conn.close()
        return rows


    def toggle_day_bookmark(self, user_id, date):
        """Returns True if now bookmarked, False if removed."""
        conn = self.db.get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id FROM bookmarked_days WHERE user_id = %s AND chat_date = %s", (user_id, date))
        row = cur.fetchone()
        if row:
            cur.execute("DELETE FROM bookmarked_days WHERE id = %s", (row["id"],))
            conn.commit(); cur.close(); conn.close()
            return False
        cur.execute("INSERT INTO bookmarked_days (user_id, chat_date) VALUES (%s, %s)", (user_id, date))
        conn.commit(); cur.close(); conn.close()
        return True

    def get_bookmarked_days(self, user_id):
        conn = self.db.get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT bd.chat_date, COUNT(c.id) AS msg_count FROM bookmarked_days bd "
            "LEFT JOIN chatbot_logs c ON c.user_id = bd.user_id AND DATE(c.created_at) = bd.chat_date "
            "WHERE bd.user_id = %s GROUP BY bd.chat_date ORDER BY bd.chat_date DESC",
            (user_id,),
        )
        rows = cur.fetchall()
        cur.close(); conn.close()
        titles = self._day_titles(user_id)
        for r in rows:
            r["title"] = titles.get(r["chat_date"], "Chat")
        return rows
    
    def get_log_by_id(self, user_id, log_id):
        conn = self.db.get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT id, user_message, bot_response FROM chatbot_logs WHERE id = %s AND user_id = %s",
            (log_id, user_id),
        )
        row = cur.fetchone()
        cur.close(); conn.close()
        return row

    def images_to_pdf(self, file_storages):
        """Joins the uploaded images (in the order given) into one PDF, one image per A4 page."""
        if not file_storages:
            raise ValueError("Koi image nahi mili.")
        if len(file_storages) > 20:
            raise ValueError("Ek baar mein maximum 20 images chalengi.")

        A4_W, A4_H, MARGIN = 1240, 1754, 60   # A4 at 150 DPI
        pages = []
        for fs in file_storages:
            name = (fs.filename or "").lower()
            if not name.endswith((".png", ".jpg", ".jpeg", ".webp")):
                raise ValueError(f"'{fs.filename}' image file nahi hai. Sirf PNG, JPG ya WEBP chalegi.")

            img = Image.open(fs.stream)
            img = ImageOps.exif_transpose(img)  # phone photos ki sahi direction
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.split()[-1])
                img = flat
            else:
                img = img.convert("RGB")

            # landscape photo -> landscape page, otherwise portrait page
            page_w, page_h = (A4_H, A4_W) if img.width > img.height else (A4_W, A4_H)
            img = ImageOps.contain(img, (page_w - 2 * MARGIN, page_h - 2 * MARGIN))
            page = Image.new("RGB", (page_w, page_h), (255, 255, 255))
            page.paste(img, ((page_w - img.width) // 2, (page_h - img.height) // 2))
            pages.append(page)

        buf = io.BytesIO()
        pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:], resolution=150.0)
        return buf.getvalue()

    def pdf_to_images(self, file_storage, fmt="png"):
        """Renders every page of a PDF as an image. One page gives a single image,
        several pages give one ZIP. Returns (bytes, mimetype, extension, page_count)."""
        import zipfile
        import fitz  # PyMuPDF

        fmt = "jpg" if fmt in ("jpg", "jpeg") else "png"
        try:
            doc = fitz.open(stream=file_storage.read(), filetype="pdf")
        except Exception:
            raise ValueError("Ye PDF khul nahi payi. File kharab ho sakti hai.")

        try:
            if doc.needs_pass:
                raise ValueError("Ye PDF password se protected hai.")
            total = doc.page_count
            if total == 0:
                raise ValueError("PDF mein koi page nahi mila.")
            if total > 30:
                raise ValueError(f"PDF mein {total} pages hain. Ek baar mein maximum 30 pages chalenge.")

            zoom = fitz.Matrix(150 / 72, 150 / 72)   # 150 DPI
            images = []
            for page in doc:
                pix = page.get_pixmap(matrix=zoom, alpha=False)
                if fmt == "jpg":
                    images.append(pix.tobytes("jpeg", jpg_quality=90))
                else:
                    images.append(pix.tobytes("png"))
        finally:
            doc.close()

        mimetype = "image/jpeg" if fmt == "jpg" else "image/png"
        if len(images) == 1:
            return images[0], mimetype, fmt, 1

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
            for i, data in enumerate(images, start=1):
                z.writestr(f"page_{i:03d}.{fmt}", data)
        return buf.getvalue(), "application/zip", "zip", len(images)
    
    @staticmethod
    def detect_music_request(text):
        """Returns None if this isn't a 'play a song' request, otherwise
        {'query': '<song name>'} (query is '' when no song name was given)."""
        t = (text or "").strip()
        if not t or len(t) > 200:
            return None
        low = t.lower()

        has_trigger = re.search(
            r"\b(play|bajao|bajado|baja|sunao|suna|sunna|sunni|sunana|chalao|chala|lagao|laga|listen|hear)\b", low)
        has_music_word = re.search(r"\b(song|songs|gaana|gana|gaane|gane|music|track)\b", low)
        if not (has_trigger and has_music_word):
            return None

        q = low
        q = re.sub(r"\b(baja|suna|chala|laga)\s+(do|de|dijiye|dena)\b", " ", q)
        q = re.sub(r"\b(sunna|sunni|sunana)\s+(hai|h|he)\b", " ", q)
        q = re.sub(r"\b(i\s+(want|wanna|would like|wish)(\s+to)?|can you|could you|will you|listen to)\b", " ", q)
        q = re.sub(
            r"\b(play|bajao|bajado|baja|sunao|suna|sunna|sunni|sunana|chalao|chala|lagao|laga|"
            r"listen|hear|song|songs|gaana|gana|gaane|gane|music|track|please|pls|plz)\b", " ", q)
        q = re.sub(r"[^\w\s'&\-]", " ", q)

        words = q.split()
        lead = {"a", "an", "the", "ek", "mujhe", "mere", "meri", "mera", "liye", "for", "me", "to", "koi", "some", "any", "kuch"}
        trail = {"do", "de", "dena", "hai", "h", "he", "kar", "karo", "ko", "on", "wala", "wali", "vala"}
        while words and words[0] in lead:
            words.pop(0)
        while words and words[-1] in trail:
            words.pop()
        return {"query": " ".join(words)}

    @staticmethod
    def build_music_links(query):
        """Search links for the song on the popular music apps/sites."""
        from urllib.parse import quote, quote_plus
        qp = quote_plus(query)
        qs = quote(query)
        return [
            {"name": "YouTube Music", "icon": "🎵", "url": f"https://music.youtube.com/search?q={qp}"},
            {"name": "YouTube", "icon": "▶️", "url": f"https://www.youtube.com/results?search_query={qp}"},
            {"name": "Spotify", "icon": "🟢", "url": f"https://open.spotify.com/search/{qs}"},
            {"name": "JioSaavn", "icon": "🎧", "url": f"https://www.jiosaavn.com/search/{qs}"},
            {"name": "Gaana", "icon": "🎶", "url": f"https://gaana.com/search/{qs}"},
            {"name": "Apple Music", "icon": "🍎", "url": f"https://music.apple.com/in/search?term={qp}"},
            {"name": "Amazon Music", "icon": "📦", "url": f"https://music.amazon.in/search/{qs}"},
        ]
    @staticmethod
    def _pdf_safe(text):
        """Helvetica (core PDF font) only supports Latin-1. Replace anything
        it can't render (Hindi/Devanagari, emoji, etc.) so PDF export never crashes."""
        if not text:
            return ""
        return text.encode("latin-1", errors="replace").decode("latin-1")

    
    @staticmethod
    def _wrap_long_tokens(text, max_len=50):
        """Breaks any single unbroken word/URL longer than max_len characters
        into chunks, so fpdf's multi_cell always has somewhere to wrap."""
        def break_token(match):
            token = match.group(0)
            if len(token) <= max_len:
                return token
            return " ".join(token[i:i + max_len] for i in range(0, len(token), max_len))
        return re.sub(r"\S+", break_token, text)

    def generate_chat_pdf(self, user_name, history, date=None):
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, self._pdf_safe("Floxy Chat Export"),
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 8, self._pdf_safe(f"User: {user_name}  |  Date: {date or 'Today'}"),
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(4)

        for turn in history:
            try:
                pdf.set_font("Helvetica", "B", 11)
                pdf.multi_cell(0, 7, self._wrap_long_tokens(self._pdf_safe(f"You: {turn['user_message']}"), max_len=30),
                                new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_font("Helvetica", "", 11)
                pdf.multi_cell(0, 7, self._wrap_long_tokens(self._pdf_safe(f"Floxy: {turn['bot_response']}"), max_len=30),
                                new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.ln(3)
            except Exception as e:
                pdf.set_x(pdf.l_margin)
                try:
                    pdf.multi_cell(0, 7, self._pdf_safe(f"[ERROR: {str(e)[:150]}]"),
                                    new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                except Exception:
                    pass
                pdf.ln(3)

        return bytes(pdf.output())
    
    # ------------------------------------------------------------------
    # Persistent "active document" knowledge base
    # ------------------------------------------------------------------
    def save_active_document(self, user_id, file_name, content):
        """Upserts this user's active document so future chat turns can reference it."""
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO knowledge_base (user_id, file_name, content)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE file_name = VALUES(file_name), content = VALUES(content)
            """,
            (user_id, file_name, content[:8000]),  # safety cap per document
        )
        conn.commit(); cur.close(); conn.close()

    def get_active_document(self, user_id):
        conn = self.db.get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT file_name, content FROM knowledge_base WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        cur.close(); conn.close()
        return row  # dict with file_name/content, or None

    def clear_active_document(self, user_id):
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM knowledge_base WHERE user_id = %s", (user_id,))
        conn.commit(); cur.close(); conn.close()

    @staticmethod
    def _friendly_error(e):
        """Turns a Gemini error into a short message that says what actually went wrong."""
        text = str(e)
        low = text.lower()
        if "429" in text or "quota" in low or "resource_exhausted" in low or "rate limit" in low:
            return ("Gemini ki free limit abhi khatam ho gayi hai (minute ya din ki). "
                    "Thodi der baad ya kal dobara try karo.")
        if "api key" in low or "api_key_invalid" in low or "permission_denied" in low or "403" in text:
            return "Gemini API key sahi nahi hai ya expire ho gayi hai. .env mein nayi key daalo."
        if "504" in text or "503" in text or "deadline" in low or "timed out" in low or "timeout" in low:
            return "AI service abhi bahut slow hai. Thodi der baad dobara try karo."
        if "finish_reason" in low or "block" in low or "safety" in low:
            return "AI ne is baar jawab nahi diya (safety ya length limit). Sawaal dobara bhejo ya thoda alag tarah se likho."
        return "AI se jawab nahi aa paya. Thodi der baad dobara try karo."

    def _time_context(self):
        """Current India time, sent along with every prompt so Floxy can answer time/date questions."""
        ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        now = datetime.datetime.now(ist)
        return (
            "[System context. Don't mention this unless the question needs it.] "
            f"Current date and time in India (IST, UTC+5:30): {now.strftime('%A, %d %B %Y, %I:%M %p')}. "
            "The user is in India. For any question about the current time, date, day, weather, "
            "currency or location, assume India / IST by default and answer directly using the "
            "exact time given above. Only use another city's or country's time if the user explicitly "
            "asks about that place; in that case, calculate it from the India time above using "
            "that place's UTC offset.\n\n"
        )
    
    def _generate_with_retry(self, prompt, max_retries=1):
        """Calls Gemini over REST with a hard timeout, retrying once on transient errors."""
        import time

        # Attach the current IST time to every request
        header = self._time_context()
        if isinstance(prompt, list):
            prompt = [header + prompt[0]] + list(prompt[1:])
        else:
            prompt = header + prompt

        last_error = RuntimeError("Gemini request failed")
        for attempt in range(max_retries + 1):
            try:
                return self.model.generate_content(prompt, request_options={"timeout": 45})
            except Exception as e:
                last_error = e
                error_text = str(e)
                if "504" in error_text or "Deadline" in error_text or "503" in error_text or "timed out" in error_text.lower():
                    time.sleep(2)
                    continue
                raise
        raise last_error

    # ------------------------------------------------------------------
    # Core chat
    # ------------------------------------------------------------------
    def send_message(self, user_id, text_prompt, search_mode="text"):
        """Sends a text prompt to Gemini, logs it, and returns the reply string.
        If the user has an active uploaded document, its content is included
        as grounding context so questions about it work without re-uploading."""
        allowed, used = self.check_and_increment_quota(user_id)
        if not allowed:
            return f"Daily limit of {Config.DAILY_API_LIMIT} messages reached. Please try again tomorrow.", None        
        
        self.log_search_action(user_id, text_prompt, search_mode)
        doc = self.get_active_document(user_id)
        if doc:
            final_prompt = (
                f"You are answering questions using the reference document below "
                f"(\"{doc['file_name']}\") whenever it is relevant. If the user's "
                f"question is unrelated to the document, just answer normally.\n\n"
                f"--- Reference document ---\n{doc['content']}\n\n"
                f"--- User question ---\n{text_prompt}"
            )
        else:
            final_prompt = text_prompt

        try:
            response = self._generate_with_retry(final_prompt)
            reply = response.text
        except Exception as e:
            print("[Floxy] Gemini error:", e)
            reply = self._friendly_error(e)

        log_id = self.log_chat_interaction(user_id, text_prompt, reply)
        return reply, log_id

    # ------------------------------------------------------------------
    # File ingestion
    # ------------------------------------------------------------------
    def extract_text_from_file(self, file_path):
        """Reads PDF / DOCX / TXT into plain text. Returns '' for images (sent as-is to Gemini)."""
        ext = file_path.rsplit(".", 1)[-1].lower()
        try:
            if ext == "pdf":
                reader = PdfReader(file_path)
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            elif ext == "docx":
                return docx2txt.process(file_path)
            elif ext == "txt":
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()
        except Exception as e:
            return f"[Could not read file: {e}]"
        return ""

    def process_file_upload(self, user_id, file_path, user_prompt=""):
        """Logs the upload, extracts/attaches content, and asks Gemini to analyse it."""
        file_name = os.path.basename(file_path)
        ext = file_name.rsplit(".", 1)[-1].lower()
        file_size_kb = f"{round(os.path.getsize(file_path) / 1024, 1)} KB"

        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO uploaded_files (user_id, file_name, file_type, file_size) "
            "VALUES (%s, %s, %s, %s)",
            (user_id, file_name, ext, file_size_kb),
        )
        conn.commit(); cur.close(); conn.close()

        allowed, used = self.check_and_increment_quota(user_id)
        if not allowed:
            return f"Daily limit of {Config.DAILY_API_LIMIT} messages reached. Please try again tomorrow.", None
        
        prompt = user_prompt or "Summarize and analyse this file for me."

        try:
            if ext in ("png", "jpg", "jpeg", "webp"):
                # Send the image directly in the request (inline) instead of using the
                # Files API — this skips the separate upload+processing wait and is
                # much faster for normal-sized photos.
                img = Image.open(file_path)
                response = self._generate_with_retry([prompt, img])
            else:
                extracted = self.extract_text_from_file(file_path)
                if extracted.strip():
                    self.save_active_document(user_id, file_name, extracted)
                full_prompt = f"{prompt}\n\n--- File content ---\n{extracted[:15000]}"
                response = self._generate_with_retry(full_prompt)
            reply = response.text
        except Exception as e:
            print("[Floxy] Gemini error:", e)
            reply = self._friendly_error(e)

        log_id = self.log_chat_interaction(user_id, f"[Uploaded file: {file_name}] {prompt}", reply)
        return reply, log_id

    # ------------------------------------------------------------------
    # Autocomplete suggestions
    # ------------------------------------------------------------------
    def get_live_suggestions(self, partial_text):
        """Asks Gemini for 3 short autocomplete continuations of the user's partial input."""
        if not partial_text or len(partial_text.strip()) < 3:
            return []
        try:
            prompt = (
                "Given this partial chat message, suggest 3 short, natural ways to complete it. "
                "Reply with ONLY the 3 suggestions, one per line, no numbering, no extra text.\n\n"
                f"Partial message: \"{partial_text}\""
            )
            response = self.model.generate_content(prompt)
            lines = [l.strip("-• ").strip() for l in response.text.strip().split("\n") if l.strip()]
            return lines[:3]
        except Exception:
            return []
