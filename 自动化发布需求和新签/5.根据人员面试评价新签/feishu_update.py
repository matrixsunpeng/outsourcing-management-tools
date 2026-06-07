"""
飞书多维表更新模块 - 签署成功或失败后回写多维表
"""

import json
import subprocess
import os
from datetime import datetime


def _run_lark_cli(args: list[str], stdin_data: str = None) -> dict | list:
    """执行 lark-cli 命令并返回 JSON 结果"""
    cmd = ["lark-cli"] + args
    print(f"  [lark-cli] {' '.join(cmd)}")
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
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


def update_records_signed(bitable_token: str, table_id: str, record_ids: list[str],
                          order_no: str = ""):
    """
    签署成功后批量更新多维表记录：
    - "是否签署" 设为 "是"
    - "未成功提交原因" 清空
    - "技术合作订单编号" 填入（如有）
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    success_count = 0
    fail_count = 0

    update_fields = {
        "是否签署": "是",
        "未成功提交原因": "",
    }
    if order_no:
        update_fields["技术合作订单编号"] = order_no

    for record_id in record_ids:
        print(f"  更新记录 {record_id}: 是否签署=是" + (f" 订单号={order_no}" if order_no else ""))

        update_json = json.dumps(update_fields, ensure_ascii=False)

        try:
            result = _run_lark_cli([
                "base", "+record-upsert",
                "--base-token", bitable_token,
                "--table-id", table_id,
                "--record-id", record_id,
                "--json", update_json,
            ])
            if isinstance(result, dict) and result.get("ok", False):
                success_count += 1
            else:
                fail_count += 1
                print(f"  [WARN] 记录 {record_id} 更新结果: {result}")
        except Exception as e:
            fail_count += 1
            print(f"  [ERROR] 更新记录 {record_id} 失败: {e}")

    print(f"  签署回写完成: 成功 {success_count}, 失败 {fail_count}")


def update_records_failure(bitable_token: str, table_id: str, record_ids: list[str], reason: str):
    """
    签署失败后批量更新多维表记录：
    - "未成功提交原因" 设为失败原因
    """
    success_count = 0
    fail_count = 0

    for record_id in record_ids:
        print(f"  更新记录 {record_id}: 未成功提交原因={reason[:50]}...")

        update_json = json.dumps({
            "未成功提交原因": reason,
        }, ensure_ascii=False)

        try:
            result = _run_lark_cli([
                "base", "+record-upsert",
                "--base-token", bitable_token,
                "--table-id", table_id,
                "--record-id", record_id,
                "--json", update_json,
            ])
            if isinstance(result, dict) and result.get("ok", False):
                success_count += 1
            else:
                fail_count += 1
                print(f"  [WARN] 记录 {record_id} 更新结果: {result}")
        except Exception as e:
            fail_count += 1
            print(f"  [ERROR] 更新记录 {record_id} 失败: {e}")

    print(f"  失败原因回写完成: 成功 {success_count}, 失败 {fail_count}")
