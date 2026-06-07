# 绩效考核下载工具

自动从 IMS 系统下载 KPI 绩效考核报表（Layui 框架页面）。

## 安装

```bash
pip install playwright
playwright install chromium
```

## 配置

编辑 `config.py`，填入账号密码：

```python
USERNAME = "your_username"
PASSWORD = "your_password"
DOWNLOAD_DIR = "./downloads"
```

## 使用

```bash
# 交互式运行
python kpi_performance_downloader.py

# 命令行运行 - 按季度和 BU 组合下载
python kpi_performance_downloader.py -u 用户名 -p 密码 \
  -q "202601,202602" -b "121,CTC" --debug

# 隐藏浏览器（无头模式）
python kpi_performance_downloader.py --headless
```

### 参数

| 参数 | 说明 |
|------|------|
| `-u, --username` | 登录用户名 |
| `-p, --password` | 登录密码 |
| `-q, --quarter` | 季度列表（逗号分隔），格式 `YYYY0Q`，如 `202601`=2026Q1 |
| `-b, --bu` | BU 列表（逗号分隔），支持代码如 `121` 或名称如 `CTC` |
| `-d, --download-dir` | 下载目录 |
| `--headless` | 隐藏浏览器（无头模式） |
| `--debug` | 调试模式，输出页面 HTML 片段 |

## 功能流程

1. 登录 IMS → "KPI绩效考核" → "KPI查询" → "绩效考核查询"
2. 需要展开两级菜单（双击 KPI绩效考核 → 双击 KPI查询）
3. 按季度 × BU 双重循环组合查询和下载
4. 季度和 BU 都是 Layui select 控件

## 注意

- 季度格式：`YYYY0Q`（如 `202601` = 2026 年第 1 季度，Q 值只能是 01-04）
- BU 选择支持：精确值匹配 → 模糊文本匹配 → 括号内代码匹配（如 `(185)亚信科技CMB`）
- 此页面使用 Layui 框架，非 MiniUI
