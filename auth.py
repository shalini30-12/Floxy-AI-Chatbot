"""
auth.py
Identity Management and Cryptographic Security Module.
Validates signup input and handles secure password hashing/verification
with bcrypt, so plain-text passwords never touch the database.
"""
import re
import bcrypt
from mysql.connector import Error



EMAIL_REGEX = re.compile(r"^[\w\.\+\-]+@[\w\-]+\.[a-zA-Z]{2,}$")
PHONE_REGEX = re.compile(r"^[6-9]\d{9}$")  # 10-digit Indian mobile format


class FloxyAuth:
    def __init__(self, db_instance):
        self.db = db_instance

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    @staticmethod
    def validate_email(email: str) -> bool:
        return bool(EMAIL_REGEX.match(email or ""))

    @staticmethod
    def validate_phone(phone: str) -> bool:
        return bool(PHONE_REGEX.match(phone or ""))

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_answer(answer: str) -> str:
        return (answer or "").strip().lower()

    def register_user(self, name, username, mobile, gmail, password,
                       security_question="", security_answer="", state=""):
        if not name or not username or not password:
            return False, "Name, username and password are required."
        if not self.validate_email(gmail):
            return False, "Please enter a valid email address."
        if not self.validate_phone(mobile):
            return False, "Please enter a valid 10-digit mobile number."
        if len(password) < 6:
            return False, "Password must be at least 6 characters."
        if not security_question or not security_answer.strip():
            return False, "Please choose a security question and provide an answer."

        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        hashed_answer = bcrypt.hashpw(
            self._normalize_answer(security_answer).encode("utf-8"), bcrypt.gensalt()
        )

        try:
            conn = self.db.get_connection()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (name, username, mobile, gmail, password, "
                "security_question, security_answer, state) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (name, username, mobile, gmail, hashed.decode("utf-8"),
                 security_question, hashed_answer.decode("utf-8"), state),
            )
            
            conn.commit()
            cur.close()
            conn.close()
            return True, "Account created successfully. Please log in."
        except Error as e:
            if "Duplicate entry" in str(e):
                return False, "That username is already taken."
            return False, f"Database error: {e}"

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------
    def verify_login(self, username, password):
        """Returns (user_dict or None, message: str)."""
        conn = self.db.get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if not user:
            return None, "No account found with that username."

        if bcrypt.checkpw(password.encode("utf-8"), user["password"].encode("utf-8")):
            user.pop("password", None)  # never hand the hash back to the app layer
            return user, "Login successful."
        return None, "Incorrect password."


    def get_security_question(self, username):
        conn = self.db.get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT security_question FROM users WHERE username = %s", (username,))
        row = cur.fetchone()
        cur.close(); conn.close()
        if row and row["security_question"]:
            return row["security_question"]
        return None

    def verify_security_answer(self, username, answer):
        conn = self.db.get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT security_answer FROM users WHERE username = %s", (username,))
        row = cur.fetchone()
        cur.close(); conn.close()
        if not row or not row["security_answer"]:
            return False
        return bcrypt.checkpw(
            self._normalize_answer(answer).encode("utf-8"),
            row["security_answer"].encode("utf-8"),
        )

    def reset_password(self, username, new_password):
        if len(new_password) < 6:
            return False, "Password must be at least 6 characters."
        hashed = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt())
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET password = %s WHERE username = %s",
                    (hashed.decode("utf-8"), username))
        conn.commit()
        affected = cur.rowcount
        cur.close(); conn.close()
        if affected == 0:
            return False, "User not found."
        return True, "Password reset successfully. Please log in."
