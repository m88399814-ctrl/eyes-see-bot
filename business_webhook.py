import os
import uuid
import time
import psycopg2
import requests
from flask import Flask, request

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
BOT_USERNAME = "EyesSeeBot"  # username бота без @

app = Flask(__name__)

# ================= DB =================

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS messages;")
            cur.execute("""
            CREATE TABLE messages (
                id SERIAL PRIMARY KEY,
                owner_id BIGINT NOT NULL,
                sender_id BIGINT NOT NULL,
                sender_name TEXT,
                message_id BIGINT NOT NULL,
                msg_type TEXT NOT NULL,
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

def save_owner(owner_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO owners (owner_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (owner_id,)
            )
        conn.commit()

def get_owner():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT owner_id FROM owners LIMIT 1")
            row = cur.fetchone()
            return row[0] if row else None

# ================= TG API =================

def tg(method, payload):
    return requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
        json=payload,
        timeout=15
    )

def send_text(chat_id, text, markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if markup:
        payload["reply_markup"] = markup
    tg("sendMessage", payload)

def send_media(chat_id, msg_type, file_id, token):
    hide_markup = {
        "inline_keyboard": [
            [{"text": "✖️ Скрыть", "callback_data": f"hide:{token}"}]
        ]
    }

    methods = {
        "photo": ("sendPhoto", "photo"),
        "video": ("sendVideo", "video"),
        "video_note": ("sendVideoNote", "video_note"),
        "voice": ("sendVoice", "voice")
    }

    method, key = methods[msg_type]
    tg(method, {
        "chat_id": chat_id,
        key: file_id,
        "reply_markup": hide_markup
    })

# ================= WEBHOOK =================

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    cleanup_old()

    if not data:
        return "ok"

    # 1️⃣ бизнес подключение
    if "business_connection" in data:
        owner_id = data["business_connection"]["user"]["id"]
        save_owner(owner_id)
        return "ok"

    owner_id = get_owner()
    if not owner_id:
        return "ok"

    # 2️⃣ сохраняем сообщения ТОЛЬКО собеседника
    if "business_message" in data:
        msg = data["business_message"]
        sender = msg["from"]

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

        token = uuid.uuid4().hex[:10]

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                INSERT INTO messages
                (owner_id, sender_id, sender_name, message_id,
                 msg_type, text, file_id, token)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    owner_id,
                    sender["id"],
                    sender.get("first_name", "Без имени"),
                    msg["message_id"],
                    msg_type,
                    text,
                    file_id,
                    token
                ))
        return "ok"

    # 3️⃣ удаление сообщений → уведомление
    if "deleted_business_messages" in data:
        deleted = data["deleted_business_messages"]
        time.sleep(1)  # группировка 1 сек

        for mid in deleted.get("message_ids", []):
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    SELECT msg_type, text, file_id, sender_name, sender_id, token
                    FROM messages
                    WHERE owner_id = %s AND message_id = %s
                    """, (owner_id, mid))
                    row = cur.fetchone()

            if not row:
                continue

            msg_type, text, file_id, sender_name, sender_id, token = row

            header = "🗑 <b>Новое удалённое сообщение</b>\n\n"
            who = f"\n\nУдалил(а): <a href=\"tg://user?id={sender_id}\">{sender_name}</a>"

            if msg_type == "text":
                body = f"<blockquote>{text}</blockquote>"
                send_text(owner_id, header + body + who)
                continue

            labels = {
                "photo": "📷 Фотография",
                "video": "📹 Видео",
                "video_note": "📹 Видеосообщение",
                "voice": "🎤 Голосовое сообщение"
            }

            label = labels[msg_type]
            link = f'<a href="https://t.me/{BOT_USERNAME}?start={token}">{label}</a>'
            send_text(owner_id, header + link + who)

        return "ok"

    # 4️⃣ /start TOKEN → открыть файл
    if "message" in data:
        msg = data["message"]
        text = msg.get("text", "")
        chat_id = msg["chat"]["id"]

        if text.startswith("/start "):
            token = text.split(" ", 1)[1]

            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    SELECT msg_type, file_id
                    FROM messages
                    WHERE owner_id = %s AND token = %s
                    """, (chat_id, token))
                    row = cur.fetchone()

            if not row:
                hide = {
                    "inline_keyboard": [
                        [{"text": "✖️ Скрыть", "callback_data": "hide:error"}]
                    ]
                }
                send_text(
                    chat_id,
                    "❌ <b>Не получилось открыть файл</b> 😔\n"
                    "Возможно он был отправлен слишком давно",
                    hide
                )
                return "ok"

            msg_type, file_id = row
            send_media(chat_id, msg_type, file_id, token)
            return "ok"

    # 5️⃣ кнопка Скрыть
    if "callback_query" in data:
        cq = data["callback_query"]
        msg = cq.get("message")
        if msg:
            tg("deleteMessage", {
                "chat_id": msg["chat"]["id"],
                "message_id": msg["message_id"]
            })
        tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        return "ok"

    return "ok"

# ================= START =================

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000)
