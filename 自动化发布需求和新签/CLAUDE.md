# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

这是一个外包招聘流程自动化工具集，包含 5 个编号子项目，构成流水线作业：

| # | 子项目 | 做什么 |
|---|--------|--------|
| 1 | `1.提取申请单建多维表` | 从 IMS 抓取新签申请单 → 写入飞书多维表 |
| 2 | `2.根据多维表发布需求` | 读多维表未发布记录 → 在 TAM 网站自动发布招聘任务 |
| 3 | `3.查找需求返回职位编号` | 在 TAM 查询已发布任务 → 匹配职位编号回写多维表 |
| 4 | `4.提取人员面试评价建多维表` | 从 IMS 导出面试评价 Excel → 写入飞书多维表 |
| 5 | `5.根据人员面试评价新签` | 读多维表未签署记录 → IMS 外包合同逐组新签 → 回写签署状态 |

每个子项目是一个独立的工作目录，有自己的 `main.py`、依赖和配置，互不引用。

## 技术栈

- **浏览器自动化**: Playwright (Chromium, headless=False)
- **多维表操作**: 项目 1-3 使用 `lark-cli` CLI（已安装在 `C:\Users\AI\AppData\Roaming\npm\lark-cli.cmd`）；项目 4 使用飞书 REST API（`https://open.feishu.cn/open-apis/bitable/v1`）
- **Excel 解析**: `openpyxl`（.xlsx）+ `xlrd`（.xls / OLE2），通过文件头 magic bytes 检测格式
- **Word 解析**: `python-docx`
- **配置管理**: `python-dotenv`（`.env` 或 `config.env`）

## 运行命令

```bash
# 项目1：提取申请单（需在子目录下运行）
cd "1.提取申请单建多维表" && python main.py

# 项目2：发布需求（-y 自动确认，不加 -y 逐条交互确认）
cd "2.根据多维表发布需求" && python main.py -y

# 项目3：查找职位编号
cd "3.查找需求返回职位编号" && python main.py

# 项目4：提取面试评价
cd "4.提取人员面试评价建多维表" && python main.py --auto    # 全自动
cd "4.提取人员面试评价建多维表" && python main.py --file <xlsx>  # 处理已有文件

# 项目5：根据面试评价新签
cd "5.根据人员面试评价新签" && python main.py -y    # 自动提交
cd "5.根据人员面试评价新签" && python main.py       # 交互模式（已废弃）

# GUI 界面（4→5 流水线）
python gui_4_5.py    # 提取评价表+新签 / 直接新签
```

## 架构模式

### 共享数据流

所有子项目通过**飞书多维表**串联，数据流向为：

```
IMS 申请单 ──(1)→ 多维表"外包申请单" ──(2)→ TAM 发布 ──(3)→ 回写职位编号
IMS 面试评价 ──(4)→ 多维表"人员面试评价表" ──(5)→ IMS 外包合同新签
```

关键字段：`合作申请单编号`（主键/去重锚点）、`是否发布`（状态标记）、`职位编号`（(3)的结果）、`发布时间`。

### 项目内部结构

每个子项目遵循相似的分层：
- **`main.py`** — 编排主流程（初始化 → 查询 → 处理 → 写入 → 报告）
- **`config.py` / `config.env` / `.env`** — 凭证和业务常量（字段定义、查询条件、日期范围）
- **Web 自动化模块**（`ims_scraper.py` / `web_automation.py` / `tam_login.py` / `tam_publish.py` / `tam_query.py`）— Playwright 页面操作
- **飞书操作模块**（`lark_bitable.py` / `feishu_client.py` / `feishu_query.py` / `feishu_update.py`）— 多维表 CRUD
- **数据处理模块**（`data_processor.py`）— Excel 解析、字段映射、去重

### 两种飞书 API 调用方式

- **lark-cli**（项目 1-3）：通过 `subprocess` 调用 CLI，JSON 通过临时文件（`@tmp.json`）传递以避免命令行编码问题。结果通过 stdout JSON 解析。
- **REST API**（项目 4）：直接用 `requests` 调用飞书 Open API，通过 `tenant_access_token` 认证。首次运行时自动创建多维表，将 `app_token` 写入 `.env`。

### TAM 页面操作模式

TAM 网站使用 Ant Design 组件。所有表单操作基于以下模式：
- `_find_form_item(page, label_title)` — 通过 `label[title]` 定位 `ant-form-item`
- 填写策略：普通 input 用 `fill()`，`ant-input-number` 用 JS 设值（触发 React 事件），select 用点击+下拉匹配，date 用键盘输入覆盖默认值
- 每次发布后重新导航到新建页面（`navigate_to_new_recruitment_task`），避免表单状态污染

### 去重策略

- 项目 1：按 `合作申请单编号` 去重（先读已有记录 ID 集合）
- 项目 4：按 `身份证号` 去重（先读已有记录身份证号集合）

## 配置说明

- 项目 1 用 `.env`（`IMS_USERNAME`, `IMS_PASSWORD`），首次运行生成 `bitable_config.json` 保存多维表地址
- 项目 2-3 用 `config.env`（`IMS_USERNAME`, `IMS_PASSWORD`, `BITABLE_TOKEN`, `TABLE_ID`），参考 `config.env.example`
- 项目 4 用 `.env`（`IMS_USERNAME`, `IMS_PASSWORD`, `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_BITABLE_ID`）
- 所有 Playwright 浏览器均为 `headless=False`（需要可见浏览器以便处理验证码和手动干预）

## 流水线编排

由根目录 `run_pipeline.py` 串联功能 1→2→3：

```bash
python run_pipeline.py                        # 完整流程（交互式输入 SBU + 凭证）
python run_pipeline.py --sbu 185              # 指定单个 SBU
python run_pipeline.py --sbu "185,186"        # 多个 SBU（中英文逗号均可）
python run_pipeline.py --from review          # 跳过功能1，从人工审核开始
python run_pipeline.py --from publish         # 直接从功能2发布开始
```

**凭证传递**：编排脚本一次性收集 IMS 用户名密码，通过 `--username`/`--password` CLI 参数传给所有子模块，密码在日志中遮盖为 `***`。

**子模块凭证优先级**：`CLI 参数 > config.env/.env 配置文件 > 交互式输入`

## 常见踩坑

### 1. Playwright 表单提交后导航超时

**现象**：SSO 登录页点击提交按钮后报 `TimeoutError: Timeout 30000ms exceeded`，Playwright 日志显示 `waiting for scheduled navigations to finish`。

**根因**：`page.click()` 默认会等待点击触发的页面导航完成（默认 30s）。SSO 重定向到 IMS 时，网络慢或目标不可达就直接超时。

**修复**：用 JS 原生 click 绕过 Playwright 的导航追踪机制：
```python
page.locator("input[name='submit']").evaluate("el => el.click()")
page.wait_for_timeout(10000)  # 手动等待
```
**适用场景**：任何 Playwright 中点击按钮会触发 SSO 重定向、OAuth 跳转或跨域导航的表单提交。

### 2. 不要在模块级复制常量到多个文件

**现象**：`SBU_VALUE = "185"` 同时存在于 `config.py` 和 `ims_scraper.py`，`tam_query.py` 直接写死 `_select_bu(page, "185")`。改一个值要搜遍所有文件。

**原则**：**每个配置值有且仅有一个"真相源头"**（如 `config.py`），运行时通过 CLI 参数或函数参数传递，不要复制到多个文件。所有子模块统一用 `--sbu`/`--bu` + `parse_sbu_values()` 解析。

### 3. `getpass` 在 Windows 终端无任何回显

**现象**：`getpass.getpass()` 输入密码时完全静默，看不到任何反馈（连 `*` 也没有），用户以为卡死。

**修复**：用 `msvcrt.getch()` 逐字符读取，每输入一个字符打印 `*`，支持退格键。本项目的 `secure_input()` 函数已封装此逻辑（各 `main.py` 和 `run_pipeline.py` 中均有定义）。

### 4. argparse 入口统一

**规范**：每个子模块的 `main.py` 使用 argparse 统一管理参数，不要混用 `sys.argv` 手动解析（如原来的 `-y in sys.argv`）。参数名与流水线编排脚本 `run_pipeline.py` 保持一致：
- `--sbu` / `--bu` — SBU/BU 代码
- `--username` / `--password` — IMS 凭证
- `-y` / `--yes` — 自动确认（功能2）

### 5. TAM "实际工作地" 是 Ant Design TreeSelect，不是 Select

**现象**：`_fill_form_select` 搜索+点击后，表单校验仍提示"请输入实际工作地"。浏览器上省/市都显示了，但选中了省而非市。

**根因**：
- 该字段是 **TreeSelect**（`ant-select-tree`），不是普通 Select 也不是 Cascader
- DOM 结构：
  ```html
  <li class="ant-select-tree-treenode-switcher-close">   <!-- 省 -->
    <span class="ant-select-tree-switcher"></span>        <!-- 展开箭头 -->
    <span class="ant-select-tree-checkbox"></span>        <!-- 勾选框 -->
    <span class="ant-select-tree-node-content-wrapper">
      <span class="ant-select-tree-title">山东省</span>
    </span>
  </li>
  ```
- 关键差异：
  1. **搜索框必须限定在 form_item 内**，否则 `.ant-select-search__field` 会匹配到页面上第一个搜索框（如"用人经理"字段）
  2. **不能用 `li.textContent()` 匹配**，因为父节点 li 的 textContent 包含了子节点文本（"山东省" 的 li 也包含 "济南"）
  3. **必须匹配 `.ant-select-tree-title` 的自身文本**，再通过 `closest('li')` 找父节点，点击其 `.ant-select-tree-checkbox`

**修复**（`tam_publish.py` `_fill_tree_select`）：

```python
# 检测：打开下拉后检查 .ant-select-tree 是否存在
is_tree = page.locator('.ant-select-tree').first
if is_tree.count() > 0:
    _fill_tree_select(page, form_item, value)  # 传入 form_item 限定搜索框范围

# 搜索：在 form_item 内找 .ant-select-search__field
search = form_item.locator('.ant-select-search__field').first
search.fill(value)
search.evaluate("el => el.dispatchEvent(new Event('input', {bubbles: true}))")

# 选择：JS 遍历 .ant-select-tree-title，匹配自身文本，勾选父节点的 checkbox
page.evaluate(f"""() => {{
    const titles = document.querySelectorAll('.ant-select-tree-title');
    for (const t of titles) {{
        if (t.offsetParent === null) continue;
        if (t.textContent.trim().includes('{value}')) {{
            const li = t.closest('li');
            const cb = li.querySelector('.ant-select-tree-checkbox');
            if (cb) {{ cb.click(); return t.textContent; }}
        }}
    }}
    return null;
}}""")
```

**教训**：Ant Design 表单中同一页面可能混用 Select、Cascader、TreeSelect 三种组件。必须先 dump 下拉框 HTML 确认组件类型（`ant-select-tree` vs `ant-select-dropdown` vs `ant-cascader-menu`），再针对性处理。

### 6. Phase 5 同一申请单有多个供应商时职位编号区分

**现象**：一个合作申请单号给两个供应商发布了需求，多维表有两条记录（供应商不同），Phase 5 查找职位编号时两条记录都返回同一个编号。

**根因**：旧版 `_search_and_match` 的 JS 用 TreeWalker 找到**第一个**包含申请单编号的文本节点就 `return`，只提取了一个容器的职位编号。同一申请单在 TAM 查询结果中有多个职位条目（每供应商一个），但只处理了第一个。

**修复**（`tam_query.py` `_search_and_match`）：

1. **JS 遍历所有匹配节点**：TreeWalker 找所有包含申请单号的文本节点，每个节点向上找包含"职位编号"+"创建时间"的容器，用容器文本前 100 字符去重
2. **标记"查看"按钮**：每个条目内的"查看"按钮打上 `data-entry-marker` 唯一标识
3. **返回条目列表**：`[{position_code, creation_time, marker}, ...]`
4. **Python 逐条校验**：对每个条目点其标记的"查看"按钮获取供应商，供应商 + 时间都匹配才返回

```python
# JS 核心改动：收集所有条目，不提前 return
entries = page.evaluate(f"""() => {{
    var entries = [];
    var seenMarkers = {{}};
    var walker = document.createTreeWalker(...);
    while (node = walker.nextNode()) {{
        // ... 找容器 ...
        var key = text.substring(0, 100);
        if (seenMarkers[key]) break;  // 去重
        seenMarkers[key] = true;
        // 标记"查看"按钮
        var marker = 'entry_' + entries.length;
        b.setAttribute('data-entry-marker', marker);
        entries.push({{marker, position_code, creation_time}});
    }}
    return entries;  // 返回全部
}}""")

# Python：逐条校验供应商
for entry in entries:
    page_supplier = _get_supplier_by_marker(page, entry['marker'])
    if supplier in page_supplier:
        return entry['position_code']  # 只返回供应商匹配的
```

**教训**：当 TAM 查询结果中同一申请单有多个条目时，必须遍历所有匹配节点分别提取和校验，不能只取第一个。

### 7. Phase4 多 BU 循环下载

**现象**：GUI 输入多个 BU（如 121,185），Step4 只下载了第一个 BU 的数据。

**根因**：IMS 页面 BU 是下拉单选，`web_automation.py` 的 `run()` 只设置一次条件就导出。`gui_4_5.py` 的 `format_bu_for_ims()` 也只取第一个 BU。

**修复**：
1. `web_automation.py`: `run()` 登录一次 → 按 BU 逐个循环（设条件→查询→导出），文件名加 `_BU{code}` 后缀防覆盖，返回文件列表
2. `config.py`: `QUERY_BU` 改为 `os.getenv("QUERY_BU", ...)` 从环境变量读取
3. `main.py`: `--auto` 模式遍历文件列表，逐个 `process_and_upload()`
4. `gui_4_5.py`: 移除 `format_bu_for_ims`，直接逗号拼接原始 BU 代码传入 `QUERY_BU` 环境变量

### 8. Phase4 飞书多维表删除后无法重建

**现象**：用户在飞书侧删除了多维表，再次运行 Step4 时报 API 错误。

**根因**：`.env` 中缓存的 `FEISHU_BITABLE_ID` 是旧 ID，`create_table_if_needed()` 直接返回旧 ID 不验证是否存在。

**修复**（`feishu_client.py`）：`create_table_if_needed()` 增加 `_bitable_exists()` —— 用 GET API 验证旧 ID，无效则清除 `.env` 中的旧值并创建新表。

**原则**：任何缓存外部资源 ID 的场景，使用前都应做存在性验证。

### 9. Step5 弹窗检测 — offsetParent 误判隐藏

**现象**：提交失败后出现错误弹窗，但 `_get_visible_dialog_text()` 返回空，代码走到成功分支。

**根因**：MiniUI 弹窗常用 `position: fixed`，CSSOM 规范中 `position: fixed` 元素的 `offsetParent` 恒为 null。旧代码用 `if (d.offsetParent === null) continue` 跳过了所有 fixed 定位弹窗。

**修复**（`ims_contract.py` `_get_visible_dialog_text`）：
- 用 `getComputedStyle(el).display !== 'none'` + `getBoundingClientRect().width > 1` 判断可见性
- 同时遍历主页面和所有 iframe（弹窗可能在 iframe 内渲染）

**原则**：不要用 `offsetParent !== null` 判断元素可见性，改用 `getComputedStyle` + `getBoundingClientRect`。

### 10. Step5 弹窗检测 — .mini-panel 误匹配表单面板

**现象**：`_get_visible_dialog_text` 返回表单面板文字而非弹窗内容，导致写入多维表的失败原因错误。

**根因**：`querySelectorAll` 选择器中 `.mini-panel` 太宽泛 —— IMS 表单面板也用此类，且 DOM 顺序排在弹窗前面。

**修复**：移除 `.mini-panel`，只搜索 `.mini-window`、`.mini-messagebox`、`.mini-modal`，在容器内部再找 `.mini-panel-body` 或 `.mini-messagebox-content` 获取正文。

### 11. Step5 提交成功/失败判断

**现象**：确认弹窗→点确认→出现错误弹窗，但代码报成功。

**根因**：判断逻辑混杂了订单编号检测。错误弹窗漏检后走到"未检测到订单编号，可能成功"分支返回 True。

**修复**（`ims_contract.py` `_submit_contract`）：只看弹窗判断成败：
1. 点「保存并提交审批」→ 等弹窗
2. 是「是否确认保存并提交订单?」→ 点确认 → 等 3.5s → 再扫弹窗 → 有新弹窗=失败（弹窗文字写入"未成功提交原因"），没弹窗=成功
3. 是其他弹窗 → 直接失败
4. 没弹窗 → 成功
不再检测订单编号字段。

**原则**：IMS/MiniUI 表单提交后，弹窗是最直接的成败信号，比字段值更可靠。

### 12. GUI 凭证传递方式

**现象**：Step4 的 `main.py` 不支持 `--username`/`--password` CLI 参数，不能用命令行传凭证。

**解决**：GUI 通过环境变量传递：
- Step4: `os.environ["IMS_USERNAME"]` / `os.environ["IMS_PASSWORD"]` / `os.environ["QUERY_BU"]` → `Config` 类通过 `os.getenv()` 读取
- Step5: GUI 直接写入 `config.env` 文件 → `main.py` 通过 `dotenv_values()` 读取

**原则**：不同模块的配置读取方式不同（`os.getenv` vs `dotenv_values`），GUI 需适配两种方式。
