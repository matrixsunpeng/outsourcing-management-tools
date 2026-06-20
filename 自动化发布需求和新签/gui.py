#!/usr/bin/env python
"""GUI 桌面工具 — 外包招聘流程自动化

所有 Phase 在主进程中以线程+runpy 执行，无子进程，不弹黑窗。
"""

import os
import sys
import io
import json
import subprocess as _sp
import threading
import webbrowser
from datetime import datetime
from contextlib import redirect_stdout, redirect_stderr
import tkinter as tk
from tkinter import ttk, messagebox

# Monkey-patch subprocess.Popen（子类方式，兼容 asyncio 继承 Popen）
# 防止 Playwright 的 Node.js 驱动在 GUI 模式下弹出黑窗
_original_popen = _sp.Popen

class _PatchedPopen(_original_popen):
    def __init__(self, args, bufsize=-1, executable=None,
                 stdin=None, stdout=None, stderr=None,
                 preexec_fn=None, close_fds=True, shell=False,
                 cwd=None, env=None, universal_newlines=None,
                 startupinfo=None, creationflags=0,
                 restore_signals=True, start_new_session=False,
                 pass_fds=(), *, encoding=None, errors=None, text=None,
                 **kwargs):
        if sys.platform == "win32" and not creationflags & _sp.CREATE_NO_WINDOW:
            creationflags |= _sp.CREATE_NO_WINDOW
            if startupinfo is None:
                startupinfo = _sp.STARTUPINFO()
                startupinfo.dwFlags |= _sp.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = _sp.SW_HIDE
        super().__init__(args, bufsize, executable,
                         stdin, stdout, stderr,
                         preexec_fn, close_fds, shell,
                         cwd, env, universal_newlines,
                         startupinfo, creationflags,
                         restore_signals, start_new_session,
                         pass_fds, encoding=encoding, errors=errors, text=text,
                         **kwargs)

_sp.Popen = _PatchedPopen


class _CaptureIO(io.StringIO):
    """捕获 stdout/stderr，同时兼容 sys.stdout.reconfigure()"""
    def __init__(self, callback):
        super().__init__()
        self._callback = callback
    def write(self, s):
        super().write(s)
        # 逐行回调
        while True:
            pos = self.getvalue().find("\n")
            if pos < 0:
                break
            line = self.getvalue()[:pos].rstrip("\r")
            if line:
                self._callback(line)
            remaining = self.getvalue()[pos + 1:]
            self.truncate(0)
            self.seek(0)
            if remaining:
                self.write(remaining)
            break
    def reconfigure(self, *args, **kwargs):
        pass
    def flush(self):
        pass


# ──── 辅助函数 ──────────────────────────────────────

def _resolve_path(relative_path: str) -> str:
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIR_F1 = _resolve_path("1.提取申请单建多维表")
DIR_F2 = _resolve_path("2.根据多维表发布需求")
DIR_F3 = _resolve_path("3.查找需求返回职位编号")
BITABLE_CONFIG = os.path.join(DIR_F1, "bitable_config.json")
CONFIG_F2 = os.path.join(DIR_F2, "config.env")
CONFIG_F3 = os.path.join(DIR_F3, "config.env")

PHASES = [
    ("1", "提取申请单建多维表"),
    ("2", "配置同步"),
    ("3", "人工审核"),
    ("4", "根据多维表发布需求"),
    ("5", "查找需求返回职位编号"),
]

STATUS_COLORS = {
    "pending": "#999", "running": "#2196F3", "waiting": "#FF9800",
    "done": "#4CAF50", "failed": "#F44336", "skipped": "#999",
}
STATUS_ICONS = {
    "pending": "○", "running": "▶", "waiting": "⏸",
    "done": "●", "failed": "✕", "skipped": "○",
}


def parse_sbu_values(raw: str) -> list[str]:
    if not raw:
        return ["185"]
    raw = raw.replace("，", ",")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    seen = set()
    result = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def load_initial_config() -> dict:
    config = {}
    for env_path in [os.path.join(DIR_F1, ".env"),
                     os.path.join(DIR_F2, "config.env"),
                     os.path.join(DIR_F3, "config.env")]:
        if not os.path.exists(env_path):
            continue
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        key, _, val = line.partition("=")
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if key in ("IMS_USERNAME", "IMS_PASSWORD") and val and key not in config:
                            config[key] = val
        except Exception:
            pass
    return config


# ──── GUI 主类 ────────────────────────────────────

class PipelineGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("外包招聘流程自动化")
        self.root.geometry("860x700")
        self.root.minsize(700, 550)
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w, h = 860, 700
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        self._stop_flag = threading.Event()
        self._checkpoint_event = threading.Event()
        self._worker = None

        initial = load_initial_config()

        # ==== 输入区 ====
        input_frame = ttk.LabelFrame(self.root, text="配置", padding=10)
        input_frame.pack(fill=tk.X, padx=12, pady=(12, 4))

        ttk.Label(input_frame, text="SBU/BU:").grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
        self.sbu_var = tk.StringVar(value="185")
        self.sbu_entry = ttk.Entry(input_frame, textvariable=self.sbu_var, width=30)
        self.sbu_entry.grid(row=0, column=1, sticky=tk.W, padx=4)

        ttk.Label(input_frame, text="IMS 用户名:").grid(row=0, column=2, sticky=tk.W, padx=(16, 4))
        self.user_var = tk.StringVar(value=initial.get("IMS_USERNAME", ""))
        self.user_entry = ttk.Entry(input_frame, textvariable=self.user_var, width=22)
        self.user_entry.grid(row=0, column=3, sticky=tk.W, padx=4)

        ttk.Label(input_frame, text="IMS 密码:").grid(row=0, column=4, sticky=tk.W, padx=(16, 4))
        self.pwd_var = tk.StringVar(value=initial.get("IMS_PASSWORD", ""))
        self.pwd_entry = ttk.Entry(input_frame, textvariable=self.pwd_var, show="*", width=22)
        self.pwd_entry.grid(row=0, column=5, sticky=tk.W, padx=4)

        # ==== 按钮区 ====
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=12, pady=4)

        self.btn_full = ttk.Button(btn_frame, text="① 提取+审核+发布",
                                   command=lambda: self._start_pipeline("start"))
        self.btn_full.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_review = ttk.Button(btn_frame, text="② 审核+发布",
                                     command=lambda: self._start_pipeline("review"))
        self.btn_review.pack(side=tk.LEFT, padx=6)
        self.btn_publish = ttk.Button(btn_frame, text="③ 仅发布",
                                      command=lambda: self._start_pipeline("publish"))
        self.btn_publish.pack(side=tk.LEFT, padx=6)
        self.btn_stop = ttk.Button(btn_frame, text="停止", command=self._stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.RIGHT, padx=6)

        # ==== 进度区 ====
        progress_frame = ttk.LabelFrame(self.root, text="进度", padding=8)
        progress_frame.pack(fill=tk.X, padx=12, pady=4)

        self.phase_labels = {}
        for num, name in PHASES:
            lbl = tk.Label(progress_frame, text=f"  {STATUS_ICONS['pending']}  Phase {num}: {name}",
                           font=("Microsoft YaHei UI", 10), fg=STATUS_COLORS["pending"],
                           anchor=tk.W, padx=4)
            lbl.pack(fill=tk.X, pady=1)
            self.phase_labels[num] = lbl

        # ==== 日志区 ====
        log_frame = ttk.LabelFrame(self.root, text="输出日志", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 12))

        self.log_text = tk.Text(log_frame, font=("Consolas", 9), wrap=tk.WORD,
                                bg="#1e1e1e", fg="#d4d4d4",
                                insertbackground="#d4d4d4",
                                selectbackground="#264f78")
        self.log_text.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(self.log_text, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self.log_text.tag_configure("error", foreground="#f44747")
        self.log_text.tag_configure("warn", foreground="#e5c07b")
        self.log_text.tag_configure("success", foreground="#89d185")
        self.log_text.tag_configure("phase", foreground="#61afef")

        self._log("就绪，请配置参数后点击按钮开始。\n", "phase")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ──── 日志 ──────────────────────────────────

    def _log(self, text: str, tag: str = ""):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {text}"
        if not text.endswith("\n"):
            line += "\n"
        self.log_text.insert(tk.END, line, tag)
        self.log_text.see(tk.END)

    def _log_phase(self, text: str):
        self._log(f"═══ {text} ═══", "phase")

    # ──── 进度 / 按钮 ──────────────────────────

    def _set_progress(self, phase: str, status: str):
        name = dict(PHASES)[phase]
        icon = STATUS_ICONS.get(status, "○")
        color = STATUS_COLORS.get(status, "#999")
        self.phase_labels[phase].configure(text=f"  {icon}  Phase {phase}: {name}", fg=color)

    def _reset_progress(self):
        for num, _ in PHASES:
            self._set_progress(num, "pending")

    def _set_buttons_state(self, running: bool):
        state = tk.DISABLED if running else tk.NORMAL
        self.btn_full.configure(state=state)
        self.btn_review.configure(state=state)
        self.btn_publish.configure(state=state)
        self.btn_stop.configure(state=tk.NORMAL if running else tk.DISABLED)

    # ──── 流水线调度 ──────────────────────────

    def _start_pipeline(self, from_phase: str):
        sbu = self.sbu_var.get().strip()
        username = self.user_var.get().strip()
        password = self.pwd_var.get().strip()
        if not username:
            messagebox.showwarning("缺少参数", "请输入 IMS 用户名")
            return
        if not password:
            messagebox.showwarning("缺少参数", "请输入 IMS 密码")
            return

        sbu_values = parse_sbu_values(sbu)
        self._sbu_arg = ",".join(sbu_values)
        self._username = username
        self._password = password
        self._from_phase = from_phase

        self._stop_flag.clear()
        self._checkpoint_event.clear()
        self._reset_progress()
        self.log_text.delete("1.0", tk.END)
        self._set_buttons_state(running=True)
        self._worker = threading.Thread(target=self._run_pipeline, daemon=True)
        self._worker.start()

    def _run_pipeline(self):
        from_phase = self._from_phase
        cred = ["--username", self._username, "--password", self._password]

        try:
            if from_phase == "start":
                ok = self._run_phase("1", "提取申请单建多维表", DIR_F1,
                                     ["main.py", "--sbu", self._sbu_arg] + cred)
                if not ok and self._stop_flag.is_set():
                    return
            else:
                self._set_progress("1", "skipped")
                self._log("Phase 1 已跳过", "warn")

            if self._stop_flag.is_set(): return

            self._set_progress("2", "running")
            self._log_phase("Phase 2/5: 配置同步")
            self._sync_config()
            self._set_progress("2", "done")
            self._log("配置同步完成", "success")

            if self._stop_flag.is_set(): return

            if from_phase in ("start", "review"):
                self._set_progress("3", "waiting")
                self._log_phase("Phase 3/5: 等待人工审核")
                self.root.after(0, self._show_review_dialog)
                self._checkpoint_event.wait()
                if self._stop_flag.is_set(): return
                self._set_progress("3", "done")
                self._log("人工审核已确认", "success")
            else:
                self._set_progress("3", "skipped")
                self._log("Phase 3 已跳过", "warn")

            if self._stop_flag.is_set(): return

            ok = self._run_phase("4", "根据多维表发布需求", DIR_F2,
                                 ["main.py", "-y"] + cred)
            if not ok and self._stop_flag.is_set(): return
            if self._stop_flag.is_set(): return

            self._run_phase("5", "查找需求返回职位编号", DIR_F3,
                            ["main.py", "--bu", self._sbu_arg] + cred)

        except Exception as e:
            self._log(f"流水线异常: {e}", "error")
        finally:
            self.root.after(0, lambda: self._set_buttons_state(running=False))
            self._log_phase("流水线结束")

    # ──── Phase 执行（同进程 runpy，无子进程无黑窗）───

    def _run_phase(self, phase: str, title: str, cwd: str, args: list[str]) -> bool:
        self._set_progress(phase, "running")
        self._log_phase(f"Phase {phase}/5: {title}")

        # 遮盖密码用于日志
        display = list(args)
        for i in range(len(display) - 1):
            if display[i] == "--password":
                display[i + 1] = "***"
        self._log(f"python {' '.join(display)}")

        old_argv = sys.argv
        old_cwd = os.getcwd()
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        pre_modules = set(sys.modules.keys())

        def _on_line(line: str):
            tag = ""
            if "ERROR" in line or "异常" in line:
                tag = "error"
            elif "WARN" in line:
                tag = "warn"
            self._log(line, tag)

        capture = _CaptureIO(_on_line)

        ok = False
        try:
            os.chdir(cwd)
            sys.path.insert(0, cwd)
            sys.argv = args
            sys.stdout = capture
            sys.stderr = capture

            # 用 exec(compile()) 替代 runpy.run_path，兼容 PyInstaller + Python 3.13
            main_path = os.path.join(cwd, "main.py")
            with open(main_path, "r", encoding="utf-8") as f:
                source = f.read()
            code = compile(source, main_path, "exec")
            exec(code, {"__name__": "__main__", "__file__": main_path})
            ok = True
        except SystemExit as e:
            ok = e.code == 0 or e.code is None
        except Exception as e:
            import traceback
            self._log(traceback.format_exc(), "error")
            self._log(f"Phase {phase} 异常: {e}", "error")
        finally:
            sys.argv = old_argv
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            # 输出残留 buffer
            remaining = capture.getvalue().strip()
            if remaining:
                for line in remaining.splitlines():
                    line = line.strip()
                    if line:
                        _on_line(line)
            os.chdir(old_cwd)
            # 清除本阶段加载的模块
            for mod in set(sys.modules.keys()) - pre_modules:
                del sys.modules[mod]
            # 清理 sys.path
            if cwd in sys.path:
                sys.path.remove(cwd)

        status = "done" if ok else "failed"
        self._set_progress(phase, status)
        self._log(f"Phase {phase} {'成功' if ok else '失败'}", "success" if ok else "error")
        return ok

    # ──── 配置同步 ────────────────────────────

    def _sync_config(self):
        if not os.path.exists(BITABLE_CONFIG):
            self._log("bitable_config.json 不存在，跳过配置同步", "warn")
            return
        with open(BITABLE_CONFIG, "r", encoding="utf-8") as f:
            bc = json.load(f)
        base_token = bc.get("base_token", "")
        table_id = bc.get("table_id", "")
        if not base_token or not table_id:
            self._log("bitable_config.json 内容不完整", "warn")
            return
        self._log(f"BITABLE_TOKEN={base_token}, TABLE_ID={table_id}")
        for cp in [CONFIG_F2, CONFIG_F3]:
            if not os.path.exists(cp):
                continue
            with open(cp, "r", encoding="utf-8") as f:
                lines = f.readlines()
            new = []
            ht = htb = False
            for line in lines:
                s = line.strip()
                if s.startswith("BITABLE_TOKEN"):
                    new.append(f"BITABLE_TOKEN={base_token}\n"); ht = True
                elif s.startswith("TABLE_ID"):
                    new.append(f"TABLE_ID={table_id}\n"); htb = True
                else:
                    new.append(line)
            if not ht: new.append(f"BITABLE_TOKEN={base_token}\n")
            if not htb: new.append(f"TABLE_ID={table_id}\n")
            with open(cp, "w", encoding="utf-8") as f:
                f.writelines(new)

    # ──── 人工审核弹窗 ──────────────────────────

    def _show_review_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("人工审核")
        dialog.geometry("520x320")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.update_idletasks()
        px = self.root.winfo_rootx() + (self.root.winfo_width() - 520) // 2
        py = self.root.winfo_rooty() + (self.root.winfo_height() - 320) // 2
        dialog.geometry(f"+{px}+{py}")

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="请在飞书多维表中完成以下操作：",
                  font=("Microsoft YaHei UI", 11, "bold")).pack(anchor=tk.W, pady=(0, 12))
        for item in [
            "1. 检查数据完整性（岗位、工作内容、技能要求等）",
            "2. 分配供应商（填写\"供应商\"和\"分配人数\"列）",
            "3. 确认无误后点击下方\"继续\"按钮",
        ]:
            ttk.Label(frame, text=item, font=("Microsoft YaHei UI", 10)).pack(anchor=tk.W, pady=2)

        bc = {}
        if os.path.exists(BITABLE_CONFIG):
            with open(BITABLE_CONFIG, "r", encoding="utf-8") as f:
                bc = json.load(f)
        url = f"https://bytedance.feishu.cn/base/{bc.get('base_token', '')}?table={bc.get('table_id', '')}"

        link_frame = ttk.Frame(frame)
        link_frame.pack(fill=tk.X, pady=(12, 4))
        ttk.Label(link_frame, text="多维表链接:", font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)

        def _open_url(event):
            webbrowser.open(url)

        link_label = tk.Label(link_frame, text=url, fg="#2196F3", cursor="hand2",
                              font=("Microsoft YaHei UI", 9, "underline"))
        link_label.pack(side=tk.LEFT, padx=(4, 0))
        link_label.bind("<Button-1>", _open_url)

        def _copy_url():
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            copy_btn.configure(text="已复制!")
            self.root.after(2000, lambda: copy_btn.configure(text="复制"))

        copy_btn = ttk.Button(link_frame, text="复制", width=6, command=_copy_url)
        copy_btn.pack(side=tk.RIGHT)

        def _continue():
            dialog.destroy()
            self._checkpoint_event.set()

        def _abort():
            self._stop_flag.set()
            self._checkpoint_event.set()
            dialog.destroy()

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(btn_frame, text="继续执行", command=_continue).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_frame, text="终止流程", command=_abort).pack(side=tk.RIGHT, padx=4)
        dialog.protocol("WM_DELETE_WINDOW", _abort)

    # ──── 停止 / 关闭 ─────────────────────────

    def _stop(self):
        self._stop_flag.set()
        self._checkpoint_event.set()
        self._log("用户请求停止（当前阶段完成后终止）", "warn")
        self._set_buttons_state(running=False)

    def _on_close(self):
        self._stop_flag.set()
        self._checkpoint_event.set()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = PipelineGUI()
    app.run()
