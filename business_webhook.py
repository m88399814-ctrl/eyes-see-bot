import os
import uuid
import time
import psycopg2
import requests
from flask import Flask, request

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
BOT_USERNAME = "EyesSeeBot"  # без @

app = Flask(__name__)

# ================= DB =================

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS owners (
                owner_id BIGINT PRIMARY KEY
            )
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                owner_id BIGINT NOT NULL,
                sender_id BIGINT NOT NULL,
                sender_name TEXT,
                message_id BIGINT NOT NULL,
                msg_type TEXT NOT NULL,
                text TEXT,
                file_id TEXT,
                token TEXT UNIQUE,
                src_chat_id BIGINT,
                src_message_id BIGINT,
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

def save_owner(owner_id: int):
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
            r = cur.fetchone()
            return r[0] if r else None

# ================= TG API =================

def tg(method, payload):
    return requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
        json=payload,
        timeout=20
    )

def send_text(chat_id, text):
    tg("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    })

def send_media(chat_id, msg_type, file_id):
    if msg_type == "voice":
        tg("sendVoice", {"chat_id": chat_id, "voice": file_id})
    elif msg_type == "video":
        tg("sendVideo", {"chat_id": chat_id, "video": file_id})
    elif msg_type == "photo":
        tg("sendPhoto", {"chat_id": chat_id, "photo": file_id})
    elif msg_type == "video_note":
        tg("sendVideoNote", {"chat_id": chat_id, "video_note": file_id})

def media_from_message(m):
    if "photo" in m and m["photo"]:
        return "photo", m["photo"][-1]["file_id"]
    if "video_note" in m:
        return "video_note", m["video_note"]["file_id"]
    if "voice" in m:
        return "voice", m["voice"]["file_id"]
    if "video" in m:
        return "video", m["video"]["file_id"]
    return None, None

def label_for(msg_type):
    return {
        "photo": "📷 Фотография",
        "video": "🎥 Видео",
        "video_note": "🎥 Видеосообщение",
        "voice": "🎤 Голосовое сообщение"
    }.get(msg_type, "📎 Файл")

# ================= WEBHOOK =================

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    cleanup_old()

    if not data:
        return "ok"

    # 1) бизнес подключение
    if "business_connection" in data:
        save_owner(data["business_connection"]["user"]["id"])
        return "ok"

    owner_id = get_owner()
    if not owner_id:
        return "ok"

    # 2) входящие бизнес-сообщения
    if "business_message" in data:
        msg = data["business_message"]
        sender = msg.get("from", {})

        # 2.1) владелец ответил на сообщение → исчезающее
        if sender.get("id") == owner_id and "reply_to_message" in msg:
            replied = msg["reply_to_message"]

            msg_type, file_id = media_from_message(replied)
            if not msg_type:
                return "ok"

            token = uuid.uuid4().hex[:10]
            src_chat_id = replied.get("chat", {}).get("id")
            src_message_id = replied.get("message_id")

            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    INSERT INTO messages
                    (owner_id, sender_id, sender_name, message_id,
                     msg_type, text, file_id, token,
                     src_chat_id, src_message_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (
                        owner_id,
                        replied["from"]["id"],
                        replied["from"].get("first_name", "Без имени"),
                        replied["message_id"],
                        msg_type,
                        None,
                        file_id,
                        token,
                        src_chat_id,
                        src_message_id
                    ))
                conn.commit()

            text = (
                "⌛️ <b>Новое исчезающее сообщение:</b>\n\n"
                f'<a href="https://t.me/{BOT_USERNAME}?start={token}">'
                f'{label_for(msg_type)}</a>'
            )
            send_text(owner_id, text)
            return "ok"

        # 2.2) сообщения владельца не сохраняем
        if sender.get("id") == owner_id:
            return "ok"

        # 2.3) обычные сообщения собеседника — сохраняем (для удалённых)
        msg_type, file_id = media_from_message(msg)
        text = msg.get("text")

        if not msg_type and not text:
            return "ok"

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
                    msg_type or "text",
                    text,
                    file_id,
                    token
                ))
            conn.commit()

        return "ok"

    # 3) удалённые сообщения
    if "deleted_business_messages" in data:
        time.sleep(1)

        blocks = []
        for mid in data["deleted_business_messages"].get("message_ids", []):
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    SELECT msg_type, text, token
                    FROM messages
                    WHERE owner_id=%s AND message_id=%s
                    """, (owner_id, mid))
                    r = cur.fetchone()

            if not r:
                continue

            msg_type, text, token = r
            if msg_type == "text":
                blocks.append(f"<blockquote>{text}</blockquote>")
            else:
                blocks.append(
                    f'<a href="https://t.me/{BOT_USERNAME}?start={token}">'
                    f'{label_for(msg_type)}</a>'
                )

        if blocks:
            send_text(
                owner_id,
                "🗑 <b>Удалено сообщение</b>\n\n" + "\n".join(blocks)
            )

        return "ok"

    # 4) /start TOKEN → открыть
    if "message" in data:
        msg = data["message"]
        text = msg.get("text", "")
        chat_id = msg["chat"]["id"]

        if text.startswith("/start "):
            token = text.split(" ", 1)[1]

            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    SELECT msg_type, file_id, src_chat_id, src_message_id
                    FROM messages
                    WHERE owner_id=%s AND token=%s
                    """, (owner_id, token))
                    r = cur.fetchone()

            if not r:
                send_text(chat_id, "❌ Файл недоступен")
                return "ok"

            msg_type, file_id, src_chat_id, src_message_id = r

            # 🔑 СЕКРЕТНЫЕ ФОТО И КРУЖКИ — COPY
            if msg_type in ("photo", "video_note"):
                tg("sendCopyMessage", {
                    "chat_id": chat_id,
                    "from_chat_id": src_chat_id,
                    "message_id": src_message_id
                })
                return "ok"

            # 🔁 ОСТАЛЬНОЕ — КАК РАНЬШЕ
            send_media(chat_id, msg_type, file_id)
            return "ok"

    return "ok"

# ================= START =================

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000)
