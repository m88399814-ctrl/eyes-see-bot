print("FILE STARTED")
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)

from db import init_db, get_connection


BOT_TOKEN = "7557240631:AAFy8O4D-KMkwdlAI-QtV7AtVJ0hhdXgh90"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👁 Привет! Я Eyes see.\n\n"
        "Я успешно запущен на macOS 🖥️\n"
        "Дальше я научусь сохранять сообщения и помогать восстанавливать удалённое."
    )

async def save_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    chat_id = msg.chat.id
    user_id = msg.from_user.id
    username = msg.from_user.username
    message_id = msg.message_id
    date = int(msg.date.timestamp())

    message_type = "text"
    content = None
    file_id = None

    if msg.text:
        message_type = "text"
        content = msg.text

    elif msg.photo:
        message_type = "photo"
        file_id = msg.photo[-1].file_id

    elif msg.video:
        message_type = "video"
        file_id = msg.video.file_id

    elif msg.voice:
        message_type = "voice"
        file_id = msg.voice.file_id

    elif msg.video_note:
        message_type = "video_note"
        file_id = msg.video_note.file_id

    elif msg.document:
        message_type = "document"
        file_id = msg.document.file_id

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO messages
        (chat_id, user_id, username, message_id, message_type, content, file_id, date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        chat_id,
        user_id,
        username,
        message_id,
        message_type,
        content,
        file_id,
        date
    ))

    conn.commit()
    conn.close()

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT message_type, content
        FROM messages
        WHERE chat_id = ?
        ORDER BY id DESC
        LIMIT 5
    """, (chat_id,))

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("👁 История пуста.")
        return

    text = "👁 Последние сообщения:\n\n"

    for i, (message_type, content) in enumerate(rows, start=1):
        if message_type == "text":
            text += f"{i}) [text] {content}\n"
        else:
            text += f"{i}) [{message_type}]\n"

    await update.message.reply_text(text)

async def last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT message_type, content
        FROM messages
        WHERE chat_id = ?
        ORDER BY id DESC
        LIMIT 1
    """, (chat_id,))

    row = cur.fetchone()
    conn.close()

    if not row:
        await update.message.reply_text("👁 Сообщений пока нет.")
        return

    message_type, content = row

    if message_type == "text":
        text = f"👁 Последнее сообщение:\n[text] {content}"
    else:
        text = f"👁 Последнее сообщение:\n[{message_type}]"

    await update.message.reply_text(text)

async def restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT message_type, content, file_id
        FROM messages
        WHERE chat_id = ?
        ORDER BY id DESC
        LIMIT 1
    """, (chat_id,))

    row = cur.fetchone()
    conn.close()

    if not row:
        await update.message.reply_text("👁 Нечего восстанавливать.")
        return

    message_type, content, file_id = row

    # ТЕКСТ
    if message_type == "text":
        await update.message.reply_text(
            f"👁 Восстановлено сообщение:\n{content}"
        )

    # ФОТО
    elif message_type == "photo":
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=file_id,
            caption="👁 Восстановлено удалённое фото"
        )

    # ВИДЕО
    elif message_type == "video":
        await context.bot.send_video(
            chat_id=chat_id,
            video=file_id,
            caption="👁 Восстановлено удалённое видео"
        )

    # ГОЛОСОВОЕ
    elif message_type == "voice":
        await context.bot.send_voice(
            chat_id=chat_id,
            voice=file_id,
            caption="👁 Восстановлено удалённое голосовое"
        )

    # КРУЖОК
    elif message_type == "video_note":
        await context.bot.send_video_note(
            chat_id=chat_id,
            video_note=file_id
        )

    # ДОКУМЕНТ
    elif message_type == "document":
        await context.bot.send_document(
            chat_id=chat_id,
            document=file_id,
            caption="👁 Восстановлён удалённый файл"
        )

    else:
        await update.message.reply_text(
            f"👁 Сообщение типа [{message_type}] восстановлено (тип не обработан)"
        )


def main():
    init_db()  # ← создаёт базу eyessee.db

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("last", last))
    app.add_handler(CommandHandler("restore", restore))
    app.add_handler(MessageHandler(filters.ALL, save_message))


    print("Eyes see запущен...")
    app.run_polling()



if __name__ == "__main__":
    main()
