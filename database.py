"""
database.py
Relational Persistence & Schema Engine.
Handles the PostgreSQL connection and auto-creates every table Floxy needs
on first run, so a fresh clone of the project needs zero manual SQL.
"""
import psycopg2
from psycopg2 import Error
from config import Config


class FloxyDatabase:
    def __init__(self):
        self.host = Config.DB_HOST
        self.port = Config.DB_PORT
        self.user = Config.DB_USER
        self.password = Config.DB_PASSWORD
        self.db_name = Config.DB_NAME

    # ------------------------------------------------------------------
    # Connections
    # ------------------------------------------------------------------
    def get_connection(self, with_db=True):
        """Return a fresh PostgreSQL connection (caller is responsible for closing it)."""
        return psycopg2.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            dbname=self.db_name if with_db else "postgres",
        )

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------
    def init_database(self):
        """Creates every table in PostgreSQL if missing."""
        conn = self.get_connection(with_db=True)
        conn.autocommit = True
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                username VARCHAR(50) UNIQUE NOT NULL,
                mobile VARCHAR(15) NOT NULL,
                gmail VARCHAR(100) NOT NULL,
                password VARCHAR(255) NOT NULL,
                state VARCHAR(50) NOT NULL DEFAULT '',
                security_question VARCHAR(255) NOT NULL DEFAULT '',
                security_answer VARCHAR(255) NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        for ddl in (
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS security_question VARCHAR(255) NOT NULL DEFAULT ''",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS security_answer VARCHAR(255) NOT NULL DEFAULT ''",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS state VARCHAR(50) NOT NULL DEFAULT ''",
        ):
            try:
                cur.execute(ddl)
            except Error:
                conn.rollback()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS chatbot_logs (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                user_message TEXT NOT NULL,
                bot_response TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS search_history (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                search_text TEXT NOT NULL,
                search_mode VARCHAR(30) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS uploaded_files (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                file_name VARCHAR(255) NOT NULL,
                file_type VARCHAR(20) NOT NULL,
                file_size VARCHAR(30) NOT NULL,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS api_logs (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL UNIQUE,
                api_calls_count INT DEFAULT 0,
                last_call_date DATE NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_base (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL UNIQUE,
                file_name VARCHAR(255) NOT NULL,
                content TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS bookmarked_days (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                chat_date DATE NOT NULL,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT unique_day_bookmark UNIQUE (user_id, chat_date),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS bookmarked_chats (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                log_id INT NOT NULL,
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT unique_bookmark UNIQUE (user_id, log_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (log_id) REFERENCES chatbot_logs(id) ON DELETE CASCADE
            )
        """)
        
        try:
            cur.execute("ALTER TABLE chatbot_logs ADD COLUMN IF NOT EXISTS attachment VARCHAR(255) NULL")
        except Error:
            conn.rollback()

        cur.close()
        conn.close()
        print("[Floxy] PostgreSQL Database ready: all tables verified/created.")


if __name__ == "__main__":
    FloxyDatabase().init_database()