# math_kids_game.py
import tkinter as tk
from tkinter import messagebox
import random

class MathGameForKids:
    def __init__(self, root):
        self.root = root
        self.root.title("🔢 数学小勇士 - 4~6岁宝宝版")
        self.root.geometry("600x500")
        self.root.configure(bg="#FFF9C4")  # 淡黄色背景，柔和护眼

        # 游戏状态
        self.score = 0
        self.total_questions = 0
        self.max_questions = 10  # 一轮10题
        self.time_left = 10      # 每题10秒
        self.timer_id = None
        self.current_answer = 0

        self.setup_ui()
        self.new_question()

    def setup_ui(self):
        # 标题
        title = tk.Label(
            self.root,
            text="🌟 数学小勇士 🌟",
            font=("Comic Sans MS", 28, "bold"),
            bg="#FFF9C4",
            fg="#E91E63"
        )
        title.pack(pady=10)

        # 分数显示
        self.score_label = tk.Label(
            self.root,
            text=f"得分: {self.score}",
            font=("Comic Sans MS", 20),
            bg="#FFF9C4",
            fg="#3F51B5"
        )
        self.score_label.pack(pady=5)

        # 倒计时
        self.timer_label = tk.Label(
            self.root,
            text=f"时间: {self.time_left}s",
            font=("Comic Sans MS", 18),
            bg="#FFF9C4",
            fg="#FF5722"
        )
        self.timer_label.pack(pady=5)

        # 题目显示
        self.question_label = tk.Label(
            self.root,
            text="?",
            font=("Comic Sans MS", 48, "bold"),
            bg="#FFF9C4",
            fg="#4CAF50"
        )
        self.question_label.pack(pady=30)

        # 反馈消息（答对/答错）
        self.feedback_label = tk.Label(
            self.root,
            text="",
            font=("Comic Sans MS", 24, "bold"),
            bg="#FFF9C4",
            fg="#2196F3"
        )
        self.feedback_label.pack(pady=10)

        # 数字按钮（0-9 + 提交）
        button_frame = tk.Frame(self.root, bg="#FFF9C4")
        button_frame.pack(pady=10)

        self.input_str = ""
        self.answer_label = tk.Label(
            button_frame,
            text="答案: ",
            font=("Comic Sans MS", 20),
            bg="#FFF9C4",
            fg="#673AB7"
        )
        self.answer_label.grid(row=0, column=0, columnspan=3, pady=5)

        # 数字按钮 0-9
        for i in range(10):
            btn = tk.Button(
                button_frame,
                text=str(i),
                font=("Comic Sans MS", 18, "bold"),
                width=4,
                height=2,
                bg="#81C784",
                fg="white",
                command=lambda x=i: self.input_digit(x)
            )
            row = 1 + (i // 3)
            col = i % 3
            btn.grid(row=row, column=col, padx=5, pady=5)

        # 删除按钮
        del_btn = tk.Button(
            button_frame,
            text="⌫",
            font=("Comic Sans MS", 18, "bold"),
            width=4,
            height=2,
            bg="#FF7043",
            fg="white",
            command=self.delete_digit
        )
        del_btn.grid(row=4, column=0, padx=5, pady=5)

        # 提交按钮
        submit_btn = tk.Button(
            button_frame,
            text="✅ 提交",
            font=("Comic Sans MS", 18, "bold"),
            width=9,
            height=2,
            bg="#4FC3F7",
            fg="white",
            command=self.check_answer
        )
        submit_btn.grid(row=4, column=1, columnspan=2, padx=5, pady=5)

        # 新游戏按钮
        restart_btn = tk.Button(
            self.root,
            text="🔄 再玩一次",
            font=("Comic Sans MS", 16),
            bg="#FFD54F",
            fg="#333",
            command=self.restart_game
        )
        restart_btn.pack(pady=10)

    def input_digit(self, digit):
        if len(self.input_str) < 2:  # 最多两位数（虽然结果≤10）
            self.input_str += str(digit)
            self.update_answer_display()

    def delete_digit(self):
        self.input_str = self.input_str[:-1]
        self.update_answer_display()

    def update_answer_display(self):
        self.answer_label.config(text=f"答案: {self.input_str if self.input_str else '_'}")

    def new_question(self):
        if self.total_questions >= self.max_questions:
            self.show_final_score()
            return

        self.total_questions += 1
        self.input_str = ""
        self.update_answer_display()
        self.feedback_label.config(text="")

        # 随机选择加法或减法
        if random.choice([True, False]):
            # 加法：a + b ≤ 10
            a = random.randint(0, 10)
            b = random.randint(0, 10 - a)
            self.current_answer = a + b
            question = f"{a} + {b} = ?"
        else:
            # 减法：a - b ≥ 0
            a = random.randint(0, 10)
            b = random.randint(0, a)
            self.current_answer = a - b
            question = f"{a} - {b} = ?"

        self.question_label.config(text=question)
        self.start_timer()

    def start_timer(self):
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
        self.time_left = 10
        self.update_timer()

    def update_timer(self):
        self.timer_label.config(text=f"时间: {self.time_left}s")
        if self.time_left > 0:
            self.time_left -= 1
            self.timer_id = self.root.after(1000, self.update_timer)
        else:
            # 超时
            self.feedback_label.config(text="⏰ 时间到！下一题～", fg="#FF5722")
            self.root.after(1500, self.new_question)

    def check_answer(self):
        if self.timer_id:
            self.root.after_cancel(self.timer_id)

        try:
            user_ans = int(self.input_str) if self.input_str else -1
        except:
            user_ans = -1

        if user_ans == self.current_answer:
            self.score += 1
            self.score_label.config(text=f"得分: {self.score}")
            self.feedback_label.config(text="🎉 答对了！真棒！", fg="#4CAF50")
            self.root.after(1200, self.new_question)
        else:
            self.feedback_label.config(text="🤔 再想想哦～", fg="#FF9800")
            # 不扣分，3秒后自动继续
            self.root.after(2000, lambda: self.feedback_label.config(text=""))

    def show_final_score(self):
        msg = f"🏆 恭喜完成！\n\n你答对了 {self.score} 题 / {self.max_questions} 题！\n\n"
        if self.score == self.max_questions:
            msg += "🌟 你是数学小天才！"
        elif self.score >= 7:
            msg += "👍 太厉害啦！"
        else:
            msg += "💪 继续加油，你会更棒的！"

        messagebox.showinfo("游戏结束", msg)
        self.restart_game()

    def restart_game(self):
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
        self.score = 0
        self.total_questions = 0
        self.score_label.config(text="得分: 0")
        self.feedback_label.config(text="")
        self.new_question()

if __name__ == "__main__":
    root = tk.Tk()
    app = MathGameForKids(root)
    root.mainloop()
