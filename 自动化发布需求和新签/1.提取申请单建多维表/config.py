"""
配置模块：多维表字段定义、IMS 查询条件、日期计算
"""
from datetime import date, timedelta

# ==================== IMS 查询条件 ====================
QUERY_DAYS_BACK = 7
TECH_COOP_TYPE_INDEX = 2   # 下拉框第3项(0-based index 2): 技术合作-||(人员类)
APP_STATE_VALUE = "40"      # 审批流程结束 的 itemCode
SBU_VALUE = "185"           # 亚信科技CMB 的 flexValue

# ==================== 飞书多维表字段定义 ====================
# type: text=文本, number=数字, datetime=日期, checkbox=是/否
FIELDS = [
    {"field_name": "合作申请单编号", "type": "text"},
    {"field_name": "事业部/SBU", "type": "text"},
    {"field_name": "统计区域", "type": "text"},
    {"field_name": "申请人", "type": "text"},
    {"field_name": "签约性质", "type": "text"},
    {"field_name": "申请日期", "type": "datetime"},
    {"field_name": "资源池代码", "type": "text"},
    {"field_name": "审批状态", "type": "text"},
    {"field_name": "技术合作人员数量", "type": "number"},
    {"field_name": "预计技术合作时成本", "type": "text"},
    {"field_name": "技术合作服务周期开始日期", "type": "datetime"},
    {"field_name": "技术合作服务周期结束日期", "type": "datetime"},
    {"field_name": "技术合作需求明细", "type": "text"},
    {"field_name": "招聘协同专员", "type": "text"},
    {"field_name": "工作地点", "type": "text"},
    {"field_name": "要求到岗时间", "type": "text"},
    {"field_name": "岗位", "type": "text"},
    {"field_name": "工作内容", "type": "text"},
    {"field_name": "技能要求", "type": "text"},
    {"field_name": "供应商", "type": "text"},
    {"field_name": "分配人数", "type": "number"},
    {"field_name": "是否发布", "type": "text"},
    {"field_name": "职位编号", "type": "text"},
    {"field_name": "发布时间", "type": "text"},
    {"field_name": "备注", "type": "text"},
]

# 弹窗中需提取的字段映射：弹窗标签名 → 多维表字段名
POPUP_FIELD_MAP = {
    "合作申请单编号": "合作申请单编号",
    "事业部/SBU": "事业部/SBU",
    "统计区域": "统计区域",
    "申请人": "申请人",
    "签约性质": "签约性质",
    "申请日期": "申请日期",
    "资源池代码": "资源池代码",
    "审批状态": "审批状态",
    "技术合作人员数量": "技术合作人员数量",
    "预计技术合作时成本": "预计技术合作时成本",
    "技术合作服务周期开始日期": "技术合作服务周期开始日期",
    "技术合作服务周期结束日期": "技术合作服务周期结束日期",
    "技术合作需求明细": "技术合作需求明细",
    "备注": "备注",
}

TABLE_NAME = "外包申请单"

# Lark CLI 路径
LARK_CLI = r"C:\Users\AI\AppData\Roaming\npm\lark-cli.cmd"


def get_date_range():
    """返回申请时间范围: (开始日期, 结束日期)，格式 yyyy-MM-dd"""
    today = date.today()
    start = today - timedelta(days=QUERY_DAYS_BACK)
    return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def format_date_for_bitable(date_str):
    """将日期字符串转为多维表日期格式 (毫秒时间戳)"""
    if not date_str:
        return None
    from datetime import datetime
    for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"]:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return None
