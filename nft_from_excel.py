import sys
import pandas as pd
from typing import Dict, List, Tuple, Union
import tkinter as tk
from tkinter import messagebox

Result = Union[int, Tuple[str, str]]

def load_from_excel(xlsx_path: str):
    qdf = pd.read_excel(xlsx_path, sheet_name="questions", engine="openpyxl")
    Q: Dict[int, str] = {int(r["id"]): str(r["text"]) for _, r in qdf.iterrows()}

    df = pd.read_excel(xlsx_path, sheet_name="transitions", engine="openpyxl")
    G: Dict[int, List[Tuple[str, Result]]] = {}

    for _, r in df.iterrows():
        start = int(r["Начальное состояние"])
        end_raw = r["Конечное состояние"]
        endflag = int(r["Конец поиска"])
        ans_full = str(r["Ответ пользователя"]).strip()

        if start not in G:
            G[start] = []

        if endflag == 1:
            if "→" in ans_full:
                ans, rec = [s.strip() for s in ans_full.split("→", 1)]
            else:
                ans, rec = ans_full, ans_full
            G[start].append((ans, ("FINAL", rec)))
        else:
            end = int(end_raw)
            G[start].append((ans_full, end))

    return Q, G

def ask(q_id: int, Q, G) -> str:
    opts = G[q_id]
    print(f"\n[{q_id}] {Q[q_id]}")
    
    for i, (t, _) in enumerate(opts, 1):
        print(f"  {i}) {t}")

    while True:
        raw = input("Ваш выбор (номер): ").strip()
        if raw.isdigit():
            k = int(raw)
            if 1 <= k <= len(opts):
                return opts[k-1][0]
        print("Введите корректный номер варианта.")

def run(xlsx_path: str, start: int = 0):
    Q, G = load_from_excel(xlsx_path)

    path = []
    q = start
    print("Экспертная система: выбор NFT-подарка в Telegram (Excel)")
    
    while True:
        ans = ask(q, Q, G)
        for t, nxt in G[q]:
            if t == ans:
                path.append((q, t))
                if isinstance(nxt, tuple) and nxt[0] == "FINAL":
                    print("\nИТОГОВАЯ РЕКОМЕНДАЦИЯ:", nxt[1])
                    print("\nПуть решения:")
                    for qi, a in path:
                        print(f"- [{qi}] {Q[qi]} → {a}")
                    return
                else:
                    q = nxt
                break

class NFTExpertGUI:
    def __init__(self, master: tk.Tk, xlsx_path: str = "NFT_System.xlsx"):
        self.master = master
        self.master.title("Экспертная система NFT-подарков")
        self.Q, self.G = load_from_excel(xlsx_path)
        self.current_state: int = 0
        self.path: List[Tuple[int, str]] = []
        self.question_label = tk.Label(master, text="", wraplength=500, justify="left", font=("Arial", 12))
        self.question_label.pack(padx=10, pady=10, anchor="w")
        self.buttons_frame = tk.Frame(master)
        self.buttons_frame.pack(padx=10, pady=10, anchor="w")
        self.show_question()

    def clear_buttons(self):
        for child in self.buttons_frame.winfo_children():
            child.destroy()

    def show_question(self):
        qid = self.current_state

        if qid not in self.G:
            messagebox.showerror("Ошибка", f"Нет переходов для состояния {qid}")
            self.master.destroy()
            return
        
        self.question_label.config(text=f"[{qid}] {self.Q.get(qid, '')}")

        self.clear_buttons()
        
        options = self.G[qid]
        for i, (ans_text, _) in enumerate(options, start=1):
            btn = tk.Button(self.buttons_frame, text=f"{i}) {ans_text}", command=lambda a=ans_text: self.on_answer(a), anchor="w", width=60)
            btn.pack(pady=2, anchor="w")

    def on_answer(self, answer_text: str):
        qid = self.current_state
        options = self.G[qid]
        for ans, nxt in options:
            if ans == answer_text:
                self.path.append((qid, ans))
                if isinstance(nxt, tuple) and nxt[0] == "FINAL":
                    self.show_result(nxt[1])
                else:
                    self.current_state = nxt
                    self.show_question()
                break

    def show_result(self, recommendation: str):
        lines = []
        for qid, ans in self.path:
            q_text = self.Q.get(qid, f"Вопрос {qid}")
            lines.append(f"[{qid}] {q_text} → {ans}")

        full_text = "ИТОГОВАЯ РЕКОМЕНДАЦИЯ:\n" + recommendation + "\n\nПуть решения:\n" + "\n".join(lines)
        messagebox.showinfo("Результат", full_text)

if __name__ == "__main__":
    xlsx = sys.argv[1] if len(sys.argv) > 1 else "NFT_System.xlsx"
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        run(xlsx)
    else:
        root = tk.Tk()
        app = NFTExpertGUI(root, xlsx_path=xlsx)
        root.mainloop()