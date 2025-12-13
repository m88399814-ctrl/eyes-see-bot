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
            # Таблица владельцев (для нескольких бизнес-подключений)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS owners (
                business_connection_id TEXT PRIMARY KEY,
                owner_id BIGINT NOT NULL
            )
            """)
            # Таблица сообщений
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
    # Сохранить ID владельца для данного бизнес-подключения
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
    # Получить ID владельца по идентификатору бизнес-подключения
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

def hide_markup(token: str):
    return {
        "inline_keyboard": [
            [{"text": "✖️ Скрыть", "callback_data": f"hide:{token}"}]
        ]
    }

def send_media(chat_id, msg_type, file_id, token):
    hide = hide_markup(token)
    try:
        if msg_type == "photo":
            r = tg("sendPhoto", {"chat_id": chat_id, "photo": file_id, "reply_markup": hide})
            if not r.ok:
                r2 = tg("sendDocument", {"chat_id": chat_id, "document": file_id, "reply_markup": hide})
                if not r2.ok:
                    raise Exception("Photo send failed")
            return

        if msg_type == "video":
            r = tg("sendVideo", {"chat_id": chat_id, "video": file_id, "reply_markup": hide})
            if not r.ok:
                raise Exception("Video send failed")
            return

        if msg_type == "voice":
            r = tg("sendVoice", {"chat_id": chat_id, "voice": file_id, "reply_markup": hide})
            if not r.ok:
                raise Exception("Voice send failed")
            return

        if msg_type == "video_note":
            r = tg("sendVideoNote", {"chat_id": chat_id, "video_note": file_id, "reply_markup": hide})
            if not r.ok:
                r2 = tg("sendVideo", {"chat_id": chat_id, "video": file_id, "reply_markup": hide})
                if not r2.ok:
                    raise Exception("Video note send failed")
            return

        # документ или неизвестный тип
        r = tg("sendDocument", {"chat_id": chat_id, "document": file_id, "reply_markup": hide})
        if not r.ok:
            raise Exception("Document send failed")

    except Exception:
        # Fallback: пробуем получить файл и отправить по URL
        resp = tg("getFile", {"file_id": file_id})
        if not resp.ok:
            send_text(chat_id,
                      "❌ <b>Не получилось открыть файл</b> 😔\nВозможно он уже исчез / недоступен",
                      hide)
            return
        data = resp.json()
        if not data.get("ok") or "result" not in data:
            send_text(chat_id,
                      "❌ <b>Не получилось открыть файл</b> 😔\nВозможно он уже исчез / недоступен",
                      hide)
            return
        file_path = data["result"].get("file_path")
        if not file_path:
            send_text(chat_id,
                      "❌ <b>Не получилось открыть файл</b> 😔\nВозможно он уже исчез / недоступен",
                      hide)
            return

        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        # Отправляем по URL в зависимости от типа:
        if msg_type == "photo":
            r3 = tg("sendPhoto", {"chat_id": chat_id, "photo": file_url, "reply_markup": hide})
            if not r3.ok:
                send_text(chat_id,
                          "❌ <b>Не получилось открыть файл</b> 😔\nВозможно он уже исчез / недоступен",
                          hide)
            return

        if msg_type == "video":
            r3 = tg("sendVideo", {"chat_id": chat_id, "video": file_url, "reply_markup": hide})
            if not r3.ok:
                send_text(chat_id,
                          "❌ <b>Не получилось открыть файл</b> 😔\nВозможно он уже исчез / недоступен",
                          hide)
            return

        if msg_type == "voice":
            r3 = tg("sendVoice", {"chat_id": chat_id, "voice": file_url, "reply_markup": hide})
            if not r3.ok:
                send_text(chat_id,
                          "❌ <b>Не получилось открыть файл</b> 😔\nВозможно он уже исчез / недоступен",
                          hide)
            return

        if msg_type == "video_note":
            # Пробуем как видеосообщение; если не выйдет – как обычное видео
            r3 = tg("sendVideoNote", {"chat_id": chat_id, "video_note": file_url, "reply_markup": hide})
            if not r3.ok:
                r4 = tg("sendVideo", {"chat_id": chat_id, "video": file_url, "reply_markup": hide})
                if not r4.ok:
                    send_text(chat_id,
                              "❌ <b>Не получилось открыть файл</b> 😔\nВозможно он уже исчез / недоступен",
                              hide)
            return

        if msg_type == "document":
            # Если документ – пытаемся определить, не фото или видео ли это по расширению
            ext = ""
            if "." in file_path:
                ext = file_path.split(".")[-1].lower()
            if ext in ("jpg", "jpeg", "png", "gif", "webp"):
                r3 = tg("sendPhoto", {"chat_id": chat_id, "photo": file_url, "reply_markup": hide})
                if r3.ok:
                    return
            if ext in ("mp4", "mov", "webm"):
                r3 = tg("sendVideo", {"chat_id": chat_id, "video": file_url, "reply_markup": hide})
                if r3.ok:
                    return
            # Иначе отправляем как документ
            r3 = tg("sendDocument", {"chat_id": chat_id, "document": file_url, "reply_markup": hide})
            if not r3.ok:
                send_text(chat_id,
                          "❌ <b>Не получилось открыть файл</b> 😔\nВозможно он уже исчез / недоступен",
                          hide)
            return

        # На всякий случай для прочих типов – отправляем как документ по URL
        r3 = tg("sendDocument", {"chat_id": chat_id, "document": file_url, "reply_markup": hide})
        if not r3.ok:
            send_text(chat_id,
                      "❌ <b>Не получилось открыть файл</b> 😔\nВозможно он уже исчез / недоступен",
                      hide)
        return

def media_from_message(m):
    # 1) photo (иногда пустой список — проверяем)
    if "photo" in m and isinstance(m["photo"], list) and len(m["photo"]) > 0:
        return "photo", m["photo"][-1].get("file_id")

    # 2) video_note
    if "video_note" in m and isinstance(m["video_note"], dict):
        return "video_note", m["video_note"].get("file_id")

    # 3) voice
    if "voice" in m and isinstance(m["voice"], dict):
        return "voice", m["voice"].get("file_id")

    # 4) video
    if "video" in m and isinstance(m["video"], dict):
        return "video", m["video"].get("file_id")

    # 5) document (часто исчезающее фото приходит сюда)
    if "document" in m and isinstance(m["document"], dict):
        fid = m["document"].get("file_id")
        mime = (m["document"].get("mime_type") or "").lower()
        if mime.startswith("image/"):
            return "photo", fid  # попробуем как photo (fallback внутри send_media есть)
        return "document", fid

    # 6) animation (редко)
    if "animation" in m and isinstance(m["animation"], dict):
        return "video", m["animation"].get("file_id")

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

    # 1) подключение бизнес-аккаунта
    if "business_connection" in data:
        bc = data["business_connection"]
        bc_id = bc.get("id") or bc.get("business_connection_id")
        owner_id = bc["user"]["id"]
        if bc_id:
            save_owner(bc_id, owner_id)
        return "ok"

    # 2) входящее сообщение
    if "business_message" in data:
        msg = data["business_message"]
        bc_id = msg.get("business_connection_id")
        owner_id = get_owner(bc_id)
        if not owner_id:
            return "ok"

        sender = msg.get("from", {})

        # 2.1) Исчезающее: владелец ответил (reply) на сообщение
        if sender.get("id") == owner_id and "reply_to_message" in msg:
            replied = msg["reply_to_message"]

            msg_type, file_id = media_from_message(replied)
            if not msg_type or not file_id:
                return "ok"

            # антидубликат по file_id
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM messages WHERE owner_id=%s AND file_id=%s LIMIT 1",
                                (owner_id, file_id))
                    if cur.fetchone():
                        return "ok"

            token = uuid.uuid4().hex[:10]

            # сохраняем
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    INSERT INTO messages
                    (owner_id, sender_id, sender_name, message_id, msg_type, text, file_id, token)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (
                        owner_id,
                        replied.get("from", {}).get("id", 0),
                        replied.get("from", {}).get("first_name", "Без имени"),
                        replied.get("message_id", 0),
                        msg_type,
                        None,
                        file_id,
                        token
                    ))
                conn.commit()

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

        # если это не медиа и нет текста — просто игнор
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

    # 3) удаление сообщений (группировка 1 сек)
    if "deleted_business_messages" in data:
        dbm = data["deleted_business_messages"]
        bc_id = dbm.get("business_connection_id")
        owner_id = get_owner(bc_id)
        if not owner_id:
            return "ok"
        time.sleep(1)

        blocks = []
        sender_id = None
        sender_name = None

        mids = dbm.get("message_ids", [])
        for mid in mids:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    SELECT msg_type, text, sender_name, sender_id, token
                    FROM messages
                    WHERE owner_id = %s AND message_id = %s
                    """, (owner_id, mid))
                    r = cur.fetchone()

            if not r:
                continue

            msg_type, text, sender_name, sender_id, token = r

            if msg_type == "text":
                blocks.append(f"<blockquote>{text}</blockquote>")
            else:
                blocks.append(
                    f'<a href="https://t.me/{BOT_USERNAME}?start={token}">{label_for(msg_type)}</a>'
                )

        if blocks:
            title = (
                "🗑 <b>Новое удалённое сообщение</b>\n\n"
                if len(blocks) == 1
                else "🗑 <b>Новые удалённые сообщения</b>\n\n"
            )

            who = ""
            if sender_id and sender_name:
                who = f'\n\nУдалил(а): <a href="tg://user?id={sender_id}">{sender_name}</a>'

            send_text(owner_id, title + "\n".join(blocks) + who)

        return "ok"

    # 4) /start TOKEN → открыть файл
    if "message" in data:
        msg = data["message"]
        owner_id = msg["from"]["id"]
        text = msg.get("text", "")
        chat_id = msg["chat"]["id"]

        if text.startswith("/start "):
            # удаляем команду
            tg("deleteMessage", {
                "chat_id": chat_id,
                "message_id": msg["message_id"]
            })

            token = text.split(" ", 1)[1].strip()

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
                    hide_markup("error")
                )
                return "ok"

            msg_type, file_id = r
            send_media(chat_id, msg_type, file_id, token)
            return "ok"

    # 5) кнопка Скрыть
    if "callback_query" in data:
        cq = data["callback_query"]
        m = cq.get("message")
        if m:
            tg("deleteMessage", {
                "chat_id": m["chat"]["id"],
                "message_id": m["message_id"]
            })
        tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        return "ok"

    return "ok"

# ================= START =================

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000)
