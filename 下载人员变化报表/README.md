# 技术合作人员变化表下载工具

自动下载 IMS 系统中的技术合作人员变化表。

## 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

## 配置

编辑 `config.py` 文件，填写登录账号和密码：

```python
USERNAME = "your_username"
PASSWORD = "your_password"
DOWNLOAD_DIR = "./downloads"
```

## 使用方法

### 交互式运行

```bash
python tech_personnel_change_downloader.py
```

程序会依次提示输入：
1. 用户名（如果 config.py 中未配置）
2. 密码（如果 config.py 中未配置）
3. SBU（多个用逗号分隔，直接回车不输入表示查询全部）
4. 人员状态（多个用逗号分隔，直接回车不输入表示查询全部）
5. 开始日期（格式：XXXX年XX月XX日）
6. 结束日期（格式：XXXX年XX月XX日）

### 命令行参数运行

```bash
python tech_personnel_change_downloader.py -u 用户名 -p 密码 -s "SBU1,SBU2" --status "状态1,状态2" --start "2025年1月1日" --end "2025年3月27日"
```

参数说明：
- `-u, --username`: 登录用户名
- `-p, --password`: 登录密码
- `-s, --sbu`: SBU 列表（逗号分隔）
- `--status`: 人员状态列表（逗号分隔）
- `--start`: 开始日期
- `--end`: 结束日期
- `-d, --download-dir`: 下载目录
- `--headless`: 隐藏浏览器（无头模式）

## 功能说明

1. 自动登录 IMS 系统
2. 导航到"外包报表" → "技术合作人员变化表"
3. 按 SBU 和人员状态组合依次查询和下载
4. 导出的 Excel 文件命名格式：`技术合作人员变化表_{SBU}_{人员状态}_{开始日期}_{结束日期}_{时间戳}.xlsx`
