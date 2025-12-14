# -*- coding: utf-8 -*-
import re
import os
import uuid
import time
import psycopg2
import requests
import html
from flask import Flask, request

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
BOT_USERNAME = "EyesSeeBot"  # без @

app = Flask(__name__)

message_history = {}

# ================= DB =================

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS owners (
                business_connection_id TEXT PRIMARY KEY,
                owner_id BIGINT NOT NULL
            )
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                owner_id BIGINT NOT NULL,
                chat_id BIGINT NOT NULL,
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

def save_owner(bc_id, owner_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO owners (business_connection_id, owner_id)
            VALUES (%s, %s)
            ON CONFLICT (business_connection_id)
            DO UPDATE SET owner_id = EXCLUDED.owner_id
            """, (bc_id, owner_id))
        conn.commit()

def get_owner(bc_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT owner_id FROM owners WHERE business_connection_id=%s", (bc_id,))
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

# ================= HELPERS =================

def label_for(msg_type):
    return {
        "photo": "📷 Фотография",
        "video": "🎥 Видео",
        "video_note": "🎥 Видеосообщение",
        "voice": "🎤 Голосовое сообщение",
        "document": "📎 Файл",
        "text": "💬 Сообщение"
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
        bc = data["business_connection"]
        bc_id = bc.get("id") or bc.get("business_connection_id")
        owner_id = bc["user"]["id"]
        if bc_id:
            save_owner(bc_id, owner_id)
        return "ok"

    # 2) business message
    if "business_message" in data:
        msg = data["business_message"]
        bc_id = msg.get("business_connection_id")
        owner_id = get_owner(bc_id)
        if not owner_id:
            return "ok"

        sender = msg.get("from", {})
        if sender.get("id") == owner_id:
            return "ok"

        msg_type = "text"
        file_id = None
        text = msg.get("text")

        token = uuid.uuid4().hex[:10]

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                INSERT INTO messages
                (owner_id, chat_id, sender_id, sender_name, message_id, msg_type, text, file_id, token)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    owner_id,
                    msg["chat"]["id"],
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

    # 3) команды
    if "message" in data:
        msg = data["message"]
        chat_id = msg["chat"]["id"]
        owner_id = msg["from"]["id"]
        text = (msg.get("text") or "").strip()

        # ===== /recover =====
        if text == "/recover":
            tg("deleteMessage", {
                "chat_id": chat_id,
                "message_id": msg["message_id"]
            })

            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    SELECT DISTINCT ON (chat_id)
                        chat_id, sender_name
                    FROM messages
                    WHERE owner_id = %s
                    ORDER BY chat_id, created_at DESC
                    """, (owner_id,))
                    rows = cur.fetchall()

            buttons = []
            for chat_id_db, name in rows:
                buttons.append([{
                    "text": f"👤 {name}",
                    "callback_data": f"recover_chat:{chat_id_db}"
                }])

            buttons.append([{
                "text": "✖️ Скрыть",
                "callback_data": "hide_menu"
            }])

            send_text(
                chat_id,
                "<b>Выбери чат, который хочешь восстановить:</b>",
                {"inline_keyboard": buttons}
            )
            return "ok"

    # 4) callbacks
    if "callback_query" in data:
        cq = data["callback_query"]
        data_cb = cq["data"]
        msg = cq["message"]

        # скрыть
        if data_cb == "hide_menu":
            tg("deleteMessage", {
                "chat_id": msg["chat"]["id"],
                "message_id": msg["message_id"]
            })
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
            return "ok"

        # восстановление чата
        if data_cb.startswith("recover_chat:"):
            chat_id_target = int(data_cb.split(":")[1])

            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    SELECT msg_type, text, sender_name
                    FROM messages
                    WHERE owner_id=%s AND chat_id=%s
                    ORDER BY created_at ASC
                    LIMIT 5
                    """, (cq["from"]["id"], chat_id_target))
                    rows = cur.fetchall()

            blocks = []
            for msg_type, text, name in rows:
                if msg_type == "text":
                    blocks.append(f"<b>{html.escape(name)}:</b> {html.escape(text or '')}")

            send_text(
                msg["chat"]["id"],
                "<b>Восстановленные сообщения:</b>\n\n" + "\n".join(blocks)
            )

            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
            return "ok"

    return "ok"

# ================= START =================

if name == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000)
