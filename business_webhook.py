from flask import Flask, request
import requests

BOT_TOKEN = "7557240631:AAFy8O4D-KMkwdlAI-QtV7AtVJ0hhdXgh90"

app = Flask(__name__)


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
    data = request.get_json(silent=True)

    print("========== RAW UPDATE ==========")
    print(data)
    print("================================")

    if not data:
        return "ok"

    # 📩 обычное бизнес-сообщение
    if "business_message" in data:
        msg = data["business_message"]
        owner_id = msg["from"]["id"]
        print("📩 СООБЩЕНИЕ ОТ:", owner_id)

    # 🗑 удалённые сообщения
    elif "deleted_business_messages" in data:
        deleted = data["deleted_business_messages"]

        # ❗ owner_id БЕРЁМ ИЗ business_connection
        owner_id = data.get("business_message", {}).get("from", {}).get("id")

        # если не нашли — пробуем из предыдущего контекста
        if not owner_id:
            print("❌ owner_id не найден")
            return "ok"

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

        send_to_user(owner_id, text)

    else:
        print("⚪ ДРУГОЕ СОБЫТИЕ")

    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)