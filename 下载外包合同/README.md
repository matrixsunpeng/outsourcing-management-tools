# 外包合同下载工具

自动从 IMS 系统下载外包合同报表。

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
python contract_downloader.py

# 命令行运行
python contract_downloader.py -u 用户名 -p 密码 \
  -s "CMB,CTC" --start "2025年1月1日" --end "2025年12月31日"

# 隐藏浏览器（无头模式）
python contract_downloader.py --headless
```

### 参数

| 参数 | 说明 |
|------|------|
| `-u, --username` | 登录用户名 |
| `-p, --password` | 登录密码 |
| `-s, --sbu` | SBU 列表（逗号分隔），不填=全部 |
| `--start` | 开始日期，格式 `YYYY年MM月DD日` |
| `--end` | 结束日期 |
| `-d, --download-dir` | 下载目录 |
| `--headless` | 隐藏浏览器（无头模式） |

## 功能流程

1. 登录 IMS → "外包数据查询" → "外包合同"
2. 每条 SBU 处理后清空表单（`_clear_form`），防止条件串扰
3. 条件：SBU + 申请期间 + 技术合作种类（人员类）+ 单据状态多选
4. 点击"导出合同" → 下载等待最长 3 分钟

## 注意

- 导出按钮显示为"导出合同"（非"导出Excel"）
- 全量查询数据量大，下载超时设为 180s
- 新标签页和 iframe 使用不同的下载上下文
