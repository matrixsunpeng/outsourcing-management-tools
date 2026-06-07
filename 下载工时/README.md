# 工时报表下载工具

自动化下载工时报表的工具，使用 Playwright 实现网页自动化操作。

## 安装

```bash
# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器
playwright install chromium
```

## 使用方法

### 方式一：命令行运行

```bash
# 基本用法（交互式输入用户名密码）
python work_hours_downloader.py

# 指定参数运行
python work_hours_downloader.py -u 用户名 -p 密码 -P "2024年01月~2024年12月"

# 指定下载目录
python work_hours_downloader.py -d "D:/报表下载"

# 隐藏浏览器（无头模式）
python work_hours_downloader.py --headless
```

### 方式二：作为模块导入使用

```python
from work_hours_downloader import WorkHoursDownloader

# 方式1：使用上下文管理器（自动管理浏览器生命周期）
with WorkHoursDownloader(
    username="your_username",
    password="your_password",
    download_dir="./downloads"
) as downloader:
    result = downloader.download_work_hours_report(period="2024年01月~2024年12月")
    print(f"下载文件: {result}")

# 方式2：手动管理
downloader = WorkHoursDownloader(
    username="your_username",
    password="your_password",
    headless=True  # True=后台运行，False=显示浏览器
)
downloader.start()
try:
    result = downloader.download_work_hours_report(
        period="2024年01月~2024年12月",
        start_browser=False  # 已经手动启动了浏览器
    )
finally:
    downloader.stop()
```

## 参数说明

| 参数 | 说明 |
|------|------|
| `username` | 登录用户名 |
| `password` | 登录密码 |
| `download_dir` | 下载文件保存目录，默认 `./downloads` |
| `headless` | 是否后台运行，默认 `True` |
| `period` | 查询时间段，支持格式：`2024年01月~2024年12月` 或 `2024-01~2024-12` |

## 自定义修改

如果网页结构发生变化，可以修改 `WorkHoursDownloader.SELECTORS` 字典中的选择器配置。

## 注意事项

1. 首次运行需要安装 Playwright 浏览器：`playwright install chromium`
2. 时间段格式需要与网页下拉选项匹配
3. 如果遇到问题，浏览器默认可见，如需隐藏可加 `--headless`
