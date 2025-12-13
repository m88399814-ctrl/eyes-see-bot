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

def hide_markup(token: str):
    return {
        "inline_keyboard": [
            [{"text": "✖️ Скрыть", "callback_data": f"hide:{token}"}]
        ]
    }

def media_from_message(m):
    # photo
    if "photo" in m and isinstance(m["photo"], list) and len(m["photo"]) > 0:
        return "photo", m["photo"][-1].get("file_id")

    # video_note (кружок)
    if "video_note" in m and isinstance(m["video_note"], dict):
        return "video_note", m["video_note"].get("file_id")

    # voice
    if "voice" in m and isinstance(m["voice"], dict):
        return "voice", m["voice"].get("file_id")

    # video
    if "video" in m and isinstance(m["video"], dict):
        return "video", m["video"].get("file_id")

    # иногда исчезающее фото приходит как document
    if "document" in m and isinstance(m["document"], dict):
        fid = m["document"].get("file_id")
        mime = (m["document"].get("mime_type") or "").lower()
        if mime.startswith("image/"):
            return "photo", fid
        return "document", fid

    return None, None

def label_for(msg_type: str) -> str:
    return {
        "photo": "📷 Фотография",
        "video": "🎥 Видео",
        "video_note": "🎥 Видеосообщение",
        "voice": "🎤 Голосовое сообщение",
        "document": "📎 Файл"
    }.get(msg_type, "📎 Файл")

# ================= WEBHOOK =================

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    cleanup_old()

    if not data:
        return "ok"

    # 1) business connection
    if "business_connection" in data:
        save_owner(data["business_connection"]["user"]["id"])
        return "ok"

    owner_id = get_owner()
    if not owner_id:
        return "ok"

    # 2) business_message
    if "business_message" in data:
        msg = data["business_message"]
        sender = msg.get("from", {})

        # 2.1) Исчезающее: владелец ответил (reply) на сообщение
        if sender.get("id") == owner_id and "reply_to_message" in msg:
            replied = msg["reply_to_message"]

            msg_type, file_id = media_from_message(replied)
            if not msg_type:
                return "ok"

            # ВАЖНО: src_chat_id — это чат текущего business_message (тот же диалог)
            src_chat_id = msg["chat"]["id"]
            src_message_id = replied.get("message_id")

            if not src_message_id:
                return "ok"

            # антидубликат по (src_chat_id, src_message_id)
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 1 FROM messages
                        WHERE owner_id=%s AND src_chat_id=%s AND src_message_id=%s
                        LIMIT 1
                    """, (owner_id, src_chat_id, src_message_id))
                    if cur.fetchone():
                        return "ok"

            token = uuid.uuid4().hex[:10]

            # сохраняем token + источник
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    INSERT INTO messages
                    (owner_id, sender_id, sender_name, message_id, msg_type, text, file_id, token, src_chat_id, src_message_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (
                        owner_id,
                        replied.get("from", {}).get("id", 0),
                        replied.get("from", {}).get("first_name", "Без имени"),
                        replied.get("message_id", 0),
                        msg_type,
                        None,
                        file_id,
                        token,
                        src_chat_id,
                        src_message_id
                    ))
                conn.commit()

            # шлём ТОЛЬКО ссылку (как ты и хотел)
            header = "⌛️ <b>Новое исчезающее сообщение:</b>\n\n"
            body = f'<a href="https://t.me/{BOT_USERNAME}?start={token}">{label_for(msg_type)}</a>'
            sid = replied.get("from", {}).get("id", 0)
            sname = replied.get("from", {}).get("first_name", "Без имени")
            who = f'\n\nОтправил(а): <a href="tg://user?id={sid}">{sname}</a>'

            send_text(owner_id, header + body + who)
            return "ok"

        # 2.2) Сообщения владельца не сохраняем
        if sender.get("id") == owner_id:
            return "ok"

        # 2.3) Обычные сообщения собеседника -> сохраняем (для удалений)
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
                    sender.get("id", 0),
                    sender.get("first_name", "Без имени"),
                    msg.get("message_id", 0),
                    msg_type,
                    text,
                    file_id,
                    token
                ))
            conn.commit()

        return "ok"

    # 3) deleted messages (как было)
    if "deleted_business_messages" in data:
        time.sleep(1)
        # ... твой код удаления можешь оставить как есть ...
        return "ok"

    # 4) /start TOKEN → открыть (ВОТ ТУТ ГЛАВНОЕ!)
    if "message" in data:
        msg = data["message"]
        text = msg.get("text", "")
        chat_id = msg["chat"]["id"]

        if text.startswith("/start "):
            tg("deleteMessage", {"chat_id": chat_id, "message_id": msg["message_id"]})

            token = text.split(" ", 1)[1].strip()

            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    SELECT msg_type, file_id, src_chat_id, src_message_id
                    FROM messages
                    WHERE owner_id = %s AND token = %s
                    """, (owner_id, token))
                    r = cur.fetchone()

            if not r:
                send_text(chat_id, "❌ <b>Не получилось открыть</b>\nВозможно слишком старое.", hide_markup("error"))
                return "ok"

            msg_type, file_id, src_chat_id, src_message_id = r

            # ✅ ПРАВИЛЬНО: копируем оригинал по message_id (работает для фото и кружков)
            if src_chat_id and src_message_id:
                resp = tg("sendCopyMessage", {
                    "chat_id": chat_id,
                    "from_chat_id": src_chat_id,
                    "message_id": src_message_id,
                    "reply_markup": hide_markup(token)
                })
                if resp.ok:
                    return "ok"

            # fallback (на случай старых записей без src_*)
            if file_id:
                # голос/видео иногда пройдут
                if msg_type == "voice":
                    tg("sendVoice", {"chat_id": chat_id, "voice": file_id, "reply_markup": hide_markup(token)})
                    return "ok"
                if msg_type == "video":
                    tg("sendVideo", {"chat_id": chat_id, "video": file_id, "reply_markup": hide_markup(token)})
                    return "ok"

            send_text(chat_id, "❌ <b>Не получилось открыть</b>\nСообщение уже могло исчезнуть.", hide_markup(token))
            return "ok"

    # 5) hide button
    if "callback_query" in data:
        cq = data["callback_query"]
        m = cq.get("message")
        if m:
            tg("deleteMessage", {"chat_id": m["chat"]["id"], "message_id": m["message_id"]})
        tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        return "ok"

    return "ok"

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000)
