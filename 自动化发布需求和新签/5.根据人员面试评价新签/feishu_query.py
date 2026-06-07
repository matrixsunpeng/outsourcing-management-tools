"""
飞书多维表查询模块 - 查询"是否签署"为否的记录，并按三字段组合分组
"""

import json
import subprocess
import os
from collections import OrderedDict
from dotenv import dotenv_values


def _run_lark_cli(args: list[str], stdin_data: str = None) -> dict | list:
    """执行 lark-cli 命令并返回 JSON 结果"""
    cmd = ["lark-cli"] + args
    print(f"  [lark-cli] {' '.join(cmd)}")
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['LANG'] = 'en_US.UTF-8'
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


def query_unsigned_records(config_path: str = None) -> list[dict]:
    """
    查询多维表中"是否签署"为"否"的记录。
    用字段索引避免编码问题。
    """
    config = _load_config(config_path)
    bitable_token = config.get("BITABLE_TOKEN", "")
    table_id = config.get("TABLE_ID", "")

    if not bitable_token or not table_id:
        print("  [ERROR] config.env 中缺少 BITABLE_TOKEN 或 TABLE_ID")
        return []

    print("  正在查询多维表未签署记录...")
    all_records, field_names = _fetch_all_records(bitable_token, table_id)
    print(f"  字段数量: {len(field_names)}, 记录数: {len(all_records)}")

    # 字段索引: 0=文本, 4=供应商/外包商, 5=身份证号, 6=技术合作订单编号,
    #   7=学历, 9=需求编号/合作申请单编号, 10=公司/签约方, 13=工资,
    #   14=校正上岗时间, 20=是否签署, 21=未成功提交原因
    unsigned = []
    skipped_empty = 0
    for rec in all_records:
        keys = list(rec.keys())
        is_signed = ''
        app_code = ''
        if len(keys) > 20:
            is_signed = str(rec.get(keys[20], "")).strip()
        if len(keys) > 9:
            app_code = str(rec.get(keys[9], "")).strip()
        if is_signed != '是':
            if not app_code or app_code == 'None':
                skipped_empty += 1
                continue
            unsigned.append(rec)

    if skipped_empty > 0:
        print(f"  跳过 {skipped_empty} 条编号为空的无效记录")
    print(f"  其中未签署记录: {len(unsigned)} 条")
    return unsigned


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


def group_records_by_contract(records: list[dict]) -> list[dict]:
    """
    按三字段组合分组:
      (需求编号/合作申请单编号, 公司/签约方, 供应商/外包商)

    每组包含该组合下所有人员记录。

    返回:
    [
        {
            "application_code": str,
            "signing_party": str,
            "supplier": str,
            "personnel": [
                {
                    "name": str,
                    "id_number": str,
                    "_record_id": str,
                    ...
                }
            ]
        },
        ...
    ]
    """
    groups = OrderedDict()

    for rec in records:
        keys = list(rec.keys())
        app_code = str(rec.get(keys[9], "")).strip() if len(keys) > 9 else ""
        signing_party = str(rec.get(keys[10], "")).strip() if len(keys) > 10 else ""
        supplier = str(rec.get(keys[4], "")).strip() if len(keys) > 4 else ""

        key = (app_code, signing_party, supplier)

        if key not in groups:
            groups[key] = {
                "application_code": app_code,
                "signing_party": signing_party,
                "supplier": supplier,
                "personnel": [],
            }

        keys = list(rec.keys())
        person = {
            "name": str(rec.get(keys[7] if len(keys) > 7 else "姓名", "")).strip(),
            "id_number": str(rec.get(keys[5] if len(keys) > 5 else "身份证号", "")).strip(),
            "_record_id": rec.get("_record_id", ""),
            "_raw": rec,
        }
        groups[key]["personnel"].append(person)

    result = list(groups.values())
    print(f"  分组完成: {len(records)} -> {len(result)} groups")
    for i, g in enumerate(result):
        n = len(g['personnel'])
        print(f"    {i+1}. [{g['application_code']}] {n} person(s)")

    return result
