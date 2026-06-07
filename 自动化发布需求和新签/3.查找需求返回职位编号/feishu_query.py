"""
飞书多维表查询模块 - 查询"是否发布"为是且"职位编号"为空的记录
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


def query_records_needing_position(bitable_token: str, table_id: str) -> list[dict]:
    """
    查询多维表中"是否发布"为"是"且"职位编号"为空的记录。
    返回记录列表，每条记录为 {字段名: 值} 字典，包含 _record_id。
    """
    print("  正在查询多维表中待查找职位编号的记录...")

    all_records, field_names = _fetch_all_records(bitable_token, table_id)
    print(f"  字段数量: {len(field_names)}, 记录数: {len(all_records)}")

    # 筛选: 是否发布=是 且 职位编号为空
    pending = []
    for rec in all_records:
        is_published = str(rec.get("是否发布", "")).strip()
        position_code = str(rec.get("职位编号", "")).strip()
        if is_published == "是" and (not position_code or position_code == "None"):
            pending.append(rec)

    print(f"  待查找职位编号的记录: {len(pending)} 条")
    return pending


def _fetch_all_records(bitable_token: str, table_id: str) -> tuple[list[dict], list[str]]:
    """分页获取多维表所有记录。"""
    all_records = []
    field_names = []
    page_token = None

    while True:
        args = [
            "base", "+record-list",
            "--base-token", bitable_token,
            "--table-id", table_id,
            "--limit", "500",
        ]
        if page_token:
            args.extend(["--page-token", page_token])

        result = _run_lark_cli(args)

        if not isinstance(result, dict):
            break

        data = result.get("data", {})
        rows = data.get("data", [])
        record_ids = data.get("record_id_list", [])
        fields = data.get("fields", [])

        if fields and not field_names:
            field_names = fields

        for i, row in enumerate(rows):
            rec = {}
            for j, val in enumerate(row):
                if j < len(field_names):
                    if isinstance(val, list):
                        val = ",".join(str(v) for v in val if v)
                    rec[field_names[j]] = val
            if i < len(record_ids):
                rec["_record_id"] = record_ids[i]
            all_records.append(rec)

        has_more = data.get("has_more", False)
        page_token = data.get("page_token", "")
        if not has_more:
            break

    return all_records, field_names
