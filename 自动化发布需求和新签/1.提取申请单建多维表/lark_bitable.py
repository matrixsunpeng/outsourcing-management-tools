"""
飞书多维表操作 — lark-cli 封装，支持配置持久化
"""
import json
import subprocess
import os
from pathlib import Path

from config import LARK_CLI, FIELDS, TABLE_NAME

CONFIG_FILE = Path(__file__).parent / "bitable_config.json"


def _run_lark(*args, timeout=60):
    cmd = ["cmd", "/c", LARK_CLI] + list(args)
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout
    )
    if result.returncode != 0:
        try:
            print(f"[lark-cli ERROR] {result.stderr[:500]}")
        except UnicodeEncodeError:
            print(f"[lark-cli ERROR] (encoding error in output)")
        raise RuntimeError(f"lark-cli 命令失败: {' '.join(args[:3])}")
    return result.stdout.strip()


def load_config():
    """加载已保存的多维表配置，返回 (base_token, table_id) 或 (None, None)"""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            bt = cfg.get("base_token", "")
            tid = cfg.get("table_id", "")
            if bt and tid:
                print(f"[配置] 加载已有多维表: {tid}")
                return bt, tid
        except Exception:
            pass
    return None, None


def save_config(base_token, table_id):
    """保存多维表配置"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"base_token": base_token, "table_id": table_id}, f, ensure_ascii=False)
    print(f"[配置] 多维表地址已保存: {table_id}")


def create_base(name="外包申请数据"):
    output = _run_lark("base", "+base-create", "--name", name)
    data = json.loads(output)
    token = data.get("data", {}).get("base", {}).get("base_token", "")
    if not token:
        raise RuntimeError(f"创建 Base 失败: {output}")
    print(f"[飞书] 创建 Base: {name} (token: {token})")
    return token


def create_table(base_token, table_name=TABLE_NAME):
    fields_json = json.dumps(FIELDS, ensure_ascii=False)
    output = _run_lark(
        "base", "+table-create",
        "--base-token", base_token,
        "--name", table_name,
        "--fields", fields_json
    )
    data = json.loads(output)
    table_id = data.get("data", {}).get("table", {}).get("id", "")
    if not table_id:
        raise RuntimeError(f"创建多维表失败: {output}")
    print(f"[飞书] 创建多维表: {table_name} (id: {table_id})")
    return table_id


def get_or_create_bitable():
    """获取或创建多维表，返回 (base_token, table_id)"""
    bt, tid = load_config()
    if bt and tid:
        ensure_fields(bt, tid)
        return bt, tid

    print("[飞书] 首次运行，创建多维表...")
    bt = create_base()
    tid = create_table(bt)
    save_config(bt, tid)
    return bt, tid


def ensure_fields(base_token, table_id):
    """确保多维表中存在 FIELDS 定义的所有字段，缺失则自动创建"""
    existing_names = _list_field_names(base_token, table_id)
    for f in FIELDS:
        fn = f["field_name"]
        if fn not in existing_names:
            print(f"[飞书] 补充创建字段: {fn}")
            _create_field(base_token, table_id, fn, f["type"])


def _list_field_names(base_token, table_id):
    """返回多维表中已有字段名集合"""
    output = _run_lark(
        "base", "+field-list",
        "--base-token", base_token,
        "--table-id", table_id
    )
    data = json.loads(output)
    fields = data.get("data", {}).get("fields", [])
    return {f.get("name", "") for f in fields}


def _create_field(base_token, table_id, field_name, field_type):
    """在已有表中创建新字段"""
    payload = json.dumps({"field_name": field_name, "type": field_type}, ensure_ascii=False)
    _run_lark(
        "base", "+field-create",
        "--base-token", base_token,
        "--table-id", table_id,
        "--json", payload
    )


def _get_field_id(base_token, table_id, field_name):
    """获取字段名对应的实际字段 ID"""
    output = _run_lark(
        "base", "+field-list",
        "--base-token", base_token,
        "--table-id", table_id
    )
    data = json.loads(output)
    # API 返回格式: data.fields[] 每个有 id, name 属性
    fields = data.get("data", {}).get("fields", [])
    for f in fields:
        if f.get("name", "") == field_name:
            return f.get("id", "")
    return ""


def list_existing_ids(base_token, table_id):
    """获取多维表中已有「合作申请单编号」集合"""
    target_field = "合作申请单编号"
    field_id = _get_field_id(base_token, table_id, target_field)
    if not field_id:
        print(f"[去重] 未找到字段「{target_field}」, 跳过去重")
        return set()

    existing = set()
    offset = 0
    limit = 200
    while True:
        output = _run_lark(
            "base", "+record-list",
            "--base-token", base_token,
            "--table-id", table_id,
            "--field-id", field_id,
            "--limit", str(limit),
            "--offset", str(offset),
            "--format", "json"
        )
        data = json.loads(output)
        payload = data.get("data", {})
        rows = payload.get("data", [])
        field_ids = payload.get("field_id_list", [])

        if not rows:
            break

        # 找到目标字段在 field_id_list 中的位置
        try:
            col_idx = field_ids.index(field_id)
        except ValueError:
            break

        for row in rows:
            if col_idx < len(row) and row[col_idx] is not None:
                app_id = str(row[col_idx])
                if app_id:
                    existing.add(app_id)

        has_more = payload.get("has_more", False)
        if not has_more:
            break
        offset += limit

    print(f"[去重] 多维表中已有 {len(existing)} 条记录")
    return existing


def batch_create_records(base_token, table_id, records):
    """逐条新增记录（避免命令行长度限制）"""
    if not records:
        print("[飞书] 无新记录")
        return 0

    field_names = [f["field_name"] for f in FIELDS]
    total = 0
    for i, rec in enumerate(records):
        row = []
        for fn in field_names:
            val = rec.get(fn, "")
            if val is None:
                val = ""
            row.append(str(val))

        payload = json.dumps(
            {"fields": field_names, "rows": [row]},
            ensure_ascii=False
        )
        # 通过文件传递JSON避免命令行编码问题
        tmp_name = f"_tmp_rec_{i}.json"
        try:
            with open(tmp_name, "w", encoding="utf-8") as f:
                f.write(payload)

            _run_lark(
                "base", "+record-batch-create",
                "--base-token", base_token,
                "--table-id", table_id,
                "--json", f"@{tmp_name}",
                timeout=60
            )
            total += 1
        except RuntimeError as e:
            print(f"[飞书] 第{i+1}条写入失败: {str(e)[:200]}")
        finally:
            try:
                os.remove(tmp_name)
            except Exception:
                pass

        if (i + 1) % 5 == 0 or (i + 1) == len(records):
            print(f"[飞书] 进度: {i+1}/{len(records)}")

    print(f"[飞书] 完成，共新增 {total} 条")
    return total
