"""
飞书多维表更新模块 - 发布成功后更新"发布时间"和"是否发布"字段
"""

import json
import subprocess
import os
from datetime import datetime


def _run_lark_cli(args: list[str], stdin_data: str = None) -> dict | list:
    """执行 lark-cli 命令并返回 JSON 结果"""
    cmd = ["lark-cli"] + args
    print(f"  [lark-cli] {' '.join(cmd)}")
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        input=stdin_data, cwd=os.path.dirname(__file__)
    )
    if result.returncode != 0:
        print(f"  [lark-cli ERROR] {result.stderr}")
        raise RuntimeError(f"lark-cli 失败: {result.stderr}")
    stdout = result.stdout.strip()
    if not stdout:
        return {}
    try:
        parsed = json.loads(stdout)
        return parsed
    except json.JSONDecodeError:
        lines = stdout.split("\n")
        values = []
        for line in lines:
            line = line.strip().strip('"')
            if line:
                values.append(line)
        if len(values) == 1:
            return {"value": values[0]}
        return values


def update_record_published(bitable_token: str, table_id: str, record_id: str):
    """
    发布成功后更新多维表记录：
    - "是否发布" 设为 "是"
    - "发布时间" 设为当前时间（格式如 2026-05-18 16:48:46）
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"  更新多维表记录 {record_id}: 是否发布=是, 发布时间={now_str}")

    update_json = json.dumps({
        "是否发布": "是",
        "发布时间": now_str,
    }, ensure_ascii=False)

    try:
        result = _run_lark_cli([
            "base", "+record-update",
            "--base-token", bitable_token,
            "--table-id", table_id,
            "--record-id", record_id,
            "--json", update_json,
        ])
        if isinstance(result, dict) and result.get("ok", False):
            print(f"  多维表记录更新成功")
        else:
            print(f"  [WARN] 多维表记录更新结果: {result}")
    except Exception as e:
        print(f"  [ERROR] 更新多维表记录失败: {e}")
