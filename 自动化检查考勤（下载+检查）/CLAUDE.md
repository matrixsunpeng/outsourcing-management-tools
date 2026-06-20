# CLAUDE.md

此文件为 Claude Code 处理本项目时提供指导。

## 项目概述

考勤合规检查工作平台 — **GUI 驱动的双标签页工具**，集成 IMS 数据自动下载与合规检查两大功能。

**目标系统**: `https://ims.asiainfo.com/AIOMS/Jsp/main.jsp`（MiniUI 组件库）。

**原始脚本**: `F:\ClaudeCode\学习检查考勤\check_compliance.py`（532行，已验证可用的纯脚本版）。

**参考项目**: `F:\ClaudeCode\外包工具箱\`（14个模块的 Playwright + IMS 自动化工具集，有共享 `BaseDownloader` 基类、丰富的 MiniUI JS API 模式）。

## 常用命令

```bash
# 安装依赖
pip install playwright pandas openpyxl
playwright install chromium

# 启动 GUI
python main_app.py

# 单独测试合规检查（使用原始数据）
python -c "
from compliance_runner import run_full_check
run_full_check('202604', ['人瑞人才'], 'F:/ClaudeCode/学习检查考勤', log_func=print)
"
```

## 文件结构

```
main_app.py              # GUI 主程序（~580行 tkinter）
download_module.py       # Playwright 下载模块（~1100行）
compliance_runner.py     # 合规检查包装器（~550行，从 check_compliance.py 提取）
README.md                # 用户文档
CLAUDE.md                # 本文件
合规检查功能.docx         # 功能规格说明书
.gui_settings.json       # 自动生成的用户设置（不保存密码）
```

## 架构

```
main_app.py (tkinter 主线程)
├── 标签页1: 下载外包数据
│   └── download_module.py
│       ├── IMSDataDownloader
│       │   ├── start() / quit()           # Playwright 浏览器生命周期
│       │   ├── login()                    # IMS 登录
│       │   ├── _expand_menu_parent()      # MiniUI 树展开
│       │   ├── _click_menu_child()        # 子菜单点击（标签页/iframe 双路径）
│       │   ├── download_workhours()       # 工时详细查询（每供应商3批）
│       │   ├── download_staff_list()      # 在岗人员清单
│       │   └── download_accrual_report()  # 计提报表
│       └── run_full_download()            # 公共接口
│
└── 标签页2: 检查合规
    └── compliance_runner.py
        ├── load_all_data()                # 加载5类Excel数据
        ├── run_compliance_check()         # 单供应商6项检查
        └── run_full_check()               # 公共接口
```

## 核心类与方法

### `IMSDataDownloader` (download_module.py)

Playwright 驱动的 IMS 下载器。参考了 `外包工具箱/common/base_downloader.py` 的模式。

**浏览器生命周期**: `sync_playwright().start()` → `chromium.launch()` → `new_context(accept_downloads=True)` → `new_page()`。**不传 `downloads_path`**，使用 `page.expect_download()` + `download.save_as()` 方式。

**菜单导航** (`_expand_menu_parent` + `_click_menu_child`):
- 先尝试 `page.locator(".mini-tree-nodetext:has-text('xxx')").dblclick()` 展开
- JS 回退: `mini.get("tree1").expandNode()`
- 子菜单点击: 先 `expect_page(timeout=5000)` 等新标签页，超时回退 iframe 扫描（URL 关键词匹配 → 兜底取最后一个非 main frame）

**Autocomplete 输入框操作** (`_autocomplete_by_label` + `_autocomplete_scan_inputs`):
IMS 商务经理工时查询页面的技术合作商字段是 autocomplete 类型——输入文本后弹出匹配列表，需点击选中。操作流程：
1. 扫描页面所有可见 `input[type='text']` / `.mini-buttonedit-input`
2. 日志输出每个输入框的 id/name/placeholder（用于调试）
3. 通过标签文本 XPath 或同行定位找到目标输入框
4. `click → Ctrl+A → Backspace → fill(text)` 输入
5. 等待 autocomplete 下拉 → 多选择器匹配 `.mini-popup:visible td` / `.mini-listbox-item` 等 → 点击
6. 回退 `Enter` 确认

### `run_full_download()` — 公共接口

```python
def run_full_download(username, password, supplier_list, month_str, download_dir, log_func=None)
```

GUI 只调用此函数，签名保持不变。内部使用 `IMSDataDownloader`。

### `run_full_check()` — 公共接口

```python
def run_full_check(month_str, supplier_list, base_dir, output_dir=None, exclude_sbu="AIS", log_func=None)
```

## 合规检查的6项条件

| # | 条件 | 阈值 | 数据来源 |
|---|------|------|---------|
| 1 | 签到合规 | >3天缺失 | 场地签 + 工时（请假排除） |
| 2 | 签到城市匹配 | >3天不匹配 | 场地签 + 在岗清单 + 差旅（豁免） |
| 3 | 工时状态合规 | >3天非"项目经理审批通过" | 工时详细查询 |
| 4 | 请假合规 | >3天非豁免类型 | 工时详细查询（产假/病假/婚假/陪产假豁免） |
| 5 | 计提报表 | 缺失即不合规 | 计提报表（小计>0） |
| 6 | 项目编号 | 全空即不合规 | 工时详细查询 |

## 5类数据文件

| 关键字 | 文件名模式 | 来源 |
|--------|-----------|------|
| 在岗人员清单 | `*在岗人员清单*.xlsx` | IMS 自动下载 |
| 工时详细查询 | `*工时详细查询*.xlsx` | IMS 自动下载（每供应商3批） |
| 计提报表 | `*计提报表*.xlsx` | IMS 自动下载 |
| 场地签 | `*场地签*.xlsx` | **手动准备** |
| 差旅 | `*差旅*.xlsx` | **手动准备** |

## GUI 线程模型

- 下载和合规检查在 `daemon=True` 后台线程中执行，避免阻塞 GUI
- 日志回调使用 `root.after(0, callback)` 线程安全写入 `ScrolledText`
- 操作期间禁用按钮和参数输入，完成后恢复
- 设置持久化到 `.gui_settings.json`（密码**不保存**）
- `WM_DELETE_WINDOW` 优雅退出：检查运行状态 → 确认 → 清理浏览器 → 保存设置

## 关键模式与注意事项

### 1. Playwright 下载处理（最重要）

```python
# 正确：使用 expect_download 精确捕获
with self._page.expect_download(timeout=120000) as download_info:
    export_btn.click()
download = download_info.value
download.save_as(target_path)   # 保存到指定路径
download.delete()               # 清理 Playwright 临时文件
```

**禁止**：文件系统轮询（`glob *.crdownload`）、`downloads_path` 参数。

### 2. MiniUI 菜单导航双路径

单击左侧树子菜单时，IMS 可能打开新标签页或嵌入 iframe。**必须同时处理两条路径**：
```python
try:
    with page.context.expect_page(timeout=5000) as new_page_info:
        page.locator(".mini-tree-nodetext:has-text('子菜单')").first.click()
    target = new_page_info.value  # 新标签页
except:
    target = find_frame_by_keywords(page, ["keyword"])  # iframe 回退
```

### 3. Autocomplete 输入框 ≠ 普通 combobox

`mini.get(id).setValue()` 对 buttonedit+autocomplete 类型**可能无效**——不会触发下拉匹配。正确做法：
```
click → 全选清空 → fill(文本) → 等下拉弹出 → 多选择器匹配点击 → Enter 回退
```

### 4. 多供应商循环防污染

每轮循环后：
- 新标签页模式：`target.close()` 关闭
- iframe 模式：`page.reload()` 刷新
- 重置 `_query_target` 和 `_query_is_tab`

### 5. 错误诊断

- 异常时自动截图 `debug_*.png` 保存到下载目录
- `_autocomplete_by_label` 启动时扫描打印所有可见输入框的 id/name/placeholder
- 日志通过 `log_func` 回调实时输出到 GUI

### 6. 页面特有的 iframe

- 商务经理工时查询: iframe URL 含 `timeInfo_toQueryTime`
- 技术合作人员变化表: 通常新标签页打开
- 计提: 通常新标签页打开

### 7. 合规检查与原始脚本的一致性

`compliance_runner.py` 是 `check_compliance.py` 的**精确逻辑提取**。验证结果：6043 人中 1816 人瑞人才员工，434 人不合规，6 项分类统计完全一致。修改合规逻辑时务必回归对比。

**关键逻辑细节**：
- 在岗清单表头自动检测（第一行含"变化表/清单/统计"则表头在第2行）
- 同一身份证号多条记录时合并工作期间（取最早开始、最晚结束）
- 场地签/差旅与人员匹配：先工号精确匹配，再姓名唯一匹配
- 场地签"是否工时人员=否"跳过签到检查和项目编号检查
- 请假日期从签到要求天数中扣除（不是从签到记录中扣除）

### 8. 批次导出表格不在主页面而在特定 iframe

点击"导出工时明细"后出现的批次选择界面**不是 MiniUI 弹窗**，而是页面内 `<table class="tableMainEdit">` 包含 `<td class="tdHead">` 和 `<a onclick="doExport(n)">` 导出按钮。

**关键发现**：该表格不在主页面，也不在工时查询的 iframe（`timeInfo_toQueryTime`），而在**另一个 iframe**（URL 含 `timeInfo_toExcelData`）。因此必须搜索**所有 frames** 才能找到。

```python
# 错误：只搜主页面 + 已知 iframe
scopes = [self._page, target]

# 正确：搜索所有 frames
def _get_all_scopes(self):
    scopes = [self._page]
    for frame in self._page.frames:
        if frame != self._page.main_frame and frame != self._page:
            scopes.append(frame)
    return scopes
```

### 9. 批次导出流程：按钮→确认弹窗→下载

每批导出需要三步，**确认弹窗和下载是分开的**：

```
1. 点击批次按钮（如 <a onclick="doExport(0)">导出</a>）
2. 等待 MiniUI messagebox "您确认导出excel吗？" 出现
3. 点击"确定" → 触发下载（expect_download 应包裹第 3 步）
```

```python
# 正确流程
self._click_batch_export_link("第一批", "1日~10日")
self._wait_for_confirm_export_dialog(timeout=5)
with self._page.expect_download(timeout=120000) as download_info:
    self._click_confirm_ok_button()
download = download_info.value
```

**批次间不要关闭批次表格**，三批全部完成后才关。

### 10. 弹窗遮挡菜单导航——用 page.reload() 清场

工时下载完成后，批次弹窗/浮层/modal（如 `#__modalmini-21`、`.mini-modal`）会残留并遮挡左侧树菜单，导致后续导航（外包报表、计提）的 `dblclick` 被拦截：

```
<iframe> from <div class="mini-modal" id="__modalmini-21"> subtree intercepts pointer events
```

**CSS `display:none` 不够**，MiniUI modal 有自身状态。正确做法：**每次下载模块结束后 `page.reload()` 刷新页面**，得到一个干净的主页面再导航。

```python
# download_staff_list 和 download_accrual_report 开头
self._page.reload(wait_until="domcontentloaded")
self._page.wait_for_timeout(3000)
```

### 11. MiniUI datepicker 用已知 ID 设值

"工作时间"标签后的两个日期选择器是 MiniUI `datepicker`：
- 开始：`<span id="p_work_start_date" class="mini-buttonedit mini-datepicker mini-popupedit">`
- 结束：`<span id="p_work_end_date">`

**不要用标签文本定位 + 找 input 的方式**，容易填到其他字段（如项目代码、技术合作编号）。直接用 `mini.get(id).setValue()`：

```python
active.evaluate("""(args) => {
    var beg = mini.get('p_work_start_date');
    var end = mini.get('p_work_end_date');
    if (beg) beg.setValue(args.start);
    if (end) end.setValue(args.end);
}""", {"start": "2026-04-01", "end": "2026-04-30"})
```

### 12. iframe target 失效检测

iframe 可能因页面导航/跳转而 detach，后续 `target.wait_for_timeout()` 或 `target.locator()` 会抛 `TargetClosedError`。

**每次使用前验证**：
```python
try:
    target.wait_for_timeout(100)  # 快速探活
except Exception:
    # 重新在所有 frames 中找
    for frame in self._page.frames:
        if "timeInfo" in (frame.url or ""):
            active = frame
            break
```

### 13. 确认弹窗"确定"按钮搜索所有 frame

`_wait_for_confirm_export_dialog` 和 `_click_confirm_ok_button` 都必须用 `_get_all_scopes()` 搜索所有 frame，**不能只搜主页面**。

`_click_confirm_ok_button` 三层回退：
1. Playwright locator（`.mini-messagebox:visible button:has-text('确定')` 等）
2. JS `querySelectorAll` + `textContent === '确定'`
3. 通用 `:visible:has-text('确定')`

### 14. 关闭弹窗的增强策略

`_close_miniui_popups` 需要多种手段组合：
1. **JS 直接移除 DOM**（`parentNode.removeChild`），不只是 `display:none`
2. MiniUI API `mini.gets()` 遍历 `destroy()` / `close()` / `hide()`
3. 点击 `.mini-tools-close` 关闭按钮
4. `keyboard.press("Escape")`
5. 清除 `body` 的 `mini-modal-open` class
```
```
