from flask import Flask, request
import requests
import sqlite3
import time
import json

BOT_TOKEN = "7557240631:AAFy8O4D-KMkwdlAI-QtV7AtVJ0hhdXgh90"
DB_NAME = "eyessee.db"

app = Flask(__name__)

OWNER_ID = None  # владелец бизнес-аккаунта


# ---------- DB ----------
def get_db():
    return sqlite3.connect(DB_NAME)


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            message_id INTEGER,
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
        print("❌ OWNER_ID не установлен")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": OWNER_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    requests.post(url, json=payload)


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

    # 📩 новое сообщение — СОХРАНЯЕМ
    if "business_message" in data:
        msg = data["business_message"]

        conn = get_db()
        cur = conn.cursor()

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

        cur.execute("""
            INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            msg["message_id"],
            msg["chat"]["id"],
            msg["from"]["id"],
            msg["from"].get("first_name", ""),
            msg_type,
            content,
            file_id,
            msg["date"]
        ))

        conn.commit()
        conn.close()
        return "ok"

    # 🗑 удаление
    if "deleted_business_messages" in data:
        ids = data["deleted_business_messages"]["message_ids"]

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT sender_name, type, content FROM messages
            WHERE message_id IN ({})
        """.format(",".join("?" * len(ids))), ids)

        rows = cur.fetchall()
        conn.close()

        if not rows:
            return "ok"

        if len(rows) == 1:
            sender, mtype, content = rows[0]
            text = "🗑 <b>Новое удалённое сообщение</b>\n\n"

            if mtype == "text":
                text += f"«{content}»\n\n"
            elif mtype == "photo":
                text += "📷 Фотография\n\n"
            elif mtype == "voice":
                text += "🎤 Голосовое сообщение\n\n"
            elif mtype == "video":
                text += "📹 Видеосообщение\n\n"

            text += f"Удалил(а): {sender}"

        else:
            text = "🗑 <b>Новые удалённые сообщения</b>\n\n"
            for sender, mtype, content in rows:
                if mtype == "text":
                    text += f"«{content}»\n"
                else:
                    text += f"[{mtype}]\n"

            text += f"\nУдалил(а): {rows[0][0]}"

        send_to_owner(text)
        return "ok"

    # ✏️ редактирование
    if "edited_business_message" in data:
        msg = data["edited_business_message"]

        old = None
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT content FROM messages WHERE message_id=?
        """, (msg["message_id"],))
        row = cur.fetchone()

        if row:
            old = row[0]
            cur.execute("""
                UPDATE messages SET content=? WHERE message_id=?
            """, (msg.get("text"), msg["message_id"]))
            conn.commit()

        conn.close()

        if old:
            text = (
                "✏️ <b>Новое изменённое сообщение</b>\n\n"
                f"<b>Старый текст:</b>\n{old}\n\n"
                f"<b>Новый текст:</b>\n{msg.get('text')}\n\n"
                f"Изменил(а): {msg['from'].get('first_name')}"
            )
            send_to_owner(text)

        return "ok"

    return "ok"


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000)
