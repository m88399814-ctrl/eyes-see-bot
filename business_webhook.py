import os
import time
import uuid
import psycopg2
import requests
from flask import Flask, request

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

app = Flask(__name__)

# ---------------- DB ----------------

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                owner_id BIGINT,
                sender_id BIGINT,
                sender_name TEXT,
                chat_id BIGINT,
                message_id BIGINT,
                msg_type TEXT,
                text TEXT,
                file_id TEXT,
                token TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
            """)
        conn.commit()

def cleanup_old():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            DELETE FROM messages
            WHERE created_at < NOW() - INTERVAL '18 hours'
            """)
        conn.commit()

# ---------------- TG API ----------------

def tg(method, data):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    return requests.post(url, json=data)

def send(owner_id, text):
    tg("sendMessage", {
        "chat_id": owner_id,
        "text": text,
        "parse_mode": "HTML"
    })

def send_file(owner_id, msg_type, file_id):
    method = {
        "photo": "sendPhoto",
        "video": "sendVideo",
        "video_note": "sendVideoNote",
        "voice": "sendVoice"
    }[msg_type]

    tg(method, {
        "chat_id": owner_id,
        msg_type if msg_type != "video_note" else "video_note": file_id
    })

# ---------------- WEBHOOK ----------------

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    cleanup_old()

    if not data:
        return "ok"

    # 📩 сообщение от собеседника → СОХРАНЯЕМ
    if "business_message" in data:
        msg = data["business_message"]
        owner_id = msg["business_connection_id"]
        sender = msg["from"]

        if sender["id"] == owner_id:
            return "ok"  # не сохраняем сообщения владельца

        msg_type = "text"
        text = msg.get("text")
        file_id = None

        if "photo" in msg:
            msg_type = "photo"
            file_id = msg["photo"][-1]["file_id"]
        elif "video" in msg:
            msg_type = "video"
            file_id = msg["video"]["file_id"]
        elif "video_note" in msg:
            msg_type = "video_note"
            file_id = msg["video_note"]["file_id"]
        elif "voice" in msg:
            msg_type = "voice"
            file_id = msg["voice"]["file_id"]

        token = uuid.uuid4().hex[:8]

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                INSERT INTO messages
                (owner_id, sender_id, sender_name, chat_id, message_id,
                 msg_type, text, file_id, token)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    owner_id,
                    sender["id"],
                    sender.get("first_name", ""),
                    msg["chat"]["id"],
                    msg["message_id"],
                    msg_type,
                    text,
                    file_id,
                    token
                ))
            conn.commit()

    # 🗑 удаление сообщения
    elif "deleted_business_messages" in data:
        deleted = data["deleted_business_messages"]
        owner_id = deleted["business_connection_id"]

        for mid in deleted["message_ids"]:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    SELECT msg_type, text, file_id, sender_name, token
                    FROM messages
                    WHERE message_id = %s
                    """, (mid,))
                    row = cur.fetchone()

            if not row:
                continue

            msg_type, text, file_id, sender_name, token = row

            header = "🗑 <b>Новое удалённое сообщение</b>\n\n"

            if msg_type == "text":
                body = f"<blockquote>{text}</blockquote>"
            else:
                label = {
                    "photo": "📷 Фотография",
                    "video": "📹 Видео",
                    "video_note": "📹 Видеосообщение",
                    "voice": "🎤 Голосовое сообщение"
                }[msg_type]

                body = f"{label}\n/get_{token}"

            footer = f"\n\nУдалил(а): <a href=\"tg://user?id={sender_name}\">{sender_name}</a>"

            send(owner_id, header + body + footer)

    # 🔁 обработка команды открытия файла
    elif "message" in data:
        msg = data["message"]
        text = msg.get("text", "")

        if text.startswith("/get_"):
            token = text.replace("/get_", "")
            owner_id = msg["chat"]["id"]

            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    SELECT msg_type, file_id
                    FROM messages
                    WHERE token = %s
                    """, (token,))
                    row = cur.fetchone()

            # удалить команду
            tg("deleteMessage", {
                "chat_id": owner_id,
                "message_id": msg["message_id"]
            })

            if not row:
                send(owner_id, "❌ Не получилось открыть файл 😔\nВозможно он был отправлен слишком давно")
                return "ok"

            msg_type, file_id = row
            send_file(owner_id, msg_type, file_id)

    return "ok"

# ---------------- START ----------------

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000)
