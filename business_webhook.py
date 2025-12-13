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
            r = cur.fetchone()
            return r[0] if r else None

# ================= TG API =================

def tg(method, payload):
    return requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
        json=payload,
        timeout=15
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

def send_media(chat_id, msg_type, file_id, token):
    hide = {
        "inline_keyboard": [
            [{"text": "✖️ Скрыть", "callback_data": f"hide:{token}"}]
        ]
    }

    try:
        if msg_type == "photo":
            r = tg("sendPhoto", {
                "chat_id": chat_id,
                "photo": file_id,
                "reply_markup": hide
            })

            # fallback как документ
            if not r.ok:
                tg("sendDocument", {
                    "chat_id": chat_id,
                    "document": file_id,
                    "reply_markup": hide
                })

        elif msg_type == "video":
            tg("sendVideo", {
                "chat_id": chat_id,
                "video": file_id,
                "reply_markup": hide
            })

        elif msg_type == "voice":
            tg("sendVoice", {
                "chat_id": chat_id,
                "voice": file_id,
                "reply_markup": hide
            })

        elif msg_type == "video_note":
            r = tg("sendVideoNote", {
                "chat_id": chat_id,
                "video_note": file_id
            })

            # fallback как видео
            if not r.ok:
                tg("sendVideo", {
                    "chat_id": chat_id,
                    "video": file_id,
                    "reply_markup": hide
                })

    except Exception:
        send_text(
            chat_id,
            "❌ <b>Не получилось открыть файл</b> 😔\n"
            "Возможно, это исчезающее сообщение",
            hide
        )

def media_from_message(msg):
    if "photo" in msg:
        return "photo", msg["photo"][-1]["file_id"]
    if "video" in msg:
        return "video", msg["video"]["file_id"]
    if "video_note" in msg:
        return "video_note", msg["video_note"]["file_id"]
    if "voice" in msg:
        return "voice", msg["voice"]["file_id"]
    return None, None

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

    # 2) сохраняем сообщения собеседника
    if "business_message" in data:
        msg = data["business_message"]
        sender = msg["from"]
            # 🔐 ИСЧЕЗАЮЩИЕ СООБЩЕНИЯ (через reply)
        if "business_message" in data:
            msg = data["business_message"]
            sender = msg["from"]
    
            # реагируем ТОЛЬКО на reply владельца
            if sender["id"] == owner_id and "reply_to_message" in msg:
                replied = msg["reply_to_message"]
    
                msg_type, file_id = media_from_message(replied)
                if not msg_type:
                    return "ok"
    
                # проверяем, не сохраняли ли уже этот файл
                with get_db() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT 1 FROM messages WHERE file_id = %s LIMIT 1",
                            (file_id,)
                        )
                        if cur.fetchone():
                            return "ok"
    
                token = uuid.uuid4().hex[:10]
    
                # сохраняем
                with get_db() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                        INSERT INTO messages
                        (owner_id, sender_id, sender_name, message_id,
                         msg_type, text, file_id, token)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        """, (
                            owner_id,
                            replied["from"]["id"],
                            replied["from"].get("first_name", "Без имени"),
                            replied["message_id"],
                            msg_type,
                            None,
                            file_id,
                            token
                        ))
    
                labels = {
                    "photo": "📷 Фотография",
                    "video": "🎥 Видео",
                    "video_note": "🎥 Видеосообщение",
                    "voice": "🎤 Голосовое сообщение"
                }
    
                header = "⌛️ <b>Новое исчезающее сообщение:</b>\n\n"
                body = f'<a href="https://t.me/{BOT_USERNAME}?start={token}">{labels[msg_type]}</a>'
                who = f'\n\nОтправил(а): <a href="tg://user?id={replied["from"]["id"]}">{replied["from"].get("first_name","")}</a>'
    
                send_text(owner_id, header + body + who)
    
                return "ok"
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

    # 3) удаление сообщений (группировка 1 сек)
    if "deleted_business_messages" in data:
        time.sleep(1)

        blocks = []
        sender_id = None
        sender_name = None

        for mid in data["deleted_business_messages"].get("message_ids", []):
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    SELECT msg_type, text, file_id, sender_name, sender_id, token
                    FROM messages
                    WHERE owner_id = %s AND message_id = %s
                    """, (owner_id, mid))
                    r = cur.fetchone()

            if not r:
                continue

            msg_type, text, file_id, sender_name, sender_id, token = r

            if msg_type == "text":
                blocks.append(f"<blockquote>{text}</blockquote>")
            else:
                label = {
                    "photo": "📷 Фотография",
                    "video": "🎥 Видео",
                    "video_note": "🎥 Видеосообщение",
                    "voice": "🎤 Голосовое сообщение"
                }[msg_type]

                link = f'<a href="https://t.me/{BOT_USERNAME}?start={token}">{label}</a>'
                blocks.append(link)

        if blocks:
            who = f'\n\nУдалил(а): <a href="tg://user?id={sender_id}">{sender_name}</a>'
            title = (
                "🗑 <b>Новое удалённое сообщение</b>\n\n"
                if len(blocks) == 1
                else "🗑 <b>Новые удалённые сообщения</b>\n\n"
            )

            send_text(
                owner_id,
                title +
                "\n".join(blocks) +
                who
            )
        return "ok"

    # 4) /start TOKEN → открыть файл
    if "message" in data:
        msg = data["message"]
        text = msg.get("text", "")
        chat_id = msg["chat"]["id"]

        if text.startswith("/start "):
            tg("deleteMessage", {
                "chat_id": chat_id,
                "message_id": msg["message_id"]
            })

            token = text.split(" ", 1)[1]

            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    SELECT msg_type, file_id
                    FROM messages
                    WHERE owner_id = %s AND token = %s
                    """, (owner_id, token))
                    r = cur.fetchone()

            if not r:
                send_text(
                    chat_id,
                    "❌ <b>Не получилось открыть файл</b> 😔\n"
                    "Возможно он был отправлен слишком давно",
                    {
                        "inline_keyboard": [
                            [{"text": "✖️ Скрыть", "callback_data": "hide:error"}]
                        ]
                    }
                )
                return "ok"

            send_media(chat_id, r[0], r[1], token)
            return "ok"

    # 5) кнопка Скрыть
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
