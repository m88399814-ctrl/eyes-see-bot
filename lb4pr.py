import logging
import re

from aiogram import Bot, Dispatcher, executor, types
from deeppavlov import __version__  
TELEGRAM_TOKEN = "7983736027:AAH4yEHYJDPOSdFdZeYZH0uhKYH2OJkODwA"
CONTEXT_FILE = "textlb4pr"  
def load_context(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

context_text = load_context(CONTEXT_FILE)

def simple_qa(question: str, context: str) -> str:

    paragraphs = [p.strip() for p in context.split("\n") if p.strip()]
    q_words = re.findall(r"[а-яА-Яa-zA-ZёЁ]+", question.lower())

    if not q_words:
        return "Задай, пожалуйста, осмысленный вопрос по теме NFT-подарков."


    best_par = ""
    best_par_score = 0

    for par in paragraphs:
        lower_par = par.lower()
        score = sum(1 for w in q_words if w and w in lower_par)
        if score > best_par_score:
            best_par_score = score
            best_par = par

    if best_par_score == 0 or not best_par:
        return "Я не нашёл точного ответа в тексте. Попробуй переформулировать вопрос."


    sentences = [s.strip() for s in re.split(r"[.!?]\s*", best_par) if s.strip()]

    scored = []
    for sent in sentences:
        lower_sent = sent.lower()
        score = sum(1 for w in q_words if w and w in lower_sent)
        scored.append((score, sent))

    scored.sort(reverse=True, key=lambda x: x[0])
    top = [s for sc, s in scored[:3] if sc > 0]

    if not top:
        return best_par

    answer = ". ".join(top)
    return answer

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)

@dp.message_handler(commands=["start", "help"])
async def cmd_start(message: types.Message):
    text = (
        "Привет \n"
        "Я бот, который отвечает на вопросы про NFT-подарки в Telegram.\n"
        "Просто задай вопрос!"
    )
    await message.answer(text)

@dp.message_handler()
async def handle_question(message: types.Message):
    question = message.text.strip()
    answer = simple_qa(question, context_text)
    await message.answer(answer)

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)



    cd ~/Desktop/stremmer
python3.9 lb4pr.py