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

# Словарь для хранения последнего известного текста сообщений (ключ: (owner_id, message_id))
message_history = {}

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
                chat_id BIGINT,
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

            # если у тебя старая таблица без chat_id — добавим (не ломает)
            cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name='messages' AND column_name='chat_id'
                ) THEN
                    ALTER TABLE messages ADD COLUMN chat_id BIGINT;
                END IF;
            END $$;
            """)

            # Таблица выбранного чата (чтобы /start показывал нужного юзера)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS active_chat (
                owner_id BIGINT PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                peer_id BIGINT NOT NULL,
                peer_name TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
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

def set_active_chat(owner_id: int, chat_id: int, peer_id: int, peer_name: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO active_chat (owner_id, chat_id, peer_id, peer_name)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (owner_id)
            DO UPDATE SET
                chat_id = EXCLUDED.chat_id,
                peer_id = EXCLUDED.peer_id,
                peer_name = EXCLUDED.peer_name,
                updated_at = NOW()
            """, (owner_id, chat_id, peer_id, peer_name))
        conn.commit()

def get_active_chat(owner_id: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT chat_id, peer_id, peer_name
            FROM active_chat
            WHERE owner_id = %s
            """, (owner_id,))
            r = cur.fetchone()
            if not r:
                return None
            return {"chat_id": r[0], "peer_id": r[1], "peer_name": r[2]}

def get_recent_peers(owner_id: int, limit: int = 8):
    # Берём последние разные чаты, чтобы ты мог выбрать нужного собеседника
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT DISTINCT ON (chat_id)
                chat_id,
                sender_id,
                sender_name,
                created_at
            FROM messages
            WHERE owner_id = %s
              AND chat_id IS NOT NULL
              AND sender_id != %s
              AND sender_id != 0
              AND sender_name IS NOT NULL
            ORDER BY chat_id, created_at DESC
            """, (owner_id, owner_id))
            rows = cur.fetchall()

    # отсортируем по времени (самые свежие сверху)
    rows = sorted(rows, key=lambda x: x[3], reverse=True)
    rows = rows[:limit]

    res = []
    for chat_id, sender_id, sender_name, _ in rows:
        res.append({
            "chat_id": int(chat_id),
            "peer_id": int(sender_id),
            "peer_name": str(sender_name)
        })
    return res

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

        r = tg("sendDocument", {"chat_id": chat_id, "document": file_id, "reply_markup": hide})
        if not r.ok:
            raise Exception("Document send failed")

    except Exception:
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
            r3 = tg("sendVideoNote", {"chat_id": chat_id, "video_note": file_url, "reply_markup": hide})
            if not r3.ok:
                r4 = tg("sendVideo", {"chat_id": chat_id, "video": file_url, "reply_markup": hide})
                if not r4.ok:
                    send_text(chat_id,
                              "❌ <b>Не получилось открыть файл</b> 😔\nВозможно он уже исчез / недоступен",
                              hide)
            return

        if msg_type == "document":
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
            r3 = tg("sendDocument", {"chat_id": chat_id, "document": file_url, "reply_markup": hide})
            if not r3.ok:
                send_text(chat_id,
                          "❌ <b>Не получилось открыть файл</b> 😔\nВозможно он уже исчез / недоступен",
                          hide)
            return

        r3 = tg("sendDocument", {"chat_id": chat_id, "document": file_url, "reply_markup": hide})
        if not r3.ok:
            send_text(chat_id,
                      "❌ <b>Не получилось открыть файл</b> 😔\nВозможно он уже исчез / недоступен",
                      hide)
        return

def media_from_message(m):
    if "photo" in m and isinstance(m["photo"], list) and len(m["photo"]) > 0:
        return "photo", m["photo"][-1].get("file_id")
    if "video_note" in m and isinstance(m["video_note"], dict):
        return "video_note", m["video_note"].get("file_id")
    if "voice" in m and isinstance(m["voice"], dict):
        return "voice", m["voice"].get("file_id")
    if "video" in m and isinstance(m["video"], dict):
        return "video", m["video"].get("file_id")
    if "document" in m and isinstance(m["document"], dict):
        fid = m["document"].get("file_id")
        mime = (m["document"].get("mime_type") or "").lower()
        if mime.startswith("image/"):
            return "photo", fid
        return "document", fid
    if "animation" in m and isinstance(m["animation"], dict):
        return "video", m["animation"].get("file_id")
    return None, None

def label_for(msg_type: str) -> str:
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
        chat_id = (msg.get("chat") or {}).get("id")

        # 2.1) Исчезающее: владелец ответил (reply) на сообщение
        if sender.get("id") == owner_id and "reply_to_message" in msg:
            replied = msg["reply_to_message"]

            msg_type, file_id = media_from_message(replied)
            if not msg_type or not file_id:
                return "ok"

            if not replied.get("has_protected_content"):
                return "ok"

            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM messages WHERE owner_id=%s AND file_id=%s LIMIT 1",
                                (owner_id, file_id))
                    if cur.fetchone():
                        return "ok"

            token = uuid.uuid4().hex[:10]

            rep_from = replied.get("from", {}) or {}
            rep_id = rep_from.get("id", 0)
            rep_name = rep_from.get("first_name", "Без имени")

            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    INSERT INTO messages
                    (owner_id, chat_id, sender_id, sender_name, message_id, msg_type, text, file_id, token)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (
                        owner_id,
                        chat_id,
                        rep_id,
                        rep_name,
                        replied.get("message_id", 0),
                        msg_type,
                        None,
                        file_id,
                        token
                    ))
                conn.commit()

            header = "⌛️ <b>Новое исчезающее сообщение:</b>\n\n"
            body = f'<a href="https://t.me/{BOT_USERNAME}?start={token}">{label_for(msg_type)}</a>'
            who = f'\n\n<b>Отправил(а):</b> <a href="tg://user?id={rep_id}">{html.escape(rep_name)}</a>'

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
                (owner_id, chat_id, sender_id, sender_name, message_id, msg_type, text, file_id, token)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    owner_id,
                    chat_id,
                    sender.get("id", 0),
                    sender.get("first_name", "Без имени"),
                    msg.get("message_id", 0),
                    msg_type,
                    text,
                    file_id,
                    token
                ))
            conn.commit()

        if text:
            message_history[(owner_id, msg.get("message_id"))] = text

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
                blocks.append(f"<blockquote>{html.escape(text or '')}</blockquote>")
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
                who = f'\n\n<b>Удалил(а):</b> <a href="tg://user?id={sender_id}">{html.escape(sender_name)}</a>'

            send_text(owner_id, title + "\n".join(blocks) + who)

        return "ok"

    # 4) изменение сообщений (группировка 1 сек)
    if "edited_business_message" in data:
        ebm = data["edited_business_message"]
        bc_id = ebm.get("business_connection_id")
        owner_id = get_owner(bc_id)
        if not owner_id:
            return "ok"
        time.sleep(1)

        mid = ebm.get("message_id")
        if not mid:
            return "ok"

        old_text = message_history.get((owner_id, mid), "")
        new_text = ebm.get("text") or ebm.get("caption") or ""
        message_history[(owner_id, mid)] = new_text

        editor_id = ebm.get("from", {}).get("id", 0)
        editor_name = f"{ebm.get('from', {}).get('first_name', '')} {ebm.get('from', {}).get('last_name', '')}".strip()
        editor_name = html.escape(editor_name)
        editor_link = f'<a href="tg://user?id={editor_id}">{editor_name}</a>'

        title = "✏️ <b>Новое изменённое сообщение</b>\n\n"
        body_old = (
            f"<blockquote>"
            f"<b>Старый текст:</b>\n"
            f"{html.escape(old_text)}"
            f"</blockquote>\n\n"
        )
        body_new = (
            f"<blockquote>"
            f"<b>Новый текст:</b>\n"
            f"{html.escape(new_text)}"
            f"</blockquote>\n\n"
        )
        who = f"<b>Изменил(а):</b> {editor_link}"

        send_text(owner_id, title + body_old + body_new + who)
        return "ok"

    # 5) /start и /start TOKEN (в личке с ботом)
    if "message" in data:
        msg = data["message"]
        owner_id = msg["from"]["id"]
        text = (msg.get("text") or "").strip()
        chat_id = msg["chat"]["id"]

        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            cmd = parts[0]
            payload = parts[1].strip() if len(parts) > 1 else ""

            if "@" in cmd and cmd != f"/start@{BOT_USERNAME}":
                return "ok"

            # /start <token>
            if payload and re.fullmatch(r"[0-9a-f]{10}", payload):
                tg("deleteMessage", {"chat_id": chat_id, "message_id": msg["message_id"]})

                token = payload
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
        # /recover — выбор чата для восстановления
        if text == "/recover" or text == f"/recover@{BOT_USERNAME}":
            tg("deleteMessage", {"chat_id": chat_id, "message_id": msg["message_id"]})
    
            peers = get_recent_peers(owner_id, limit=10)
    
            if not peers:
                send_text(chat_id, "❌ <b>Нет данных для восстановления</b>")
                return "ok"
    
            kb = []
            for p in peers:
                name = (p["peer_name"] or "пользователь").strip()
                if len(name) > 28:
                    name = name[:28] + "…"
                kb.append([{
                    "text": f"👤 {name}",
                    "callback_data": f"choose_chat:{p['chat_id']}:{p['peer_id']}"
                }])
    
            # кнопка СКРЫТЬ — ВСЕГДА В КОНЦЕ
            kb.append([{"text": "✖️ Скрыть", "callback_data": "hide:recover"}])
    
            send_text(
                chat_id,
                "<b>♻️ Восстановить чат</b>\n\nВыбери чат, который хочешь восстановить:",
                {"inline_keyboard": kb}
            )
            return "ok"

        return "ok"
    # 6) callback-кнопки
    if "callback_query" in data:
        cq = data["callback_query"]
        m = cq.get("message")
        chat_id = (m.get("chat") or {}).get("id") if m else None
        mid = m.get("message_id") if m else None

        owner_id = (cq.get("from") or {}).get("id", 0)
        cd = cq.get("data") or ""
        print("CALLBACK:", cd)

        # скрыть
        if cd.startswith("hide:"):
            if chat_id and mid:
                tg("deleteMessage", {"chat_id": chat_id, "message_id": mid})
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
            return "ok"

            
        # === выбран пользователь → показать меню "Открыть чат" ===
        if cd.startswith("choose_chat:"):
            # ✅ 1. СРАЗУ отвечаем Telegram
            tg("answerCallbackQuery", {
                "callback_query_id": cq["id"]
            })
        
            # ✅ 2. ПОТОМ парсим данные
            try:
                _, biz_chat_id, peer_id = cd.split(":", 2)
                biz_chat_id = int(biz_chat_id)
                peer_id = int(peer_id)
            except Exception:
                return "ok"
        
            # ✅ 3. ПОТОМ БД
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    SELECT sender_name
                    FROM messages
                    WHERE owner_id = %s AND chat_id = %s AND sender_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """, (owner_id, biz_chat_id, peer_id))
                    r = cur.fetchone()
        
            peer_name = r[0] if r and r[0] else "пользователь"
        
            # ✅ 4. Удаляем старое меню
            if chat_id and mid:
                tg("deleteMessage", {
                    "chat_id": chat_id,
                    "message_id": mid
                })
        
            # ✅ 5. Показываем новое меню
            send_text(
                chat_id,
                (   
                    f"👤 <b>{html.escape(peer_name)}</b> "
                    f"(id: <code>{peer_id}</code>)\n\n"
                    f"Здесь ты можешь восстановить чат "
                    f"(если он был удалён) или вернуться назад, "
                    f"чтобы выбрать другого пользователя."

                ),
                {
                    "inline_keyboard": [
                        [{"text": "♻️ Восстановить чат", "callback_data": f"open_chat:{biz_chat_id}"}],
                        [{"text": "⬅️ Назад", "callback_data": "back_to_chats"}]
                    ]
                }
            )
        
            return "ok"



        # === назад к списку пользователей ===
        if cd == "back_to_chats":
            # удаляем текущее меню
            if chat_id and mid:
                tg("deleteMessage", {
                    "chat_id": chat_id,
                    "message_id": mid
                })
        
            # имитируем повторный вызов pick_chat
            peers = get_recent_peers(owner_id, limit=10)
        
            kb = []
            for p in peers:
                nm = (p["peer_name"] or "пользователь").strip()
                if len(nm) > 24:
                    nm = nm[:24] + "…"
                kb.append([{
                    "text": f"👤 {nm}",
                    "callback_data": f"choose_chat:{p['chat_id']}:{p['peer_id']}"
                }])
        
            kb.append([{"text": "✖️ Скрыть", "callback_data": "hide:menu"}])
            
            tg("answerCallbackQuery", {
                "callback_query_id": cq["id"]
            })

            send_text(
                chat_id,
                "<b>♻️ Восстановить чат</b>\n\nВыбери чат, который хочешь восстановить:",
                {"inline_keyboard": kb}
            )
            
            return "ok"
        # === открыть чат (пока заглушка) ===
        if cd.startswith("open_chat:"):
            tg("answerCallbackQuery", {
                "callback_query_id": cq["id"],
                "text": "🚧 Веб-чат скоро будет добавлен"
            })
            return "ok"


        
        tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        return "ok"

  
# ================= WEB APP API =================
@app.route("/api/chat", methods=["GET"])
def api_chat():
    owner_id = request.args.get("owner_id", type=int)
    chat_id = request.args.get("chat_id", type=int)

    if not owner_id or not chat_id:
        return {"ok": False, "error": "missing params"}

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT sender_name, msg_type, text, created_at
                FROM messages
                WHERE owner_id = %s AND chat_id = %s
                ORDER BY created_at ASC
            """, (owner_id, chat_id))

            rows = cur.fetchall()

    messages = []
    for name, mtype, text, dt in rows:
        messages.append({
            "name": name,
            "type": mtype,
            "text": text,
            "time": dt.isoformat()
        })

    return {
        "ok": True,
        "messages": messages
    }

# ================= WEB APP =================

@app.route("/webapp")
def webapp():
    return open("webapp.html", encoding="utf-8").read()
   
# ================= START =================

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000)
