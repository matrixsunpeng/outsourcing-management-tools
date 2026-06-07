# 外包预算滚动预测

一键式预算管控仪表盘：下载数据 → 合并 → 生成交互式 HTML 仪表盘。

## 安装

```bash
pip install pandas openpyxl
playwright install chromium
```

## 数据源

工具依赖以下 Excel 文件（需提前准备）：

| 文件 | 说明 |
|------|------|
| `26年全面预算.xlsx` | 年度预算数据（BU + 费用 + HC） |
| `费用结算单计提与结算金额查询.xlsx` | 计提结算实际成本 |
| `技术合作订单查询报表.xlsx` | 订单明细（用于计算在岗人数和续签预测） |
| `26年继续投入.xlsx` | 继续投入/实习生转外包计划 |
| `资源池列表.xls` | 资源池预算和HC数据 |
| `滚动预测update.xlsx` | Excel 导出模板（复制样式用） |

## 使用

```bash
# 一键更新（启动交互式菜单）
python run_budget_update.py

# 或双击
run_budget_update.bat
```

交互菜单提供 5 种模式：
1. 下载计提与结算 + 合并 + 生成仪表盘
2. 下载外包合同 + 合并 + 生成仪表盘
3. 两个都下载 + 合并 + 生成
4. 仅合并数据 + 生成（不下载）
5. 仅生成仪表盘（用现有数据）

## 输出

- `dashboard.html` — 交互式仪表盘，包含 BU 分析卡片、明细数据（实际/续签/投入三页签）、资源池明细（可展开）
- `滚动预测_YYYYMMDD.xlsx` — 滚动预测 Excel，按锚点时间切割实际/预测

## 架构

```
run_budget_update.py          # 一键更新脚本（编排层）
  ├─ settlement/settlement_downloader.py  # 下载计提结算
  ├─ contract/contract_downloader.py      # 下载外包合同
  ├─ merge_data.py            # 数据合并
  └─ generate_dashboard.py    # 仪表盘生成
       ├─ 读取 6 个 Excel 数据源
       ├─ 计算：实际发生 / 预测续签 / 继续投入
       ├─ 生成 dashboard.html（内嵌 JSON 数据 + JS 渲染）
       └─ export_rolling_forecast() 导出 Excel
```

## 注意

- 所有脚本路径均使用相对路径，模块可整体迁移到其他目录
- 仪表盘页面内嵌了 SheetJS CDN（导出 Excel 用）和 Google Fonts CDN
- 续签预测口径：锚点当天在岗（工作开始 ≤ 锚点 ≤ 工作结束）的人员逐月计算费用
