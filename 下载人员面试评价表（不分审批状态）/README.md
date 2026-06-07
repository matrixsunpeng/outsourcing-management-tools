# 人员面试评价表下载工具

自动从 IMS 系统下载人员面试评价表（Layui 框架页面）。

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
python interview_evaluation_downloader.py

# 命令行运行
python interview_evaluation_downloader.py -u 用户名 -p 密码 \
  -s "CMB,CTC" --start "2025年1月1日" --end "2025年12月31日"

# 隐藏浏览器（无头模式）
python interview_evaluation_downloader.py --headless
```

### 参数

| 参数 | 说明 |
|------|------|
| `-u, --username` | 登录用户名 |
| `-p, --password` | 登录密码 |
| `-s, --bu` | BU 列表（逗号分隔），不填=全部 |
| `--start` | 开始日期，格式 `YYYY年MM月DD日` |
| `--end` | 结束日期 |
| `-d, --download-dir` | 下载目录 |
| `--headless` | 隐藏浏览器（无头模式） |

## 功能流程

1. 登录 IMS → "招聘过程管理" → "人员面试评价表"
2. 支持新标签页和 iframe 两种打开方式
3. 选择 BU（Layui select）、填写申请期间（日期输入框 id=beg/end）
4. 查询 → 导出 → 自动重命名保存

## 注意

此页面使用 Layui 框架（非 MiniUI），日期控件需要手动移除弹出层防止遮挡。
