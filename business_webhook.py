from flask import Flask, request

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)

    deleted = data.get("deleted_business_messages")
    message = data.get("business_message")

    if deleted:
        chat = deleted.get("chat", {})
        chat_id = chat.get("id")
        message_ids = deleted.get("message_ids", [])

        print("🗑 УДАЛЕНИЕ СООБЩЕНИЯ")
        print("Чат ID:", chat_id)
        print("ID сообщений:", message_ids)

    elif message:
        print("📩 НОВОЕ СООБЩЕНИЕ")
        print("ID:", message.get("message_id"))
        print("Текст:", message.get("text"))

    else:
        print("⚪ ДРУГОЕ СОБЫТИЕ")
        print(data)

    return "ok"

if __name__ == "__main__":
    # локально
    app.run(host="0.0.0.0", port=8000)
