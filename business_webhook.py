from flask import Flask, request
import requests

BOT_TOKEN = "7557240631:AAFy8O4D-KMkwdlAI-QtV7AtVJ0hhdXgh90"

app = Flask(__name__)

# 🔐 глобально храним владельца бизнес-аккаунта
OWNER_ID = None


def send_to_user(user_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": user_id,
        "text": text,
        "parse_mode": "HTML"
    }
    requests.post(url, json=payload)


@app.route("/webhook", methods=["POST"])
def webhook():
    global OWNER_ID

    data = request.get_json(silent=True)

    print("\n========== RAW UPDATE ==========")
    print(data)
    print("================================\n")

    if not data:
        return "ok"

    # 🔑 1. ПОДКЛЮЧЕНИЕ БИЗНЕС-АККАУНТА
    if "business_connection" in data:
        OWNER_ID = data["business_connection"]["user"]["id"]
        print(f"✅ BUSINESS OWNER CONNECTED: {OWNER_ID}")
        return "ok"

    # 📩 2. ОБЫЧНОЕ БИЗНЕС-СООБЩЕНИЕ (ПОКА ТОЛЬКО ЛОГ)
    if "business_message" in data:
        msg = data["business_message"]
        print("📩 BUSINESS MESSAGE:",
              "from:", msg.get("from", {}).get("id"),
              "text:", msg.get("text"))
        return "ok"

    # 🗑 3. УДАЛЁННЫЕ СООБЩЕНИЯ
    if "deleted_business_messages" in data:
        if not OWNER_ID:
            print("❌ OWNER_ID ещё не установлен")
            return "ok"

        deleted = data["deleted_business_messages"]
        message_ids = deleted.get("message_ids", [])
        count = len(message_ids)

        if count == 1:
            text = (
                "🗑 <b>Новое удалённое сообщение</b>\n\n"
                "Сообщение было удалено."
            )
        else:
            text = (
                "🗑 <b>Новые удалённые сообщения</b>\n\n"
                f"Количество: {count}"
            )

        send_to_user(OWNER_ID, text)
        print(f"🗑 Уведомление отправлено OWNER_ID={OWNER_ID}")

        return "ok"

    # ⚪ всё остальное игнорируем
    print("⚪ ДРУГОЕ СОБЫТИЕ")
    return "ok"


if name == "__main__":
    app.run(host="0.0.0.0", port=8000)
