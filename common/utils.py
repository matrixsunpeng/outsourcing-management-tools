"""
外包工具箱 — 共享工具函数
"""
import re
from datetime import datetime


def parse_date_input(date_str: str) -> str:
    """解析日期输入 '2025年1月1日' → '2025年01月01日'"""
    match = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日?', date_str.strip())
    if match:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        return f"{year}年{month:02d}月{day:02d}日"
    raise ValueError(f"无法解析日期: {date_str}，请使用格式如 '2025年1月1日'")


def to_iso_date(date_str: str) -> str:
    """将中文日期转为 ISO 格式 '2025年1月1日' → '2025-01-01'"""
    match = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日?', date_str.strip())
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return date_str


def parse_time_input(time_str: str):
    """解析时间输入 '2025年3月' → (2025, 3)"""
    match = re.match(r'(\d{4})年(\d{1,2})月', time_str.strip())
    if match:
        return int(match.group(1)), int(match.group(2))
    raise ValueError(f"无法解析时间: {time_str}，请使用格式如 '2025年3月'")


def parse_period_input(period_str: str):
    """解析时间段 '2024年01月~2024年12月' → ('2024年01月', '2024年12月')"""
    cn_pattern = r'(\d{4})年(\d{1,2})月\s*[~至\-]\s*(\d{4})年(\d{1,2})月'
    match = re.search(cn_pattern, period_str)
    if match:
        sy, sm, ey, em = match.groups()
        return f"{sy}年{int(sm):02d}月", f"{ey}年{int(em):02d}月"
    short_pattern = r'(\d{4})-(\d{2})\s*[~至\-]\s*(\d{4})-(\d{2})'
    match = re.search(short_pattern, period_str)
    if match:
        sy, sm, ey, em = match.groups()
        return f"{sy}年{sm}月", f"{ey}年{em}月"
    raise ValueError(f"无法解析时间段: {period_str}，请使用格式如 '2024年01月~2024年12月'")


def parse_quarter_input(quarter_str: str) -> str:
    """解析季度 '202601' → 标准化为 '202601'"""
    quarter_str = quarter_str.strip()
    match = re.match(r'(\d{4})(0?[1-4])', quarter_str)
    if match:
        return f"{match.group(1)}0{int(match.group(2))}"
    match_wrong = re.match(r'(\d{4})(\d{2})', quarter_str)
    if match_wrong:
        q = int(match_wrong.group(2))
        if q > 4:
            raise ValueError(f"季度只能是01-04，输入为{q}。正确示例: 202601")
    raise ValueError(f"无法解析季度: {quarter_str}，请使用格式如 '202601'")


def now_timestamp() -> str:
    """返回当前时间戳字符串 YYYYMMDD_HHMMSS"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")
