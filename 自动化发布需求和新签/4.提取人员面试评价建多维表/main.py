"""Main entry point: extract interview evaluations from IMS and fill Feishu Bitable.

Workflow:
  1. Validate config
  2. (Optional) Run IMS web automation to download export file
  3. Read exported Excel, filter by supplier, deduplicate by ID number
  4. Initialize / verify Feishu table
  5. Add new records to Feishu Bitable

Usage:
  python main.py              # interactive mode
  python main.py --auto       # full automation (web + feishu)
  python main.py --file <xlsx>  # process existing file
"""

import argparse
import sys

from config import Config
from data_processor import (
    read_exported_file,
    filter_by_supplier,
    deduplicate,
    map_to_bitable_fields,
)
from feishu_client import FeishuBitableClient


def process_and_upload(filepath: str):
    """Read exported file, process, and upload to Feishu."""
    # 1. Read exported data
    print(f"\n[处理] 读取文件: {filepath}")
    all_records = read_exported_file(filepath)
    print(f"[处理] 导出记录总数: {len(all_records)}")

    if not all_records:
        print("[处理] 没有数据，退出。")
        return

    # 2. Filter by supplier
    matched, rejected = filter_by_supplier(all_records)
    print(f"[处理] 供应商过滤后: {len(matched)} 条保留, {len(rejected)} 条排除")

    if not matched:
        print("[处理] 没有符合供应商条件的记录，退出。")
        return

    # 3. Initialize Feishu client and table
    print("\n[飞书] 连接飞书...")
    feishu = FeishuBitableClient()

    bitable_id = feishu.create_table_if_needed()
    table_id = feishu.init_table_fields(bitable_id)

    # 4. Get existing ID numbers for dedup
    print("[飞书] 读取表中已有记录用于去重...")
    existing_ids = feishu.get_existing_id_numbers(bitable_id, table_id)
    print(f"[飞书] 已有记录数: {len(existing_ids)}")

    new_records, skipped = deduplicate(matched, existing_ids)
    print(f"[处理] 去重后: {len(new_records)} 条新增, {skipped} 条重复跳过")

    if not new_records:
        print("[处理] 所有记录已存在，无新增。")
        return

    # 5. Map fields and add to Feishu
    bitable_records = map_to_bitable_fields(new_records)
    print(f"[飞书] 开始写入 {len(bitable_records)} 条记录...")
    added = feishu.add_records(bitable_id, table_id, bitable_records)

    # 6. Summary
    print()
    print("=" * 60)
    print("  处理完成")
    print("=" * 60)
    print(f"  导出总数:       {len(all_records)}")
    print(f"  供应商过滤排除: {len(rejected)}")
    print(f"  去重跳过:       {skipped}")
    print(f"  实际新增:       {added}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="提取人员面试评价表至飞书多维表")
    parser.add_argument("--auto", action="store_true", help="完整自动化流程（浏览器+写入）")
    parser.add_argument("--file", type=str, help="指定导出的 Excel 文件路径")
    args = parser.parse_args()

    errors = Config.validate()
    if errors:
        print("配置错误:")
        for e in errors:
            print(f"  - {e}")
        print("\n请在 .env 文件中填写必要配置后重试。")
        sys.exit(1)

    print("=" * 60)
    print("  人员面试评价表 → 飞书多维表")
    print("=" * 60)

    if args.file:
        # Mode 2: process existing file
        process_and_upload(args.file)
    elif args.auto:
        # Mode 1: full automation
        try:
            from web_automation import IMSAutomator
            automator = IMSAutomator()
            filepath = automator.run()
            if filepath:
                process_and_upload(filepath)
        except Exception as e:
            print(f"IMS 自动化失败: {e}")
            print("可以手动导出文件后用 --file 参数重试。")
            sys.exit(1)
    else:
        # Interactive mode
        print()
        print("模式选择:")
        print("  1. 完整流程（浏览器自动化登录IMS → 导出 → 写入飞书）")
        print("  2. 仅数据处理（已有导出文件，直接处理写入飞书）")
        try:
            choice = input("请选择 (1/2, 默认1): ").strip() or "1"
        except EOFError:
            print("未检测到交互输入，使用 --auto 或 --file 参数运行。")
            print("  python main.py --auto       # 完整自动化")
            print("  python main.py --file <xlsx> # 处理已有文件")
            sys.exit(1)

        filepath = None
        if choice == "1":
            try:
                from web_automation import IMSAutomator
                automator = IMSAutomator()
                filepath = automator.run()
            except Exception as e:
                print(f"IMS 自动化失败: {e}")
                print("可以手动导出文件后选择模式2重试。")
                sys.exit(1)
        else:
            filepath = input("请输入导出文件路径: ").strip().strip('"')
            if not filepath:
                print("未提供文件路径，退出。")
                sys.exit(1)

        if filepath:
            process_and_upload(filepath)


if __name__ == "__main__":
    main()
