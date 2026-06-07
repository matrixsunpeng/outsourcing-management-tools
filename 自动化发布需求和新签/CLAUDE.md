# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

这是一个外包招聘流程自动化工具集，包含 5 个编号子项目，构成流水线作业：

| # | 子项目 | 做什么 |
|---|--------|--------|
| 1 | `1.提取申请单建多维表` | 从 IMS 抓取新签申请单 → 写入飞书多维表 |
| 2 | `2.根据多维表发布需求` | 读多维表未发布记录 → 在 TAM 网站自动发布招聘任务 |
| 3 | `3.查找需求返回职位编号` | 在 TAM 查询已发布任务 → 匹配职位编号回写多维表 |
| 4 | `4.提取人员面试评价建多维表` | 从 IMS 导出面试评价 Excel → 写入飞书多维表 |
| 5 | `5.根据人员面试评价新签` | 仅有 spec 文档，尚未实现 |

每个子项目是一个独立的工作目录，有自己的 `main.py`、依赖和配置，互不引用。

## 技术栈

- **浏览器自动化**: Playwright (Chromium, headless=False)
- **多维表操作**: 项目 1-3 使用 `lark-cli` CLI（已安装在 `C:\Users\AI\AppData\Roaming\npm\lark-cli.cmd`）；项目 4 使用飞书 REST API（`https://open.feishu.cn/open-apis/bitable/v1`）
- **Excel 解析**: `openpyxl`（.xlsx）+ `xlrd`（.xls / OLE2），通过文件头 magic bytes 检测格式
- **Word 解析**: `python-docx`
- **配置管理**: `python-dotenv`（`.env` 或 `config.env`）

## 运行命令

```bash
# 项目1：提取申请单（需在子目录下运行）
cd "1.提取申请单建多维表" && python main.py

# 项目2：发布需求（-y 自动确认，不加 -y 逐条交互确认）
cd "2.根据多维表发布需求" && python main.py -y

# 项目3：查找职位编号
cd "3.查找需求返回职位编号" && python main.py

# 项目4：提取面试评价
cd "4.提取人员面试评价建多维表" && python main.py --auto    # 全自动
cd "4.提取人员面试评价建多维表" && python main.py --file <xlsx>  # 处理已有文件
```

## 架构模式

### 共享数据流

所有子项目通过**飞书多维表**串联，数据流向为：

```
IMS 申请单 ──(1)→ 多维表"外包申请单" ──(2)→ TAM 发布 ──(3)→ 回写职位编号
IMS 面试评价 ──(4)→ 多维表"人员面试评价表" ──(5)→ (待实现)
```

关键字段：`合作申请单编号`（主键/去重锚点）、`是否发布`（状态标记）、`职位编号`（(3)的结果）、`发布时间`。

### 项目内部结构

每个子项目遵循相似的分层：
- **`main.py`** — 编排主流程（初始化 → 查询 → 处理 → 写入 → 报告）
- **`config.py` / `config.env` / `.env`** — 凭证和业务常量（字段定义、查询条件、日期范围）
- **Web 自动化模块**（`ims_scraper.py` / `web_automation.py` / `tam_login.py` / `tam_publish.py` / `tam_query.py`）— Playwright 页面操作
- **飞书操作模块**（`lark_bitable.py` / `feishu_client.py` / `feishu_query.py` / `feishu_update.py`）— 多维表 CRUD
- **数据处理模块**（`data_processor.py`）— Excel 解析、字段映射、去重

### 两种飞书 API 调用方式

- **lark-cli**（项目 1-3）：通过 `subprocess` 调用 CLI，JSON 通过临时文件（`@tmp.json`）传递以避免命令行编码问题。结果通过 stdout JSON 解析。
- **REST API**（项目 4）：直接用 `requests` 调用飞书 Open API，通过 `tenant_access_token` 认证。首次运行时自动创建多维表，将 `app_token` 写入 `.env`。

### TAM 页面操作模式

TAM 网站使用 Ant Design 组件。所有表单操作基于以下模式：
- `_find_form_item(page, label_title)` — 通过 `label[title]` 定位 `ant-form-item`
- 填写策略：普通 input 用 `fill()`，`ant-input-number` 用 JS 设值（触发 React 事件），select 用点击+下拉匹配，date 用键盘输入覆盖默认值
- 每次发布后重新导航到新建页面（`navigate_to_new_recruitment_task`），避免表单状态污染

### 去重策略

- 项目 1：按 `合作申请单编号` 去重（先读已有记录 ID 集合）
- 项目 4：按 `身份证号` 去重（先读已有记录身份证号集合）

## 配置说明

- 项目 1 用 `.env`（`IMS_USERNAME`, `IMS_PASSWORD`），首次运行生成 `bitable_config.json` 保存多维表地址
- 项目 2-3 用 `config.env`（`IMS_USERNAME`, `IMS_PASSWORD`, `BITABLE_TOKEN`, `TABLE_ID`），参考 `config.env.example`
- 项目 4 用 `.env`（`IMS_USERNAME`, `IMS_PASSWORD`, `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_BITABLE_ID`）
- 所有 Playwright 浏览器均为 `headless=False`（需要可见浏览器以便处理验证码和手动干预）
