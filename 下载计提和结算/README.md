# 计提与结算下载工具

自动从 IMS 系统下载费用结算单计提与结算金额查询报表（MiniUI 框架页面）。

## 安装

```bash
pip install -r requirements.txt
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
python settlement_downloader.py

# 命令行运行
python settlement_downloader.py -u 用户名 -p 密码 \
  -s "CMB,CTC" --start "2025年1月" --end "2025年12月"

# 隐藏浏览器（无头模式）
python settlement_downloader.py --headless
```

### 参数

| 参数 | 说明 |
|------|------|
| `-u, --username` | 登录用户名 |
| `-p, --password` | 登录密码 |
| `-s, --sbu` | SBU 列表（逗号分隔），不填=全部 |
| `--start` | 开始时间，格式 `YYYY年MM月` |
| `--end` | 结束时间 |
| `-d, --download-dir` | 下载目录，默认 `./downloads` |
| `--headless` | 隐藏浏览器（无头模式） |

## 功能流程

1. 登录 IMS → "外包数据查询" → "费用结算单计提与结算金额查询"
2. 在 iframe 内通过标签文本定位 combobox（SBU、服务类型=人员类）
3. 月份范围通过定位"月份范围"标签所在行找到两个输入框，直接输入 `YYYY-MM` 格式
4. 查询 → 导出（按钮文本为"导出Excel"）

## 注意

- `_select_combobox_option()` 使用遍历策略：先通过标签定位关联 combobox，失败则逐一打开检查选项
- 每个 combobox 操作后需等待 800ms 让弹窗完全关闭，否则会干扰下一个 combobox 的点击
- 日期输入通过 `.type()` 逐字符输入 + `dispatch_event("blur")` 触发 MiniUI 识别
