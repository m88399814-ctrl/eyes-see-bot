# -*- coding: utf-8 -*-
import re
import os
import uuid
import time
import psycopg2
import requests
import html
from flask import Flask, request
from urllib.parse import quote
from datetime import timedelta

SUPPORT_TEXT = "Здравствуйте. Вопрос по поводу EyesSee:\n\n"
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
BOT_USERNAME = "EyesSeeBot"  # без @
CONNECT_PHOTO_URL = "https://eyes-see-bot.onrender.com/static/connect_bot.jpg"
SUPPORT_ADMIN_USERNAME = "eyesseeadmin"  # <-- сюда ID админа
TONCENTER_API_KEY = os.getenv("TONCENTER_API_KEY")  # ты уже добавил в Render
TONCENTER_URL = "https://toncenter.com/api/v2"

app = Flask(__name__, static_folder="static", static_url_path="/static")

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
                owner_id BIGINT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE
            )
            """)
            cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name='owners' AND column_name='is_active'
                ) THEN
                    ALTER TABLE owners ADD COLUMN is_active BOOLEAN DEFAULT TRUE;
                END IF;
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name='owners'
                      AND column_name='ref_progress_msg_id'
                ) THEN
                    ALTER TABLE owners
                    ADD COLUMN ref_progress_msg_id BIGINT;
                END IF;
            END $$;
            """)
            cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='owners' AND column_name='deleted_enabled'
                ) THEN
                    ALTER TABLE owners ADD COLUMN deleted_enabled BOOLEAN DEFAULT TRUE;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='owners' AND column_name='deleted_count'
                ) THEN
                    ALTER TABLE owners ADD COLUMN deleted_count INTEGER DEFAULT 0;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='owners' AND column_name='edited_enabled'
                ) THEN
                    ALTER TABLE owners ADD COLUMN edited_enabled BOOLEAN DEFAULT TRUE;
                END IF;
            
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='owners' AND column_name='edited_count'
                ) THEN
                    ALTER TABLE owners ADD COLUMN edited_count INTEGER DEFAULT 0;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='owners' AND column_name='disappear_count'
                ) THEN
                    ALTER TABLE owners ADD COLUMN disappear_count INTEGER DEFAULT 0;
                END IF;
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name='owners' AND column_name='trial_until'
                ) THEN
                    ALTER TABLE owners
                    ADD COLUMN trial_until TIMESTAMP;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name='owners' AND column_name='sub_until'
                ) THEN
                    ALTER TABLE owners
                    ADD COLUMN sub_until TIMESTAMP;
                END IF;
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name='owners' AND column_name='referral_used'
                ) THEN
                    ALTER TABLE owners
                    ADD COLUMN referral_used BOOLEAN DEFAULT FALSE;
                END IF;
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name='owners' AND column_name='last_bite_at'
                ) THEN
                    ALTER TABLE owners ADD COLUMN last_bite_at TIMESTAMP;
                END IF;
            END $$;
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

            # ================================
            # 🔐 ИСПОЛЬЗОВАННЫЕ ПЛАТЕЖИ (TON)
            # ================================
            cur.execute("""
            CREATE TABLE IF NOT EXISTS used_payments (
                tx_hash TEXT PRIMARY KEY,
                owner_id BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
            """)

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
                owner_id BIGINT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE
            )
            """)
            cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name='owners' AND column_name='is_active'
                ) THEN
                    ALTER TABLE owners ADD COLUMN is_active BOOLEAN DEFAULT TRUE;
                END IF;
            END $$;
            """)
            cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='owners' AND column_name='deleted_enabled'
                ) THEN
                    ALTER TABLE owners ADD COLUMN deleted_enabled BOOLEAN DEFAULT TRUE;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='owners' AND column_name='deleted_count'
                ) THEN
                    ALTER TABLE owners ADD COLUMN deleted_count INTEGER DEFAULT 0;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='owners' AND column_name='edited_enabled'
                ) THEN
                    ALTER TABLE owners ADD COLUMN edited_enabled BOOLEAN DEFAULT TRUE;
                END IF;
            
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='owners' AND column_name='edited_count'
                ) THEN
                    ALTER TABLE owners ADD COLUMN edited_count INTEGER DEFAULT 0;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='owners' AND column_name='disappear_count'
                ) THEN
                    ALTER TABLE owners ADD COLUMN disappear_count INTEGER DEFAULT 0;
                END IF;
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name='owners' AND column_name='trial_until'
                ) THEN
                    ALTER TABLE owners
                    ADD COLUMN trial_until TIMESTAMP;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name='owners' AND column_name='sub_until'
                ) THEN
                    ALTER TABLE owners
                    ADD COLUMN sub_until TIMESTAMP;
                END IF;
            END $$;
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

            # ================================
            # 🔐 ИСПОЛЬЗОВАННЫЕ ПЛАТЕЖИ (TON)
            # ================================
            cur.execute("""
            CREATE TABLE IF NOT EXISTS used_payments (
                tx_hash TEXT PRIMARY KEY,
                owner_id BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
            """)

        conn.commit()

def is_payment_used(tx_hash: str) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM used_payments WHERE tx_hash = %s LIMIT 1", (tx_hash,))
            return cur.fetchone() is not None

def mark_payment_used(tx_hash: str, owner_id: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO used_payments (tx_hash, owner_id)
                VALUES (%s, %s)
                ON CONFLICT (tx_hash) DO NOTHING
            """, (tx_hash, owner_id))
        conn.commit()

def cleanup_old():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            DELETE FROM messages
            WHERE created_at < NOW() - INTERVAL '18 hours'
            """)
        conn.commit()

def save_owner(bc_id: str, owner_id: int, is_active: bool = True):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO owners (business_connection_id, owner_id, is_active)
            VALUES (%s, %s, %s)
            ON CONFLICT (business_connection_id)
            DO UPDATE SET
                owner_id = EXCLUDED.owner_id,
                is_active = EXCLUDED.is_active
            """, (bc_id, owner_id, is_active))
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

def is_owner_active(owner_id: int) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT 1
            FROM owners
            WHERE owner_id = %s
              AND is_active = TRUE
            LIMIT 1
            """, (owner_id,))
            return cur.fetchone() is not None
            
def toggle_deleted_enabled(owner_id: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE owners
            SET deleted_enabled = NOT deleted_enabled
            WHERE owner_id = %s
            """, (owner_id,))
        conn.commit()
        
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


def has_access(owner_id: int) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT
                CASE
                    WHEN sub_until IS NOT NULL AND sub_until > NOW() THEN TRUE
                    WHEN sub_until IS NULL AND trial_until IS NOT NULL AND trial_until > NOW() THEN TRUE
                    ELSE FALSE
                END
            FROM owners
            WHERE owner_id = %s
            LIMIT 1
            """, (owner_id,))
            r = cur.fetchone()
            return bool(r[0]) if r else False

def get_trial_dates(owner_id: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    trial_until
                FROM owners
                WHERE owner_id = %s
                LIMIT 1
            """, (owner_id,))
            r = cur.fetchone()

    if not r or not r[0]:
        return "—", "—"

    end_dt = r[0]
    start_dt = end_dt - timedelta(days=14)

    return (
        start_dt.strftime("%Y-%m-%d"),
        end_dt.strftime("%Y-%m-%d")
    )

def get_ref_link(owner_id: int):
    return f"https://t.me/{BOT_USERNAME}?start=ref_{owner_id}"

# ================= CRYPTO PAYMENTS (STUB) =================

def activate_subscription(owner_id: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE owners
                SET sub_until = NOW() + INTERVAL '30 days'
                WHERE owner_id = %s
            """, (owner_id,))
        conn.commit()


def check_ton_payment(owner_id: int):
    """
    Ищет входящий платеж на TON_WALLET:
    - сумма = TON_AMOUNT
    - комментарий = EYESSEE_<owner_id>
    Возвращает tx_hash если найдено, иначе None
    """

    if not TONCENTER_API_KEY:
        print("TONCENTER_API_KEY is missing")
        return None

    comment_expected = f"EYESSEE_{owner_id}"

    try:
        amount_nano = int(float(TON_AMOUNT) * 1_000_000_000)
    except Exception:
        print("Bad TON_AMOUNT:", TON_AMOUNT)
        return None

    params = {
        "address": TON_WALLET,
        "limit": 20
    }

    headers = {
        "X-API-Key": TONCENTER_API_KEY
    }

    try:
        r = requests.get(f"{TONCENTER_URL}/getTransactions", params=params, headers=headers, timeout=15)
        if not r.ok:
            print("TONCENTER HTTP:", r.status_code, r.text)
            return None

        data = r.json()
        if not data.get("ok"):
            print("TONCENTER NOT OK:", data)
            return None

        txs = data.get("result", [])

        for tx in txs:
            txid = tx.get("transaction_id") or {}
            tx_hash = txid.get("hash")
            if not tx_hash:
                continue
        
            msgs = []
        
            if tx.get("in_msg"):
                msgs.append(tx["in_msg"])
        
            for m in tx.get("out_msgs", []):
                msgs.append(m)
        
            for m in msgs:
                value = int(m.get("value", 0))

                # fallback — если value = 0, берём value всей транзакции
                if value == 0:
                    value = int(tx.get("value", 0))
        
                msg = ""
                if "message" in m and m["message"]:
                    msg = m["message"].strip()
                elif "decoded_body" in m:
                    msg = m["decoded_body"].get("text", "").strip()
        
                if value == amount_nano and msg == comment_expected:
                    if is_payment_used(tx_hash):
                        return None
                    return tx_hash

        return None

    except Exception as e:
        print("TON CHECK ERROR:", e)
        return None

def check_usdt_payment(owner_id: int):
    comment_expected = f"EYESSEE_{owner_id}"
    amount_units = int(float(USDT_AMOUNT) * (10 ** USDT_DECIMALS))

    headers = {
        "X-API-Key": TONCENTER_API_KEY
    }

    # 1️⃣ получаем jetton wallet
    r = requests.get(
        f"{TONCENTER_URL}/getJettonWallet",
        params={
            "address": USDT_WALLET,
            "jetton": USDT_JETTON_MASTER
        },
        headers=headers,
        timeout=15
    )

    if not r.ok:
        return None

    data = r.json()
    jetton_wallet = data.get("result", {}).get("address")
    if not jetton_wallet:
        return None

    # 2️⃣ получаем jetton transfers
    r = requests.get(
        f"{TONCENTER_URL}/getJettonTransfers",
        params={
            "address": jetton_wallet,
            "limit": 20
        },
        headers=headers,
        timeout=15
    )

    if not r.ok:
        return None

    data = r.json()
    transfers = data.get("result", [])

    for t in transfers:
        if t.get("destination") != jetton_wallet:
            continue

        amount = int(t.get("amount", 0))
        comment = (t.get("comment") or "").strip()
        tx_hash = t.get("transaction_hash")

        if amount == amount_units and comment == comment_expected:
            if is_payment_used(tx_hash):
                return None
            return tx_hash

    return None

# ================= BITE MESSAGE =================
def can_send_bite(owner_id: int) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT last_bite_at
                FROM owners
                WHERE owner_id = %s
                LIMIT 1
            """, (owner_id,))
            r = cur.fetchone()

    if not r or not r[0]:
        return True

    return (time.time() - r[0].timestamp()) >= 5 * 60 * 60
    
def mark_bite_sent(owner_id: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE owners
                SET last_bite_at = NOW()
                WHERE owner_id = %s
            """, (owner_id,))
        conn.commit()

def bite_text(deleted_text: str, sender_name: str, token: str):
    return (
        "🗑 <b>Новое удалённое сообщение:</b>\n\n"
        f"<blockquote>{html.escape(deleted_text)}</blockquote>\n\n"
        f"<b>Удалил(а):</b> {html.escape(sender_name)}\n\n"
        "❗️ Твой пробный период EyesSee закончился\n"
        "Но его можно продлить <b>бесплатно!</b>"
        f"<a href=\"https://t.me/{BOT_USERNAME}?start={token}\">Подробнее</a>"
    )
# ================= SETTINGS: DELETED MESSAGES =================

def is_deleted_enabled(owner_id: int) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT deleted_enabled
            FROM owners
            WHERE owner_id = %s
            LIMIT 1
            """, (owner_id,))
            r = cur.fetchone()
            return r[0] if r else True


def toggle_deleted(owner_id: int) -> bool:
    """
    Переключает состояние:
    True -> False
    False -> True
    Возвращает НОВОЕ состояние
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE owners
            SET deleted_enabled = NOT deleted_enabled
            WHERE owner_id = %s
            RETURNING deleted_enabled
            """, (owner_id,))
            r = cur.fetchone()
        conn.commit()
    return r[0]


def inc_deleted_count(owner_id: int, value: int = 1):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE owners
            SET deleted_count = deleted_count + %s
            WHERE owner_id = %s
            """, (value, owner_id))
        conn.commit()


def get_deleted_count(owner_id: int) -> int:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT deleted_count
            FROM owners
            WHERE owner_id = %s
            LIMIT 1
            """, (owner_id,))
            r = cur.fetchone()
            return r[0] if r else 0

def set_deleted_enabled(owner_id: int, value: bool):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE owners
            SET deleted_enabled = %s
            WHERE owner_id = %s
            """, (value, owner_id))
        conn.commit()

# ================= SETTINGS: EDITED MESSAGES =================
def toggle_edited_enabled(owner_id: int) -> bool:
    """
    Переключает состояние:
    True -> False
    False -> True
    Возвращает НОВОЕ состояние
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE owners
            SET edited_enabled = NOT edited_enabled
            WHERE owner_id = %s
            RETURNING edited_enabled
            """, (owner_id,))
            r = cur.fetchone()
        conn.commit()
    return r[0]

def is_edited_enabled(owner_id: int) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT edited_enabled
            FROM owners
            WHERE owner_id = %s
            LIMIT 1
            """, (owner_id,))
            r = cur.fetchone()
            return r[0] if r else True

def inc_edited_count(owner_id: int, value: int = 1):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE owners
            SET edited_count = edited_count + %s
            WHERE owner_id = %s
            """, (value, owner_id))
        conn.commit()


def get_edited_count(owner_id: int) -> int:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT edited_count
            FROM owners
            WHERE owner_id = %s
            LIMIT 1
            """, (owner_id,))
            r = cur.fetchone()
            return r[0] if r else 0


def set_edited_enabled(owner_id: int, value: bool):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE owners
            SET edited_enabled = %s
            WHERE owner_id = %s
            """, (value, owner_id))
        conn.commit()

# ================= SETTINGS: DISAPPEARING MEDIA =================

def inc_disappear_count(owner_id: int, value: int = 1):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE owners
            SET disappear_count = disappear_count + %s
            WHERE owner_id = %s
            """, (value, owner_id))
        conn.commit()


def get_disappear_count(owner_id: int) -> int:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT disappear_count
            FROM owners
            WHERE owner_id = %s
            LIMIT 1
            """, (owner_id,))
            r = cur.fetchone()
            return r[0] if r else 0
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
def send_photo(chat_id, photo_url, caption, markup=None):
    data = {
        "chat_id": chat_id,
        "photo": photo_url,
        "caption": caption,
        "parse_mode": "HTML"
    }
    if markup:
        data["reply_markup"] = markup
    tg("sendPhoto", data)

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

def setup_menu():
    tg("setChatMenuButton", {
        "menu_button": {
            "type": "commands"
        }
    })

    tg("setMyCommands", {
        "commands": [
            {"command": "start", "description": "🔄 Перезапустить бота"},
            {"command": "settings", "description": "⚙️ Настройки"},
            {"command": "help", "description": "🆘 Поддержка"}
        ]
    })
def settings_markup(owner_id: int):
    d = is_deleted_enabled(owner_id)

    return {
        "inline_keyboard": [
            [{"text": f"🗑 Удалённые сообщения: {'✅' if d else '🚫'}", "callback_data": "deleted_settings"}],
            [{"text": f"✏️ Изменённые сообщения: {'✅' if is_edited_enabled(owner_id) else '🚫'}","callback_data": "edited_settings"}],
            [{"text": "♻️ Восстановить чат", "callback_data": "recover_menu"}],
            [{"text": "⏳ Исчезающие медиа", "callback_data": "disappearing_settings"}],
        ]
    }


def show_bot_ready(chat_id: int, owner_id: int):
    setup_menu()
    tg("sendMessage", {
        "chat_id": chat_id,
        "text": (
            "Бот работает, подключение есть — я\n"
            "готов следить за сообщениями 👁️"
        ),
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "⚙️ Настройки", "callback_data": "settings"}
            ]]
        }
    })

def settings_text():
    return (
        "⚙️ <b>Настройки</b>\n\n"
        "Глаза всё видят. Выбери, что хочешь настроить:"
    )
def deleted_settings_text(count: int):
    return (
        "🗑 <b>Удалённые сообщения</b>\n\n"
        "<blockquote>"
        "Даже когда ты не в сети, бот заметит, что твой собеседник удалил сообщение, "
        "и отправит тебе уведомление. "
        "И, конечно,\nсобеседник не может заметить работу EyesSee!"
        "</blockquote>\n\n"
        f"<b>Заметил удалённых сообщений:</b> {count}"
    )


def deleted_settings_markup(enabled: bool):
    return {
        "inline_keyboard": [
            [{
                "text": "✅ Включено" if enabled else "🚫 Отключено",
                "callback_data": "toggle_deleted"
            }],
            [{
                "text": "◀️ Назад",
                "callback_data": "back_to_settings"
            }]
        ]
    }
            
def edited_settings_markup(enabled: bool):
    return {
        "inline_keyboard": [
            [{
                "text": "🚫 Отключено" if not enabled else "✅ Включено",
                "callback_data": "toggle_edited"
            }],
            [{
                "text": "◀️ Назад",
                "callback_data": "back_to_settings"
            }]
        ]
    }
def edited_settings_text(count: int):
    return (
        "✏️ <b>Изменённые сообщения</b>\n\n"
        "<blockquote>"
        "EyesSee замечает редактирование сообщений твоими собеседниками. В\n"
        "случае изменений я отправлю тебе как старый, так и новый текст сообщения.\n"
        "Думаю, когда-нибудь эта функция тебе пригодится!"
        "</blockquote>\n\n"
        f"<b>Заметил изменённых сообщений:</b> {count}"
    )

def disappearing_settings_text(count: int):
    return (
        "⌛️ <b>Исчезающие медиа (с таймером)</b>\n\n"
        "<blockquote>"
        "<b>Как это работает?</b>\n\n"
        "Если ты хочешь сохранить любой одноразовый файл, сделай так:\n\n"
        "1. В переписке с отправителем, не открывая файл, смахни сообщение с ним налево, чтобы ответить на него.\n"
        "2. Напиши что угодно, например «Попозже» или «Не грузит»\n"
        "3. Отправь сообщение.\n\n"
        "За долю секунды EyesSee поймёт, что надо сохранить, и отправит тебе!"
        "</blockquote>\n\n"
        "<blockquote>"
        "<b>Как это включить?</b>\n\n"
        "Эта функция всегда включена. Бот будет присылать: "
        "одноразовые фото и видео,\nголосовые и видеосообщения. "
        "Главное,\nделай всё по инструкции выше.\n\n"
        "Приятного пользования ❤️"
        "</blockquote>\n\n"
        f"<b>Заметил медиа:</b> {count}"
    )

def disappearing_settings_markup():
    return {
        "inline_keyboard": [
            [{"text": "◀️ Назад", "callback_data": "back_to_settings"}]
        ]
    }


def help_text():
    return (
        "<b>🆘 Поддержка</b>\n\n"
        "Любые вопросы по поводу бота: технические моменты, реклама, "
        "подписка, партнёрская программа, а также баги, ошибки и ваши предложения. "
        "Всё сюда 😉"
    )


def help_markup():
    return {
        "inline_keyboard": [
            [{
                "text": "✍️ Задать вопрос",
                "url": (
                    f"tg://resolve?"
                    f"domain={SUPPORT_ADMIN_USERNAME}"
                    f"&text={quote(SUPPORT_TEXT)}"
                )
            }]
        ]
    }

def trial_expired_text(start_date: str, end_date: str, ref_link: str):
    return (
        "<b>Твой пробный период закончился</b>\n\n"
        f"<b>Начало:</b> <code>{start_date}</code>\n"
        f"<b>Конец:</b> <code>{end_date}</code>\n\n"
        "Ты можешь <b>бесплатно</b> продлить подписку ещё на 14 дней, "
        "если 2 твоих друга с Telegram Premium запустят и подключат бота по твоей ссылке:\n"
        f"<blockquote><code>{ref_link}</code></blockquote>\n\n"
        "<b>Ну, или продлить платно (см. ниже)</b>\n"
        "<b>Вопросы?</b> — /help"
    )
    
def trial_expired_text_without_ref(start_date: str, end_date: str):
    return (
        "<b>Твой пробный период закончился</b>\n\n"
        f"<b>Начало:</b> <code>{start_date}</code>\n"
        f"<b>Конец:</b> <code>{end_date}</code>\n\n"
        "Чтобы продолжить пользоваться EyesSee, "
        "продли подписку любым удобным способом ниже 👇\n\n"
        "<b>Вопросы?</b> — /help"
    )
    
def trial_expired_markup(ref_link: str):
    share_text = (
        "EyesSee — первый бот в Telegram, который научился замечать удалённые сообщения!\n"
        "Подключи по моей ссылке, чтобы получить бесплатный доступ 🎁"
    )

    return {
        "inline_keyboard": [
            [
                {
                    "text": "📤 Поделиться",
                    "url": (
                        "https://t.me/share/url?"
                        f"url={quote(ref_link)}"
                        f"&text={quote(share_text)}"
                    )
                }
            ],
            [
                {"text": "⭐ Оплатить 1 месяц — 80", "callback_data": "pay_stars_1m"}
            ],
            [
                {"text": "💎 Оплатить криптовалютой", "callback_data": "pay_crypto"}
            ],
            [
                {"text": "💳 Оплатить картой", "callback_data": "pay_card"}
            ]
        ]
    }
    
def trial_expired_markup_without_ref():
    return {
        "inline_keyboard": [
            [
                {"text": "⭐ Оплатить 1 месяц — 80", "callback_data": "pay_1m"}
            ],
            [
                {"text": "💎 Оплатить криптовалютой", "callback_data": "pay_crypto"}
            ],
            [
                {"text": "💳 Оплатить картой", "callback_data": "pay_card"}
            ]
        ]
    }
def pay_card_unavailable_text():
    return (
        "<b>💳 Оплата картой</b>\n\n"
        "<b>На данный момент оплата картой через бота временно недоступна.</b>\n"
        "<blockquote>"
        "Если ты хочешь оплатить подписку\n"
        "картой, обратись к администратору 👇"
        "</blockquote>"
    )


def pay_card_unavailable_markup():
    return {
        "inline_keyboard": [
            [
                {
                    "text": "✍️ Администратор",
                    "url": (
                        f"tg://resolve?"
                        f"domain={SUPPORT_ADMIN_USERNAME}"
                        f"&text={quote(SUPPORT_TEXT)}"
                    )
                }
            ],
            [
                {"text": "◀️ Назад", "callback_data": "back_to_paywall"}
            ]
        ]
    }


def crypto_warning_block():
    return (
        "<blockquote>"
        "<b>⚠️ Важно:</b> "
        "если указать неточную сумму или не добавить комментарий к платежу, "
        "денежные средства могут быть утеряны "
        "<b>без права возврата.</b>"
        "</blockquote>"
    )
def crypto_check_hint_block():
    return (
        "<blockquote>"
        "После перевода нажми кнопку "
        "<b>«Проверить платёж»</b>"
        "</blockquote>"
    )
def pay_crypto_text():
    return (
        "<b>💎 Оплата криптовалютой</b>\n\n"
        "Выбери валюту для оплаты\n"
        "подписки 👇"
    )

def pay_crypto_markup():
    return {
        "inline_keyboard": [
            [
                {"text": "💎 TON", "callback_data": "crypto_ton"},
                {"text": "💵 USDT", "callback_data": "crypto_usdt"}
            ],
            [
                {"text": "◀️ Назад", "callback_data": "back_to_paywall"}
            ]
        ]
    }

# === ЗДЕСЬ ЦЕНЫ (Поменяешь на свои) ===
TON_AMOUNT = "1"          # например "1"
USDT_AMOUNT = "1.46"        # например "10"

TON_WALLET = "UQBbZQckRBO11wIwf-5nBnsslgIfVxkb1vzWuK3YbyxDonrD"
USDT_WALLET = "UQBbZQckRBO11wIwf-5nBnsslgIfVxkb1vzWuK3YbyxDonrD"   # если тот же — оставь тот же адрес

# === USDT JETTON ===
USDT_JETTON_MASTER = "EQCxE6mUtQJKFnGfaROTKOt1lZb0uZ2C6J8uY8FZ4kZ9FzZ5"
USDT_DECIMALS = 6

def ton_comment(owner_id: int) -> str:
    return f"EYESSEE_{owner_id}"

def usdt_comment(owner_id: int) -> str:
    return f"EYESSEE_{owner_id}"

# ====== TON TEXT (заголовки НЕ в цитате, значения в цитате) ======
def pay_ton_text(owner_id: int):
    c = ton_comment(owner_id)

    return (
        "<b>💎 Оплата TON</b>\n\n"
        "<b>Сумма:</b>\n"
        f"<blockquote><code>{TON_AMOUNT}</code> TON</blockquote>\n\n"
        "<b>Адрес:</b>\n"
        f"<blockquote><code>{TON_WALLET}</code></blockquote>\n\n"
        "<b>Комментарий (обязательно):</b>\n"
        f"<blockquote><code>{c}</code></blockquote>\n\n"
        + crypto_check_hint_block() + "\n"
        + crypto_warning_block()
    )

# ====== USDT TEXT (то же самое) ======
def pay_usdt_text(owner_id: int):
    c = usdt_comment(owner_id)

    return (
        "<b>💵 Оплата USDT</b>\n\n"
        "<b>Сумма:</b>\n"
        f"<blockquote><code>{USDT_AMOUNT}</code> USDT</blockquote>\n\n"
        "<b>Адрес:</b>\n"
        f"<blockquote><code>{USDT_WALLET}</code></blockquote>\n\n"
        "<b>Комментарий (обязательно):</b>\n"
        f"<blockquote><code>{c}</code></blockquote>\n\n"
        + crypto_check_hint_block() + "\n"
        + crypto_warning_block()
    )

def pay_ton_markup():
    return {
        "inline_keyboard": [
            [{"text": "💎 Проверить платёж", "callback_data": "check_ton"}],
            [{"text": "◀️ Назад", "callback_data": "back_to_crypto"}]
        ]
    }

def pay_usdt_markup():
    return {
        "inline_keyboard": [
            [{"text": "💵 Проверить платёж", "callback_data": "check_usdt"}],
            [{"text": "◀️ Назад", "callback_data": "back_to_crypto"}]
        ]
    }
# ================= WEBHOOK =================

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    cleanup_old()
    if not data:
        return "ok"
    # 1) подключение / отключение бизнес-аккаунта
    if "business_connection" in data:
        bc = data["business_connection"]
    
        bc_id = bc.get("id") or bc.get("business_connection_id")
        owner_id = bc["user"]["id"]

        # ВОТ ЭТО ПРАВИЛЬНОЕ ПОЛЕ:
        is_enabled = bc.get("is_enabled", True)
        is_new_connection = False
        with get_db() as conn:
            with conn.cursor() as cur:
                # если отключили — выключаем ВСЁ для этого owner
                if not is_enabled:
                    cur.execute("""
                        UPDATE owners
                        SET is_active = FALSE
                        WHERE owner_id = %s
                    """, (owner_id,))
                cur.execute(
                    "SELECT 1 FROM owners WHERE business_connection_id = %s",
                    (bc_id,)
                )
                if not cur.fetchone():
                    is_new_connection = True
                # текущее подключение пишем как есть
                cur.execute("""
                    WITH existing AS (
                        SELECT trial_until
                        FROM owners
                        WHERE owner_id = %s
                          AND trial_until IS NOT NULL
                        LIMIT 1
                    )
                    INSERT INTO owners (business_connection_id, owner_id, is_active, trial_until)
                    VALUES (
                        %s,
                        %s,
                        %s,
                        COALESCE(
                            (SELECT trial_until FROM existing),
                            NOW() + INTERVAL '14 days'
                        )
                    )
                    ON CONFLICT (business_connection_id)
                    DO UPDATE SET
                        owner_id = EXCLUDED.owner_id,
                        is_active = EXCLUDED.is_active,
                        trial_until = COALESCE(
                            owners.trial_until,
                            EXCLUDED.trial_until
                        );
                """, (
                    owner_id,   # ← ДЛЯ existing (ЭТО ГЛАВНОЕ)
                    bc_id,
                    owner_id,
                    is_enabled
                ))
        
            conn.commit()
    
        if is_enabled and is_new_connection:
            send_text(
                owner_id,
                "Бот подключён 👁️",
                {
                    "inline_keyboard": [
                        [{
                            "text": "⚙️ Настройки",
                            "callback_data": "settings"
                        }]
                    ]
                }
            )
        if not is_enabled:
            send_text(owner_id, "Бот отключён 😴")
    
        return "ok"

    # ⭐ Telegram Stars — pre checkout
    if "pre_checkout_query" in data:
        pcq = data["pre_checkout_query"]

        tg("answerPreCheckoutQuery", {
            "pre_checkout_query_id": pcq["id"],
            "ok": True
        })
        return "ok"

    
    # 2) входящее сообщение
    if "business_message" in data:
        msg = data["business_message"]
        bc_id = msg.get("business_connection_id")
        owner_id = get_owner(bc_id)
        # 🔥 БАЙТ-СООБЩЕНИЕ (появляется само)
        if not has_access(owner_id) and can_send_bite(owner_id):
            token = "bite_" + uuid.uuid4().hex[:10]
        
            send_text(
                owner_id,
                bite_text(
                    deleted_text="Сообщение",
                    sender_name="EyesSee",
                    token=token
                )
            )
        
            mark_bite_sent(owner_id)
        if not owner_id:
            return "ok"
        
        # 🔒 ПРОВЕРКА ДОСТУПА
        if not has_access(owner_id):
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
            inc_disappear_count(owner_id)
            send_text(owner_id, header + body + who)
            return "ok"

        # 2.2) Сообщения владельца не сохраняем
        #if sender.get("id") == owner_id:
            #return "ok"

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
        mids = dbm.get("message_ids", [])
        if not mids:
            return "ok"
        bc_id = dbm.get("business_connection_id")
        owner_id = get_owner(bc_id)
        if not owner_id:
            return "ok"
        
        # 🔒 ПРОВЕРКА ДОСТУПА
        if not has_access(owner_id):
            return "ok"
        



        # ❌ НЕ показываем удаление сообщений владельца
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                SELECT sender_id
                FROM messages
                WHERE owner_id = %s AND message_id = ANY(%s)
                LIMIT 1
                """, (owner_id, mids))
                r = cur.fetchone()
        
        if r and r[0] == owner_id:
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
            inc_deleted_count(owner_id, len(blocks))
    
            title = (
                "🗑 <b>Новое удалённое сообщение</b>\n\n"
                if len(blocks) == 1
                else "🗑 <b>Новые удалённые сообщения</b>\n\n"
            )
    
            who = ""
            if sender_id and sender_name:
                who = (
                    f'\n\n<b>Удалил(а):</b> '
                    f'<a href="tg://user?id={sender_id}">{html.escape(sender_name)}</a>'
                )
    
            # ❌ если уведомления выключены — НЕ отправляем (но счётчик уже посчитали)
            if not is_deleted_enabled(owner_id):
                return "ok"
    
            send_text(owner_id, title + "\n".join(blocks) + who)
    
        return "ok"
    # 4) изменение сообщений (группировка 1 сек)
    if "edited_business_message" in data:
        ebm = data["edited_business_message"]
        mid = ebm.get("message_id")
        if not mid:
            return "ok"
        bc_id = ebm.get("business_connection_id")
        owner_id = get_owner(bc_id)
        if not owner_id:
            return "ok"
        
        # 🔒 ПРОВЕРКА ДОСТУПА
        if not has_access(owner_id):
            return "ok"


        # ❌ НЕ показываем изменения сообщений владельца
        editor_id = ebm.get("from", {}).get("id")
        if editor_id == owner_id:
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
        # если уведомления выключены — только считаем
        if not is_edited_enabled(owner_id):
            inc_edited_count(owner_id)
            return "ok"
        
        # если включены — считаем и отправляем
        inc_edited_count(owner_id)
        send_text(owner_id, title + body_old + body_new + who)
        return "ok"
    
  
    # 5) /start и /start TOKEN (в личке с ботом)
    if "message" in data:
        msg = data["message"]
        owner_id = msg["from"]["id"]
        text = (msg.get("text") or "").strip()
        chat_id = msg["chat"]["id"]
        # ✅ гарантируем, что пользователь существует и у него есть trial
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO owners (owner_id, trial_until, is_active)
                    VALUES (%s, NOW() + INTERVAL '14 days', TRUE)
                    ON CONFLICT (owner_id) DO NOTHING
                """, (owner_id,))
            conn.commit()
        # ===== START HANDLER =====

        # ❌ если пользователь БЕЗ Telegram Premium
        if not msg["from"].get("is_premium"):
            send_text(
                chat_id,
                "<b>К сожалению, чтобы пользоваться</b>\n"
                "<b>ботом нужно иметь Telegram Premium</b>\n\n"
                "Без этого бот нельзя привязать к\n"
                "аккаунту. Покупай премку и приходи\n"
                "ещё 😉"
            )
            return "ok"
        
        if "successful_payment" in msg:
            payload = msg["successful_payment"]["invoice_payload"]
        
            if payload == "sub_1m":
                with get_db() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE owners
                            SET is_active = TRUE
                            WHERE owner_id = %s
                        """, (owner_id,))
                    conn.commit()
                activate_subscription(owner_id)
        
                # ✅ ЯВНОЕ СООБЩЕНИЕ О АКТИВАЦИИ
                send_text(
                    chat_id,
                    "<b>✅ Подписка активирована!</b>\n\n"
                    "Спасибо за оплату 🙌\n"
                    "Доступ открыт на <b>30 дней</b>."
                )
        
                # 🚀 ПОКАЗЫВАЕМ ГОТОВНОСТЬ БОТА
                show_bot_ready(chat_id, owner_id)
        
                return "ok"
        if text == "/settings" or text == f"/settings@{BOT_USERNAME}":
            send_text(chat_id, settings_text(), settings_markup(owner_id))
            return "ok"
            
        if text == "/help" or text == f"/help@{BOT_USERNAME}":
            send_text(chat_id, help_text(), help_markup())
            return "ok"
        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            cmd = parts[0]
            payload = parts[1].strip() if len(parts) > 1 else ""
            # 🔥 BITE TOKEN (/start bite_xxx)
            if payload and payload.startswith("bite_"):
                tg("deleteMessage", {
                    "chat_id": chat_id,
                    "message_id": msg["message_id"]
                })
            
                start_date, end_date = get_trial_dates(owner_id)
                ref_link = get_ref_link(owner_id)
            
                send_text(
                    chat_id,
                    trial_expired_text(start_date, end_date, ref_link),
                    trial_expired_markup(ref_link)
                )
                return "ok"
            if payload.startswith("ref_"):
                inviter_id = int(payload.replace("ref_", ""))
                with get_db() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT referral_used FROM owners WHERE owner_id = %s",
                            (inviter_id,)
                        )
                        row = cur.fetchone()
                
                if row and row[0]:
                    return "ok"
                # ❌ нельзя пригласить самого себя
                if inviter_id == owner_id:
                    return "ok"
            
                # ❌ проверяем Telegram Premium
                if not msg["from"].get("is_premium"):
                    send_text(
                        chat_id,
                        "<b>К сожалению, чтобы пользоваться</b>\n"
                        "<b>ботом нужно иметь Telegram Premium</b>\n\n"
                        "Без этого бот нельзя привязать к\n"
                        "аккаунту. Покупай премку и приходи\n"
                        "ещё 😉"
                    )
                    return "ok"

                
                with get_db() as conn:
                    with conn.cursor() as cur:
                        # ❌ если уже был приглашён кем-то
                        cur.execute(
                            "SELECT 1 FROM referrals WHERE invited_id = %s",
                            (owner_id,)
                        )
                        if cur.fetchone():
                            send_text(
                                chat_id,
                                "❌ <b>Этот аккаунт уже запускал EyesSee ранее\n</b>"
                                "<blockquote>"
                                "Реферальная ссылка работает только для пользователей, "
                                "которые <b>впервые запускают бота</b>. "
                                "Пригласи друзей с Telegram Premium, "
                                "которые ещё не пользовались EyesSee 👌"
                                "</blockquote>"
                            )
                            return "ok"

            
                        # ✅ сохраняем реферал
                        cur.execute(
                            "INSERT INTO referrals (inviter_id, invited_id) VALUES (%s, %s)",
                            (inviter_id, owner_id)
                        )

                        
                    conn.commit()
            
                # 👉 считаем, сколько приглашено
                with get_db() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT COUNT(*) FROM referrals WHERE inviter_id = %s",
                            (inviter_id,)
                        )
                        count = cur.fetchone()[0]
                
                # =========================
                # ✅ ШАГ 2 — ПЕРВЫЙ РЕФЕРАЛ (1 / 2)
                # =========================
                if count == 1:
                    res = tg("sendMessage", {
                        "chat_id": inviter_id,
                        "text": "📊 <b>Рефералы:</b> 1 / 2",
                        "parse_mode": "HTML"
                    })
                
                    data = res.json()
                    msg_id = data["result"]["message_id"]
                
                    with get_db() as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                UPDATE owners
                                SET ref_progress_msg_id = %s
                                WHERE owner_id = %s
                            """, (msg_id, inviter_id))
                        conn.commit()
                # =========================
                # ✅ ШАГ 3 — ВТОРОЙ РЕФЕРАЛ (2 / 2)
                # =========================
                if count >= 2:
                    with get_db() as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                SELECT ref_progress_msg_id
                                FROM owners
                                WHERE owner_id = %s
                            """, (inviter_id,))
                            row = cur.fetchone()
                
                    msg_id = row[0] if row else None
                
                    if msg_id:
                        tg("deleteMessage", {
                            "chat_id": inviter_id,
                            "message_id": msg_id
                        })
                
                    with get_db() as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                UPDATE owners
                                SET
                                    ref_progress_msg_id = NULL,
                                    referral_used = TRUE,
                                    trial_until = NOW() + INTERVAL '14 days'
                                WHERE owner_id = %s
                            """, (inviter_id,))
                        conn.commit()
                
                    send_text(
                        inviter_id,
                        "🎉 <b>Поздравляю!</b>\n\n"
                        "Два друга подключили EyesSee — тебе продлён доступ ещё на <b>14 дней</b> 🔥"
                    )
                
                    show_bot_ready(inviter_id, inviter_id)
        
            if "@" in cmd and cmd != f"/start@{BOT_USERNAME}":
                return "ok"


            
            # 🔐 PAYWALL — ТОЛЬКО ЗДЕСЬ
            if not has_access(owner_id):
                if payload:
                    tg("deleteMessage", {
                        "chat_id": chat_id,
                        "message_id": msg["message_id"]
                    })
            
                start_date, end_date = get_trial_dates(owner_id)
                ref_link = get_ref_link(owner_id)
            
                with get_db() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT referral_used FROM owners WHERE owner_id = %s",
                            (owner_id,)
                        )
                        row = cur.fetchone()
                        referral_used = row[0] if row else False
                
                if referral_used:
                    send_text(
                        chat_id,
                        trial_expired_text_without_ref(start_date, end_date),
                        trial_expired_markup_without_ref()
                    )
                else:
                    send_text(
                        chat_id,
                        trial_expired_text(start_date, end_date, ref_link),
                        trial_expired_markup(ref_link)
                    )
                return "ok"

            
            # =========================
            # /start БЕЗ токена
            # =========================
            if not payload:
                if is_owner_active(owner_id):
                    setup_menu()
                    send_text(
                        chat_id,
                        "Бот работает, подключение есть — я\nготов следить за сообщениями 👁️",
                        {
                            "inline_keyboard": [[
                                {"text": "⚙️ Настройки", "callback_data": "settings"}
                            ]]
                        }
                    )
                else:
                    send_photo(
                        chat_id,
                        CONNECT_PHOTO_URL,
                        (
                            "<b>Для работы бота нужно подключить его к аккаунту:</b>\n\n"
                            "Настройки → Telegram для бизнеса → Чат-боты\n"
                            "Вставь <code>EyesSeeBot</code> → Готово!"
                        ),
                        {
                            "inline_keyboard": [[
                                {
                                  "text": "📋 Скопировать",
                                  "web_app": { "url": "https://eyes-see-bot.onrender.com/static/copy.html" }
                                }
                            ]]
                        }
                    )
                return "ok"
        
            # =========================
            # /start <token>
            # =========================
            if re.fullmatch(r"[0-9a-f]{10}", payload):
                tg("deleteMessage", {
                    "chat_id": chat_id,
                    "message_id": msg["message_id"]
                })
        
                with get_db() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                        SELECT msg_type, file_id
                        FROM messages
                        WHERE owner_id = %s AND token = %s
                        """, (owner_id, payload))
                        r = cur.fetchone()
        
                if not r:
                    send_text(
                        chat_id,
                        "❌ <b>Не получилось открыть файл</b> 😔\n"
                        "Возможно он был отправлен слишком давно"
                    )
                    return "ok"
        
                msg_type, file_id = r
                send_media(chat_id, msg_type, file_id, payload)
                return "ok"
        
            # ✅ /start БЕЗ токена — показать главное меню
            setup_menu()
        
            send_text(
                chat_id,
                "👁️ Бот запущен\n\nНажми кнопку «Меню» снизу 👇"
            )
            return "ok"
            
            # ✅ /start <token> — ТВОЯ СТАРАЯ ЛОГИКА (НЕ ТРОГАЛ)
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
            

        return "ok"
    # 6) callback-кнопки
    if "callback_query" in data:
        cq = data["callback_query"]
        m = cq.get("message")
        chat_id = (m.get("chat") or {}).get("id") if m else None
        mid = m.get("message_id") if m else None

        owner_id = (cq.get("from") or {}).get("id", 0)
        cd = cq.get("data") or ""

        if cd == "pay_crypto":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        
            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": pay_crypto_text(),
                "parse_mode": "HTML",
                "reply_markup": pay_crypto_markup()
            })
            return "ok"
        
        # ⚙️ НАСТРОЙКИ
        if cd == "deleted_settings":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        
            count = get_deleted_count(owner_id)
            enabled = is_deleted_enabled(owner_id)
        
            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": deleted_settings_text(count),
                "parse_mode": "HTML",
                "reply_markup": deleted_settings_markup(enabled)
            })
        
            return "ok"
        if cd == "settings":
            tg("answerCallbackQuery", {
                "callback_query_id": cq["id"]
            })
        
            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": settings_text(),
                "parse_mode": "HTML",
                "reply_markup": settings_markup(owner_id)
            })
            return "ok"

        if cd == "pay_stars_1m":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        
            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": (
                    "<b>⭐ Оплата подписки за звёзды</b>\n\n"
                    "<blockquote>"
                    "После оплаты подписка активируется автоматически. "
                    "Если передумал — можешь вернуться назад 👇"
                    "</blockquote>"
                ),
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": "⭐ Оплатить 80 звёзд", "callback_data": "stars_invoice"}],
                        [{"text": "◀️ Назад", "callback_data": "back_to_paywall"}]
                    ]
                }
            })
        
            return "ok"

        if cd == "stars_invoice":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})

            # 1️⃣ УДАЛЯЕМ меню "Оплата подписки за звёзды"
            if chat_id and mid:
                tg("deleteMessage", {
                    "chat_id": chat_id,
                    "message_id": mid
                })

            # 2️⃣ ОТПРАВЛЯЕМ INVOICE (Telegram Stars)
            tg("sendInvoice", {
                "chat_id": owner_id,
                "title": "EyesSee — подписка на 1 месяц",
                "description": "Доступ ко всем функциям EyesSee на 30 дней",
                "payload": "sub_1m",
                "provider_token": "",   # Stars → всегда пусто
                "currency": "XTR",
                "prices": [
                    {"label": "Подписка на 1 месяц", "amount": 80}
                ]
            })

            return "ok"

        if cd == "pay_card":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        
            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": pay_card_unavailable_text(),
                "parse_mode": "HTML",
                "reply_markup": pay_card_unavailable_markup()
            })
            return "ok"
            
        if cd == "back_to_paywall":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        
            start_date, end_date = get_trial_dates(owner_id)
            ref_link = get_ref_link(owner_id)
        
            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": trial_expired_text(start_date, end_date, ref_link),
                "parse_mode": "HTML",
                "reply_markup": trial_expired_markup(ref_link)
            })
            return "ok"

        if cd == "pay_crypto":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        
            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": pay_crypto_text(),
                "parse_mode": "HTML",
                "reply_markup": pay_crypto_markup()
            })
            return "ok"
            
        if cd == "check_ton":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        
            tx_hash = check_ton_payment(owner_id)
        
            if tx_hash:
                mark_payment_used(tx_hash, owner_id)
                activate_subscription(owner_id)
        
                tg("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": mid,
                    "text": "<b>Платёж найден ✅</b>",
                    "parse_mode": "HTML"
                })
        
                show_bot_ready(chat_id, owner_id)
        
            else:
                tg("sendMessage", {
                    "chat_id": chat_id,
                    "text": "❌ Платёж не найден. Попробуй через 1-2 минуты."
                })
        
            return "ok"
        
        if cd == "check_usdt":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        
            tx_hash = check_usdt_payment(owner_id)
        
            if tx_hash:
                mark_payment_used(tx_hash, owner_id)
                activate_subscription(owner_id)
        
                tg("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": mid,
                    "text": "<b>Платёж найден ✅</b>",
                    "parse_mode": "HTML"
                })
        
                show_bot_ready(chat_id, owner_id)
            else:
                tg("sendMessage", {
                    "chat_id": chat_id,
                    "text": "❌ Платёж не найден. Попробуй через 1-2 минуты."
                })
        
            return "ok"
        if cd == "crypto_ton":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        
            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": pay_ton_text(owner_id),
                "parse_mode": "HTML",
                "reply_markup": pay_ton_markup()
            })
            return "ok"
        
        if cd == "crypto_usdt":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        
            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": pay_usdt_text(owner_id),
                "parse_mode": "HTML",
                "reply_markup": pay_usdt_markup()
            })
            return "ok"
        if cd == "back_to_crypto":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        
            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": pay_crypto_text(),
                "parse_mode": "HTML",
                "reply_markup": pay_crypto_markup()
            })
            return "ok"
        if cd == "copy_ref":
            tg("answerCallbackQuery", {
                "callback_query_id": cq["id"],
                "text": "Ссылка скопирована",
                "show_alert": False
            })
            return "ok"
        # ♻️ Восстановить чат — ОТКРЫТЬ МЕНЮ (БЕЗ УДАЛЕНИЯ)
        if cd == "recover_menu":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        
            peers = get_recent_peers(owner_id, limit=10)
        
            kb = []
        
            if not peers:
                text = "❌ <b>Нет данных для восстановления</b>"
            else:
                for p in peers:
                    name = (p["peer_name"] or "пользователь").strip()
                    if len(name) > 28:
                        name = name[:28] + "…"
        
                    kb.append([{
                        "text": f"👤 {name}",
                        "callback_data": f"choose_chat:{p['chat_id']}:{p['peer_id']}"
                    }])
        
                text = "<b>♻️ Восстановить чат</b>\n\nВыбери чат, который хочешь восстановить:"
        
            # ⬅️ ТОЛЬКО НАЗАД (БЕЗ СКРЫТЬ)
            kb.append([{"text": "⬅️ Назад", "callback_data": "back_to_settings"}])
        
            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": kb}
            })
        
            return "ok"
        if cd == "toggle_deleted":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
    
            toggle_deleted_enabled(owner_id)
    
            enabled = is_deleted_enabled(owner_id)
            count = get_deleted_count(owner_id)
    
            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": deleted_settings_text(count),
                "parse_mode": "HTML",
                "reply_markup": deleted_settings_markup(enabled)
            })
    
            return "ok"
        # ⬅️ Назад в настройки
        if cd == "back_to_settings":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        
            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": settings_text(),
                "parse_mode": "HTML",
                "reply_markup": settings_markup(owner_id)
            })
            return "ok"
        # скрыть
        if cd.startswith("hide:"):
            if chat_id and mid:
                tg("deleteMessage", {"chat_id": chat_id, "message_id": mid})
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
            return "ok"
            
        # ⌛️ Исчезающие медиа — открыть меню
        if cd == "disappearing_settings":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})

            count = get_disappear_count(owner_id)

            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": disappearing_settings_text(count),
                "parse_mode": "HTML",
                "reply_markup": disappearing_settings_markup()
            })
            return "ok"
            
        

        # === выбран пользователь → показать меню "Открыть чат" (ЧЕРЕЗ EDIT) ===
        if cd.startswith("choose_chat:"):
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})

            try:
                _, biz_chat_id, peer_id = cd.split(":", 2)
                biz_chat_id = int(biz_chat_id)
                peer_id = int(peer_id)
            except Exception:
                return "ok"

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

            set_active_chat(
                owner_id=owner_id,
                chat_id=biz_chat_id,
                peer_id=peer_id,
                peer_name=peer_name
            )

            text2 = (
                f"👤 <b>{html.escape(peer_name)}</b> "
                f"(id: <code>{peer_id}</code>)\n\n"
                f"Здесь ты можешь восстановить чат "
                f"(если он был удалён) или вернуться назад, "
                f"чтобы выбрать другого пользователя."
            )

            kb2 = {
                "inline_keyboard": [
                    [{
                        "text": "♻️ Восстановить чат",
                        "web_app": { "url": f"https://eyes-see-bot.onrender.com/webapp?chat_id={biz_chat_id}" }
                    }],
                    [{"text": "⬅️ Назад", "callback_data": "back_to_chats"}]
                ]
            }

            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": text2,
                "parse_mode": "HTML",
                "reply_markup": kb2
            })
            return "ok"

        if cd == "back_settings":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        
            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": settings_text(),
                "parse_mode": "HTML",
                "reply_markup": settings_markup(owner_id)
            })
        
            return "ok"

                # === назад к списку пользователей (ЧЕРЕЗ EDIT) ===
        if cd == "back_to_chats":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})

            peers = get_recent_peers(owner_id, limit=10)

            if not peers:
                tg("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": mid,
                    "text": "❌ <b>Нет данных для восстановления</b>",
                    "parse_mode": "HTML"
                })
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

            # тут по твоему требованию: ВМЕСТО "Скрыть" — "Назад" (в меню настроек)
            kb.append([{"text": "⬅️ Назад", "callback_data": "back_to_settings"}])

            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": "<b>♻️ Восстановить чат</b>\n\nВыбери чат, который хочешь восстановить:",
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": kb}
            })
            return "ok"
        # ✏️ Изменённые сообщения — открыть меню
        if cd == "edited_settings":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        
            count = get_edited_count(owner_id)
            enabled = is_edited_enabled(owner_id)
        
            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": edited_settings_text(count),
                "parse_mode": "HTML",
                "reply_markup": edited_settings_markup(enabled)
            })
            return "ok"
        
        
        # ✏️ Вкл / выкл изменённые
        if cd == "toggle_edited":
            tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        
            toggle_edited_enabled(owner_id)
        
            enabled = is_edited_enabled(owner_id)
            count = get_edited_count(owner_id)
        
            tg("editMessageText", {
                "chat_id": chat_id,
                "message_id": mid,
                "text": edited_settings_text(count),
                "parse_mode": "HTML",
                "reply_markup": edited_settings_markup(enabled)
            })
            return "ok"
            
        if cd == "noop":
            tg("answerCallbackQuery", {
                "callback_query_id": cq["id"],
                "text": "Скоро будет доступно 👀",
                "show_alert": False
            })
            return "ok"


        tg("answerCallbackQuery", {"callback_query_id": cq["id"]})
        return "ok"
        
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
                SELECT
                    sender_id,
                    sender_name,
                    msg_type,
                    text,
                    file_id,
                    created_at
                FROM messages
                WHERE owner_id = %s
                  AND chat_id = %s
                ORDER BY created_at ASC
            """, (owner_id, chat_id))

            rows = cur.fetchall()

    messages = []
    for sender_id, name, mtype, text, file_id, dt in rows:
        messages.append({
            "sender_id": sender_id,
            "name": name,
            "type": mtype,
            "text": text,
            "file_id": file_id,
            "time": dt.isoformat(),
            "is_owner": sender_id == owner_id
        })

    return {
        "ok": True,
        "messages": messages
    }

# ================= WEB APP =================

@app.route("/webapp")
def webapp():
    return open("webapp.html", encoding="utf-8").read()



from flask import redirect, request, jsonify

@app.route("/api/file", methods=["GET"])
def api_file():
    file_id = request.args.get("file_id")

    if not file_id:
        return jsonify({"ok": False, "error": "file_id missing"}), 400

    r = tg("getFile", {"file_id": file_id})

    if not r.ok:
        return jsonify({"ok": False, "error": "getFile failed"}), 500

    data = r.json()

    if not data.get("ok") or "result" not in data or not data["result"].get("file_path"):
        return jsonify({"ok": False, "error": "no file_path"}), 500

    file_path = data["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

    return redirect(url, code=302)
   
# ================= START =================

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000)
