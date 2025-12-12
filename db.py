import sqlite3

DB_NAME = "eyessee.db"


def get_connection():
    return sqlite3.connect(DB_NAME)


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user_id INTEGER,
            username TEXT,
            message_id INTEGER,
            message_type TEXT,
            content TEXT,
            file_id TEXT,
            date INTEGER
        )
    """)

    conn.commit()
    conn.close()
