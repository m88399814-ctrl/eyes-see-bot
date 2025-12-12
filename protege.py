import re
from nltk import CFG, ChartParser


def tokenize(text: str):
    text = text.lower()
    text = re.sub(r"[^\w\sё-]", "", text)  
    return text.split()


grammar_text = r"""
S   -> NP VP
S   -> VP
S   -> VP NP
S -> NP VP    

NP  -> Det Adj N
NP  -> Det N
NP  -> Adj N
NP  -> N
NP  -> Pron

VP  -> V NP
VP  -> V PP
VP  -> V
VP  -> V PP NP
VP  -> V NP PP
VP -> NP V
VP -> Adj N V

PP  -> P NP

Det -> 'этот' | 'эта' | 'это' | 'эти' | 'мой' | 'моя' | 'моё' | 'мои' | 'тот' | 'та' | 'то' | 'те'
Pron -> 'я' | 'ты' | 'он' | 'она' | 'мы' | 'вы' | 'они'

N   -> 'кот' | 'кошка' | 'мышь' | 'мяч' | 'книга' | 'стол' | 'город' | 'машина' | 'дом' | 'человек' | 'студент' | 'учитель' | 'окно' | 'дверь' | 'дворе' 
N   -> 'кошку' | 'мыши' | 'книгу' | 'книги' | 'стола' | 'столу' | 'машину' | 'городу' | 'домом' | 'учителя' | 'студента'

Adj -> 'большой' | 'маленький' | 'красный' | 'новый' | 'старый' | 'умный' | 'интересный' | 'серую' |

V   -> 'видит' | 'вижу' | 'видим' | 'видят' | 'любит' | 'люблю' | 'любим' | 'читал' | 'читает' | 'читаю' | 'играет' | 'играю' | 'ест' | 'ел' | 'купил' | 'нашёл' | 'кладу' | 'положил' | 'идёт' | 'иду'

P   -> 'на' | 'в' | 'под' | 'с' | 'у' | 'к' | 'за' | 'над' | 'перед' | 'во' |
"""

grammar = CFG.fromstring(grammar_text)
parser = ChartParser(grammar)

def parse_sentence(sent: str):
    tokens = tokenize(sent)
    trees = list(parser.parse(tokens))
    return tokens, trees

def pretty_print_trees(tokens, trees):
    if not trees:
        print("Не удалось распознать.")
        print("Токены:", tokens)
        return
    print(f"✅ Найдено разборов: {len(trees)}")
    for i, t in enumerate(trees, 1):
        print(f"\n--- Дерево {i} ---")
        print(t)          
        t.pretty_print()
        t.draw()
if __name__ == "__main__":
    print("Пиши предложение (или exit для выхода).")
    while True:
        s = input("\n> ")
        if not s.strip():
            continue
        if s.strip().lower() == "exit":
            break
        tokens, trees = parse_sentence(s)
        pretty_print_trees(tokens, trees)
