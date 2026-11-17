"""
config.py
Central place that reads the .env file and exposes app-wide settings.
"""
import os
from dotenv import load_dotenv

load_dotenv()  # reads variables from a local .env file if present

class Config:
    # --- MySQL ---
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", 3306))
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "floxy_db")

    # --- Gemini ---
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

    # --- Flask ---
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
    DAILY_API_LIMIT = int(os.getenv("DAILY_API_LIMIT", 50))

    # --- File uploads ---
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
    ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "png", "jpg", "jpeg", "webp"}
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 15 MB
