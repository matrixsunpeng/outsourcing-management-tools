#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
预算管控仪表盘 — 一键更新脚本（交互式）
用法：双击 run_budget_update.bat 或直接运行本脚本

流程：
  1. 询问是否下载计提结算（可选）
  2. 询问是否下载外包合同（可选）
  3. 合并下载数据到目标Excel（自动处理所有下载文件）
  4. 生成仪表盘HTML
"""

import os
import sys
import subprocess
import threading
from pathlib import Path

# ===== 路径配置 =====
# Python 解释器（自动检测当前运行的 Python）
PYTHON = sys.executable

# 仪表盘生成脚本（本模块内）
DASHBOARD_DIR = str(Path(__file__).parent)
DASHBOARD_SCRIPT = os.path.join(DASHBOARD_DIR, "generate_dashboard.py")
DASHBOARD_OUTPUT = os.path.join(DASHBOARD_DIR, "dashboard.html")

# 本模块内的下载脚本（settlement / contract 子目录）
SETTLEMENT_DIR = os.path.join(DASHBOARD_DIR, "settlement")
CONTRACT_DIR = os.path.join(DASHBOARD_DIR, "contract")
SETTLEMENT_SCRIPT = os.path.join(SETTLEMENT_DIR, "settlement_downloader.py")
CONTRACT_SCRIPT = os.path.join(CONTRACT_DIR, "contract_downloader.py")

# 数据合并脚本（本模块内）
MERGE_SCRIPT = os.path.join(DASHBOARD_DIR, "merge_data.py")
USERNAME = ''
PASSWORD = ''


def input_choice(prompt: str, options: list) -> str:
    """让用户从选项中选择"""
    print(prompt)
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    while True:
        choice = input("请选择 (输入序号): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1]
        print(f"  无效输入，请输入 1-{len(options)}")


def input_nonempty(prompt: str, default: str = '') -> str:
    """输入，支持默认值"""
    hint = f" [{default}]" if default else ""
    val = input(f"{prompt}{hint}: ").strip()
    return val if val else default


def clear_downloads(download_dir: str, label: str):
    """下载前清空downloads目录，确保只有本次下载的文件"""
    downloads_path = os.path.join(download_dir, 'downloads')
    if not os.path.exists(downloads_path):
        os.makedirs(downloads_path, exist_ok=True)
        return
    files = [f for f in os.listdir(downloads_path) if f.endswith('.xlsx')]
    if not files:
        return
    print(f"[INFO] 清空 {label} 旧下载文件 ({len(files)} 个)...")
    for f in files:
        try:
            os.remove(os.path.join(downloads_path, f))
        except PermissionError:
            print(f"[WARNING] 无法删除 {f}（文件被占用），跳过")
    print(f"[INFO] downloads 目录已清空，本次下载的文件将单独存放")


def run_download(script_path: str, script_dir: str, label: str, time_format: str):
    """
    交互式下载：询问BU和时间范围，然后执行下载脚本。
    下载前清空downloads目录，确保合并时只处理本次文件。
    time_format: 'month' 或 'date'
    返回 (bool, start_time, end_time)
    """
    print(f"\n{'='*60}")
    print(f"  {label} 下载参数设置")
    print(f"{'='*60}")

    # BU选择
    print("\n可选BU（输入全称，如 亚信科技CMB）:")
    print("  预算内: 亚信科技CMB, 亚信科技CSC, 亚信科技CMD, 亚信科技CUC, 亚信科技CTC, 亚信科技ESU, 亚信科技AID, 亚信科技RIC, 亚信科技AIO, 亚信科技CSU")
    print("  预算外: 亚信科技DIG1, 亚信科技TSG1, 亚信科技AIS, 亚信科技AIC, 亚信科技SCC, 亚信科技00, 亚信科技IDI DCU")
    bu_input = input("请输入BU（逗号分隔，直接回车=全部）: ").strip()
    bu_list = [b.strip() for b in bu_input.replace('，', ',').split(',') if b.strip()]

    # 时间范围
    if time_format == 'month':
        print("\n时间格式示例: 2026年1月, 2026年4月")
        start_time = input_nonempty("起始月份", "2026年1月")
        end_time = input_nonempty("结束月份", "2026年4月")
    else:
        print("\n时间格式示例: 2026年1月1日, 2026年12月31日")
        print("  ⚠️ 起始日期为月度首日，结束日期为月度末日")
        start_time = input_nonempty("起始日期", "2026年1月1日")
        end_time = input_nonempty("结束日期", "2026年12月31日")

    # 构造命令
    cmd = [PYTHON, script_path, '-u', USERNAME, '-p', PASSWORD,
           '--start', start_time, '--end', end_time]
    if bu_list:
        cmd.extend(['-s', ','.join(bu_list)])

    # 显示确认信息
    print(f"\n即将执行 {label} 下载:")
    print(f"  BU: {', '.join(bu_list) if bu_list else '全部'}")
    print(f"  时间: {start_time} ~ {end_time}")
    confirm = input("确认执行？(Y/n): ").strip().lower()
    if confirm == 'n':
        print(f"[SKIP] 已跳过{label}下载")
        return False, start_time, end_time

    # 下载前清空旧文件
    clear_downloads(script_dir, label)

    # 执行下载
    print(f"\n[INFO] 正在执行{label}下载，请稍候...")
    result = subprocess.run(cmd, cwd=script_dir)
    if result.returncode == 0:
        print(f"[SUCCESS] {label}下载完成")
        return True, start_time, end_time
    else:
        print(f"[ERROR] {label}下载失败（返回码: {result.returncode}）")
        retry = input("是否重试？(Y/n): ").strip().lower()
        if retry != 'n':
            return run_download(script_path, script_dir, label, time_format)
        return False, start_time, end_time


def parse_date_to_ymonth(date_str: str) -> str:
    """将中文日期字符串转为 YYYYMM 格式"""
    import re
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{0,2})日?', date_str)
    if m:
        year, month = m.group(1), m.group(2)
        return f"{year}{month.zfill(2)}"
    return ''


def run_merge(contract_start: str = '', contract_end: str = ''):
    """执行合并脚本，传递外包合同日期范围"""
    print(f"\n{'='*60}")
    print(f"  合并数据到目标Excel")
    print(f"{'='*60}")
    print("[INFO] 正在合并所有下载文件...")
    cmd = [PYTHON, MERGE_SCRIPT]
    # 转换中文日期格式为 YYYYMM
    cs_ym = parse_date_to_ymonth(contract_start)
    ce_ym = parse_date_to_ymonth(contract_end)
    if cs_ym:
        cmd.extend(['--contract-start', cs_ym])
    if ce_ym:
        cmd.extend(['--contract-end', ce_ym])
    result = subprocess.run(cmd)
    return result.returncode == 0


def run_export_server():
    """启动导出 HTTP 服务"""
    print(f"\n{'='*60}")
    print(f"  启动导出服务（用于导出 Excel）")
    print(f"{'='*60}")
    import threading
    import http.server, socketserver, urllib.parse, datetime

    PORT = 8765

    class ExportHandler(http.server.SimpleHTTPRequestHandler):
        def do_POST(self):
            if self.path != '/export':
                self.send_error(404)
                return
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                params = urllib.parse.parse_qs(body)
                anch_str = params.get('anchDate', [None])[0]
            except Exception:
                anch_str = None
            if not anch_str:
                self.send_response(400); self.end_headers()
                self.wfile.write(b'Missing anchDate'); return
            try:
                anch_date = datetime.datetime.strptime(anch_str, '%Y-%m-%d').date()
            except ValueError:
                self.send_response(400); self.end_headers()
                self.wfile.write(b'Invalid anchDate format'); return
            import importlib, importlib.util, sys
            sys.path.insert(0, DASHBOARD_DIR)
            spec = importlib.util.spec_from_file_location("generate_dashboard",
                os.path.join(DASHBOARD_DIR, 'generate_dashboard.py'))
            gd = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(gd)
            out_path = gd.export_rolling_forecast(anch_date=anch_date)
            with open(out_path, 'rb') as f:
                data = f.read()
            fname = f'滚动预测_{anch_date.strftime("%Y%m%d")}.xlsx'
            self.send_response(200)
            self.send_header('Content-Type',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            self.send_header('Content-Disposition',
                f"attachment; filename*=UTF-8''{urllib.parse.quote(fname)}")
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ('/', '/dashboard', '/index.html'):
                self.path = '/dashboard.html'
            return http.server.SimpleHTTPRequestHandler.do_GET(self)

        def log_message(self, fmt, *args):
            print(f'[ExportServer] {args[0]}')

    with socketserver.TCPServer(('', PORT), ExportHandler) as httpd:
        print(f"导出服务已启动: http://localhost:{PORT}/dashboard")
        print("修改锚点时间 → 点查询 → 点导出Excel")
        print("按 Ctrl+C 停止服务\n")
        httpd.serve_forever()


def run_dashboard():
    """生成仪表盘并启动导出服务"""
    print(f"\n{'='*60}")
    print(f"  生成预算管控仪表盘")
    print(f"{'='*60}")
    result = subprocess.run([PYTHON, DASHBOARD_SCRIPT], cwd=DASHBOARD_DIR)
    if result.returncode == 0 and os.path.exists(DASHBOARD_OUTPUT):
        print(f"\n[SUCCESS] 仪表盘已生成: {DASHBOARD_OUTPUT}")

        # 自动打开浏览器
        os.startfile(DASHBOARD_OUTPUT)
        # 启动导出服务（在后台线程）
        print("[INFO] 正在启动导出服务...")
        t = threading.Thread(target=run_export_server, daemon=True)
        t.start()
        return True
    else:
        print("[ERROR] 仪表盘生成失败")
        return False


def main():
    print("=" * 60)
    print("  预算管控仪表盘 — 一键更新工具")
    print("=" * 60)

    # 如果凭据为空，交互式输入
    global USERNAME, PASSWORD
    if not USERNAME:
        USERNAME = input("请输入用户名: ").strip()
    if not PASSWORD:
        PASSWORD = input("请输入密码: ").strip()

    # Step 0: 选择要执行的操作
    print("\n请选择要执行的操作:")
    print("  1. 下载计提与结算 + 合并 + 生成仪表盘")
    print("  2. 下载外包合同 + 合并 + 生成仪表盘")
    print("  3. 两个都下载 + 合并 + 生成仪表盘")
    print("  4. 仅合并数据 + 生成仪表盘（不下载）")
    print("  5. 仅生成仪表盘（用现有数据）")

    choice = input("\n请选择 (1-5): ").strip()

    download_settlement = choice in ('1', '3')
    download_contract = choice in ('2', '3')
    do_merge = choice in ('1', '2', '3', '4')
    do_dashboard = True  # 总是生成仪表盘

    # 记录外包合同下载的日期范围（用于合并逻辑）
    contract_start = ''
    contract_end = ''

    # Step 1: 下载计提结算
    if download_settlement:
        if not os.path.exists(SETTLEMENT_SCRIPT):
            print(f"[ERROR] 找不到下载脚本: {SETTLEMENT_SCRIPT}")
        else:
            run_download(SETTLEMENT_SCRIPT, SETTLEMENT_DIR, "计提与结算", 'month')

    # Step 2: 下载外包合同
    if download_contract:
        if not os.path.exists(CONTRACT_SCRIPT):
            print(f"[ERROR] 找不到下载脚本: {CONTRACT_SCRIPT}")
        else:
            _, contract_start, contract_end = run_download(
                CONTRACT_SCRIPT, CONTRACT_DIR, "外包合同", 'date')

    # Step 3: 合并数据
    if do_merge:
        if not os.path.exists(MERGE_SCRIPT):
            print(f"[ERROR] 找不到合并脚本: {MERGE_SCRIPT}")
        else:
            # 合并前检查目标文件是否被占用
            print("\n[提醒] 请确保目标Excel文件已关闭，否则合并会失败！")
            run_merge(contract_start, contract_end)

    # Step 4: 生成仪表盘
    if do_dashboard:
        if not os.path.exists(DASHBOARD_SCRIPT):
            print(f"[ERROR] 找不到生成脚本: {DASHBOARD_SCRIPT}")
        else:
            run_dashboard()

    print("\n" + "=" * 60)
    print("  全部完成！")
    print("=" * 60)
    input("\n按回车键退出...")


if __name__ == '__main__':
    # 修复Windows控制台编码
    if sys.platform == 'win32':
        os.system('chcp 65001 >nul 2>&1')
        sys.stdout.reconfigure(encoding='utf-8')
    main()
