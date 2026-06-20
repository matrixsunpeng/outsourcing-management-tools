"""Feishu Bitable (多维表) REST API client.

Handles: tenant token, create table, read records, add records.
"""

import requests

from config import Config


class FeishuBitableClient:
    def __init__(self):
        self.config = Config
        self._token: str | None = None

    def _get_tenant_token(self) -> str:
        """Get tenant_access_token."""
        if self._token:
            return self._token

        resp = requests.post(
            self.config.FEISHU_TOKEN_URL,
            json={
                "app_id": self.config.FEISHU_APP_ID,
                "app_secret": self.config.FEISHU_APP_SECRET,
            },
            timeout=30,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise Exception(f"获取飞书token失败: {data}")
        self._token = data["tenant_access_token"]
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_tenant_token()}",
            "Content-Type": "application/json",
        }

    def create_table_if_needed(self) -> str:
        """Create the bitable if it doesn't exist. Returns bitable_id.

        If FEISHU_BITABLE_ID is set in .env but the table has been deleted
        from Feishu, it will be auto-detected and a new table created.
        """
        bitable_id = self.config.FEISHU_BITABLE_ID
        if bitable_id:
            if self._bitable_exists(bitable_id):
                return bitable_id
            else:
                print(f"[飞书] 多维表 {bitable_id} 已不存在（可能被删除），将创建新表")
                # Clear the stale ID so a new one is created
                self._clear_saved_bitable_id()
                self.config.FEISHU_BITABLE_ID = ""
                bitable_id = ""

        base = self.config.FEISHU_BITABLE_BASE
        resp = requests.post(
            f"{base}/apps",
            headers=self._headers(),
            json={"name": self.config.BITABLE_NAME},
            timeout=30,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise Exception(f"创建多维表格失败: {data}")

        bitable_id = data["data"]["app"]["app_token"]
        print(f"[飞书] 多维表格已创建, app_token: {bitable_id}")

        # Save bitable_id back to .env
        self._save_bitable_id(bitable_id)
        self.config.FEISHU_BITABLE_ID = bitable_id
        return bitable_id

    def _bitable_exists(self, bitable_id: str) -> bool:
        """Check whether a bitable still exists on Feishu."""
        try:
            base = self.config.FEISHU_BITABLE_BASE
            resp = requests.get(
                f"{base}/apps/{bitable_id}",
                headers=self._headers(),
                timeout=15,
            )
            return resp.json().get("code") == 0
        except Exception:
            return False

    def _clear_saved_bitable_id(self):
        """Remove stale FEISHU_BITABLE_ID from .env file."""
        import os
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            with open(env_path, "w", encoding="utf-8") as f:
                for line in lines:
                    if not line.startswith("FEISHU_BITABLE_ID="):
                        f.write(line)
            print("[飞书] 已清除 .env 中的旧 FEISHU_BITABLE_ID")
        except Exception as e:
            print(f"[飞书] 清除旧 BITABLE_ID 失败: {e}")

    def _save_bitable_id(self, bitable_id: str):
        """Save bitable_id to .env file for future use."""
        import os
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            with open(env_path, "w", encoding="utf-8") as f:
                for line in lines:
                    if line.startswith("FEISHU_BITABLE_ID="):
                        f.write(f"FEISHU_BITABLE_ID={bitable_id}\n")
                    else:
                        f.write(line)
            print(f"[飞书] BITABLE_ID 已保存到 .env")
        except Exception as e:
            print(f"[飞书] 保存 BITABLE_ID 失败: {e}")

    def init_table_fields(self, bitable_id: str):
        """Ensure all required fields exist in the table."""
        base = self.config.FEISHU_BITABLE_BASE
        fields = self.config.BITABLE_FIELDS

        # Get tables in the bitable
        resp = requests.get(
            f"{base}/apps/{bitable_id}/tables",
            headers=self._headers(),
            timeout=30,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise Exception(f"获取表格列表失败: {data}")

        tables = data.get("data", {}).get("items", [])

        if not tables:
            # No tables — create first table with all fields in one request
            resp = requests.post(
                f"{base}/apps/{bitable_id}/tables",
                headers=self._headers(),
                json={
                    "table": {
                        "name": self.config.BITABLE_NAME,
                        "default_view_name": "全部",
                        "fields": fields,
                    }
                },
                timeout=30,
            )
            data = resp.json()
            if data.get("code") != 0:
                raise Exception(f"创建表格失败(错误码{data.get('code')}): {data}")
            table_id = data["data"]["table_id"]
            print(f"[飞书] 表格已创建, table_id: {table_id}")
            return table_id

        # Use first table
        table_id = tables[0]["table_id"]
        # Rename if needed
        if tables[0].get("name") != self.config.BITABLE_NAME:
            requests.patch(
                f"{base}/apps/{bitable_id}/tables/{table_id}",
                headers=self._headers(),
                json={"name": self.config.BITABLE_NAME},
                timeout=30,
            )

        # Get existing fields
        resp = requests.get(
            f"{base}/apps/{bitable_id}/tables/{table_id}/fields",
            headers=self._headers(),
            timeout=30,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise Exception(f"获取字段列表失败: {data}")

        existing_items = data.get("data", {}).get("items", [])
        existing_names = {f["field_name"] for f in existing_items}

        missing = [f for f in fields if f["field_name"] not in existing_names]
        if missing:
            print(f"[飞书] 添加缺失字段: {[f['field_name'] for f in missing]}")
            for field in missing:
                # API format: top-level field_name and type, NOT wrapped in {"field": ...}
                add_resp = requests.post(
                    f"{base}/apps/{bitable_id}/tables/{table_id}/fields",
                    headers=self._headers(),
                    json={
                        "field_name": field["field_name"],
                        "type": field["type"],
                    },
                    timeout=30,
                )
                add_data = add_resp.json()
                if add_data.get("code") != 0:
                    print(f"[飞书] 添加字段失败 [{field['field_name']}]: code={add_data.get('code')} msg={add_data.get('msg', add_data)}")
                else:
                    print(f"[飞书] 字段已添加: {field['field_name']}")

        # Verify all fields exist
        resp = requests.get(
            f"{base}/apps/{bitable_id}/tables/{table_id}/fields",
            headers=self._headers(),
            timeout=30,
        )
        verify_data = resp.json()
        verify_names = {f["field_name"] for f in verify_data.get("data", {}).get("items", [])}
        still_missing = [f["field_name"] for f in fields if f["field_name"] not in verify_names]
        if still_missing:
            print(f"[飞书] 警告: 以下字段仍未创建成功: {still_missing}")

        return table_id

    def get_existing_id_numbers(self, bitable_id: str, table_id: str) -> set[str]:
        """Get all existing ID numbers from the table for dedup."""
        base = self.config.FEISHU_BITABLE_BASE
        id_numbers = set()
        page_token = None

        while True:
            params = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token

            resp = requests.get(
                f"{base}/apps/{bitable_id}/tables/{table_id}/records",
                headers=self._headers(),
                params=params,
                timeout=30,
            )
            data = resp.json()
            if data.get("code") != 0:
                break

            items = data.get("data", {}).get("items", [])
            for record in items:
                fields = record.get("fields", {})
                id_no = fields.get("身份证号", "")
                if isinstance(id_no, list):
                    id_no = id_no[0].get("text", "") if id_no else ""
                if id_no:
                    id_numbers.add(str(id_no).strip())

            if not data.get("data", {}).get("has_more"):
                break
            page_token = data.get("data", {}).get("page_token")

        return id_numbers

    def add_records(self, bitable_id: str, table_id: str, records: list[dict]) -> int:
        """Add records to the table. Returns number of records added."""
        if not records:
            return 0

        base = self.config.FEISHU_BITABLE_BASE
        batch_size = 500
        added = 0

        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            payload = {
                "records": [{"fields": r} for r in batch],
            }
            resp = requests.post(
                f"{base}/apps/{bitable_id}/tables/{table_id}/records/batch_create",
                headers=self._headers(),
                json=payload,
                timeout=60,
            )
            data = resp.json()
            if data.get("code") != 0:
                raise Exception(f"添加记录失败: {data}")
            added += len(batch)
            print(f"[飞书] 已添加 {added}/{len(records)} 条记录")

        return added
