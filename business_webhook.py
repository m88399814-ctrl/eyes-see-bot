import os
import uuid
import psycopg2
import requests
from flask import Flask, request

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

app = Flask(__name__)

# ================= DATABASE =================

def db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                owner_id BIGINT NOT NULL,
                sender_id BIGINT NOT NULL,
                sender_name TEXT,
                chat_id BIGINT NOT NULL,
                message_id BIGINT NOT NULL,
                msg_type TEXT NOT NULL,
                text TEXT,
                file_id TEXT,
                token TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT NOW()
            )
            """)
        conn.commit()

def cleanup_old():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            DELETE FROM messages
            WHERE created_at < NOW() - INTERVAL '18 hours'
            """)
        conn.commit()

# ================= TELEGRAM API =================

def tg(method, payload):
    return requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
        json=payload,
        timeout=10
    )

def send_text(chat_id, text):
    tg("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    })

def send_file(chat_id, msg_type, file_id):
    methods = {
        "photo": ("sendPhoto", "photo"),
        "video": ("sendVideo", "video"),
        "video_note": ("sendVideoNote", "video_note"),
        "voice": ("sendVoice", "voice")
    }
    method, key = methods[msg_type]
    tg(method, {"chat_id": chat_id, key: file_id})

# ================= WEBHOOK =================

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    cleanup_old()

    if not data:
        return "ok"

    # 🔑 ВЛАДЕЛЕЦ БИЗНЕС-АККАУНТА (ГЛАВНОЕ!)
    owner_id = None
    if "business_connection" in data:
        owner_id = data["business_connection"]["user"]["id"]

    # ================= СООБЩЕНИЕ ОТ СОБЕСЕДНИКА =================
    if "business_message" in data:
        msg = data["business_message"]
        sender = msg["from"]

        if not owner_id:
            return "ok"

        # ❌ не сохраняем сообщения владельца
        if sender["id"] == owner_id:
            return "ok"

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

        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                INSERT INTO messages
                (owner_id, sender_id, sender_name, chat_id, message_id,
                 msg_type, text, file_id, token)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    owner_id,
                    sender["id"],
                    sender.get("first_name", "Без имени"),
                    msg["chat"]["id"],
                    msg["message_id"],
                    msg_type,
                    text,
                    file_id,
                    token
                ))
            conn.commit()

    # ================= УДАЛЕНИЕ СООБЩЕНИЯ =================
    elif "deleted_business_messages" in data:
        deleted = data["deleted_business_messages"]

        if not owner_id:
            return "ok"

        for mid in deleted["message_ids"]:
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    SELECT msg_type, text, file_id, sender_name, token
                    FROM messages
                    WHERE message_id = %s AND owner_id = %s
                    """, (mid, owner_id))
                    row = cur.fetchone()

            if not row:
                continue

            msg_type, text, file_id, sender_name, token = row

            header = "🗑 <b>Новое удалённое сообщение</b>\n\n"

            if msg_type == "text":
                body = f"<blockquote>{text}</blockquote>"
            else:
                labels = {
                    "photo": "📷 Фотография",
                    "video": "📹 Видео",
                    "video_note": "📹 Видеосообщение",
                    "voice": "🎤 Голосовое сообщение"
                }
                body = f"{labels[msg_type]}\n/get_{token}"

            footer = f"\n\nУдалил(а): <a href=\"tg://user?id={owner_id}\">{sender_name}</a>"

            send_text(owner_id, header + body + footer)

    # ================= ОТКРЫТИЕ ФАЙЛА =================
    elif "message" in data:
        msg = data["message"]
        text = msg.get("text", "")

        if text.startswith("/get_"):
            token = text.replace("/get_", "")
            chat_id = msg["chat"]["id"]

            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    SELECT msg_type, file_id
                    FROM messages
                    WHERE token = %s AND owner_id = %s
                    """, (token, chat_id))
                    row = cur.fetchone()

            # удалить команду
            tg("deleteMessage", {
                "chat_id": chat_id,
                "message_id": msg["message_id"]
            })

            if not row:
                send_text(chat_id, "❌ Не получилось открыть файл 😔\nВозможно он был отправлен слишком давно")
                return "ok"

            msg_type, file_id = row
            send_file(chat_id, msg_type, file_id)

    return "ok"

# ================= START =================

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000)
