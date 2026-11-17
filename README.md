# Floxy — AI Chatbot (Flask + MySQL + Gemini API)

A web-based version of the Floxy AI Chatbot: Python (Flask) backend, MySQL
database, Google Gemini API for the AI, and an HTML/CSS/JS frontend with
text chat, voice input/output, and file (PDF/DOCX/TXT/image) analysis.

## 1. Prerequisites

- Python 3.10–3.12
- MySQL Server 8.0+ running locally (or a reachable host)
- A Gemini API key → https://aistudio.google.com/apikey
- Chrome or Edge browser (best support for voice input via Web Speech API)

## 2. Setup

```bash
cd floxy
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Copy the example env file and fill in your real values:

```bash
cp .env.example .env
```

Edit `.env`:

You do **not** need to create the database or tables by hand — `app.py`
calls `database.py`'s `init_database()` on startup, which creates
`floxy_db` and every table automatically if they don't already exist.

## 3. Run

```bash
python app.py
```

Open **http://127.0.0.1:5000** in your browser. Sign up, log in, and start chatting.

## 4. What's included

| File                     | Purpose                                                           |
| ------------------------ | ----------------------------------------------------------------- |
| `app.py`               | Flask routes & the JSON APIs the frontend calls                   |
| `database.py`          | MySQL connection + auto schema creation                           |
| `auth.py`              | Signup/login validation + bcrypt password hashing                 |
| `chatbot.py`           | Gemini API calls, file text extraction, daily quota, logging      |
| `config.py`            | Reads`.env` into one settings object                            |
| `templates/`           | HTML pages (login, signup, chat)                                  |
| `static/css/style.css` | Dark navy/blue UI theme                                           |
| `static/js/chat.js`    | Sending messages, mic (Web Speech API), file upload, autocomplete |

## 5. Notes / how it maps to the synopsis

- The original synopsis used CustomTkinter (desktop GUI). This build swaps
  that for a **web app** (Flask + HTML/CSS) per your request — everything
  else (Bcrypt auth, MySQL schema, Gemini integration, file parsing,
  daily API quota, chat logging) is implemented as described.
- Voice input/output uses the **browser's built-in Web Speech API**
  instead of `SpeechRecognition`/`pyttsx3`, since those are desktop-only
  libraries and don't work inside a browser. This is the standard way to
  do voice in a web app and needs no extra system setup.
- Tables implemented: `users`, `chatbot_logs`, `search_history`,
  `uploaded_files`, `api_logs`. `subscriptions`, `bookmarked_chats`, and
  `user_feedback` from the synopsis were left out of this MVP to keep the
  first version focused — happy to add them (bookmarking a reply, thumbs
  up/down feedback, paid tiers) as a next step if you want.

## 6. Common issues

- **"Access denied" MySQL error** → check `DB_USER`/`DB_PASSWORD` in `.env`.
- **Gemini errors** → confirm `GEMINI_API_KEY` is correct and has quota.
- **Mic button does nothing** → use Chrome/Edge; Firefox/Safari don't
  support the Web Speech API's recognition side yet.
