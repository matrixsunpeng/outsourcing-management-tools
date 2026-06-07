#!/usr/bin/env python
"""
快速开始脚本 - 运行完整的续签自动下单流程
"""

import sys
import os
from pathlib import Path

# 检查环境
print("[检查] 验证环境...")

required_packages = ['pandas', 'openpyxl', 'playwright']
missing_packages = []

for pkg in required_packages:
    try:
        __import__(pkg)
        print(f"  ✓ {pkg}")
    except ImportError:
        print(f"  ✗ {pkg} 未安装")
        missing_packages.append(pkg)

if missing_packages:
    print(f"\n[提示] 需要安装依赖包: {', '.join(missing_packages)}")
    print("[建议] 运行以下命令:")
    print(f"      pip install -r requirements.txt")
    sys.exit(1)

print("\n[检查] 环境检查完成！")
print("\n" + "="*60)
print("续签自动下单工具 - 快速开始")
print("="*60)

# 获取用户输入
print("\n请选择操作模式:")
print("1. 完整流程（下载 -> 清单 -> 下单）")
print("2. 仅下载并生成清单")
print("3. 仅处理已有的待办清单")

mode = input("\n请选择 (1-3): ").strip()

# 统一获取账号密码
username = input("\n请输入 IMS 用户名: ").strip()
if not username:
    print("❌ 用户名不能为空")
    sys.exit(1)
password = input("请输入 IMS 密码: ").strip()
if not password:
    print("❌ 密码不能为空")
    sys.exit(1)

if mode == "1":
    print("\n[执行] 完整流程模式")
    
    start_date = input("开始日期（格式: 2026年3月1日）: ").strip()
    if not start_date:
        print("❌ 开始日期不能为空")
        sys.exit(1)
    end_date = input("结束日期（格式: 2026年3月31日）: ").strip()
    if not end_date:
        print("❌ 结束日期不能为空")
        sys.exit(1)
    audit_date = input(f"稽核时间（格式: 2026-03-31，直接回车则使用续签查询结束日期 {end_date}）: ").strip() or end_date
    sbu = input("SBU（多个用逗号间隔，直接回车默认全部）: ").strip() or None
    
    cmd = f'python main.py --username "{username}" --password "{password}" --start "{start_date}" --end "{end_date}" --audit-date "{audit_date}" --sbu "{sbu or ""}"'

    # 是否跳过人员删除
    skip_delete = input("是否跳过离岗不续签人员删除？（y/N，默认执行）: ").strip().lower()
    if skip_delete in ("y", "yes"):
        cmd += " --skip-delete"
        print("[确认] 将跳过离岗不续签人员删除")
    
    # 断点续跑
    resume_input = input("是否断点续跑（跳过已处理的记录）？(y/N): ").strip().lower()
    if resume_input == "y" or resume_input == "yes":
        cmd += " --resume"
        print("[确认] 启用断点续跑")
    
    print(f"\n[执行命令]: {cmd}\n")
    os.system(cmd)

elif mode == "2":
    print("\n[执行] 仅下载模式")
    
    start_date = input("开始日期（格式: 2026年3月1日）: ").strip()
    if not start_date:
        print("❌ 开始日期不能为空")
        sys.exit(1)
    end_date = input("结束日期（格式: 2026年3月31日）: ").strip()
    if not end_date:
        print("❌ 结束日期不能为空")
        sys.exit(1)
    audit_date = input(f"稽核时间（格式: 2026-03-31，直接回车则使用续签查询结束日期 {end_date}）: ").strip() or end_date
    sbu = input("SBU（多个用逗号间隔，直接回车默认全部）: ").strip() or None
    
    cmd = f'python main.py --username "{username}" --password "{password}" --download-only --start "{start_date}" --end "{end_date}" --audit-date "{audit_date}" --sbu "{sbu or ""}"'
    
    print(f"\n[执行命令]: {cmd}\n")
    os.system(cmd)

elif mode == "3":
    print("\n[执行] 仅处理模式")
    
    todo_file = input("输入待办清单文件路径: ").strip()
    
    if not Path(todo_file).exists():
        print(f"❌ 文件不存在: {todo_file}")
        sys.exit(1)
    
    # 自动定位同目录下最新的离岗不续签清单
    todo_dir = Path(todo_file).parent
    import glob
    not_renewing_files = sorted(
        glob.glob(str(todo_dir / "离岗不续签清单_*.xlsx")),
        reverse=True
    )
    
    cmd = f'python main.py --username "{username}" --password "{password}" --process-only "{todo_file}"'
    
    # 断点续跑选项
    resume_input = input("是否断点续跑（跳过已处理的记录）？(y/N): ").strip().lower()
    if resume_input == "y" or resume_input == "yes":
        cmd += " --resume"
    
    if not_renewing_files:
        nr_file = not_renewing_files[0]
        print(f"[自动] 检测到离岗不续签清单: {nr_file}")
        
        # 让用户选择是否执行人员删除比对
        delete_choice = input("是否使用离岗不续签清单进行人员删除比对？(Y/n): ").strip().lower()
        if delete_choice in ("", "y", "yes"):
            cmd += f' --not-renewing-file "{nr_file}"'
            print(f"[确认] 将进行离岗不续签人员删除")
        else:
            cmd += " --skip-delete"
            print("[确认] 跳过人员删除")
    else:
        print("[提示] 未找到离岗不续签清单，将跳过人员删除步骤")
    
    print(f"\n[执行命令]: {cmd}\n")
    os.system(cmd)

else:
    print("❌ 无效选择")
    sys.exit(1)
