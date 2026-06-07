# 自动发布需求

外包招聘流程自动化工具集，包含 5 个编号子项目，通过飞书多维表串联成流水线。

## 子项目概览

| # | 目录 | 功能 | 输入 | 输出 |
|---|------|------|------|------|
| 1 | `1.提取申请单建多维表` | IMS 抓取新签申请单 → 写入飞书多维表 | IMS 申请单页面 | 多维表"外包申请单" |
| 2 | `2.根据多维表发布需求` | 读多维表 → TAM 网站发布招聘任务 | 多维表记录 | TAM 发布结果 |
| 3 | `3.查找需求返回职位编号` | TAM 查询已发布任务 → 回写职位编号 | TAM 任务列表 | 职位编号回写 |
| 4 | `4.提取人员面试评价建多维表` | IMS 导出面试评价 → 写入飞书多维表 | IMS 面试评价 Excel | 多维表"人员面试评价表" |
| 5 | `5.根据人员面试评价新签` | 仅有 spec 文档，尚未实现 | - | - |

## 技术栈

- **浏览器自动化**: Playwright (Chromium, headless=False)
- **多维表**: 项目 1-3 用 `lark-cli` CLI；项目 4 用飞书 REST API
- **Excel**: `openpyxl` (.xlsx) + `xlrd` (.xls)，通过文件头 magic bytes 检测格式
- **配置**: `python-dotenv` (.env 或 config.env)

## 数据流

```
IMS 申请单 ──(1)→ 多维表"外包申请单" ──(2)→ TAM 发布 ──(3)→ 回写职位编号
IMS 面试评价 ──(4)→ 多维表"人员面试评价表" ──(5)→ (待实现)
```

## 运行

```bash
# 项目1：提取申请单
cd "1.提取申请单建多维表" && python main.py

# 项目2：发布需求（-y 自动确认）
cd "2.根据多维表发布需求" && python main.py -y

# 项目3：查找职位编号
cd "3.查找需求返回职位编号" && python main.py

# 项目4：提取面试评价
cd "4.提取人员面试评价建多维表" && python main.py --auto
cd "4.提取人员面试评价建多维表" && python main.py --file <xlsx>
```

## 每个子项目的内部结构

- `main.py` — 编排主流程
- `config.py` / `.env` — 凭证和业务常量
- Web 自动化模块 — Playwright 页面操作
- 飞书操作模块 — 多维表 CRUD
- 数据处理模块 — Excel 解析、字段映射、去重

## 配置说明

- 项目 1: `.env`（`IMS_USERNAME`, `IMS_PASSWORD`），首次运行生成 `bitable_config.json`
- 项目 2-3: `config.env`（含 `BITABLE_TOKEN`, `TABLE_ID`），参考 `config.env.example`
- 项目 4: `.env`（含 `FEISHU_APP_ID`, `FEISHU_APP_SECRET`）

## 注意

- 所有项目 Playwright 均为 `headless=False`，需要可见浏览器处理验证码
- 去重策略：项目 1 按"合作申请单编号"，项目 4 按"身份证号"
- 项目 1-3 使用 lark-cli 时 JSON 通过临时文件传递（`@tmp.json`），避免命令行编码问题
