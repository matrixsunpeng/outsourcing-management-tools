import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # IMS credentials
    IMS_USERNAME = os.getenv("IMS_USERNAME", "")
    IMS_PASSWORD = os.getenv("IMS_PASSWORD", "")

    # IMS URLs
    IMS_LOGIN_URL = "https://ims.asiainfo.com/AIOMS/Jsp/main.jsp"

    # Feishu credentials
    FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
    FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
    FEISHU_BITABLE_ID = os.getenv("FEISHU_BITABLE_ID", "")

    # Feishu API
    FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    FEISHU_BITABLE_BASE = "https://open.feishu.cn/open-apis/bitable/v1"

    # Download
    DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "./downloads")

    # Query defaults: last N days
    QUERY_DAYS_BACK = 7
    QUERY_STATUS = "审批通过"
    QUERY_BU = os.getenv("QUERY_BU", "(185)亚信科技CMB")

    # Allowed suppliers (fuzzy match)
    ALLOWED_SUPPLIERS = [
        "江苏迈特望",
        "西安万德富",
        "万联",
        "人瑞人才",
        "科之锐",
    ]

    # Bitable fields definition
    BITABLE_NAME = "人员面试评价表"
    BITABLE_FIELDS = [
        {"field_name": "需求编号/合作申请单编号", "type": 1},  # 1=文本
        {"field_name": "项目名称", "type": 1},
        {"field_name": "公司/签约方", "type": 1},
        {"field_name": "创建时间", "type": 5},  # 5=日期
        {"field_name": "BU/SBU", "type": 1},
        {"field_name": "大区", "type": 1},
        {"field_name": "姓名", "type": 1},
        {"field_name": "身份证号", "type": 1},
        {"field_name": "供应商/外包商", "type": 1},
        {"field_name": "角色", "type": 1},
        {"field_name": "学历", "type": 1},
        {"field_name": "工作地", "type": 1},
        {"field_name": "工资", "type": 2},  # 2=数字
        {"field_name": "确认定级", "type": 1},
        {"field_name": "每月标准单价", "type": 2},
        {"field_name": "预计工作开始时间", "type": 5},
        {"field_name": "校正上岗时间", "type": 5},  # 外包商填写
        {"field_name": "外包商联系人", "type": 1},  # 人员类型用文本简化
        {"field_name": "是否签署", "type": 1},  # 是/否
        {"field_name": "技术合作订单编号", "type": 1},
        {"field_name": "未成功提交原因", "type": 1},
    ]

    # Mapping: Excel column name → Bitable field name
    EXCEL_TO_BITABLE_MAP = {
        "需求编号": "需求编号/合作申请单编号",
        "合作申请单编号": "需求编号/合作申请单编号",
        "项目名称": "项目名称",
        "公司": "公司/签约方",
        "签约方": "公司/签约方",
        "创建时间": "创建时间",
        "BU": "BU/SBU",
        "SBU": "BU/SBU",
        "大区": "大区",
        "姓名": "姓名",
        "身份证": "身份证号",
        "身份证号": "身份证号",
        "外包商": "供应商/外包商",
        "供应商": "供应商/外包商",
        "角色": "角色",
        "学历": "学历",
        "工作地": "工作地",
        "工资": "工资",
        "确认定级": "确认定级",
        "每月标准单价": "每月标准单价",
        "预计工作开始时间": "预计工作开始时间",
    }

    # Fields that should be converted to date format
    DATE_FIELDS = {"创建时间", "预计工作开始时间", "校正上岗时间"}

    # Fields that should be converted to number format
    NUMBER_FIELDS = {"工资", "每月标准单价"}

    @classmethod
    def validate(cls):
        errors = []
        if not cls.IMS_USERNAME:
            errors.append("IMS_USERNAME 未配置")
        if not cls.IMS_PASSWORD:
            errors.append("IMS_PASSWORD 未配置")
        if not cls.FEISHU_APP_ID:
            errors.append("FEISHU_APP_ID 未配置")
        if not cls.FEISHU_APP_SECRET:
            errors.append("FEISHU_APP_SECRET 未配置")
        return errors
