# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

外包续签自动下单工具。自动化三个环节：从企业系统（IMS/MiniUI 框架）下载报表 → 筛选生成待办清单 → 在外包合同页面逐条填表下单提交审批。

目标系统: `https://ims.asiainfo.com/AIOMS/Jsp/main.jsp`（MiniUI 组件库）。

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 完整流程（下载 → 清单 → 下单），浏览器默认可见
python main.py --start "2026年6月1日" --end "2026年6月30日" --sbu "CMB"

# 仅下载并生成清单（不执行下单）
python main.py --start "2026年6月1日" --end "2026年6月30日" --sbu "CMB" --audit-date "2026-06-30" --download-only

# 仅处理已有待办清单（含离岗不续签人员删除）
python main.py --process-only 待办订单清单_xxx.xlsx --not-renewing-file 离岗不续签清单_xxx.xlsx

# 断点续跑（跳过已有反馈的记录）
python main.py --process-only 待办订单清单_已处理_xxx.xlsx --resume

# 如需要后台运行，加 --headless

# 交互式启动
python quick_start.py
```

## 架构

```
main.py                     # 主入口，argparse 解析，编排三种运行模式
  ├─ download_and_parse.py  # DownloadAndParseManager：下载编排层
  │    ├─ 下载外包续签查询/renewal_query_downloader.py  # RenewalQueryDownloader：续签查询报表下载
  │    ├─ 下载外包续签查询/application_form_downloader.py # ApplicationFormDownloader：申请单下载（新增）
  │    └─ utils/excel_parser.py  # ExcelParser：Excel 解析、过滤、清单生成
  └─ renewal_order_processor.py # RenewalOrderProcessor：逐条下单流程编排
       └─ renewal_order_submitter.py  # OutsourceContractSubmitter：外包合同页面交互层
```

**数据流**: 下载3个报表（续签查询 + 申请单 + 人员变更）→ 解析/过滤 → 生成待办清单 + 离岗不续签清单 → 逐条登录外包合同页面填表下单 → 输出已处理清单。

## 核心类与职责

### `ExcelParser` (utils/excel_parser.py)
- `load_and_filter(file_path, valid_app_nos=None)` — 加载原始续签查询 Excel，按4个条件筛选：待续签申请单非空、单据状态=审批流程结束、离职时间为空、申请单号在 valid_app_nos 中（可选）。
- `generate_todo_list(filtered_df)` — 复制 DataFrame 并增加"反馈"列。
- `parse_application_form(file_path)` — 解析申请单 Excel（第2行为表头），提取"合作申请单编号"集合。
- `load_personnel_change(file_path)` / `filter_personnel_not_renewing(df, audit_date)` — 人员变更报表加载与离岗不续签筛选（预计离岗时间在稽核时间前20天范围内）。
- `_save_with_idcard_as_text(df, output_file)` — 用 openpyxl 保存，身份证列设 Text 格式防止科学计数法。

### `DownloadAndParseManager` (download_and_parse.py)
- `execute_full_pipeline()` — 完整下载→解析→双清单生成流程。步骤：下载续签查询 → 为申请单单独启动浏览器下载 → 解析生成待办清单 → 下载人员变更 → 生成离岗清单。
- `_calculate_app_form_date_range(end_date)` — 申请单的申请时间：结束时间 ~ 结束时间前30天。
- `_calculate_personnel_date_range(end_date)` — 人员变更申请时间：结束时间 ~ 结束时间前2个月。

### `OutsourceContractSubmitter` (renewal_order_submitter.py)
~4400行，核心交互层。关键方法：
- `process_single_order(vendor_name, app_no, work_location, not_renewing_df, signing_party)` — 单条订单完整流程：新增→选技术合作商→搜索申请单→**填签约方**→填工作地点→删不续签人员→计算成本→提交审批→返回列表。
- `search_application(app_no)` — 定位"合作申请单编号"输入框，先尝试直接输入触发加载，失败了则打开弹框查询。弹框检测通过 `detect_popup_context()` JS 扫描 `.mini-window/.mini-popup` 实现。
- `select_vendor(vendor_name)` — 定位"技术合作商名称"输入框，输入后等待下拉选择匹配项。
- `fill_signing_party(signing_party)` — 定位"签约方"控件并选择（新增方法）。
- `delete_personnel_by_id_card(id_card_list)` — 扫描所有 frame 找人员 datagrid，按身份证号勾选→删除。
- `calculate_cost()` — 点击计算成本，轮询等待 `p_order_amount` 回填（最多30秒），检测弹窗（HC不足等）并点取消。

### `ApplicationFormDownloader` (下载外包续签查询/application_form_downloader.py)
申请单页面下载器。外部 `start()` + `login()` 后传入 page 对象。关键：
- `navigate_to_application_form()` — 左侧树：双击"外包数据查询" → 单击"申请单"。
- `_query_and_export()` — 填写4个查询条件：申请时间（两个日期输入框）、技术合作种类（`p_coop_type`，click→下拉→选"技术合作-||"）、单据状态（`p_app_state`，click→下拉→选"审批流程结束"）、SBU（`p_sbu_id`，文本匹配）。
- `_select_combobox_by_click(control_id, match_text, fallback_index)` — 核心方法：点击 buttonedit 按钮打开下拉 → 等待 `.mini-listbox-item` 出现 → 文本匹配或索引选择。

### `RenewalQueryDownloader` (下载外包续签查询/renewal_query_downloader.py)
续签查询报表下载器。独立管理浏览器生命周期（`start()`/`stop()`）。通过 `_select_miniui_combobox` 使用 MiniUI API `combo.setValue()` 选择 SBU，`_input_date_range` 填写日期，点击查询后点"导出待续签人员"。

## 关键模式与注意事项

### MiniUI 控件交互
- **combobox 普通类型**：可用 `mini.get(id).setValue(val)` 设置值（如 p_sbu_id）。
- **buttonedit+combobox+popupedit 类型**（如 p_coop_type、p_app_state）：`setValue()` 不触发 UI 更新，必须用 click→等下拉→点击选项的方式。使用 `_select_combobox_by_click()`。
- 日期控件：尝试常见 ID 列表（`p_apply_begin_date` 等），回退到 DOM 标签匹配找相邻 input。

### 待办清单空 DataFrame 陷阱
当 `filtered_df` 为0行时，对其做 `filtered_df[column].apply(...)` 再用于布尔索引会**同时清空所有列**（pandas 2.2.3 复现）。必须加 `len(filtered_df) > 0` 守卫。参见 `excel_parser.py` load_and_filter 中条件4的实现。

### 浏览器生命周期
- `RenewalQueryDownloader.download_renewal_reports(start_browser=True)` 自行管理浏览器启停。
- 申请单下载和人员变更下载各自独立启动浏览器（通过 `self.downloader.start()` / `login()` / `stop()`）。
- 下单流程在 `RenewalOrderProcessor.execute_full_flow()` 中统一管理浏览器。

### 页面 frame/tab 切换
左侧树菜单点击后可能打开新标签页（`expect_page`）或嵌入 iframe。所有导航代码都需要处理两种分支：先尝试 `expect_page`，超时后回退到 frame 扫描（URL 关键词匹配或取最后一个非 main frame）。

### 下单页面串单校验
`OutsourceContractSubmitter` 在 `search_application` 成功后会记录表单快照（`_remember_current_form`），后续操作前校验页面一致性（`_snapshot_consistent`），防止操作串到上一条记录。

### 计算成本异步等待
`calculate_cost()` 分两阶段轮询：阶段A等 `changeOrderAmount` 出现（前端已响应），阶段B等 `p_order_amount` 出现（框架异步完成，服务器校验用此字段）。最多等30秒，超时后手动尝试将 orderAmount 写入 p_order_amount。

## 配置

- 账号密码: `下载外包续签查询/config.py`（USERNAME, PASSWORD）
- 下载目录: DOWNLOAD_DIR（默认 `./downloads`）
- 依赖: pandas, openpyxl, playwright
- 外部模块依赖（未包含在本项目中）: `F:\CodeBuddy\下载人员变更\personnel_change_downloader.py`

## 输出文件

| 文件 | 说明 |
|------|------|
| `待办订单清单_YYYYMMDD_HHMMSS.xlsx` | 筛选后的待办记录（含反馈列） |
| `待办订单清单_已处理_YYYYMMDD_HHMMSS.xlsx` | 下单完成后的结果文件 |
| `离岗不续签清单_YYYYMMDD_HHMMSS.xlsx` | 即将离岗无需续签的人员清单 |
| `logs/` | 日志输出目录 |
| `downloads/` | 下载的原始报表 |

## 多 SBU 数据合并规则

当 `--sbu "CMB,CUC"` 传入多个 SBU 时，三种报表各产生 N 个独立文件（每个 SBU 一个）。最终清单必须跨文件合并：

| 清单 | 合并方式 | 去重键 |
|------|----------|--------|
| 待办订单清单 | `pd.concat` → `drop_duplicates` | `合作申请单编号` |
| 离岗不续签清单 | `pd.concat` → `drop_duplicates` | `身份证号`（同人保留离岗时间最迟的） |
| 申请单过滤集 | `set.update` 取并集 | `合作申请单编号`（set 天然去重） |

实现位置：`download_and_parse.py` 的 `execute_full_pipeline()`。

## 申请单下载多 SBU 的标签页管理

`ApplicationFormDownloader.download_application_form()` 每轮开始前必须：
1. 关闭上一轮打开的标签页（`self._query_target.close()`）
2. 重置 `_query_target = None` / `_query_is_tab = False`
3. `_query_and_export` 开头执行 `location.reload()` 强制刷新

否则 MiniUI 控件（尤其是 `p_app_state`）可能残留上一条 SBU 的状态，导致"单据状态"未选中。

`p_app_state` 选择有双重保险：先用 `_select_combobox_by_click`（点击方式），失败则回退到 `_select_combobox_by_text`（MiniUI API）。

## quick_start.py 与 main.py 的接口契约

`quick_start.py` 负责收集所有参数并拼成命令行传给 `main.py`。关键约定：
- `--username` / `--password` / `--sbu` 必须始终出现在命令中，即使值为空（`--sbu ""` 表示全部 SBU）
- `main.py` 用 `args.sbu is not None` 区分"显式传空=全部"和"未提供=交互询问"
- `main.py` 在 `args.username or input(...)` 处处理凭据：命令行已传则跳过询问
- 不加 `--headless`，浏览器默认可见

## Playwright 下载：禁止设置 downloads_path

无论是 `launch()` 还是 `new_context()` 都**不要**传 `downloads_path`。原因：
- 参数位置因 Playwright 版本而异，`launch()` 和 `new_context()` 的支持情况不一致
- 一旦设置，Chromium 可能在当前工作目录写入 UUID 命名的临时文件

正确的下载处理只需：
```python
context = browser.new_context(accept_downloads=True)
# ...
with page.expect_download(timeout=180000) as download_info:
    export_btn.click()
download = download_info.value
download.save_as(target_path)
download.delete()  # 清理 Playwright 内部临时文件
```

流程末尾有兜底清理：扫描工作目录删除 UUID 格式命名的残留文件（`download_and_parse.py`）。

## gui_app.py — 图形化工作界面

`gui_app.py` 替代 `quick_start.py` 的终端交互，提供 tkinter GUI 表单 + 实时日志输出。双击即可运行。

### 架构

```
gui_app.py (tkinter 主线程)
  ├─ 参数表单（模式选择 / 凭据 / 日期 / SBU / 选项 / 文件路径）
  ├─ subprocess.Popen("python -u main.py ...")
  │     ├─ _read_output() 线程：stdout.read(4096) → 解码 → queue.Queue
  │     └─ _wait_process() 线程：等待进程结束
  ├─ _drain_log_queue()：主线程 root.after(80ms) 定时排空队列 → 更新 ScrolledText
  └─ 确认对话框：检测 main.py "是否继续？(y/n)" 提示 → messagebox.askyesno → 写 stdin
```

### 子进程实时日志的五个坑（2026-06-10 ~ 2026-06-11）

**坑1：stdout 全缓冲（日志堆积到进程结束才显示）**

Python 检测到 stdout 是管道（非终端）时，自动切换到 8KB 全缓冲模式。`logging.StreamHandler` 虽每次 `emit()` 后调 `flush()`，但 C 层缓冲不受影响。

解决三管齐下：
- 命令行加 `-u` 参数：`python -u main.py ...`
- 环境变量 `PYTHONUNBUFFERED=1`
- `subprocess.Popen` 用二进制模式 `bufsize=0`（跳过 TextIOWrapper 额外缓冲层），手动 `decode("utf-8", errors="replace")`

```python
# 正确：二进制无缓冲管道
self._proc = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    stdin=subprocess.PIPE,
    bufsize=0,  # 二进制模式无缓冲
    env={"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", **os.environ},
)
# 读取端手动解码
raw = self._proc.stdout.read(4096)
text = raw.decode("utf-8", errors="replace")
```

**坑2：`main.py` 在 `input()` 处阻塞**

`main.py` 的 `--audit-date` 未传命令行参数时，会进入交互式 `input()` 等待用户输入。GUI 子进程的 stdin 是管道，`input()` 永远等不到输入 → 进程阻塞。

解决：GUI 始终传递 `--audit-date`，留空时 fallback 到结束日期（与 `quick_start.py` 行为一致）。

**坑3：中文乱码（Windows GBK 环境）**

Windows 中文环境子进程默认输出 GBK 编码，GUI 用 UTF-8 解码导致 `��ǩ�Զ��µ�` 乱码。

解决：设置 `PYTHONIOENCODING=utf-8` 环境变量强制子进程输出 UTF-8。

**坑4：tkinter `after(0, callback)` 逐行回调淹没事循环**

子进程实时产出大量日志行时，每行一个 `root.after(0, _append_log, line)` 会淹没 tkinter 事件队列，UI 来不及渲染。

解决：改为生产者-消费者模式：
- 读取线程推入 `queue.Queue`
- 主线程 `root.after(80, _drain_log_queue)` 每 80ms 排空队列，批量更新 ScrolledText

### `--audit-date` 传递约定

`gui_app.py` 在模式 ①/② 时**始终传递** `--audit-date`。用户未填写稽核时间时，自动使用结束日期的值。这避免了 `main.py` 进入 `input()` 交互阻塞。

### 确认对话框机制

`main.py` 模式 ①（完整流程）在下载完成后、下单前会输出 `[确认] 将执行自动下单流程，是否继续？(y/n): ` 提示。GUI 的 `_read_output` 线程检测到 `是否继续？(y/n)` 关键词后，在队列中放入 `("confirm", None)` 事件，`_drain_log_queue` 在主线程弹出 `messagebox.askyesno` 让用户选择。

`_confirm_shown` 标志防止同一确认提示被检测多次（因分块读取可能触发多次匹配）。每次启动新进程时重置该标志。

**坑5：`input()` 确认提示无尾部换行符，残留 buffer 不被检测（2026-06-11）**

`main.py` 的确认提示通过 `input()` 输出，格式为 `\n[确认] 将执行自动下单流程，是否继续？(y/n): `。`input()` 在末尾**不加换行符**。`_read_output` 中按 `\n` 拆分行时，`[确认]...` 这部分残留在 buffer 中无换行符结尾，旧代码只在完整行（以 `\n` 结尾）中检测确认关键词，导致永远不触发弹窗，子进程在 `input()` 处永久阻塞。

解决：在每次 `read(4096)` 后，除按 `\n` 拆分行检测外，**额外检查残留 buffer** 中是否包含确认关键词。

```python
# 检测残留在 buffer 中的确认提示（input() 提示不含尾部换行符）
if any(kw in buf for kw in confirm_keywords) and self._proc:
    self._log_queue.put(("confirm", None))
```

## 打包为独立 .exe（PyInstaller）

### 单 exe 双模式架构

打包后的 `续签自动下单.exe` 支持两种运行模式：
- **GUI 模式**（直接双击）：正常显示图形界面
- **Worker 模式**（`--internal-worker` 参数）：GUI 点击"开始执行"时，启动自身 exe 的新实例作为子进程，直接调用 `main.py` 的 `main()` 函数

### Worker 模式编码问题（2026-06-11）

PyInstaller 打包后，`PYTHONIOENCODING=utf-8` 环境变量传递给子进程可能不生效，`sys.stdout.encoding` 仍为 GBK，导致日志中文乱码。

解决：在 `--internal-worker` 入口处直接调用 `sys.stdout.reconfigure(encoding='utf-8')`，不依赖环境变量。

```python
if "--internal-worker" in sys.argv:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ...
```

```
续签自动下单.exe (GUI)
  └─ subprocess.Popen("续签自动下单.exe --internal-worker --username ...")
       └─ from main import main; main()
```

### 构建命令

```bash
cd "F:\ClaudeCode\外包工具箱\自动化续签下单"
python -m PyInstaller gui_app.spec --noconfirm
# 输出: dist/续签自动下单.exe (~80MB)
```

### .spec 关键配置

- `console=False`：双击不显示黑窗口
- `excludes`：排除不相关的大型包（torch, scipy, matplotlib 等），防止体积膨胀
- `datas`：将 `utils/`、`下载外包续签查询/`、`下载人员变更/` 子目录打包到 MEIPASS
- `strip=False, upx=False`：Windows 下 strip 命令不可用，须关闭

### Playwright 浏览器依赖

打包后的 .exe 使用 `channel="chrome"` 调用**系统已安装的 Chrome**，不再依赖 Playwright 自带的 chromium。同事电脑只需安装 Chrome 即可运行。

### 设置文件

frozen 模式下 `.gui_settings.json` 保存在 exe 同级目录，而非 MEIPASS 内部（后者只读）。

### 分享给同事

1. 将 `dist/续签自动下单.exe` 复制给同事
2. 同事需安装 **Google Chrome** 浏览器
3. 首次运行可能被杀毒软件拦截，需添加信任
4. IMS 内网环境需能连接（VPN 等）

### 修改过的文件（channel="chrome" 适配）

- `下载外包续签查询/renewal_query_downloader.py:60` — `chromium.launch(..., channel="chrome")`
- `下载人员变更/personnel_change_downloader.py:57` — 同上
