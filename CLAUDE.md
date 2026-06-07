# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## 项目概述

`外包工具箱` 是一套 IMS 企业系统网页自动化工具集，共 13 个模块，分为三类：

1. **报表下载类**（9 个）：自动登录 IMS → 导航到特定页面 → 选择条件 → 查询 → 导出 Excel
2. **数据修改类**（1 个）：在 IMS 页面批量修改资源池预算数据
3. **流程编排类**（3 个）：多步骤流水线（下载→解析→下单→回写），通过飞书多维表串联

目标系统: `https://ims.asiainfo.com/AIOMS/Jsp/main.jsp`，左侧 MiniUI 树形菜单导航。

## 模块清单

| 模块 | 主要页面框架 | 特殊点 |
|------|-------------|--------|
| 下载人员变化报表 | MiniUI | 新标签页打开，SBU+人员状态+工作时间三条件 |
| 下载人员变更 | MiniUI | 单据状态多选（UI交互方式），含死代码已清理 |
| 下载人员面试评价表 | **Layui** | 非MiniUI，普通HTML select+Layui日期控件 |
| 下载外包合同 | MiniUI | 导出按钮为"导出合同"，技术合作种类按索引选择 |
| 下载外包续签查询 | MiniUI | 导出按钮为"导出待续签人员"，含表单清空逻辑 |
| 下载工时 | MiniUI | Combobox滚动查找选项 |
| 下载绩效考核 | **Layui** | 两级菜单展开，季度×BU双重循环，支持代码/名称匹配 |
| 下载节假日加班 | **Layui** | 日期输入需手动移除`.layui-laydate`弹出层 |
| 下载计提和结算 | MiniUI | 通过标签文本定位关联combobox，月份范围直接输入 |
| 外包预算滚动预测 | - | Excel数据处理+HTML仪表盘生成，含JS续签预测计算 |
| 自动化修改资源池预算 | **Layui**（表格）+ layer弹窗 | JS dispatchEvent绕过遮挡，编辑弹窗是iframe |
| 自动化续签下单 | MiniUI | 最复杂模块：下载→解析→逐条下单→状态回写 |
| 自动发布需求 | MiniUI+Layui | 5个子项目流水线，含飞书多维表+lark-cli |

## 核心架构模式

### 1. 下载器基类模式

每个下载模块几乎完全遵循相同的类结构。新增模块时可从任一模块复制骨架：

```python
class XxxDownloader:
    LOGIN_URL = "https://ims.asiainfo.com/AIOMS/Jsp/main.jsp"
    SELECTORS = { ... }        # CSS选择器字典
    MINIUI_IDS = { ... }       # MiniUI控件ID映射（Layui页面用LAYUI_IDS）

    def __init__(self, username, password, download_dir, headless):  # 初始化路径和状态
    def start(self):           # 启动Playwright浏览器
    def stop(self):            # 关闭浏览器
    def __enter__/__exit__:    # 上下文管理器
    def login(self):           # 统一登录流程
    def navigate_to_xxx(self): # 左侧树菜单导航（新标签页/iframe双模式）
    def _find_target_frame(self):  # iframe关键词匹配
    def _get_fresh_frame(self):    # 重新获取frame（防detach）
    def _query_and_export(self):   # 条件填写→查询→导出
    def download_xxx_reports(self):  # 主入口：批量循环
    def main():                # argparse + 交互式输入
```

### 2. 左侧树形菜单导航（核心模式）

所有模块的导航流程相同，必须处理两种页面打开方式：

```python
# 步骤1：双击父菜单展开（带JS回退方案）
try:
    page.locator(".mini-tree-nodetext:has-text('父菜单名')").first.dblclick()
except Exception:
    page.evaluate("""
        var tree = mini.get("tree1");
        var nodes = tree.getData();
        for(var i=0; i<nodes.length; i++){
            if(nodes[i].text == '父菜单名'){ tree.expandNode(nodes[i]); break; }
        }
    """)

# 步骤2：单击子菜单（先尝试新标签页，超时后回退iframe）
try:
    with page.context.expect_page(timeout=5000) as new_page_info:
        page.locator(".mini-tree-nodetext:has-text('子菜单名')").first.click()
    target = new_page_info.value  # 新标签页
except Exception:
    # 回退iframe：URL关键词匹配 → 兜底取最后一个非main frame
    target = find_frame_by_keywords(page, ["keyword1", "keyword2"])
```

**重要**：`expect_page` timeout 不应超过 5 秒（`timeout=5000`），否则用户等待过长。

### 3. iframe/标签页生命周期管理

```python
# 状态标记
self._query_is_tab = False   # 当前页面是标签页还是iframe
self._query_target = None     # 目标页面/iframe引用

# 重新获取frame（每次操作前调用，防止frame detach）
def _get_fresh_frame(self):
    frame = self._find_target_frame()
    if frame:
        self._query_target = frame
        return frame
    return None

# 多SBU循环时，每条处理完后重置
if self._query_is_tab:
    self._query_target.close()   # 关闭标签页
else:
    page.reload()                # 刷新iframe
```

## 两种 UI 框架对照

IMS 系统中使用了两种不同的前端框架，交互方式完全不同：

### MiniUI 页面

- 控件通过 `mini.get(id)` JS API 操作
- **combobox 普通类型**（如 p_sbu_id）：可用 `combo.setValue(val)` 设置值
- **buttonedit+combobox+popupedit 类型**（如 p_coop_type）：`setValue()` 不触发 UI 更新，必须 click→等下拉→点击选项
- 多选：点击按钮打开下拉 → 遍历选项勾选 `.mini-listbox-checkbox` → Esc 关闭
- 日期控件：`mini.get(id).setValue('YYYY-MM-DD')`
- 查询按钮通常是 `<a>` 标签（`a#Query`）
- 导出按钮文本可能是"导出Excel"/"导出合同"/"导出待续签人员"

MiniUI combobox 单选的标准实现（模糊匹配）：
```javascript
// 先确保数据加载
combo.load();
// 模糊匹配：遍历data，跳过 __NullItem，按 flexValue/id/value 取值
combo.setValue(matched.flexValue || matched.id || matched.value);
```

### Layui 页面

- 使用标准 HTML 表单元素 + Layui JS 增强
- **select**：通过 `document.getElementById('id')` → 设置 value → `dispatchEvent(new Event('change'))` → `layui.form.render('select')`
- **日期输入**：直接用 JS 设值 `el.value = val` → 触发 input/change 事件 → **关键**：手动移除 `.layui-laydate` 弹出层（否则遮挡后续元素）
- **表格工具栏**：导出按钮在 `.layui-table-tool` 内
- **查询按钮**：`a[lay-filter='searchForm']` 或 `a.layui-btn:has-text('查询')`

### 弹窗遮挡问题的通用解法

不同框架的弹窗遮挡有三种情况：

1. **MiniUI modal/window**：用 `mini.gets()` 遍历关闭或直接设置 `display:none`
2. **Layui 日期选择器**：`document.querySelector('.layui-laydate').remove()`
3. **layui-table-fixed-r 遮挡按钮**：用 `dispatchEvent(new MouseEvent('click', {...}))` 绕过

## Playwright 关键配置

```python
# 浏览器启动
browser = p.chromium.launch(
    headless=headless,
    args=["--headless=new"] if headless else [],   # 新版已不推荐此参数
)
context = browser.new_context(accept_downloads=True)
# 禁止在任何地方设置 downloads_path！Playwright 内部管理下载临时目录，
# 设了反而会导致 Chromium 往工作目录写入 UUID 命名的临时文件。只需：
#   download = download_info.value
#   download.save_as(custom_path)
#   download.delete()     # 清理临时文件

# 下载监听（注意上下文选择）
if is_new_tab:
    with target_page.expect_download(timeout=180000) as download_info:  # 大文件用更长超时
        export_btn.click()
else:
    with main_page.expect_download(timeout=60000) as download_info:
        export_btn.click()
download = download_info.value
download.save_as(custom_path)  # 自定义文件名
```

**注意**：下载事件的上下文归属取决于页面的打开方式。iframe 内的导出按钮，下载事件可能触发在主页面而非 iframe。需要根据实际情况测试。

## 配置管理

- 凭据统一存放在各模块的 `config.py` 中
- **凭据应为空字符串**，运行时通过命令行参数或交互式输入提供
- `config.py` 结构：
  ```python
  USERNAME = ""
  PASSWORD = ""
  DOWNLOAD_DIR = "./downloads"
  ```
- `main()` 函数模式：
  ```python
  try:
      from config import USERNAME, PASSWORD, DOWNLOAD_DIR
  except ImportError:
      USERNAME = PASSWORD = ""
      DOWNLOAD_DIR = "./downloads"

  args = parser.parse_args()
  username = args.username or input("请输入用户名: ")
  ```

## 模块路径原则

**所有模块必须自包含，使用相对路径，可整体迁移到其他目录。**

- 模块内脚本之间的引用一律使用 `Path(__file__).parent` 或 `os.path.dirname(os.path.abspath(__file__))` 构建相对路径
- **禁止**硬编码绝对路径（如 `C:\Users\xxx\...`），确保模块复制到其他机器或目录后仍可直接运行
- 模块内部子目录（如 `settlement/`、`contract/`）的引用相对于模块根目录，不依赖外部同级模块

示例：
```python
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MERGE_SCRIPT = os.path.join(BASE_DIR, "merge_data.py")
DOWNLOAD_SCRIPT = os.path.join(BASE_DIR, "settlement", "settlement_downloader.py")
```

## 常见踩坑

### 1. 表单条件串扰
切换 SBU 查询时，上一次的条件可能残留。解决：每次查询前调用清空方法（`_clear_form`），用 `mini.get(id).setValue('')` 重置所有控件。

### 2. Frame detach
DOM 变化（如 partial page refresh）后，之前获取的 Frame 引用会失效。解决：每次操作前调用 `_get_fresh_frame()` 重新获取。

### 3. Combobox 弹窗重叠
连续操作多个 combobox 时，前一个的弹窗可能还未完全关闭。解决：每次操作后等待 800-1000ms，确保弹窗关闭。

### 4. 下拉选项需要滚动查找
选项可能不在可视区。解决：找到 `.mini-listbox:visible` 容器，循环 `scrollTop += 50` 并检查选项是否出现（最多循环 20-30 次）。

### 5. 身份证号被 Excel 转成科学计数法
pandas `read_excel` 会默认推断类型。解决：用 `dtype=str` 强制文本模式读取；写入时用 openpyxl 给身份证列设 `FORMAT_TEXT`。

### 6. 空 DataFrame 塌陷
pandas 2.x 对空 DataFrame 做列操作可能意外清空数据。解决：在链式操作前加 `len(df) > 0` 守卫。

### 7. MiniUI 控件类型不同，交互方式不同
同一个页面中，外观相似的 combobox 底层类型可能不同。用 `combo.type` 或观察 HTML 结构判断是普通 combobox 还是 buttonedit+popupedit。后者必须用 click→选选项的方式，`setValue()` 不够。

### 8. 新标签页/iframe 判断
不能假设页面一定以某种方式打开。必须同时处理两种分支：
- 先尝试 `expect_page`（新标签页）
- 超时后扫描 frames 找关键词匹配
- 最终兜底：取最后一个 URL 非空的非 main frame

### 9. IMS 登录按钮选择器覆盖不全

IMS 登录页的实际按钮可能不是 `<button type="submit">` 或 `<input type="submit">`，而是 `<a>` 标签、`<input type="button">` 等。当前 `SELECTORS["login_button"]` 覆盖的标签有限。

解决：`login()` 方法中对登录按钮先尝试 `click(timeout=5000)`，若超时则用 `password_input.press("Enter")` 作为回退。大多数登录表单都支持 Enter 提交。

### 10. 多 SBU 循环时表单条件串扰

循环处理多个 SBU 时，上一轮查询后页面可能仍显示查询结果，MiniUI 控件的下拉状态也可能残留。解决：
- 每轮开始前关闭上一轮的标签页（`self._query_target.close()`）
- 重置 `_query_target` / `_query_is_tab`
- 在 `_query_and_export` 开头执行 `location.reload()` 强制刷新页面
- 对 buttonedit 类型控件按文本选择失败时，回退到 MiniUI API `combo.setValue()`

## 日期格式约定

项目中使用两种日期格式：
- **用户输入**：`YYYY年MM月DD日`（如 `2026年1月1日`）
- **系统设置**：`YYYY-MM-DD`（如 `2026-01-01`，MiniUI/Layui 控件要求）
- 各模块的 `parse_date_input()` 函数负责转换

## 依赖

核心依赖：`playwright`、`pandas`、`openpyxl`
可选依赖：`python-dotenv`（自动发布需求模块）、`xlrd`（读取老 .xls 文件）

首次使用需安装 Playwright 浏览器：
```bash
playwright install chromium
```

## 安全注意事项

- **永远不要**在 config.py 中硬编码真实凭据，保持空字符串
- config.py 中的凭据通过命令行参数或交互式输入获取
- `.env` 文件应加入 `.gitignore`
- 日志文件中可能包含敏感业务数据，注意清理
