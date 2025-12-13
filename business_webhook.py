import os
import uuid
import psycopg2
import requests
from flask import Flask, request

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

app = Flask(__name__)

# ================= DB =================

def db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                owner_id BIGINT,
                message_id BIGINT,
                msg_type TEXT,
                text TEXT,
                file_id TEXT,
                token TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT NOW()
            )
            """)
        conn.commit()

def cleanup():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM messages
                WHERE created_at < NOW() - INTERVAL '18 hours'
            """)
        conn.commit()

# ================= TG API =================

def tg(method, payload):
    return requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
        json=payload
    )

def send_message(chat_id, text, buttons=None):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if buttons:
        data["reply_markup"] = {"inline_keyboard": buttons}
    tg("sendMessage", data)

def send_file(chat_id, msg_type, file_id):
    method = {
        "photo": "sendPhoto",
        "video": "sendVideo",
        "video_note": "sendVideoNote",
        "voice": "sendVoice"
    }[msg_type]

    payload_key = "video_note" if msg_type == "video_note" else msg_type

    r = tg(method, {
        "chat_id": chat_id,
        payload_key: file_id,
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "✖️ Скрыть", "callback_data": "hide"}
            ]]
        }
    })
    return r.json().get("result", {}).get("message_id")

# ================= WEBHOOK =================

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    cleanup()

    if not data:
        return "ok"

    # ---------- СООБЩЕНИЕ ОТ СОБЕСЕДНИКА ----------
    if "business_message" in data:
        msg = data["business_message"]
        owner_id = msg["business_connection_id"]
        sender_id = msg["from"]["id"]

        # игнорируем сообщения владельца
        if sender_id == owner_id:
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

        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO messages
                    (owner_id, message_id, msg_type, text, file_id, token)
                    VALUES (%s,%s,%s,%s,%s,%s)
                """, (
                    owner_id,
                    msg["message_id"],
                    msg_type,
                    text,
                    file_id,
                    token
                ))
            conn.commit()

    # ---------- УДАЛЕНИЕ СООБЩЕНИЯ ----------
    elif "deleted_business_messages" in data:
        d = data["deleted_business_messages"]
        owner_id = d["business_connection_id"]

        for mid in d["message_ids"]:
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT msg_type, text, file_id, token
                        FROM messages
                        WHERE message_id = %s
                    """, (mid,))
                    row = cur.fetchone()

            if not row:
                continue

            msg_type, text, file_id, token = row

            header = "🗑 <b>Новое удалённое сообщение</b>\n\n"

            if msg_type == "text":
                body = f"<blockquote>{text}</blockquote>"
                send_message(owner_id, header + body)
            else:
                labels = {
                    "photo": "📷 Фотография",
                    "video": "📹 Видео",
                    "video_note": "📹 Видеосообщение",
                    "voice": "🎤 Голосовое сообщение"
                }

                send_message(
                    owner_id,
                    header + labels[msg_type],
                    buttons=[[{
                        "text": labels[msg_type],
                        "callback_data": f"open:{token}"
                    }]]
                )

    # ---------- CALLBACK ----------
    elif "callback_query" in data:
        cq = data["callback_query"]
        chat_id = cq["message"]["chat"]["id"]
        msg_id = cq["message"]["message_id"]
        data_cb = cq["data"]

        if data_cb == "hide":
            tg("deleteMessage", {
                "chat_id": chat_id,
                "message_id": msg_id
            })
            return "ok"

        if data_cb.startswith("open:"):
            token = data_cb.split(":")[1]

            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT msg_type, file_id
                        FROM messages
                        WHERE token = %s
                    """, (token,))
                    row = cur.fetchone()

            if not row:
                send_message(chat_id, "❌ Файл недоступен (прошло больше 18 часов)")
                return "ok"

            msg_type, file_id = row
            send_file(chat_id, msg_type, file_id)

    return "ok"

# ================= START =================

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000)
