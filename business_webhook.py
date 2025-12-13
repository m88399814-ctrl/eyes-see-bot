import os
import time
import json
import requests
import psycopg2
from flask import Flask, request

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

RETENTION_SECONDS = 18 * 60 * 60  # 18 часов

app = Flask(__name__)

# ---------- DB ----------

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                owner_id BIGINT,
                chat_id BIGINT,
                message_id BIGINT,
                sender_id BIGINT,
                type TEXT,
                content TEXT,
                file_id TEXT,
                created_at BIGINT
            )
            """)
        conn.commit()

init_db()

def cleanup_old():
    cutoff = int(time.time()) - RETENTION_SECONDS
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM messages WHERE created_at < %s", (cutoff,))
        conn.commit()

# ---------- Telegram helpers ----------

def send_message(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(f"{API_URL}/sendMessage", json=payload)

def send_file(chat_id, msg):
    try:
        if msg["type"] == "photo":
            requests.post(f"{API_URL}/sendPhoto", json={
                "chat_id": chat_id,
                "photo": msg["file_id"]
            })
        elif msg["type"] == "voice":
            requests.post(f"{API_URL}/sendVoice", json={
                "chat_id": chat_id,
                "voice": msg["file_id"]
            })
        elif msg["type"] == "video_note":
            requests.post(f"{API_URL}/sendVideoNote", json={
                "chat_id": chat_id,
                "video_note": msg["file_id"]
            })
        elif msg["type"] == "video":
            requests.post(f"{API_URL}/sendVideo", json={
                "chat_id": chat_id,
                "video": msg["file_id"]
            })
    except:
        send_message(chat_id, "❌ <b>Не получилось открыть файл</b> 😔\nВозможно он был отправлен слишком давно")

# ---------- Webhook ----------

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    if not data:
        return "ok"

    cleanup_old()

    # OWNER
    if "business_connection" in data:
        owner_id = data["business_connection"]["user"]["id"]
        return "ok"

    # MESSAGE
    if "business_message" in data:
        msg = data["business_message"]
        owner_id = msg["from"]["id"] if msg["from"]["is_bot"] is False else None
        chat_id = msg["chat"]["id"]
        sender_id = msg["from"]["id"]

        # владелец → не сохраняем
        if sender_id == owner_id:
            return "ok"

        msg_type = "text"
        content = msg.get("text")
        file_id = None

        if "photo" in msg:
            msg_type = "photo"
            file_id = msg["photo"][-1]["file_id"]
        elif "voice" in msg:
            msg_type = "voice"
            file_id = msg["voice"]["file_id"]
        elif "video_note" in msg:
            msg_type = "video_note"
            file_id = msg["video_note"]["file_id"]
        elif "video" in msg:
            msg_type = "video"
            file_id = msg["video"]["file_id"]

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                INSERT INTO messages (owner_id, chat_id, message_id, sender_id, type, content, file_id, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    owner_id,
                    chat_id,
                    msg["message_id"],
                    sender_id,
                    msg_type,
                    content,
                    file_id,
                    int(time.time())
                ))
            conn.commit()

    # DELETE
    if "deleted_business_messages" in data:
        deleted = data["deleted_business_messages"]
        chat_id = deleted["chat"]["id"]

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                SELECT * FROM messages
                WHERE chat_id=%s AND message_id = ANY(%s)
                """, (chat_id, deleted["message_ids"]))
                rows = cur.fetchall()

        for r in rows:
            msg = {
                "type": r[5],
                "content": r[6],
                "file_id": r[7]
            }

            label = {
                "photo": "📷 Фотография",
                "voice": "🎤 Голосовое сообщение",
                "video_note": "📹 Видеосообщение",
                "video": "📹 Видео",
                "text": msg["content"]
            }.get(msg["type"], "Сообщение")

            keyboard = {
                "inline_keyboard": [[
                    {
                        "text": label,
                        "callback_data": f"open_{r[0]}"
                    }
                ]]
            }

            send_message(
                r[1],
                "🗑 <b>Новое удалённое сообщение</b>",
                keyboard
            )

    # CALLBACK
    if "callback_query" in data:
        cq = data["callback_query"]
        chat_id = cq["message"]["chat"]["id"]
        msg_id = int(cq["data"].split("_")[1])

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM messages WHERE id=%s", (msg_id,))
                row = cur.fetchone()

        if not row:
            send_message(chat_id, "❌ <b>Не получилось открыть файл</b> 😔\nВозможно он был отправлен слишком давно")
            return "ok"

        send_file(chat_id, {
            "type": row[5],
            "file_id": row[7]
        })

    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
