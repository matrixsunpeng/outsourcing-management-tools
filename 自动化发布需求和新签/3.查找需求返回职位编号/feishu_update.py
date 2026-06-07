"""
飞书多维表更新模块 - 将找到的职位编号写入多维表记录
"""

import json
import subprocess
import os


def _run_lark_cli(args: list[str]) -> dict | list:
    """执行 lark-cli 命令并返回 JSON 结果"""
    cmd = ["lark-cli"] + args
    print(f"  [lark-cli] {' '.join(cmd)}")
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        cwd=os.path.dirname(__file__)
    )
    if result.returncode != 0:
        print(f"  [lark-cli ERROR] {result.stderr}")
        raise RuntimeError(f"lark-cli 失败: {result.stderr}")
    stdout = result.stdout.strip()
    if not stdout:
        return {}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {}


def update_position_code(bitable_token: str, table_id: str, record_id: str, position_codes: str):
    """
    更新多维表记录的"职位编号"字段。
    position_codes: 职位编号字符串，多个用逗号分隔
    """
    print(f"  更新记录 {record_id}: 职位编号={position_codes}")

    update_json = json.dumps({
        "职位编号": position_codes,
    }, ensure_ascii=False)

    result = _run_lark_cli([
        "base", "+record-upsert",
        "--base-token", bitable_token,
        "--table-id", table_id,
        "--record-id", record_id,
        "--json", update_json,
    ])
    if isinstance(result, dict) and result.get("ok", False):
        print(f"  职位编号更新成功")
    else:
        print(f"  [WARN] 更新结果: {result}")
