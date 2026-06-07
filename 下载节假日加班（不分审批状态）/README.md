# 节假日加班下载工具

自动从 IMS 系统下载节假日加班查询报表（Layui 框架页面）。

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
python holiday_overtime_downloader.py

# 命令行运行
python holiday_overtime_downloader.py -u 用户名 -p 密码 \
  -s "CMB,CTC" --start "2025年1月1日" --end "2025年12月31日"

# 隐藏浏览器（无头模式）
python holiday_overtime_downloader.py --headless
```

### 参数

| 参数 | 说明 |
|------|------|
| `-u, --username` | 登录用户名 |
| `-p, --password` | 登录密码 |
| `-s, --sbu` | SBU 列表（逗号分隔），不填=全部 |
| `--start` | 开始日期 |
| `--end` | 结束日期 |
| `-d, --download-dir` | 下载目录 |
| `--headless` | 隐藏浏览器（无头模式） |

## 功能流程

1. 登录 IMS → "外包数据查询" → "节假日加班查询"
2. 选择 BU（Layui select 元素 `id="bu"`，支持模糊匹配）
3. 输入节假日范围（日期输入框 `id="beg"` / `id="end"`，通过 JS 设值避免弹出层遮挡）
4. 查询 → 导出按钮在 `.layui-table-tool` 工具栏内

## 注意

- 使用 Layui 框架（非 MiniUI），日期输入后需手动移除 `.layui-laydate` 弹出层
- 导出按钮位于 Layui 表格工具栏 `.layui-table-tool a:has-text('导出')`
