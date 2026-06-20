"""
主入口 — 提取申请单信息至飞书多维表
流程: 导出Excel → 筛选新签 → 逐条搜索弹窗 → 去重 → 写入

用法:
  python main.py               # 默认 SBU=185
  python main.py --sbu 185     # 单个 SBU
  python main.py --sbu 185,186 # 多个 SBU（中英文逗号均可）
"""
import os
import sys
import argparse
from dotenv import load_dotenv


def secure_input(prompt="密码: "):
    """密码输入 — Windows 显示 * 回显，其他平台用 getpass"""
    if sys.platform == "win32":
        import msvcrt
        print(prompt, end="", flush=True)
        password = ""
        while True:
            ch = msvcrt.getch()
            if ch in (b"\r", b"\n"):
                print()
                break
            elif ch == b"\x08":
                if password:
                    password = password[:-1]
                    print("\b \b", end="", flush=True)
            elif ch == b"\x03":
                raise KeyboardInterrupt()
            else:
                password += ch.decode("utf-8", errors="ignore")
                print("*", end="", flush=True)
        return password
    else:
        import getpass
        return getpass.getpass(prompt)
from config import get_date_range, parse_sbu_values
from lark_bitable import get_or_create_bitable, list_existing_ids, batch_create_records
from ims_scraper import run_full_extraction

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="提取申请单信息至飞书多维表")
    parser.add_argument("--sbu", default=os.getenv("SBU_VALUES", "185"),
                        help="SBU 代码，多个用逗号分隔（默认 185）")
    parser.add_argument("--username", default=os.getenv("IMS_USERNAME", ""),
                        help="IMS 登录用户名")
    parser.add_argument("--password", default=os.getenv("IMS_PASSWORD", ""),
                        help="IMS 登录密码")
    args = parser.parse_args()

    username = args.username
    password = args.password

    if not username:
        username = input("IMS 用户名: ").strip()
    if not password:
        password = secure_input("IMS 密码: ").strip()

    if not username or not password:
        print("[ERROR] 用户名和密码不能为空")
        sys.exit(1)

    sbu_values = parse_sbu_values(args.sbu)

    print("=" * 60)
    print("  提取申请单信息至多维表")
    print(f"  SBU: {', '.join(sbu_values)}")
    print("=" * 60)

    # 1. 计算日期
    date_start, date_end = get_date_range()
    print(f"\n查询范围: {date_start} ~ {date_end}")

    # 2. 初始化/加载多维表
    print("\n[步骤1] 初始化多维表...")
    base_token, table_id = get_or_create_bitable()
    print(f"  Base: {base_token}")
    print(f"  Table: {table_id}")

    # 3. 获取已有记录（去重）
    existing_ids = list_existing_ids(base_token, table_id)

    # 4. IMS 数据提取
    print("\n[步骤2] IMS 数据提取...")
    details = run_full_extraction(date_start, date_end, sbu_values, username, password)
    print(f"\n共提取 {len(details)} 条详情")

    # 5. 去重
    print("\n[步骤3] 去重...")
    new_records = [d for d in details
                   if d.get("合作申请单编号", "") not in existing_ids]
    skipped = len(details) - len(new_records)
    print(f"  新记录: {len(new_records)}, 已存在跳过: {skipped}")

    # 6. 写入
    print("\n[步骤4] 写入多维表...")
    written = batch_create_records(base_token, table_id, new_records)

    # 7. 报告
    print("\n" + "=" * 60)
    print(f"  完成!")
    print(f"  提取: {len(details)} 条")
    print(f"  新增: {written} 条")
    print(f"  跳过: {skipped} 条")
    print("=" * 60)


if __name__ == "__main__":
    main()
