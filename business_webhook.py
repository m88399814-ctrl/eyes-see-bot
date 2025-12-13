from flask import Flask, request
import requests
import sqlite3
import json
import time
import secrets
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_NAME = "eyessee.db"

app = Flask(__name__)
OWNER_ID = None

TOKEN_LIFETIME = 60  # секунд


# ---------- DB ----------
def get_db():
    return sqlite3.connect(DB_NAME)


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            message_id INTEGER PRIMARY KEY,
            chat_id INTEGER,
            sender_id INTEGER,
            sender_name TEXT,
            type TEXT,
            content TEXT,
            file_id TEXT,
            date INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS file_tokens (
            token TEXT PRIMARY KEY,
            file_id TEXT,
            type TEXT,
            expires_at INTEGER
        )
    """)

    conn.commit()
    conn.close()


# ---------- TOKENS ----------
def create_file_token(file_id, ftype):
    token = secrets.token_hex(4)
    expires = int(time.time()) + TOKEN_LIFETIME

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO file_tokens VALUES (?, ?, ?, ?)",
        (token, file_id, ftype, expires)
    )
    conn.commit()
    conn.close()

    return token


def get_file_by_token(token):
    now = int(time.time())
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT file_id, type FROM file_tokens
        WHERE token=? AND expires_at>=?
    """, (token, now))
    row = cur.fetchone()

    if row:
        cur.execute("DELETE FROM file_tokens WHERE token=?", (token,))
        conn.commit()

    conn.close()
    return row


# ---------- SEND ----------
def send_to_owner(text):
    if not OWNER_ID:
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": OWNER_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    requests.post(url, json=payload)


# ---------- WEBHOOK ----------
@app.route("/webhook", methods=["POST"])
def webhook():
    global OWNER_ID
    data = request.get_json(silent=True)

    print("\n========== RAW UPDATE ==========")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print("================================")

    if not data:
        return "ok"

    # 🔑 бизнес-подключение
    if "business_connection" in data:
        OWNER_ID = data["business_connection"]["user"]["id"]
        print(f"✅ OWNER CONNECTED: {OWNER_ID}")
        return "ok"

    # 📩 новое сообщение — сохраняем
    if "business_message" in data:
        msg = data["business_message"]

        msg_type = "text"
        content = None
        file_id = None

        if "text" in msg:
            content = msg["text"]

        elif "photo" in msg:
            msg_type = "photo"
            file_id = msg["photo"][-1]["file_id"]

        elif "voice" in msg:
            msg_type = "voice"
            file_id = msg["voice"]["file_id"]

        elif "video_note" in msg:
            msg_type = "video_note"
            file_id = msg["video_note"]["file_id"]

        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO messages
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            msg["message_id"],
            msg["chat"]["id"],
            msg["from"]["id"],
            msg["from"].get("first_name", "Без имени"),
            msg_type,
            content,
            file_id,
            msg["date"]
        ))
        conn.commit()
        conn.close()
        return "ok"

    # 🗑 удаление
    if "deleted_business_messages" in data:
        ids = data["deleted_business_messages"]["message_ids"]

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            f"SELECT sender_id, sender_name, type, content, file_id FROM messages "
            f"WHERE message_id IN ({','.join('?'*len(ids))})",
            ids
        )
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return "ok"

        sender_id, sender_name, _, _, _ = rows[0]
        sender_link = f'<a href="tg://user?id={sender_id}">{sender_name}</a>'

        text = "🗑 <b>Новое удалённое сообщение</b>\n\n"

        for _, _, mtype, content, file_id in rows:
            if mtype == "text":
                text += f"<blockquote>{content}</blockquote>\n\n"
            else:
                token = create_file_token(file_id, mtype)
                label = {
                    "photo": "📷 Фотография",
                    "voice": "🎤 Голосовое сообщение",
                    "video_note": "📹 Видеосообщение"
                }[mtype]
                text += f"{label}\n/get_{token}\n\n"

        text += f"Удалил(а): {sender_link}"
        send_to_owner(text)
        return "ok"

    # 📥 клик по /get_xxx
    if "message" in data:
        msg = data["message"]
        txt = msg.get("text", "")

        if txt.startswith("/get_"):
            token = txt.replace("/get_", "")
            result = get_file_by_token(token)

            if not result:
                send_to_owner(
                    "❌ Не получилось открыть файл 😔\n"
                    "Возможно он был отправлен слишком давно"
                )
                return "ok"

            file_id, ftype = result
            base = f"https://api.telegram.org/bot{BOT_TOKEN}"

            if ftype == "photo":
                requests.post(f"{base}/sendPhoto",
                              json={"chat_id": OWNER_ID, "photo": file_id})
            elif ftype == "voice":
                requests.post(f"{base}/sendVoice",
                              json={"chat_id": OWNER_ID, "voice": file_id})
            elif ftype == "video_note":
                requests.post(f"{base}/sendVideoNote",
                              json={"chat_id": OWNER_ID, "video_note": file_id})

        return "ok"

    return "ok"


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000)
