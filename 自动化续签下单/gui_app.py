#!/usr/bin/env python
"""
续签自动下单工具 - 图形化工作界面
替代 quick_start.py 的终端交互，提供 GUI 表单 + 实时日志输出
双击运行即可使用
"""

import sys
import os
import json
import queue
import subprocess
import threading
import re
from pathlib import Path
from datetime import datetime
from tkinter import Tk, StringVar, BooleanVar, IntVar, Frame, Label, \
    Entry, Button, Checkbutton, Radiobutton, Canvas, filedialog, messagebox, \
    ttk, scrolledtext, PanedWindow
from tkinter.ttk import Labelframe

BASE_DIR = Path(__file__).parent
# frozen 模式（PyInstaller 打包后）：设置文件放在 exe 同级目录
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
    MAIN_PY = None  # worker 模式使用 import，不需要文件路径
else:
    MAIN_PY = BASE_DIR / "main.py"
SETTINGS_FILE = BASE_DIR / ".gui_settings.json"

ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')
LOG_COLORS = {
    "INFO": "#2ecc71", "WARNING": "#f39c12", "ERROR": "#e74c3c",
    "DEBUG": "#95a5a6", "SUCCESS": "#27ae60", "FAIL": "#c0392b",
    "完成": "#2ecc71", "失败": "#e74c3c", "取消": "#f39c12", "错误": "#e74c3c",
}


def load_settings():
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_settings(data):
    try:
        SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    except Exception:
        pass


class RenewalOrderGUI:
    def __init__(self):
        self.root = Tk()
        self.root.title("续签自动下单工具")
        self.root.geometry("940x800")
        self.root.minsize(800, 640)

        self._proc = None
        self._stop_flag = threading.Event()
        self._log_queue = queue.Queue()
        self._confirm_shown = False  # 防止确认对话框重复弹出
        self._saved = load_settings()
        # 定期从队列取日志更新 UI（每 80ms）
        self._drain_log_queue()

        # 绑定变量
        self.mode_var = IntVar(value=self._saved.get("mode", 1))
        self.username_var = StringVar(value=self._saved.get("username", ""))
        self.password_var = StringVar(value="")
        self.start_var = StringVar(value=self._saved.get("start_date", ""))
        self.end_var = StringVar(value=self._saved.get("end_date", ""))
        self.audit_var = StringVar(value=self._saved.get("audit_date", ""))
        self.sbu_var = StringVar(value=self._saved.get("sbu", ""))
        self.skip_delete_var = BooleanVar(value=self._saved.get("skip_delete", False))
        self.resume_var = BooleanVar(value=self._saved.get("resume", False))
        self.todo_file_var = StringVar(value=self._saved.get("todo_file", ""))
        self.nr_file_var = StringVar(value=self._saved.get("nr_file", ""))
        self.headless_var = BooleanVar(value=self._saved.get("headless", False))

        self._build_ui()
        self._on_mode_change()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ═══════════════════════════════════════════════════════════════════
    # UI 构建 — 上半表单 + 下半日志，可拖动分割
    # ═══════════════════════════════════════════════════════════════════

    def _build_ui(self):
        pw = PanedWindow(self.root, orient="vertical", sashrelief="raised",
                         sashwidth=5)
        pw.pack(fill="both", expand=True)

        # ── 上半：参数表单（带滚动） ──
        form_outer = ttk.Frame(pw)
        pw.add(form_outer, minsize=220, stretch="always")

        canvas = Canvas(form_outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(form_outer, orient="vertical", command=canvas.yview)
        form_frame = ttk.Frame(canvas)

        form_frame.bind("<Configure>",
                        lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=form_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # 鼠标滚轮
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel, add="+")

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 绑定宽度自适应
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(canvas.find_withtag("all")[0],
                                                width=e.width)
                    if canvas.find_withtag("all") else None)

        # ── 标题 ──
        title = ttk.Label(form_frame,
                          text="续签自动下单工具",
                          font=("Microsoft YaHei UI", 14, "bold"))
        title.pack(pady=(10, 12))

        # ── 模式 ──
        mode_frame = Labelframe(form_frame, text="运行模式", padding=8)
        mode_frame.pack(fill="x", padx=14, pady=(0, 8))
        ttk.Radiobutton(mode_frame, text="完整流程（下载 → 清单 → 下单）",
                        variable=self.mode_var, value=1,
                        command=self._on_mode_change).pack(anchor="w", padx=6)
        ttk.Radiobutton(mode_frame, text="仅下载并生成清单",
                        variable=self.mode_var, value=2,
                        command=self._on_mode_change).pack(anchor="w", padx=6, pady=2)
        ttk.Radiobutton(mode_frame, text="仅处理已有待办清单",
                        variable=self.mode_var, value=3,
                        command=self._on_mode_change).pack(anchor="w", padx=6)

        # ── 凭据 ──
        cred_frame = Labelframe(form_frame, text="IMS 凭据", padding=8)
        cred_frame.pack(fill="x", padx=14, pady=(0, 8))
        cred_inner = ttk.Frame(cred_frame)
        cred_inner.pack(fill="x")
        ttk.Label(cred_inner, text="用户名:").pack(side="left")
        ttk.Entry(cred_inner, textvariable=self.username_var, width=22)\
            .pack(side="left", padx=6)
        ttk.Label(cred_inner, text="密码:").pack(side="left", padx=(16, 0))
        ttk.Entry(cred_inner, textvariable=self.password_var, width=22, show="*")\
            .pack(side="left", padx=6)

        # ── 下载参数 ──
        self.download_frame = Labelframe(form_frame, text="下载参数（模式 ① / ②）", padding=8)
        self.download_frame.pack(fill="x", padx=14, pady=(0, 8))

        row1 = ttk.Frame(self.download_frame)
        row1.pack(fill="x", pady=(0, 4))
        ttk.Label(row1, text="开始日期:").pack(side="left")
        ttk.Entry(row1, textvariable=self.start_var, width=22)\
            .pack(side="left", padx=6)
        ttk.Label(row1, text="例: 2026年6月1日", foreground="gray")\
            .pack(side="left", padx=(0, 20))
        ttk.Label(row1, text="结束日期:").pack(side="left")
        ttk.Entry(row1, textvariable=self.end_var, width=22)\
            .pack(side="left", padx=6)
        ttk.Label(row1, text="例: 2026年6月30日", foreground="gray")\
            .pack(side="left")

        row2 = ttk.Frame(self.download_frame)
        row2.pack(fill="x")
        ttk.Label(row2, text="稽核时间:").pack(side="left")
        ttk.Entry(row2, textvariable=self.audit_var, width=22)\
            .pack(side="left", padx=6)
        ttk.Label(row2, text="留空=结束日期", foreground="gray")\
            .pack(side="left", padx=(0, 20))
        ttk.Label(row2, text="SBU:").pack(side="left")
        ttk.Entry(row2, textvariable=self.sbu_var, width=22)\
            .pack(side="left", padx=6)
        ttk.Label(row2, text="逗号分隔，留空=全部", foreground="gray")\
            .pack(side="left")

        # ── 下单选项 ──
        self.order_opts_frame = Labelframe(form_frame, text="下单选项（模式 ① / ③）", padding=8)
        self.order_opts_frame.pack(fill="x", padx=14, pady=(0, 8))
        opts_inner = ttk.Frame(self.order_opts_frame)
        opts_inner.pack(fill="x")
        ttk.Checkbutton(opts_inner, text="跳过人员删除",
                        variable=self.skip_delete_var).pack(side="left", padx=6)
        ttk.Checkbutton(opts_inner, text="断点续跑",
                        variable=self.resume_var).pack(side="left", padx=20)
        ttk.Checkbutton(opts_inner, text="无头模式",
                        variable=self.headless_var).pack(side="left", padx=20)

        # ── 文件路径 ──
        self.file_frame = Labelframe(form_frame, text="文件路径（模式 ③）", padding=8)
        self.file_frame.pack(fill="x", padx=14, pady=(0, 8))

        fr1 = ttk.Frame(self.file_frame)
        fr1.pack(fill="x", pady=(0, 4))
        ttk.Label(fr1, text="待办清单:").pack(side="left")
        ttk.Entry(fr1, textvariable=self.todo_file_var)\
            .pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(fr1, text="浏览",
                   command=lambda: self._pick_file(self.todo_file_var, "Excel", "*.xlsx")
                   ).pack(side="left", padx=(0, 4))
        ttk.Button(fr1, text="自动选择",
                   command=self._auto_pick_todo).pack(side="left")

        fr2 = ttk.Frame(self.file_frame)
        fr2.pack(fill="x")
        ttk.Label(fr2, text="离岗清单:").pack(side="left")
        ttk.Entry(fr2, textvariable=self.nr_file_var)\
            .pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(fr2, text="浏览",
                   command=lambda: self._pick_file(self.nr_file_var, "Excel", "*.xlsx")
                   ).pack(side="left", padx=(0, 4))
        ttk.Button(fr2, text="自动选择",
                   command=self._auto_pick_nr).pack(side="left")

        # ── 按钮栏 ──
        btn_frame = ttk.Frame(form_frame)
        btn_frame.pack(fill="x", padx=14, pady=(12, 8))

        self.start_btn = ttk.Button(btn_frame, text="▶  开始执行",
                                    command=self._start_process)
        self.start_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = ttk.Button(btn_frame, text="■  停止",
                                   command=self._stop_process, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 8))
        ttk.Button(btn_frame, text="清空日志",
                   command=self._clear_log).pack(side="left")
        self.status_label = ttk.Label(btn_frame, text="就绪", foreground="gray")
        self.status_label.pack(side="right", padx=8)

        # ── 下半：日志 ──
        log_frame = ttk.Frame(pw)
        pw.add(log_frame, minsize=160, stretch="always")

        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap="word", state="disabled",
            font=("Consolas", 10), bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="white", relief="flat", borderwidth=0)
        self.log_text.pack(fill="both", expand=True)

        for tag_name, color in LOG_COLORS.items():
            self.log_text.tag_configure(tag_name, foreground=color)
        self.log_text.tag_configure("timestamp", foreground="#569cd6")
        self.log_text.tag_configure("bold", font=("Consolas", 10, "bold"))

    # ═══════════════════════════════════════════════════════════════════
    # 模式切换 — 根据所选模式显隐字段组
    # ═══════════════════════════════════════════════════════════════════

    def _on_mode_change(self):
        mode = self.mode_var.get()
        self._set_children_state(self.download_frame, mode in (1, 2))
        self._set_children_state(self.order_opts_frame, mode in (1, 3))
        self._set_children_state(self.file_frame, mode == 3)

    @staticmethod
    def _set_children_state(parent, enabled):
        state = "normal" if enabled else "disabled"
        for child in parent.winfo_children():
            RenewalOrderGUI._recursive_state(child, state)

    @staticmethod
    def _recursive_state(widget, state):
        try:
            widget.configure(state=state)
        except Exception:
            pass
        for child in widget.winfo_children():
            RenewalOrderGUI._recursive_state(child, state)

    # ═══════════════════════════════════════════════════════════════════
    # 文件选择
    # ═══════════════════════════════════════════════════════════════════

    def _pick_file(self, var, title, pattern):
        path = filedialog.askopenfilename(
            title=f"选择{title}文件",
            filetypes=[(title, pattern), ("All files", "*.*")],
            initialdir=BASE_DIR)
        if path:
            var.set(path)

    def _auto_pick_todo(self):
        import glob
        candidates = sorted(glob.glob(str(BASE_DIR / "待办订单清单_*.xlsx")),
                            reverse=True)
        if candidates:
            self.todo_file_var.set(candidates[0])
            self._log(f"[自动] 待办清单: {Path(candidates[0]).name}", "INFO")
        else:
            messagebox.showwarning("未找到", "当前目录未找到待办订单清单文件")

    def _auto_pick_nr(self):
        import glob
        candidates = sorted(glob.glob(str(BASE_DIR / "离岗不续签清单_*.xlsx")),
                            reverse=True)
        if candidates:
            self.nr_file_var.set(candidates[0])
            self._log(f"[自动] 离岗清单: {Path(candidates[0]).name}", "INFO")
        else:
            messagebox.showwarning("未找到", "当前目录未找到离岗不续签清单文件")

    # ═══════════════════════════════════════════════════════════════════
    # 校验 → 构建命令 → 启动子进程
    # ═══════════════════════════════════════════════════════════════════

    def _validate(self):
        errors = []
        if not self.username_var.get().strip():
            errors.append("IMS 用户名不能为空")
        if not self.password_var.get().strip():
            errors.append("IMS 密码不能为空")

        mode = self.mode_var.get()
        if mode in (1, 2):
            if not self.start_var.get().strip():
                errors.append("开始日期不能为空")
            if not self.end_var.get().strip():
                errors.append("结束日期不能为空")
        if mode == 3:
            todo = self.todo_file_var.get().strip()
            if not todo:
                errors.append("待办清单文件路径不能为空")
            elif not Path(todo).exists():
                errors.append(f"待办清单文件不存在:\n{todo}")
            nr = self.nr_file_var.get().strip()
            if nr and not Path(nr).exists():
                errors.append(f"离岗清单文件不存在:\n{nr}")
        return errors

    def _build_cmd(self):
        mode = self.mode_var.get()
        if getattr(sys, 'frozen', False):
            parts = [sys.executable, "--internal-worker"]
        else:
            parts = [sys.executable, "-u", str(MAIN_PY)]
        parts += [
            "--username", self.username_var.get().strip(),
            "--password", self.password_var.get().strip(),
        ]
        if self.headless_var.get():
            parts.append("--headless")

        if mode in (1, 2):
            end_date = self.end_var.get().strip()
            parts += ["--start", self.start_var.get().strip(),
                      "--end", end_date,
                      "--sbu", self.sbu_var.get().strip() or ""]
            # 始终传 --audit-date，留空时 fallback 到结束日期，避免 main.py 阻塞在 input()
            audit = self.audit_var.get().strip() or end_date
            parts += ["--audit-date", audit]
        if mode == 2:
            parts.append("--download-only")
        if mode in (1, 3):
            if self.skip_delete_var.get():
                parts.append("--skip-delete")
            if self.resume_var.get():
                parts.append("--resume")
        if mode == 3:
            parts += ["--process-only", self.todo_file_var.get().strip()]
            nr = self.nr_file_var.get().strip()
            if nr:
                parts += ["--not-renewing-file", nr]
        return parts

    def _start_process(self):
        errors = self._validate()
        if errors:
            messagebox.showerror("表单校验失败", "\n".join(errors))
            return

        self._stop_flag.clear()
        self._confirm_shown = False
        self._clear_log()
        self._set_running(True)

        save_settings({
            "mode": self.mode_var.get(),
            "username": self.username_var.get(),
            "start_date": self.start_var.get(),
            "end_date": self.end_var.get(),
            "audit_date": self.audit_var.get(),
            "sbu": self.sbu_var.get(),
            "skip_delete": self.skip_delete_var.get(),
            "resume": self.resume_var.get(),
            "todo_file": self.todo_file_var.get(),
            "nr_file": self.nr_file_var.get(),
            "headless": self.headless_var.get(),
        })

        cmd = self._build_cmd()
        self._log(f"[命令] {' '.join(cmd)}", "DEBUG")
        self._log("=" * 60, "bold")

        try:
            # 强制子进程 stdout 无缓冲：-u 参数 + PYTHONUNBUFFERED 环境变量
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUNBUFFERED"] = "1"
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                bufsize=0,  # 二进制模式下的无缓冲，实际由 text=False 时生效
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                cwd=str(BASE_DIR),
                env=env,
            )
        except Exception as e:
            self._log(f"[错误] 无法启动进程: {e}", "ERROR")
            self._set_running(False)
            return

        self.status_label.config(text="运行中...", foreground="#f39c12")
        threading.Thread(target=self._read_output, daemon=True).start()
        threading.Thread(target=self._wait_process, daemon=True).start()

    def _read_output(self):
        """读取子进程 stdout，按行解码后推入队列"""
        confirm_keywords = ["是否继续？(y/n)"]
        buf = ""
        while self._proc and self._proc.stdout and not self._stop_flag.is_set():
            raw = self._proc.stdout.read(4096)
            if not raw:
                break
            buf += raw.decode("utf-8", errors="replace")
            while "\n" in buf:
                idx = buf.index("\n")
                line = buf[:idx]
                buf = buf[idx + 1:]
                clean = ANSI_RE.sub("", line)
                self._log_queue.put(("line", clean))
                if any(kw in clean for kw in confirm_keywords) and self._proc:
                    self._log_queue.put(("confirm", None))
            # 检测残留在 buffer 中的确认提示（input() 提示不含尾部换行符）
            if any(kw in buf for kw in confirm_keywords) and self._proc:
                self._log_queue.put(("confirm", None))
        if buf:
            self._log_queue.put(("line", ANSI_RE.sub("", buf)))
        self._log_queue.put(("done", None))

    def _drain_log_queue(self):
        """定期从队列取日志并更新 UI（主线程调用）"""
        try:
            while True:
                kind, data = self._log_queue.get_nowait()
                if kind == "line":
                    self._append_log(data)
                elif kind == "confirm":
                    if self._proc and self._proc.poll() is None:
                        self._on_confirm_needed()
                elif kind == "done":
                    pass
        except queue.Empty:
            pass
        self.root.after(80, self._drain_log_queue)

    def _on_confirm_needed(self):
        if self._confirm_shown:
            return
        if not self._proc or self._proc.poll() is not None:
            return
        self._confirm_shown = True
        answer = messagebox.askyesno("确认操作", "main.py 等待确认，是否继续？")
        try:
            self._proc.stdin.write(b"y\n" if answer else b"n\n")
            self._proc.stdin.flush()
        except Exception:
            pass
        self._log(f"[用户] {'确认继续' if answer else '取消操作'}", "INFO")

    def _wait_process(self):
        if not self._proc:
            return
        try:
            returncode = self._proc.wait()
        except Exception:
            returncode = -1
        self.root.after(0, self._on_process_done, returncode)

    def _on_process_done(self, returncode):
        self._proc = None
        self._set_running(False)
        if returncode == 0:
            self._log("\n[完成] 流程执行完毕", "SUCCESS")
            self.status_label.config(text="执行完成", foreground="#27ae60")
        else:
            self._log(f"\n[失败] 进程退出码: {returncode}", "FAIL")
            self.status_label.config(text=f"异常退出 (code={returncode})",
                                     foreground="#e74c3c")

    def _stop_process(self):
        if not self._proc:
            return
        self._log("\n[操作] 用户请求停止...", "WARNING")
        self._stop_flag.set()

        try:
            self._proc.stdin.write(b"n\n")
            self._proc.stdin.flush()
        except Exception:
            pass

        try:
            self._proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._log("[操作] 已强制终止进程", "WARNING")

        self._proc = None
        self._set_running(False)
        self.status_label.config(text="已停止", foreground="gray")

    def _set_running(self, running):
        self.start_btn.config(state="disabled" if running else "normal")
        self.stop_btn.config(state="normal" if running else "disabled")

    # ═══════════════════════════════════════════════════════════════════
    # 日志
    # ═══════════════════════════════════════════════════════════════════

    def _log(self, msg, tag=None):
        self.root.after(0, self._append_log, msg, tag)

    def _append_log(self, line, tag=None):
        self.log_text.configure(state="normal")

        if tag is None:
            for kw, color_tag in LOG_COLORS.items():
                if kw in line:
                    tag = color_tag
                    break

        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] ", "timestamp")
        self.log_text.insert("end", line + "\n", tag or "")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ═══════════════════════════════════════════════════════════════════
    # 退出
    # ═══════════════════════════════════════════════════════════════════

    def _on_close(self):
        if self._proc and self._proc.poll() is None:
            ok = messagebox.askyesno("确认退出", "有任务正在运行，确定要退出吗？")
            if not ok:
                return
            self._stop_process()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if "--internal-worker" in sys.argv:
        # PyInstaller frozen 模式：强制 stdout/stderr 使用 UTF-8 编码
        # （PYTHONIOENCODING 环境变量在 PyInstaller 打包后可能不生效）
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass
        sys.argv.remove("--internal-worker")
        from main import main
        main()
    else:
        RenewalOrderGUI().run()
