# 资源池预算修改工具 v2

根据 Excel 数据自动登录 IMS 系统，批量修改资源池的年化人数预算和年度费用预算。

## 安装

```bash
pip install playwright pandas openpyxl
playwright install chromium
```

## 准备工作

1. 编辑 `资源池预算.xlsx`，包含以下列：
   - `资源池代码` — 要修改的资源池编号
   - `年化人数预算` — 目标年化人数
   - `年度费用预算（元）` — 目标年度费用

2. 确认账号有"资源池设立"页面的访问权限

## 使用

```bash
# 交互式运行
python resource_pool_updater.py

# 命令行运行
python resource_pool_updater.py -u 用户名 -p 密码

# 隐藏浏览器（无头模式）
python resource_pool_updater.py -u 用户名 -p 密码 --headless
```

### 参数

| 参数 | 说明 |
|------|------|
| `-u, --username` | 登录用户名 |
| `-p, --password` | 登录密码 |
| `--headless` | 隐藏浏览器（无头模式） |

## 功能流程

1. 读取 Excel 数据 → 登录 IMS
2. 导航到"资源池" → "资源池管理" → "资源池设立"
3. 逐条处理：
   - 输入资源池代码 → 查询
   - JS 触发编辑按钮（绕过 layui-table-fixed-r 遮挡问题）
   - 在编辑弹窗 iframe（URL 含 `editPoolDetail`）中修改两个字段
   - 点击"发布"按钮保存
4. 失败后自动重新导航，截图保存到工具目录

## 关键点

- **编辑按钮遮挡问题**：layui 表格的固定列（`layui-table-fixed-r`）会遮挡编辑按钮，通过 `dispatchEvent(MouseEvent)` 绕过
- **编辑弹窗是 layer.open iframe**：需要扫描所有 frame 找到 `editPoolDetail` URL
- **字段 ID**：年化人数预算 = `input#yearHc`，年度费用预算 = `input#yearExpenses`
- 每次修改前后自动截图（`before_save_{code}.png` / `after_save_{code}.png`）
