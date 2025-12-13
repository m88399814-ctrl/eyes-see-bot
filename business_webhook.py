from flask import Flask, request
import requests
import sqlite3
import json

app = Flask(__name__)

DB_NAME = "eyessee.db"
OWNER_ID = None


# ---------- DB ----------
def get_db():
    return sqlite3.connect(DB_NAME)


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            message_id INTEGER PRIMARY KEY,
            chat_id INTEGER,
            sender_id INTEGER,
            sender_name TEXT,
            type TEXT,
            content TEXT,
            file_id TEXT,
            date INTEGER
        )
    """)
    conn.commit()
    conn.close()


# ---------- SEND ----------
def send_to_owner(text):
    if not OWNER_ID:
        return

    token = get_token()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": OWNER_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    requests.post(url, json=payload)


def get_token():
    import os
    return os.getenv("BOT_TOKEN")


# ---------- WEBHOOK ----------
@app.route("/webhook", methods=["POST"])
def webhook():
    global OWNER_ID
    data = request.get_json(silent=True)

    print("\n========== RAW UPDATE ==========")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print("================================")

    if not data:
        return "ok"

    # 🔑 бизнес-подключение
    if "business_connection" in data:
        OWNER_ID = data["business_connection"]["user"]["id"]
        print(f"✅ OWNER CONNECTED: {OWNER_ID}")
        return "ok"

    # 📩 новое сообщение — сохраняем
    if "business_message" in data:
        msg = data["business_message"]

        msg_type = "text"
        content = msg.get("text")
        file_id = None

        if "photo" in msg:
            msg_type = "photo"
            file_id = msg["photo"][-1]["file_id"]
        elif "voice" in msg:
            msg_type = "voice"
            file_id = msg["voice"]["file_id"]
        elif "video" in msg:
            msg_type = "video"
            file_id = msg["video"]["file_id"]

        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO messages
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            msg["message_id"],
            msg["chat"]["id"],
            msg["from"]["id"],
            msg["from"].get("first_name", "Без имени"),
            msg_type,
            content,
            file_id,
            msg["date"]
        ))
        conn.commit()
        conn.close()
        return "ok"

    # 🗑 удалённые сообщения
    if "deleted_business_messages" in data:
        ids = data["deleted_business_messages"]["message_ids"]

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            f"SELECT sender_id, sender_name, type, content FROM messages WHERE message_id IN ({','.join('?'*len(ids))})",
            ids
        )
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return "ok"

        sender_id, sender_name, mtype, content = rows[0]
        sender_link = f'<a href="tg://user?id={sender_id}">{sender_name}</a>'

        if len(rows) == 1:
            text = "🗑 <b>Новое удалённое сообщение</b>\n\n"
            if mtype == "text":
                text += f"<blockquote>{content}</blockquote>\n\n"
            elif mtype == "photo":
                text += "📷 Фотография\n\n"
            elif mtype == "voice":
                text += "🎤 Голосовое сообщение\n\n"
            elif mtype == "video":
                text += "📹 Видеосообщение\n\n"
            text += f"Удалил(а): {sender_link}"
        else:
            text = "🗑 <b>Новые удалённые сообщения</b>\n\n"
            for _, _, t, c in rows:
                if t == "text":
                    text += f"<blockquote>{c}</blockquote>\n"
                else:
                    text += f"[{t}]\n"
            text += f"\nУдалил(а): {sender_link}"

        send_to_owner(text)
        return "ok"

    # ✏️ изменённое сообщение
    if "edited_business_message" in data:
        msg = data["edited_business_message"]

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT content FROM messages WHERE message_id=?", (msg["message_id"],))
        row = cur.fetchone()

        if row:
            old_text = row[0]
            new_text = msg.get("text")
            cur.execute("UPDATE messages SET content=? WHERE message_id=?", (new_text, msg["message_id"]))
            conn.commit()

            sender = msg["from"]
            sender_link = f'<a href="tg://user?id={sender["id"]}">{sender.get("first_name")}</a>'

            text = (
                "✏️ <b>Новое изменённое сообщение</b>\n\n"
                "<b>Старый текст:</b>\n"
                f"<blockquote>{old_text}</blockquote>\n\n"
                "<b>Новый текст:</b>\n"
                f"<blockquote>{new_text}</blockquote>\n\n"
                f"Изменил(а): {sender_link}"
            )
            send_to_owner(text)

        conn.close()
        return "ok"

    return "ok"


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000)
