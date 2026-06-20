"""
流水线编排脚本 — 串联 功能1 → 人工审核 → 功能2 → 功能3

用法:
  python run_pipeline.py                    # 完整流程
  python run_pipeline.py --sbu 185          # 指定 SBU
  python run_pipeline.py --sbu 185,186      # 多个 SBU（中英文逗号均可）
  python run_pipeline.py --from review      # 跳过功能1，从人工审核开始
  python run_pipeline.py --from publish     # 直接从功能2（发布）开始
"""

import os
import sys
import json
import subprocess
import argparse
from datetime import datetime


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
                char = ch.decode("utf-8", errors="ignore")
                password += char
                print("*", end="", flush=True)
        return password
    else:
        import getpass
        return getpass.getpass(prompt)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DIR_F1 = os.path.join(BASE_DIR, "1.提取申请单建多维表")
DIR_F2 = os.path.join(BASE_DIR, "2.根据多维表发布需求")
DIR_F3 = os.path.join(BASE_DIR, "3.查找需求返回职位编号")

BITABLE_CONFIG = os.path.join(DIR_F1, "bitable_config.json")
CONFIG_F2 = os.path.join(DIR_F2, "config.env")
CONFIG_F3 = os.path.join(DIR_F3, "config.env")


def parse_sbu_values(raw: str) -> list[str]:
    """解析逗号分隔的 SBU/BU 代码，支持中英文逗号，去空白去重"""
    if not raw:
        return ["185"]
    raw = raw.replace("，", ",")  # 中文逗号
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    seen = set()
    result = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def run_phase(title: str, cwd: str, args: list[str]) -> bool:
    """运行一个阶段，返回是否成功"""
    # 打印时遮盖密码
    display_args = []
    skip_next = False
    for i, a in enumerate(args):
        if skip_next:
            display_args.append("***")
            skip_next = False
        elif a == "--password":
            display_args.append("--password")
            skip_next = True
        else:
            display_args.append(a)

    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"  cwd: {cwd}")
    print(f"  cmd: python {' '.join(display_args)}")
    print(f"{'=' * 60}\n")

    result = subprocess.run(
        [sys.executable] + args,
        cwd=cwd,
        check=False,
    )
    success = result.returncode == 0
    status = "SUCCESS" if success else f"FAILED (code={result.returncode})"
    print(f"\n--- {title}: {status} ---")
    return success


def sync_config():
    """将功能1的 bitable_config.json 同步到功能2/3的 config.env"""
    if not os.path.exists(BITABLE_CONFIG):
        print("[Phase 2] bitable_config.json 不存在，跳过配置同步")
        return False

    with open(BITABLE_CONFIG, "r", encoding="utf-8") as f:
        bc = json.load(f)

    base_token = bc.get("base_token", "")
    table_id = bc.get("table_id", "")

    if not base_token or not table_id:
        print("[Phase 2] bitable_config.json 内容不完整，跳过")
        return False

    print(f"[Phase 2] 同步配置: BITABLE_TOKEN={base_token}, TABLE_ID={table_id}")

    for config_path in [CONFIG_F2, CONFIG_F3]:
        if not os.path.exists(config_path):
            print(f"  {os.path.basename(config_path)} 不存在，跳过")
            continue

        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        new_lines = []
        updated_token = False
        updated_table = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("BITABLE_TOKEN=") or stripped.startswith("BITABLE_TOKEN "):
                new_lines.append(f"BITABLE_TOKEN={base_token}\n")
                updated_token = True
            elif stripped.startswith("TABLE_ID=") or stripped.startswith("TABLE_ID "):
                new_lines.append(f"TABLE_ID={table_id}\n")
                updated_table = True
            else:
                new_lines.append(line)

        if not updated_token:
            new_lines.append(f"BITABLE_TOKEN={base_token}\n")
        if not updated_table:
            new_lines.append(f"TABLE_ID={table_id}\n")

        with open(config_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print(f"  已更新 {os.path.basename(config_path)}")

    return True


def human_checkpoint(bu_values: list[str]):
    """人工审核检查点"""
    print(f"\n{'=' * 60}")
    print(f"  [Phase 3] 人工审核检查点")
    print(f"{'=' * 60}")

    # 尝试打印多维表链接
    if os.path.exists(BITABLE_CONFIG):
        with open(BITABLE_CONFIG, "r", encoding="utf-8") as f:
            bc = json.load(f)
        base_token = bc.get("base_token", "")
        table_id = bc.get("table_id", "")
        if base_token and table_id:
            url = f"https://bytedance.feishu.cn/base/{base_token}?table={table_id}"
            print(f"\n  多维表链接: {url}")
            print(f"  SBU: {', '.join(bu_values)}")

    print(f"""
  ┌─────────────────────────────────────────────────────┐
  │  请在飞书多维表中完成以下操作：                       │
  │  1. 检查数据完整性（岗位、工作内容、技能要求等）      │
  │  2. 分配供应商（填写"供应商"和"分配人数"列）         │
  │  3. 确认无误后回到此处按 Enter 继续                   │
  │                                                     │
  │  按 Ctrl+C 可随时终止流程                            │
  └─────────────────────────────────────────────────────┘
""")

    try:
        input("  按 Enter 继续执行功能2（发布需求）...")
    except KeyboardInterrupt:
        print("\n\n  流程已终止。")
        sys.exit(0)

    print("  已确认，继续执行...\n")


def prompt_sbu() -> str:
    """交互式提示输入 SBU"""
    print(f"\n{'=' * 60}")
    print(f"  SBU/BU 配置")
    print(f"{'=' * 60}")
    print("\n  请输入 SBU/BU 代码，多个用逗号分隔（如 185,186）")
    print("  默认为 185（亚信科技CMB）")

    try:
        raw = input("  SBU [185]: ").strip()
    except KeyboardInterrupt:
        print("\n\n  流程已终止。")
        sys.exit(0)

    if not raw:
        raw = "185"
    return raw


def prompt_credentials():
    """交互式提示输入 IMS 登录凭证"""
    print(f"\n{'=' * 60}")
    print(f"  IMS 登录凭证")
    print(f"{'=' * 60}")

    try:
        username = input("  IMS 用户名: ").strip()
    except KeyboardInterrupt:
        print("\n\n  流程已终止。")
        sys.exit(0)

    if not username:
        print("[ERROR] 用户名不能为空")
        sys.exit(1)

    try:
        password = secure_input("  IMS 密码: ").strip()
    except KeyboardInterrupt:
        print("\n\n  流程已终止。")
        sys.exit(0)

    if not password:
        print("[ERROR] 密码不能为空")
        sys.exit(1)

    return username, password


def main():
    parser = argparse.ArgumentParser(
        description="流水线编排 — 功能1→人工审核→功能2→功能3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_pipeline.py                      完整流程（交互式输入 SBU）
  python run_pipeline.py --sbu 185            指定单个 SBU
  python run_pipeline.py --sbu "185,186"      指定多个 SBU
  python run_pipeline.py --from review        从人工审核开始（跳过功能1）
  python run_pipeline.py --from publish       从功能2发布开始
        """,
    )
    parser.add_argument("--sbu", default=None,
                        help="SBU/BU 代码，多个用逗号分隔（默认 185）")
    parser.add_argument("--username", default=None, help="IMS 登录用户名")
    parser.add_argument("--password", default=None, help="IMS 登录密码")
    parser.add_argument("--from", dest="from_phase", default="start",
                        choices=["start", "review", "publish"],
                        help="起始阶段: start(默认), review(跳过功能1), publish(跳过功能1+审核)")
    args = parser.parse_args()

    # 收集 SBU
    if args.sbu:
        sbu_values = parse_sbu_values(args.sbu)
    else:
        sbu_raw = prompt_sbu()
        sbu_values = parse_sbu_values(sbu_raw)

    sbu_arg = ",".join(sbu_values)

    # 收集 IMS 凭证
    if args.username and args.password:
        username = args.username
        password = args.password
    elif args.from_phase == "start":
        username, password = prompt_credentials()
    else:
        # 从 review/publish 开始时，凭证可能已不需要（只是给子模块回退用）
        username = args.username or ""
        password = args.password or ""

    # 构建凭证参数（如果都有值才传）
    cred_args = []
    if username and password:
        cred_args = ["--username", username, "--password", password]

    start_time = datetime.now()
    results = {}

    # ==================== Phase 1: 功能1 ====================
    if args.from_phase == "start":
        results["Phase1_提取申请单"] = run_phase(
            "Phase 1/5: 提取申请单建多维表",
            DIR_F1,
            ["main.py", "--sbu", sbu_arg] + cred_args,
        )
    else:
        print(f"\n  [Phase 1] 跳过（--from {args.from_phase}）")
        results["Phase1_提取申请单"] = "skipped"

    # ==================== Phase 2: 配置同步 ====================
    sync_config()
    results["Phase2_配置同步"] = True

    # ==================== Phase 3: 人工审核 ====================
    if args.from_phase in ("start", "review"):
        human_checkpoint(sbu_values)
        results["Phase3_人工审核"] = "confirmed"
    else:
        print(f"\n  [Phase 3] 跳过人工审核（--from {args.from_phase}）")
        results["Phase3_人工审核"] = "skipped"

    # ==================== Phase 4: 功能2 ====================
    results["Phase4_发布需求"] = run_phase(
        "Phase 4/5: 根据多维表发布需求",
        DIR_F2,
        ["main.py", "-y"] + cred_args,
    )

    # ==================== Phase 5: 功能3 ====================
    results["Phase5_查找职位编号"] = run_phase(
        "Phase 5/5: 查找需求返回职位编号",
        DIR_F3,
        ["main.py", "--bu", sbu_arg] + cred_args,
    )

    # ==================== 汇总报告 ====================
    elapsed = datetime.now() - start_time
    print(f"\n{'=' * 60}")
    print(f"  流水线执行完毕")
    print(f"  耗时: {elapsed}")
    print(f"{'=' * 60}")
    for phase, status in results.items():
        icon = "✅" if status == True or status == "confirmed" or status == "skipped" else "❌"
        print(f"  {icon} {phase}: {status}")
    print(f"{'=' * 60}")

    # 再次打印多维表链接方便检查
    if os.path.exists(BITABLE_CONFIG):
        with open(BITABLE_CONFIG, "r", encoding="utf-8") as f:
            bc = json.load(f)
        base_token = bc.get("base_token", "")
        table_id = bc.get("table_id", "")
        if base_token and table_id:
            url = f"https://bytedance.feishu.cn/base/{base_token}?table={table_id}"
            print(f"\n  检查多维表: {url}")


if __name__ == "__main__":
    main()
