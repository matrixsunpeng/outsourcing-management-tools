#!/usr/bin/env python
"""GUI 桌面工具 — 人员面试评价 → 新签 自动化

流程: Step 4 (提取人员面试评价建多维表) → 检查多维表 → Step 5 (根据人员面试评价新签)

所有步骤在主进程中以线程+exec 执行，无子进程，不弹黑窗。
"""

import os
import sys
import io
import json
import re
import subprocess as _sp
import threading
import webbrowser
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

# ──── Monkey-patch subprocess.Popen 防止 Playwright 弹黑窗 ────
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


# ──── 日志捕获 ──────────────────────────────────────

class _CaptureIO(io.StringIO):
    """捕获 stdout/stderr，同时兼容 sys.stdout.reconfigure()"""

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def write(self, s):
        super().write(s)
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


# ──── 路径解析 ──────────────────────────────────────

def _resolve_path(relative_path: str) -> str:
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIR_STEP4 = _resolve_path("4.提取人员面试评价建多维表")
DIR_STEP5 = _resolve_path("5.根据人员面试评价新签")
ENV_STEP4 = os.path.join(DIR_STEP4, ".env")
ENV_STEP5 = os.path.join(DIR_STEP5, "config.env")

# ──── 辅助函数 ──────────────────────────────────────


def parse_bu_values(raw: str) -> list[str]:
    """解析逗号分隔的 BU 代码，支持中英文逗号，去空白去重，不区分大小写"""
    if not raw:
        return ["185"]
    raw = raw.replace("，", ",")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    seen = set()
    result = []
    for p in parts:
        # 不区分大小写去重
        key = p.lower()
        if key not in seen:
            seen.add(key)
            result.append(p)
    return result


def load_initial_config() -> dict:
    """从现有配置文件读取初始值"""
    config = {}
    # 从 step4 .env 读 IMS 凭证
    if os.path.exists(ENV_STEP4):
        try:
            with open(ENV_STEP4, "r", encoding="utf-8") as f:
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
    # 从 step5 config.env 补充
    if os.path.exists(ENV_STEP5):
        try:
            with open(ENV_STEP5, "r", encoding="utf-8") as f:
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


def get_bitable_url() -> str:
    """从 step5 config.env 构造多维表链接"""
    try:
        with open(ENV_STEP5, "r", encoding="utf-8") as f:
            content = f.read()
        bt = re.search(r'BITABLE_TOKEN\s*=\s*(\S+)', content)
        ti = re.search(r'TABLE_ID\s*=\s*(\S+)', content)
        if bt and ti:
            return f"https://bytedance.feishu.cn/base/{bt.group(1)}?table={ti.group(1)}"
    except Exception:
        pass
    # 回退：读 step4 .env 的 FEISHU_BITABLE_ID
    try:
        with open(ENV_STEP4, "r", encoding="utf-8") as f:
            content = f.read()
        bt = re.search(r'FEISHU_BITABLE_ID\s*=\s*(\S+)', content)
        if bt:
            return f"https://bytedance.feishu.cn/base/{bt.group(1)}"
    except Exception:
        pass
    return ""


def sync_bitable_config():
    """将 step4 的多维表配置同步到 step5 的 config.env。

    Step4 创建/填充多维表后，其 table_id 可能变化。
    通过飞书 API 查询最新 table_id 并写入 step5 config。
    """
    # 读 step4 配置
    feishu_app_id = ""
    feishu_app_secret = ""
    bitable_id = ""
    try:
        with open(ENV_STEP4, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k == "FEISHU_APP_ID":
                        feishu_app_id = v
                    elif k == "FEISHU_APP_SECRET":
                        feishu_app_secret = v
                    elif k == "FEISHU_BITABLE_ID":
                        bitable_id = v
    except Exception:
        pass

    if not bitable_id:
        print("[同步] 未找到 FEISHU_BITABLE_ID，跳过配置同步")
        return False

    table_id = ""
    # 尝试通过飞书 API 获取 table_id
    if feishu_app_id and feishu_app_secret:
        try:
            import requests
            # 获取 token
            resp = requests.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": feishu_app_id, "app_secret": feishu_app_secret},
                timeout=15,
            )
            if resp.json().get("code") == 0:
                token = resp.json()["tenant_access_token"]
                headers = {"Authorization": f"Bearer {token}"}
                # 获取 table 列表
                resp2 = requests.get(
                    f"https://open.feishu.cn/open-apis/bitable/v1/apps/{bitable_id}/tables",
                    headers=headers,
                    timeout=15,
                )
                if resp2.json().get("code") == 0:
                    tables = resp2.json().get("data", {}).get("items", [])
                    if tables:
                        table_id = tables[0]["table_id"]
                        print(f"[同步] 获取到 TABLE_ID: {table_id}")
        except Exception as e:
            print(f"[同步] 获取 table_id 失败: {e}")

    # 更新 step5 config.env
    if os.path.exists(ENV_STEP5):
        try:
            with open(ENV_STEP5, "r", encoding="utf-8") as f:
                lines = f.readlines()

            updated_token = False
            updated_table = False
            new_lines = []
            for line in lines:
                s = line.strip()
                if s.startswith("BITABLE_TOKEN"):
                    new_lines.append(f"BITABLE_TOKEN={bitable_id}\n")
                    updated_token = True
                elif s.startswith("TABLE_ID") and table_id:
                    new_lines.append(f"TABLE_ID={table_id}\n")
                    updated_table = True
                else:
                    new_lines.append(line)

            if not updated_token:
                new_lines.append(f"BITABLE_TOKEN={bitable_id}\n")
            if not updated_table and table_id:
                new_lines.append(f"TABLE_ID={table_id}\n")

            with open(ENV_STEP5, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            print(f"[同步] 已更新 step5 config.env: BITABLE_TOKEN={bitable_id}, TABLE_ID={table_id}")
            return True
        except Exception as e:
            print(f"[同步] 更新 config.env 失败: {e}")

    return False


# ──── GUI 主类 ────────────────────────────────────

class Step4to5GUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("人员面试评价 → 新签 自动化")
        self.root.geometry("860x700")
        self.root.minsize(700, 550)

        # 居中
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w, h = 860, 700
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        self._stop_flag = threading.Event()
        self._checkpoint_event = threading.Event()
        self._checkpoint_confirmed = False
        self._worker = None

        initial = load_initial_config()

        # ════ 输入区 ════
        input_frame = ttk.LabelFrame(self.root, text="配置", padding=10)
        input_frame.pack(fill=tk.X, padx=12, pady=(12, 4))

        # 第一行：BU + IMS 用户名 + 密码
        ttk.Label(input_frame, text="BU代码:").grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
        self.bu_var = tk.StringVar(value="185")
        self.bu_entry = ttk.Entry(input_frame, textvariable=self.bu_var, width=28)
        self.bu_entry.grid(row=0, column=1, sticky=tk.W, padx=4)
        ttk.Label(input_frame, text="多个用逗号分隔",
                  font=("Microsoft YaHei UI", 8), foreground="#888").grid(
            row=0, column=2, sticky=tk.W, padx=(0, 8))

        ttk.Label(input_frame, text="IMS 用户名:").grid(row=0, column=3, sticky=tk.W, padx=(8, 4))
        self.user_var = tk.StringVar(value=initial.get("IMS_USERNAME", ""))
        self.user_entry = ttk.Entry(input_frame, textvariable=self.user_var, width=22)
        self.user_entry.grid(row=0, column=4, sticky=tk.W, padx=4)

        ttk.Label(input_frame, text="IMS 密码:").grid(row=0, column=5, sticky=tk.W, padx=(12, 4))
        self.pwd_var = tk.StringVar(value=initial.get("IMS_PASSWORD", ""))
        self.pwd_entry = ttk.Entry(input_frame, textvariable=self.pwd_var, show="*", width=22)
        self.pwd_entry.grid(row=0, column=6, sticky=tk.W, padx=4)

        # ════ 按钮区 ════
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=12, pady=4)

        self.btn_start = ttk.Button(btn_frame, text="提取评价表+新签",
                                    command=self._start_pipeline)
        self.btn_start.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_stop = ttk.Button(btn_frame, text="停止", command=self._stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=6)

        # Step 5 单独执行按钮（跳过 step4，直接新签）
        self.btn_step5_only = ttk.Button(btn_frame, text="直接新签",
                                         command=lambda: self._start_pipeline(skip_step4=True))
        self.btn_step5_only.pack(side=tk.RIGHT, padx=6)

        # ════ 进度区 ════
        progress_frame = ttk.LabelFrame(self.root, text="进度", padding=8)
        progress_frame.pack(fill=tk.X, padx=12, pady=4)

        self.progress_steps = [
            ("step4", "Step 4: 提取人员面试评价建多维表"),
            ("checkpoint", "检查点: 人工检查多维表数据"),
            ("step5", "Step 5: 根据人员面试评价新签"),
        ]

        STATUS_COLORS = {
            "pending": "#999", "running": "#2196F3", "waiting": "#FF9800",
            "done": "#4CAF50", "failed": "#F44336", "skipped": "#999",
        }
        STATUS_ICONS = {
            "pending": "○", "running": "▶", "waiting": "⏸",
            "done": "●", "failed": "✕", "skipped": "○",
        }

        self._status_colors = STATUS_COLORS
        self._status_icons = STATUS_ICONS
        self.progress_labels = {}

        for key, name in self.progress_steps:
            lbl = tk.Label(progress_frame, text=f"  {STATUS_ICONS['pending']}  {name}",
                           font=("Microsoft YaHei UI", 10), fg=STATUS_COLORS["pending"],
                           anchor=tk.W, padx=4)
            lbl.pack(fill=tk.X, pady=1)
            self.progress_labels[key] = lbl

        # ════ 日志区 ════
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
        self.log_text.tag_configure("info", foreground="#56b6c2")

        self._log("就绪 — 请填写配置后点击「开始执行」\n", "phase")
        self._log("流程: Step4(提取面试评价→多维表) → 检查多维表 → Step5(自动新签)\n", "info")

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

    def _set_progress(self, key: str, status: str):
        name = dict(self.progress_steps)[key]
        icon = self._status_icons.get(status, "○")
        color = self._status_colors.get(status, "#999")
        self.progress_labels[key].configure(text=f"  {icon}  {name}", fg=color)

    def _reset_progress(self):
        for key, _ in self.progress_steps:
            self._set_progress(key, "pending")

    def _set_buttons_state(self, running: bool):
        state = tk.DISABLED if running else tk.NORMAL
        self.btn_start.configure(state=state)
        self.btn_step5_only.configure(state=state)
        self.btn_stop.configure(state=tk.NORMAL if running else tk.DISABLED)

    # ──── 启动流水线 ──────────────────────────

    def _start_pipeline(self, skip_step4: bool = False):
        username = self.user_var.get().strip()
        password = self.pwd_var.get().strip()
        if not username:
            messagebox.showwarning("缺少参数", "请输入 IMS 用户名")
            return
        if not password:
            messagebox.showwarning("缺少参数", "请输入 IMS 密码")
            return

        bu_raw = self.bu_var.get().strip()
        bu_values = parse_bu_values(bu_raw)
        self._bu_values = bu_values
        self._bu_arg = ",".join(bu_values)
        self._username = username
        self._password = password
        self._skip_step4 = skip_step4

        self._stop_flag.clear()
        self._checkpoint_event.clear()
        self._checkpoint_confirmed = False
        self._reset_progress()
        self.log_text.delete("1.0", tk.END)

        if skip_step4:
            self._set_progress("step4", "skipped")
            self._set_progress("checkpoint", "skipped")
            self._log("跳过 Step4 和检查点，直接执行 Step5\n", "warn")

        self._set_buttons_state(running=True)
        self._worker = threading.Thread(target=self._run_pipeline, daemon=True)
        self._worker.start()

    # ──── 流水线主逻辑 ──────────────────────────

    def _run_pipeline(self):
        try:
            if not self._skip_step4:
                # ── Step 4 ──
                ok = self._run_step4()
                if not ok:
                    if self._stop_flag.is_set():
                        self._log("用户终止流程", "warn")
                    return

                if self._stop_flag.is_set():
                    return

                # ── 同步配置 ──
                self._log_phase("同步多维表配置到 Step5")
                sync_bitable_config()

                if self._stop_flag.is_set():
                    return

                # ── 检查点 ──
                self._set_progress("checkpoint", "waiting")
                self._log_phase("检查点: 请在多维表中检查数据")
                self.root.after(0, self._show_checkpoint_dialog)
                self._checkpoint_event.wait()

                if self._stop_flag.is_set():
                    return

                if not self._checkpoint_confirmed:
                    self._log("用户在检查点终止流程", "warn")
                    return

                self._set_progress("checkpoint", "done")
                self._log("用户已确认多维表数据", "success")

            # ── Step 5 ──
            if self._stop_flag.is_set():
                return
            self._run_step5()

        except Exception as e:
            self._log(f"流水线异常: {e}", "error")
            import traceback
            self._log(traceback.format_exc(), "error")
        finally:
            self.root.after(0, lambda: self._set_buttons_state(running=False))
            self._log_phase("流水线结束")

    # ──── Step 4 执行 ──────────────────────────

    def _run_step4(self) -> bool:
        self._set_progress("step4", "running")
        self._log_phase("Step 4: 提取人员面试评价 → 飞书多维表")
        self._log(f"BU 列表: {self._bu_arg}  ({len(self._bu_values)} 个)", "info")

        # 设置环境变量供 Config 类读取（逗号分隔的BU代码，web_automation 会逐个循环）
        os.environ["IMS_USERNAME"] = self._username
        os.environ["IMS_PASSWORD"] = self._password
        os.environ["QUERY_BU"] = self._bu_arg

        display_args = ["main.py", "--auto"]
        self._log(f"执行: python {' '.join(display_args)}  (cwd={DIR_STEP4})")

        ok = self._exec_module(
            cwd=DIR_STEP4,
            args=["main.py", "--auto"],
            phase_label="step4",
        )

        return ok

    # ──── Step 5 执行 ──────────────────────────

    def _run_step5(self) -> bool:
        self._set_progress("step5", "running")
        self._log_phase("Step 5: 根据人员面试评价新签")

        # 写入 step5 config.env
        self._write_step5_config()

        self._log(f"BU 列表: {', '.join(self._bu_values)}  (供参考)", "info")

        display_args = ["main.py", "-y"]
        self._log(f"执行: python {' '.join(display_args)}  (cwd={DIR_STEP5})")

        ok = self._exec_module(
            cwd=DIR_STEP5,
            args=["main.py", "-y"],
            phase_label="step5",
        )

        status = "done" if ok else "failed"
        self._set_progress("step5", status)
        self._log(f"Step 5 {'成功' if ok else '失败'}", "success" if ok else "error")
        return ok

    # ──── 写入 Step5 配置 ──────────────────────

    def _write_step5_config(self):
        """将 GUI 中的凭证写入 step5 的 config.env"""
        try:
            # 读取现有配置
            existing = {}
            if os.path.exists(ENV_STEP5):
                with open(ENV_STEP5, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            k, _, v = line.partition("=")
                            existing[k.strip()] = v.strip()

            existing["IMS_USERNAME"] = self._username
            existing["IMS_PASSWORD"] = self._password

            with open(ENV_STEP5, "w", encoding="utf-8") as f:
                for k, v in existing.items():
                    f.write(f"{k}={v}\n")
            self._log(f"[配置] 已写入 step5 config.env (IMS_USERNAME=***)", "info")
        except Exception as e:
            self._log(f"[配置] 写入 step5 config.env 失败: {e}", "error")

    # ──── 模块执行（同进程 exec，无子进程无黑窗）───

    def _exec_module(self, cwd: str, args: list[str], phase_label: str) -> bool:
        """在当前进程中执行 main.py，捕获输出到 GUI 日志。"""
        old_argv = sys.argv
        old_cwd = os.getcwd()
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        pre_modules = set(sys.modules.keys())

        def _on_line(line: str):
            tag = ""
            if "ERROR" in line or "异常" in line or "失败" in line:
                tag = "error"
            elif "WARN" in line or "警告" in line:
                tag = "warn"
            elif "成功" in line or "完成" in line or "SUCCESS" in line:
                tag = "success"
            self._log(line, tag)

        capture = _CaptureIO(_on_line)
        ok = False

        try:
            os.chdir(cwd)
            sys.path.insert(0, cwd)
            sys.argv = args
            sys.stdout = capture
            sys.stderr = capture

            main_path = os.path.join(cwd, "main.py")
            with open(main_path, "r", encoding="utf-8") as f:
                source = f.read()
            code = compile(source, main_path, "exec")
            exec(code, {"__name__": "__main__", "__file__": main_path})
            ok = True
        except SystemExit as e:
            ok = e.code == 0 or e.code is None
            if not ok:
                self._log(f"Step 异常退出 (code={e.code})", "error")
        except Exception as e:
            import traceback
            self._log(traceback.format_exc(), "error")
            self._log(f"Step 异常: {e}", "error")
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
        self._set_progress(phase_label, status)
        self._log(f"{'Step' if 'step' in phase_label else 'Phase'} {'成功' if ok else '失败'}\n",
                  "success" if ok else "error")
        return ok

    # ──── 检查点弹窗 ──────────────────────────

    def _show_checkpoint_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("检查多维表 — 人工确认")
        dialog.geometry("560x400")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.update_idletasks()
        px = self.root.winfo_rootx() + (self.root.winfo_width() - 560) // 2
        py = self.root.winfo_rooty() + (self.root.winfo_height() - 400) // 2
        dialog.geometry(f"+{px}+{py}")

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="📋 Step 4 已完成 — 请检查多维表",
                  font=("Microsoft YaHei UI", 12, "bold")).pack(anchor=tk.W, pady=(0, 12))

        ttk.Label(frame, text="请在飞书多维表中完成以下检查：",
                  font=("Microsoft YaHei UI", 10)).pack(anchor=tk.W, pady=(0, 8))

        check_items = [
            "1. 确认数据已正确导入（姓名、身份证号、需求编号等）",
            "2. 检查供应商列是否匹配正确",
            "3. 如需补充字段（如 校正上岗时间、外包商联系人），请手动填写",
            "4. 确认\"是否签署\"列状态正确（新导入的记录应为\"否\"）",
        ]
        for item in check_items:
            ttk.Label(frame, text=item, font=("Microsoft YaHei UI", 10)).pack(
                anchor=tk.W, pady=2)

        url = get_bitable_url()
        if url:
            ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(12, 8))

            link_bar = ttk.Frame(frame)
            link_bar.pack(fill=tk.X, pady=(0, 4))
            ttk.Label(link_bar, text="多维表链接:",
                      font=("Microsoft YaHei UI", 10, "bold")).pack(side=tk.LEFT)

            def _open_url(event):
                webbrowser.open(url)

            link_label = tk.Label(link_bar, text=url, fg="#2196F3", cursor="hand2",
                                  font=("Microsoft YaHei UI", 9, "underline"))
            link_label.pack(side=tk.LEFT, padx=(4, 0))
            link_label.bind("<Button-1>", _open_url)

            def _copy_url():
                self.root.clipboard_clear()
                self.root.clipboard_append(url)
                copy_btn.configure(text="已复制!")
                self.root.after(2000, lambda: copy_btn.configure(text="复制"))

            copy_btn = ttk.Button(link_bar, text="复制", width=6, command=_copy_url)
            copy_btn.pack(side=tk.RIGHT)

        # 底部按钮
        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(16, 12))

        btn_bar = ttk.Frame(frame)
        btn_bar.pack(fill=tk.X)

        def _confirm():
            self._checkpoint_confirmed = True
            dialog.destroy()
            self._checkpoint_event.set()

        def _abort():
            self._checkpoint_confirmed = False
            self._stop_flag.set()
            dialog.destroy()
            self._checkpoint_event.set()

        ttk.Button(btn_bar, text="✓ 确认无误，继续执行 Step5",
                   command=_confirm).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_bar, text="✕ 终止流程",
                   command=_abort).pack(side=tk.RIGHT, padx=4)

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


# ──── 入口 ────────────────────────────────────

if __name__ == "__main__":
    app = Step4to5GUI()
    app.run()
