from flask import Flask, request

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    print("========== RAW UPDATE ==========")
    print(data)
    print("================================")

    if not data:
        return "ok"

    if "business_message" in data:
        message = data["business_message"]
        print("📩 ТЕКСТ:", message.get("text"))

    elif "deleted_business_messages" in data:
        deleted = data["deleted_business_messages"]
        print("🗑 УДАЛЕНО СООБЩЕНИЕ:", deleted)

    else:
        print("⚪ ДРУГОЕ СОБЫТИЕ")

    return "ok"

if __name__ == "__main__":
    # локально
    app.run(host="0.0.0.0", port=8000)
