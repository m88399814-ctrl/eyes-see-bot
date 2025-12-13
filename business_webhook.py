import os
import uuid
import time
import psycopg2
import requests
from flask import Flask, request

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
BOT_USERNAME = "EyesSeeBot"

app = Flask(__name__)

# ================= DB =================

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:

            # владельцы бизнес-подключений
            cur.execute("""
            CREATE TABLE IF NOT EXISTS owners (
                business_connection_id TEXT PRIMARY KEY,
                owner_id BIGINT NOT NULL
            )
            """)

            # сообщения
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

def save_owner(bc_id: str, owner_id: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO owners (business_connection_id, owner_id)
            VALUES (%s, %s)
            ON CONFLICT (business_connection_id)
            DO UPDATE SET owner_id = EXCLUDED.owner_id
            """, (bc_id, owner_id))
        conn.commit()

def get_owner(bc_id: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT owner_id FROM owners
            WHERE business_connection_id = %s
            """, (bc_id,))
            r = cur.fetchone()
            return r[0] if r else None

# ================= TG API =================

def tg(method, payload):
    return requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
        json=payload,
        timeout=20
    )

def send_text(chat_id, text, markup=None):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if markup:
        data["reply_markup"] = markup
    tg("sendMessage", data)

def hide_markup(token):
    return {
        "inline_keyboard": [
            [{"text": "✖️ Скрыть", "callback_data": f"hide:{token}"}]
        ]
    }

# ================= MEDIA =================

def send_media(chat_id, msg_type, file_id, token):
    hide = hide_markup(token)

    if msg_type == "photo":
        tg("sendPhoto", {"chat_id": chat_id, "photo": file_id, "reply_markup": hide})
        return

    if msg_type == "video":
        tg("sendVideo", {"chat_id": chat_id, "video": file_id, "reply_markup": hide})
        return

    if msg_type == "voice":
        tg("sendVoice", {"chat_id": chat_id, "voice": file_id, "reply_markup": hide})
        return

    if msg_type == "video_note":
        tg("sendVideoNote", {"chat_id": chat_id, "video_note": file_id, "reply_markup": hide})
        return

    tg("sendDocument", {"chat_id": chat_id, "document": file_id, "reply_markup": hide})

def media_from_message(m):
    if "photo" in m:
        return "photo", m["photo"][-1]["file_id"]
    if "video_note" in m:
        return "video_note", m["video_note"]["file_id"]
    if "voice" in m:
        return "voice", m["voice"]["file_id"]
    if "video" in m:
        return "video", m["video"]["file_id"]
    if "document" in m:
        return "document", m["document"]["file_id"]
    return None, None

def label_for(t):
    return {
        "photo": "📷 Фотография",
        "video": "🎥 Видео",
        "video_note": "🎥 Видеосообщение",
        "voice": "🎤 Голосовое сообщение",
        "document": "📎 Файл"
    }.get(t, "📎 Файл")

# ================= WEBHOOK =================

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    cleanup_old()

    if not data:
        return "ok"

    # 1️⃣ подключение бизнес-аккаунта
    if "business_connection" in data:
        bc = data["business_connection"]
        bc_id = bc.get("id") or bc.get("business_connection_id")
        owner_id = bc["user"]["id"]
        if bc_id:
            save_owner(bc_id, owner_id)
        return "ok"

    # 2️⃣ входящее сообщение
    if "business_message" in data:
        msg = data["business_message"]
        bc_id = msg.get("business_connection_id")
        owner_id = get_owner(bc_id)

        if not owner_id:
            return "ok"

        sender = msg.get("from", {})

        # ответ владельца → сохраняем исчезающее
        if sender.get("id") == owner_id and "reply_to_message" in msg:
            replied = msg["reply_to_message"]
            msg_type, file_id = media_from_message(replied)
            if not msg_type:
                return "ok"

            token = uuid.uuid4().hex[:10]

            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    INSERT INTO messages
                    (owner_id, sender_id, sender_name, message_id, msg_type, text, file_id, token)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (
                        owner_id,
                        replied["from"]["id"],
                        replied["from"].get("first_name", ""),
                        replied["message_id"],
                        msg_type,
                        None,
                        file_id,
                        token
                    ))
                conn.commit()

            send_text(
                owner_id,
                f"⌛️ <b>Новое исчезающее сообщение:</b>\n\n"
                f'<a href="https://t.me/{BOT_USERNAME}?start={token}">{label_for(msg_type)}</a>'
            )
            return "ok"

        # обычные сообщения
        msg_type, file_id = media_from_message(msg)
        text = msg.get("text")

        if not msg_type and not text:
            return "ok"

        if not msg_type:
            msg_type = "text"
            file_id = None

        token = uuid.uuid4().hex[:10]

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                INSERT INTO messages
                (owner_id, sender_id, sender_name, message_id, msg_type, text, file_id, token)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    owner_id,
                    sender["id"],
                    sender.get("first_name", ""),
                    msg["message_id"],
                    msg_type,
                    text,
                    file_id,
                    token
                ))
            conn.commit()

        return "ok"

    # 3️⃣ удаление сообщений
    if "deleted_business_messages" in data:
        dbm = data["deleted_business_messages"]
        bc_id = dbm.get("business_connection_id")
        owner_id = get_owner(bc_id)

        if not owner_id:
            return "ok"

        time.sleep(1)

        blocks = []
        for mid in dbm["message_ids"]:
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
                    f'<a href="https://t.me/{BOT_USERNAME}?start={token}">{label_for(msg_type)}</a>'
                )

        if blocks:
            send_text(owner_id, "🗑 <b>Удалено сообщение</b>\n\n" + "\n".join(blocks))

        return "ok"

    # 4️⃣ /start
    if "message" in data:
        msg = data["message"]
        if msg.get("text", "").startswith("/start "):
            owner_id = msg["from"]["id"]
            token = msg["text"].split(" ", 1)[1]

            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    SELECT msg_type, file_id
                    FROM messages
                    WHERE owner_id=%s AND token=%s
                    """, (owner_id, token))
                    r = cur.fetchone()

            if not r:
                send_text(owner_id, "❌ Файл недоступен")
                return "ok"

            send_media(owner_id, r[0], r[1], token)
            return "ok"

    return "ok"

# ================= START =================

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000)
