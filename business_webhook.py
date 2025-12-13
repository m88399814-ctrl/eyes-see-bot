import os
import uuid
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from flask import Flask, request

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

app = Flask(__name__)

conn = psycopg2.connect(
    DATABASE_URL,
    sslmode="require",
    cursor_factory=RealDictCursor
)
conn.autocommit = True


# ---------- DB ----------

def init_db():
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            owner_id BIGINT,
            chat_id BIGINT,
            message_id BIGINT,
            file_id TEXT,
            file_type TEXT,
            text TEXT,
            token TEXT UNIQUE,
            created_at TIMESTAMP
        );
        """)

def cleanup_old():
    with conn.cursor() as cur:
        cur.execute("""
        DELETE FROM messages
        WHERE created_at < NOW() - INTERVAL '18 hours';
        """)

init_db()


# ---------- TELEGRAM HELPERS ----------

def tg_send_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(url, json=payload)

def tg_send_file(chat_id, file_id, file_type):
    method = {
        "photo": "sendPhoto",
        "voice": "sendVoice",
        "video": "sendVideo",
        "video_note": "sendVideoNote"
    }[file_type]

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    requests.post(url, json={"chat_id": chat_id, "file_id": file_id})


# ---------- WEBHOOK ----------

@app.route("/webhook", methods=["POST"])
def webhook():
    cleanup_old()
    data = request.get_json(silent=True)
    if not data:
        return "ok"

    # 📩 входящее бизнес-сообщение — сохраняем
    if "business_message" in data:
        msg = data["business_message"]
        owner_id = msg["from"]["id"]

        file_id = None
        file_type = None
        text = msg.get("text")

        if "photo" in msg:
            file_id = msg["photo"][-1]["file_id"]
            file_type = "photo"
        elif "voice" in msg:
            file_id = msg["voice"]["file_id"]
            file_type = "voice"
        elif "video" in msg:
            file_id = msg["video"]["file_id"]
            file_type = "video"
        elif "video_note" in msg:
            file_id = msg["video_note"]["file_id"]
            file_type = "video_note"

        if file_id or text:
            token = uuid.uuid4().hex[:12]
            with conn.cursor() as cur:
                cur.execute("""
                INSERT INTO messages
                (owner_id, chat_id, message_id, file_id, file_type, text, token, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    owner_id,
                    msg["chat"]["id"],
                    msg["message_id"],
                    file_id,
                    file_type,
                    text,
                    token,
                    datetime.utcnow()
                ))

    # 🗑 удаление сообщений
    elif "deleted_business_messages" in data:
        deleted = data["deleted_business_messages"]
        chat = deleted["chat"]

        with conn.cursor() as cur:
            cur.execute("""
            SELECT * FROM messages
            WHERE chat_id=%s
            ORDER BY created_at DESC
            LIMIT %s
            """, (chat["id"], len(deleted["message_ids"])))
            rows = cur.fetchall()

        if not rows:
            return "ok"

        owner_id = rows[0]["owner_id"]

        header = (
            "🗑 <b>Новое удалённое сообщение</b>\n\n"
            if len(rows) == 1
            else "🗑 <b>Новые удалённые сообщения</b>\n\n"
        )

        body = ""
        buttons = []

        for r in rows:
            if r["file_type"]:
                label = {
                    "photo": "📷 Фотография",
                    "voice": "🎤 Голосовое сообщение",
                    "video": "📹 Видео",
                    "video_note": "📹 Видеосообщение"
                }[r["file_type"]]

                body += f"{label}\n"
                buttons.append([{
                    "text": label,
                    "callback_data": f"get_{r['token']}"
                }])
            else:
                body += f"<blockquote>{r['text']}</blockquote>\n"

        name = chat.get("first_name", "")
        username = chat.get("username")
        tag = f"<a href='https://t.me/{username}'>{name}</a>" if username else name

        body += f"\nУдалил(а): {tag}"

        tg_send_message(
            owner_id,
            header + body,
            reply_markup={"inline_keyboard": buttons} if buttons else None
        )

    # 🔘 нажатие на кнопку
    elif "callback_query" in data:
        cq = data["callback_query"]
        token = cq["data"].replace("get_", "")
        user_id = cq["from"]["id"]

        with conn.cursor() as cur:
            cur.execute("SELECT * FROM messages WHERE token=%s", (token,))
            row = cur.fetchone()

        if not row:
            tg_send_message(
                user_id,
                "❌ Не получилось открыть файл 😔\nВозможно он был отправлен слишком давно"
            )
            return "ok"

        tg_send_file(user_id, row["file_id"], row["file_type"])

    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
