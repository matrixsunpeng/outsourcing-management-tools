"""
飞书多维表查询模块 - 查询"是否发布"为否的记录
lark-cli +record-list 返回:
  data.fields: 字段名列表（列顺序）
  data.data: 二维数组（行数据）
  data.record_id_list: 记录ID列表
"""

import json
import subprocess
import os
from dotenv import dotenv_values


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


def _load_config(config_path: str = None) -> dict:
    """加载配置"""
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "config.env")
    return dotenv_values(config_path)


def get_bitable_config(config_path: str = None) -> tuple[str, str]:
    """获取多维表配置，返回 (bitable_token, table_id)"""
    config = _load_config(config_path)
    bitable_token = config.get("BITABLE_TOKEN", "")
    table_id = config.get("TABLE_ID", "")
    if not bitable_token or not table_id:
        raise RuntimeError("config.env 中缺少 BITABLE_TOKEN 或 TABLE_ID")
    return bitable_token, table_id


def query_unpublished_records(config_path: str = None) -> list[dict]:
    """
    查询多维表中"是否发布"为"否"的记录。
    返回记录列表，每条记录为 {字段名: 值} 字典，包含 _record_id。
    """
    config = _load_config(config_path)
    bitable_token = config.get("BITABLE_TOKEN", "")
    table_id = config.get("TABLE_ID", "")

    if not bitable_token or not table_id:
        print("  [ERROR] config.env 中缺少 BITABLE_TOKEN 或 TABLE_ID")
        return []

    print("  正在查询多维表未发布记录...")

    # 分页获取所有记录（带字段名和record_id）
    all_records, field_names = _fetch_all_records(bitable_token, table_id)
    print(f"  字段数量: {len(field_names)}, 记录数: {len(all_records)}")

    # 筛选"是否发布"为"否"且"合作申请单编号"不为空的记录
    unpublished = []
    skipped_empty = 0
    for rec in all_records:
        is_published = str(rec.get("是否发布", "")).strip()
        application_code = str(rec.get("合作申请单编号", "")).strip()
        if is_published != "是":
            # 跳过编号为空的无效记录（空行）
            if not application_code or application_code == "None":
                skipped_empty += 1
                continue
            unpublished.append(rec)

    if skipped_empty > 0:
        print(f"  跳过 {skipped_empty} 条编号为空的无效记录")
    print(f"  其中有效未发布记录: {len(unpublished)} 条")
    return unpublished


def _fetch_all_records(bitable_token: str, table_id: str) -> tuple[list[dict], list[str]]:
    """
    分页获取多维表所有记录。
    返回 (records, field_names)，每条记录为 {字段名: 值, "_record_id": id}
    """
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

        # 第一页时保存字段名
        if fields and not field_names:
            field_names = fields

        # 将二维数组映射为字典
        for i, row in enumerate(rows):
            rec = {}
            for j, val in enumerate(row):
                if j < len(field_names):
                    # 供应商字段可能是数组 ["xxx"]，转为字符串
                    if isinstance(val, list):
                        val = ",".join(str(v) for v in val if v)
                    rec[field_names[j]] = val
            # 添加 record_id
            if i < len(record_ids):
                rec["_record_id"] = record_ids[i]
            all_records.append(rec)

        # 检查是否有下一页
        has_more = data.get("has_more", False)
        page_token = data.get("page_token", "")
        if not has_more:
            break

    return all_records, field_names
