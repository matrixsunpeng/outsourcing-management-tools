# 外包人员变更下载工具

自动从 IMS 系统下载外包人员变更报表。

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
python personnel_change_downloader.py

# 命令行运行
python personnel_change_downloader.py -u 用户名 -p 密码 \
  -s "CMB,CTC" --start "2025年1月1日" --end "2025年12月31日"

# 隐藏浏览器（无头模式）
python personnel_change_downloader.py --headless
```

### 参数

| 参数 | 说明 |
|------|------|
| `-u, --username` | 登录用户名 |
| `-p, --password` | 登录密码 |
| `-s, --sbu` | SBU 列表（逗号分隔），不填=全部 |
| `--start` | 开始日期，格式 `YYYY年MM月DD日` |
| `--end` | 结束日期 |
| `-d, --download-dir` | 下载目录，默认 `./downloads` |
| `--headless` | 隐藏浏览器（无头模式） |

## 功能流程

1. 登录 IMS → 导航到"外包数据查询" → "外包人员变更"
2. 选择 SBU、填写申请期间、多选单据状态（审批流程中/审批流程结束/待确认到岗中）
3. 查询 → 导出 Excel → 自动重命名保存
