"""
考勤合规检查工作平台
GUI 主程序 - 基于 tkinter

功能:
  标签页1 - 下载外包数据: 自动登录IMS系统，下载工时详细查询、在岗人员清单、计提报表
  标签页2 - 检查合规:    人工确认文件完整后，执行合规检查并显示结果

依赖安装: pip install playwright pandas openpyxl && playwright install chromium
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import os
import re
import sys
import json
import glob
from pathlib import Path
from datetime import datetime

# 确保当前目录在 sys.path 中，以便导入同目录下的模块
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from download_module import run_full_download
from compliance_runner import run_full_check

SETTINGS_FILE = os.path.join(SCRIPT_DIR, ".gui_settings.json")


def load_settings():
    """加载用户设置"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_settings(data: dict):
    """保存用户设置（不保存密码）"""
    safe = {k: v for k, v in data.items() if "password" not in k.lower()}
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(safe, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ===== 主应用类 =====
class ComplianceApp:
    def __init__(self, root):
        self.root = root
        self.root.title("考勤合规检查工作平台")
        self.root.geometry("1280x880")
        self.root.minsize(1050, 700)

        # 下载器引用（用于优雅退出+停止）
        self._downloader = None
        self._download_thread = None
        self._check_thread = None
        self._stop_event = threading.Event()

        # 加载持久化设置
        self._saved = load_settings()

        # 优雅退出
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        # 尝试设置图标
        try:
            self.root.iconbitmap(default="")
        except Exception:
            pass

        self._setup_styles()
        self._create_widgets()
        self._load_saved_values()

    # ----- 样式设置 -----
    def _setup_styles(self):
        style = ttk.Style()
        available_themes = style.theme_names()
        if 'vista' in available_themes:
            style.theme_use('vista')
        elif 'clam' in available_themes:
            style.theme_use('clam')

        style.configure("TNotebook.Tab", padding=[16, 6], font=("微软雅黑", 14))
        style.configure("TLabel", font=("微软雅黑", 13))
        style.configure("TButton", font=("微软雅黑", 13))
        style.configure("TEntry", font=("微软雅黑", 13), padding=[6, 4, 6, 4])
        style.configure("Header.TLabel", font=("微软雅黑", 16, "bold"))
        style.configure("Status.TLabel", font=("微软雅黑", 11), foreground="#555555")

    # ----- 加载保存的设置 -----
    def _load_saved_values(self):
        if self._saved.get("dl_account"):
            self.dl_account.insert(0, self._saved["dl_account"])
        if self._saved.get("dl_suppliers"):
            self.dl_suppliers.insert(0, self._saved["dl_suppliers"])
        if self._saved.get("dl_month"):
            self.dl_month.insert(0, self._saved["dl_month"])
        if self._saved.get("dl_folder"):
            self.dl_folder.insert(0, self._saved["dl_folder"])
            self.ck_folder.insert(0, self._saved["dl_folder"])
        if self._saved.get("ck_suppliers"):
            self.ck_suppliers.insert(0, self._saved["ck_suppliers"])
        if self._saved.get("ck_month"):
            self.ck_month.insert(0, self._saved["ck_month"])
        if self._saved.get("ck_exclude_sbu"):
            self.ck_exclude_sbu.delete(0, tk.END)
            self.ck_exclude_sbu.insert(0, self._saved["ck_exclude_sbu"])

    def _save_current_values(self):
        """收集当前值并保存"""
        data = {
            "dl_account": self.dl_account.get().strip(),
            "dl_suppliers": self.dl_suppliers.get().strip(),
            "dl_month": self.dl_month.get().strip(),
            "dl_folder": self.dl_folder.get().strip(),
            "ck_suppliers": self.ck_suppliers.get().strip(),
            "ck_month": self.ck_month.get().strip(),
            "ck_exclude_sbu": self.ck_exclude_sbu.get().strip(),
        }
        save_settings(data)

    # ----- 优雅退出 -----
    def _on_closing(self):
        """窗口关闭时的清理"""
        is_running = False
        if self._download_thread and self._download_thread.is_alive():
            is_running = True
        if self._check_thread and self._check_thread.is_alive():
            is_running = True

        if is_running:
            if not messagebox.askyesno("确认退出",
                                       "有任务正在运行中，确定要退出吗？\n\n"
                                       "退出后浏览器进程可能需要手动关闭。"):
                return

        # 尝试清理下载器
        if self._downloader:
            try:
                self._downloader.quit()
            except Exception:
                pass

        # 保存设置
        self._save_current_values()

        self.root.destroy()

    # ----- 创建主界面 -----
    def _create_widgets(self):
        # 顶部标题
        title_frame = ttk.Frame(self.root, padding=(15, 10, 15, 5))
        title_frame.pack(fill=tk.X)
        ttk.Label(title_frame, text="考勤合规检查工作平台",
                  style="Header.TLabel").pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(title_frame, textvariable=self.status_var,
                  style="Status.TLabel").pack(side=tk.RIGHT)

        # 标签页
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(5, 10))

        self.tab_download = ttk.Frame(self.notebook, padding=10)
        self.tab_compliance = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_download, text="  下载外包数据  ")
        self.notebook.add(self.tab_compliance, text="  检查合规  ")

        self._create_download_tab()
        self._create_compliance_tab()

    # ==========================================
    #  标签页1: 下载外包数据
    # ==========================================
    def _create_download_tab(self):
        # --- 参数输入区域 ---
        param_frame = ttk.LabelFrame(self.tab_download, text="参数设置", padding=12)
        param_frame.pack(fill=tk.X, pady=(0, 8))

        # 第一行
        row1 = ttk.Frame(param_frame)
        row1.pack(fill=tk.X, pady=3)

        ttk.Label(row1, text="登录账号:", width=10).pack(side=tk.LEFT)
        self.dl_account = ttk.Entry(row1, width=28)
        self.dl_account.pack(side=tk.LEFT, padx=(0, 20))

        ttk.Label(row1, text="登录密码:", width=10).pack(side=tk.LEFT)
        self.dl_password = ttk.Entry(row1, width=28, show="*")
        self.dl_password.pack(side=tk.LEFT, padx=(0, 20))

        ttk.Label(row1, text="月份:", width=6).pack(side=tk.LEFT)
        self.dl_month = ttk.Entry(row1, width=14)
        self.dl_month.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(row1, text="(格式:202602)", foreground="#888888").pack(side=tk.LEFT)

        # 第二行
        row2 = ttk.Frame(param_frame)
        row2.pack(fill=tk.X, pady=3)

        ttk.Label(row2, text="供应商名称:", width=10).pack(side=tk.LEFT)
        self.dl_suppliers = ttk.Entry(row2, width=70)
        self.dl_suppliers.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(row2, text="(多个用逗号分隔，不区分中英文)", foreground="#888888").pack(side=tk.LEFT)

        # 第三行
        row3 = ttk.Frame(param_frame)
        row3.pack(fill=tk.X, pady=3)

        ttk.Label(row3, text="工作文件夹:", width=10).pack(side=tk.LEFT)
        self.dl_folder = ttk.Entry(row3, width=70)
        self.dl_folder.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(row3, text="浏览...", width=8,
                   command=self._browse_dl_folder).pack(side=tk.LEFT)

        # --- 下载项目说明 ---
        items_frame = ttk.LabelFrame(self.tab_download, text="下载项目", padding=8)
        items_frame.pack(fill=tk.X, pady=(0, 8))

        dl_items = [
            ("1. 工时详细查询", "每个供应商导出3批（1~10日、11~20日、21~31日），命名: 供应商_工时详细查询X-3.xlsx"),
            ("2. 在岗人员清单", "导出当月在岗人员，命名: 在岗人员清单.xlsx"),
            ("3. 计提报表", "导出当月计提报表，命名: 计提报表.xlsx"),
        ]
        for title, desc in dl_items:
            item_row = ttk.Frame(items_frame)
            item_row.pack(fill=tk.X, pady=1)
            ttk.Label(item_row, text=title, width=20,
                      font=("微软雅黑", 13, "bold")).pack(side=tk.LEFT)
            ttk.Label(item_row, text=desc, foreground="#666666").pack(side=tk.LEFT)

        # --- 操作按钮 ---
        btn_frame = ttk.Frame(self.tab_download)
        btn_frame.pack(fill=tk.X, pady=(0, 5))
        self.btn_start_download = ttk.Button(
            btn_frame, text="  开始下载  ",
            command=self._on_start_download)
        self.btn_start_download.pack(side=tk.LEFT)

        self.btn_stop_download = ttk.Button(
            btn_frame, text="  停止  ",
            command=self._on_stop_download)

        # 下载进度
        self.dl_progress = ttk.Progressbar(
            btn_frame, mode='indeterminate', length=200)
        self.dl_progress.pack(side=tk.LEFT, padx=15)

        # --- 日志区域 ---
        log_frame = ttk.LabelFrame(self.tab_download, text="工作日志", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.dl_log = scrolledtext.ScrolledText(
            log_frame, height=12, font=("Consolas", 11), wrap=tk.WORD,
            state=tk.DISABLED)
        self.dl_log.pack(fill=tk.BOTH, expand=True)

        # 日志右键菜单
        self.dl_log_menu = tk.Menu(self.dl_log, tearoff=0)
        self.dl_log_menu.add_command(label="复制", command=self._copy_dl_log)
        self.dl_log_menu.add_command(label="全选", command=self._select_all_dl_log)
        self.dl_log_menu.add_separator()
        self.dl_log_menu.add_command(label="清空日志", command=self._clear_dl_log)
        self.dl_log.bind("<Button-3>", self._show_dl_log_menu)

    # ==========================================
    #  标签页2: 检查合规
    # ==========================================
    def _create_compliance_tab(self):
        # --- 文件检查区域 ---
        file_frame = ttk.LabelFrame(
            self.tab_compliance,
            text="第一步：确认工作文件夹中以下文件已完备（可手动补充场地签、差旅等下载项无法获取的文件）",
            padding=10)
        file_frame.pack(fill=tk.X, pady=(0, 8))

        # 文件夹路径
        folder_row = ttk.Frame(file_frame)
        folder_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(folder_row, text="工作文件夹:", width=10).pack(side=tk.LEFT)
        self.ck_folder = ttk.Entry(folder_row, width=70)
        self.ck_folder.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(folder_row, text="浏览...", width=8,
                   command=self._browse_ck_folder).pack(side=tk.LEFT)
        self.btn_detect = ttk.Button(folder_row, text="检测文件", width=10,
                                     command=self._on_detect_files)
        self.btn_detect.pack(side=tk.LEFT, padx=(10, 0))

        # 文件清单与检测结果
        files_grid = ttk.Frame(file_frame)
        files_grid.pack(fill=tk.X)

        self.required_files = [
            ("场地签", "场地签"),
            ("差旅", "差旅"),
            ("在岗人员清单", "在岗人员清单"),
            ("工时详细查询", "工时详细查询"),
            ("计提报表", "计提报表"),
        ]
        self.file_status_vars = {}
        self.file_status_labels = {}
        for i, (label, keyword) in enumerate(self.required_files):
            ttk.Label(files_grid, text=f"  {label}", width=18).grid(
                row=i, column=0, sticky=tk.W, pady=1)
            var = tk.StringVar(value="-- 未检测 --")
            lbl = ttk.Label(files_grid, textvariable=var, foreground="#888888")
            lbl.grid(row=i, column=1, sticky=tk.W, padx=10, pady=1)
            self.file_status_vars[keyword] = var
            self.file_status_labels[keyword] = lbl

        # --- 检查参数 ---
        param_frame = ttk.LabelFrame(
            self.tab_compliance,
            text="第二步：设置检查参数",
            padding=10)
        param_frame.pack(fill=tk.X, pady=(0, 8))

        prow = ttk.Frame(param_frame)
        prow.pack(fill=tk.X, pady=3)
        ttk.Label(prow, text="供应商名称:", width=10).pack(side=tk.LEFT)
        self.ck_suppliers = ttk.Entry(prow, width=60)
        self.ck_suppliers.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(prow, text="月份:", width=6).pack(side=tk.LEFT)
        self.ck_month = ttk.Entry(prow, width=14)
        self.ck_month.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(prow, text="排除SBU:").pack(side=tk.LEFT)
        self.ck_exclude_sbu = ttk.Entry(prow, width=14)
        self.ck_exclude_sbu.pack(side=tk.LEFT, padx=(5, 0))
        self.ck_exclude_sbu.insert(0, "AIS")

        # --- 操作按钮 ---
        btn_frame = ttk.Frame(self.tab_compliance)
        btn_frame.pack(fill=tk.X, pady=(0, 5))
        self.btn_run_check = ttk.Button(
            btn_frame, text="  确认文件完备，开始检查  ",
            command=self._on_run_check)
        self.btn_run_check.pack(side=tk.LEFT)

        self.btn_stop_check = ttk.Button(
            btn_frame, text="  停止  ",
            command=self._on_stop_check)

        self.ck_progress = ttk.Progressbar(
            btn_frame, mode='indeterminate', length=200)
        self.ck_progress.pack(side=tk.LEFT, padx=15)

        # 文件检测状态提示
        self.ck_file_warning = tk.StringVar(value="")
        ttk.Label(btn_frame, textvariable=self.ck_file_warning,
                  foreground="#DC143C", font=("微软雅黑", 11)).pack(side=tk.LEFT, padx=(15, 0))

        # --- 检查日志 ---
        log_frame = ttk.LabelFrame(
            self.tab_compliance, text="检查日志", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        self.ck_log = scrolledtext.ScrolledText(
            log_frame, height=8, font=("Consolas", 11), wrap=tk.WORD,
            state=tk.DISABLED)
        self.ck_log.pack(fill=tk.BOTH, expand=True)

        # --- 结果区域 ---
        result_frame = ttk.LabelFrame(
            self.tab_compliance, text="检查简报", padding=5)
        result_frame.pack(fill=tk.BOTH, expand=True)

        self.ck_result = scrolledtext.ScrolledText(
            result_frame, height=8, font=("Consolas", 12), wrap=tk.WORD,
            state=tk.DISABLED)
        self.ck_result.pack(fill=tk.BOTH, expand=True)

        # 结果文本标签
        self.ck_result.tag_configure("header", font=("Consolas", 14, "bold"))
        self.ck_result.tag_configure("good", foreground="#228B22")
        self.ck_result.tag_configure("bad", foreground="#DC143C")
        self.ck_result.tag_configure("warn", foreground="#FF8C00")
        self.ck_result.tag_configure("info", foreground="#4169E1")

    # ==========================================
    #  标签页1: 下载功能
    # ==========================================
    def _browse_dl_folder(self):
        folder = filedialog.askdirectory(title="选择工作文件夹")
        if folder:
            self.dl_folder.delete(0, tk.END)
            self.dl_folder.insert(0, folder)
            # 同步到合规检查标签页
            self.ck_folder.delete(0, tk.END)
            self.ck_folder.insert(0, folder)
            self._save_current_values()

    def _set_download_params_state(self, enabled: bool):
        """控制下载参数输入状态"""
        state = tk.NORMAL if enabled else tk.DISABLED
        self.dl_account.config(state=state)
        self.dl_password.config(state=state)
        self.dl_month.config(state=state)
        self.dl_suppliers.config(state=state)
        self.dl_folder.config(state=state)

    def _on_start_download(self):
        """开始下载"""
        account = self.dl_account.get().strip()
        password = self.dl_password.get().strip()
        suppliers_text = self.dl_suppliers.get().strip()
        month = self.dl_month.get().strip()
        folder = self.dl_folder.get().strip()

        # 保存设置
        self._save_current_values()

        # 验证
        errors = []
        if not account:
            errors.append("请输入登录账号")
        if not password:
            errors.append("请输入登录密码")
        if not suppliers_text:
            errors.append("请输入供应商名称")
        if not re.match(r'^\d{6}$', month):
            errors.append("月份格式应为6位数字，如 202602")
        if not folder:
            errors.append("请选择工作文件夹路径")
        elif not os.path.isdir(folder):
            errors.append("工作文件夹路径不存在")
        if errors:
            messagebox.showerror("参数错误", "\n".join(errors))
            return

        # 解析供应商列表
        supplier_list = []
        _seen = set()
        for s in re.split(r'[,，]', suppliers_text):
            s = s.strip()
            if s and s.lower() not in _seen:
                supplier_list.append(s)
                _seen.add(s.lower())
        if not supplier_list:
            messagebox.showerror("参数错误", "请至少输入一个供应商名称")
            return

        # 切换按钮：显示停止，隐藏开始
        self.btn_start_download.pack_forget()
        self.btn_stop_download.pack(side=tk.LEFT, before=self.dl_progress)
        self._set_download_params_state(False)
        self.dl_progress.start(10)
        self._clear_dl_log()
        self.status_var.set("正在下载数据...")
        # 重置停止标志
        self._stop_event.clear()

        # 确认Playwright浏览器已安装
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            messagebox.showerror(
                "缺少依赖",
                "未检测到 Playwright，请先安装:\n\n"
                "  pip install playwright\n"
                "  playwright install chromium\n\n"
                "安装完成后重新启动程序。")
            self._download_finished()
            return

        def download_thread():
            try:
                run_full_download(
                    username=account,
                    password=password,
                    supplier_list=supplier_list,
                    month_str=month,
                    download_dir=folder,
                    log_func=self._dl_log_callback,
                    stop_event=self._stop_event,
                )
                self.root.after(0, lambda: self.status_var.set("下载完成"))
                self.root.after(0, lambda: messagebox.showinfo("完成", "所有数据下载任务已完成！"))
            except Exception as e:
                self._dl_log_callback(f"\n[错误] 下载过程出现异常: {e}")
                import traceback
                self._dl_log_callback(traceback.format_exc())
                self.root.after(0, lambda err=str(e): self.status_var.set(f"下载异常: {err[:40]}"))
                self.root.after(0, lambda err=str(e): messagebox.showerror("下载错误",
                    f"{err}\n\n请查看日志获取详细信息。\n截图文件保存在工作文件夹中。"))
            finally:
                self.root.after(0, self._download_finished)

        self._download_thread = threading.Thread(target=download_thread, daemon=True)
        self._download_thread.start()

    def _download_finished(self):
        self.btn_stop_download.pack_forget()
        self.btn_start_download.pack(side=tk.LEFT, before=self.dl_progress)
        self._set_download_params_state(True)
        self.dl_progress.stop()

    def _on_stop_download(self):
        """停止下载"""
        self._stop_event.set()
        self._dl_log_callback("[用户操作] 正在停止下载...")
        self.btn_stop_download.config(state=tk.DISABLED)

    def _dl_log_callback(self, msg):
        """线程安全的日志写入"""
        def _write():
            self.dl_log.config(state=tk.NORMAL)
            self.dl_log.insert(tk.END, msg + "\n")
            self.dl_log.see(tk.END)
            self.dl_log.config(state=tk.DISABLED)
        self.root.after(0, _write)

    def _clear_dl_log(self):
        self.dl_log.config(state=tk.NORMAL)
        self.dl_log.delete("1.0", tk.END)
        self.dl_log.config(state=tk.DISABLED)

    def _copy_dl_log(self):
        try:
            selected = self.dl_log.get(tk.SEL_FIRST, tk.SEL_LAST)
            self.root.clipboard_clear()
            self.root.clipboard_append(selected)
        except tk.TclError:
            pass

    def _select_all_dl_log(self):
        self.dl_log.config(state=tk.NORMAL)
        self.dl_log.tag_add(tk.SEL, "1.0", tk.END)
        self.dl_log.config(state=tk.DISABLED)

    def _show_dl_log_menu(self, event):
        try:
            self.dl_log_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.dl_log_menu.grab_release()

    # ==========================================
    #  标签页2: 合规检查功能
    # ==========================================
    def _browse_ck_folder(self):
        folder = filedialog.askdirectory(title="选择工作文件夹")
        if folder:
            self.ck_folder.delete(0, tk.END)
            self.ck_folder.insert(0, folder)
            # 同步到下载标签页
            self.dl_folder.delete(0, tk.END)
            self.dl_folder.insert(0, folder)
            self._save_current_values()

    def _on_detect_files(self):
        """检测工作文件夹中的文件"""
        folder = self.ck_folder.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("提示", "请先选择有效的工作文件夹")
            return

        all_files = glob.glob(os.path.join(folder, "*.xlsx")) + \
                    glob.glob(os.path.join(folder, "*.xls"))
        all_files = [f for f in all_files if not os.path.basename(f).startswith('~')]
        basenames = [os.path.basename(f) for f in all_files]

        missing_count = 0
        for keyword, var in self.file_status_vars.items():
            matched = [bn for bn in basenames if keyword in bn]
            if matched:
                var.set(f"已找到: {', '.join(matched)}")
                self.file_status_labels[keyword].config(foreground="#228B22")
            else:
                var.set("未找到!")
                self.file_status_labels[keyword].config(foreground="#DC143C")
                missing_count += 1

        # 更新文件状态提示
        if missing_count == 0:
            self.ck_file_warning.set("✓ 所有文件已就绪，可以开始检查")
            self.btn_run_check.config(state=tk.NORMAL)
        else:
            self.ck_file_warning.set(f"⚠ 缺少 {missing_count} 个文件类型，请补充后再检查")
            # 仍然允许检查（用户可能知道某些文件是可选的），但给提示

        # 保存设置
        self._save_current_values()

    def _set_check_params_state(self, enabled: bool):
        """控制检查参数输入状态"""
        state = tk.NORMAL if enabled else tk.DISABLED
        self.ck_folder.config(state=state)
        self.ck_suppliers.config(state=state)
        self.ck_month.config(state=state)
        self.ck_exclude_sbu.config(state=state)
        self.btn_detect.config(state=state)

    def _on_run_check(self):
        """开始合规检查"""
        folder = self.ck_folder.get().strip()
        suppliers_text = self.ck_suppliers.get().strip()
        month = self.ck_month.get().strip()
        exclude_sbu = self.ck_exclude_sbu.get().strip()

        # 保存设置
        self._save_current_values()

        # 验证
        errors = []
        if not folder or not os.path.isdir(folder):
            errors.append("请选择有效的工作文件夹")
        if not suppliers_text:
            errors.append("请输入供应商名称")
        if not re.match(r'^\d{6}$', month):
            errors.append("月份格式应为6位数字，如 202602")
        if errors:
            messagebox.showerror("参数错误", "\n".join(errors))
            return

        supplier_list = []
        _seen = set()
        for s in re.split(r'[,，]', suppliers_text):
            s = s.strip()
            if s and s.lower() not in _seen:
                supplier_list.append(s)
                _seen.add(s.lower())
        if not supplier_list:
            messagebox.showerror("参数错误", "请至少输入一个供应商名称")
            return

        # 自动检测文件，如有缺失给出警告但允许继续
        self._on_detect_files()
        missing = sum(1 for v in self.file_status_vars.values()
                      if "未找到" in v.get())
        if missing > 0:
            if not messagebox.askyesno(
                "文件缺失",
                f"检测到 {missing} 个文件类型未找到。\n\n"
                "缺少某些文件可能导致检查结果不完整。\n"
                "是否仍然继续检查？"):
                return

        # 切换按钮：显示停止，隐藏开始
        self.btn_run_check.pack_forget()
        self.btn_stop_check.pack(side=tk.LEFT, before=self.ck_progress)
        self._set_check_params_state(False)
        self.ck_progress.start(10)
        self._clear_ck_log()
        self._clear_ck_result()
        self.status_var.set("正在执行合规检查...")
        self._stop_event.clear()

        def check_thread():
            try:
                results = run_full_check(
                    month_str=month,
                    supplier_list=supplier_list,
                    base_dir=folder,
                    output_dir=folder,
                    exclude_sbu=exclude_sbu if exclude_sbu else "AIS",
                    log_func=self._ck_log_callback,
                    stop_event=self._stop_event,
                )
                self.root.after(0, lambda r=results: self._display_results(r))
                self.root.after(0, lambda: self.status_var.set("合规检查完成"))
            except Exception as e:
                self._ck_log_callback(f"\n[错误] 检查过程出现异常: {e}")
                import traceback
                self._ck_log_callback(traceback.format_exc())
                self.root.after(0, lambda err=str(e): self.status_var.set(f"检查异常: {err[:40]}"))
                self.root.after(0, lambda err=str(e): messagebox.showerror("检查错误", err))
            finally:
                self.root.after(0, self._check_finished)

        self._check_thread = threading.Thread(target=check_thread, daemon=True)
        self._check_thread.start()

    def _check_finished(self):
        self.btn_stop_check.pack_forget()
        self.btn_run_check.pack(side=tk.LEFT, before=self.ck_progress)
        self._set_check_params_state(True)
        self.ck_progress.stop()

    def _on_stop_check(self):
        """停止合规检查"""
        self._stop_event.set()
        self._ck_log_callback("[用户操作] 正在停止检查...")
        self.btn_stop_check.config(state=tk.DISABLED)

    def _ck_log_callback(self, msg):
        def _write():
            self.ck_log.config(state=tk.NORMAL)
            self.ck_log.insert(tk.END, msg + "\n")
            self.ck_log.see(tk.END)
            self.ck_log.config(state=tk.DISABLED)
        self.root.after(0, _write)

    def _clear_ck_log(self):
        self.ck_log.config(state=tk.NORMAL)
        self.ck_log.delete("1.0", tk.END)
        self.ck_log.config(state=tk.DISABLED)

    def _clear_ck_result(self):
        self.ck_result.config(state=tk.NORMAL)
        self.ck_result.delete("1.0", tk.END)
        self.ck_result.config(state=tk.DISABLED)

    def _display_results(self, results):
        """在结果区域显示各供应商的检查简报"""
        self.ck_result.config(state=tk.NORMAL)
        self.ck_result.delete("1.0", tk.END)

        self.ck_result.insert(tk.END, "=" * 60 + "\n")
        self.ck_result.insert(tk.END, "  合规检查简报\n", "header")
        self.ck_result.insert(tk.END, "=" * 60 + "\n\n")

        total_nc = 0
        for supplier, (nc, stats) in results.items():
            nc_count = len(nc)
            total_nc += nc_count

            # 供应商标题
            self.ck_result.insert(tk.END, f"  【{supplier}】\n", "header")

            if nc_count == 0:
                self.ck_result.insert(tk.END, "    所有人员均合规\n", "good")
            else:
                self.ck_result.insert(tk.END, f"    不合规: {nc_count}人\n", "bad")
                # 分类统计
                if stats:
                    for k, v in stats.items():
                        if v > 0:
                            tag = "warn" if v > 3 else "info"
                            self.ck_result.insert(tk.END, f"      {k}: {v}人\n", tag)

            # 不合规人员明细（前10个）
            if nc:
                self.ck_result.insert(tk.END, "    不合规人员:\n")
                for item in nc[:10]:
                    name = item.get('姓名', '')
                    sbu = item.get('SBU', '')
                    reason = item.get('不合规原因', '')
                    self.ck_result.insert(
                        tk.END, f"      {name}({sbu}): {reason}\n")
                if len(nc) > 10:
                    self.ck_result.insert(
                        tk.END, f"      ... 还有{len(nc) - 10}人，详见Excel文件\n",
                        "warn")

            self.ck_result.insert(tk.END, "\n")

        # 总计
        self.ck_result.insert(tk.END, "-" * 60 + "\n")
        if total_nc == 0:
            self.ck_result.insert(
                tk.END, f"  总计: 所有供应商所有人员均合规\n", "good")
        else:
            self.ck_result.insert(
                tk.END, f"  总计: {total_nc}人不合规\n", "bad")
        self.ck_result.insert(
            tk.END, f"  详细检查结果已保存到工作文件夹中的Excel文件\n", "info")
        self.ck_result.insert(tk.END, "=" * 60 + "\n")

        self.ck_result.config(state=tk.DISABLED)


# ===== 入口 =====
def main():
    root = tk.Tk()
    # Windows DPI 适配
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = ComplianceApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
