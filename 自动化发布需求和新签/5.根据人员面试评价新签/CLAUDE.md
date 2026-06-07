# CLAUDE.md — 项目5：根据人员面试评价表新签

## 运行方式
```bash
cd "5.根据人员面试评价新签"
python main.py        # 交互模式，每条询问是否提交
python main.py -y     # 自动提交
```

## 核心难点与解决方案

### 难点1：合作申请单编号弹窗

**问题**：用 `frame.evaluate("showApplicationQueryPage()")` JS调用打开弹窗后，弹窗内填写+查询正常，但弹窗**永远不会自动关闭**。原因是JS生成的事件 `isTrusted: false`，MiniUI据此拒绝执行自动关闭回调。

**解决方案**：用 Playwright 的 `page.mouse.click()` 点击 btnEdit1 的右边缘位置（trigger图标所在），产生 trusted 鼠标事件。

```python
box = frame.locator('#btnEdit1').bounding_box()
page.mouse.click(box['x'] + box['width'] - 8, box['y'] + box['height'] / 2)
```

**弹窗iframe**：确认弹窗 → 点"确定" → 搜索弹窗在 `goToQueryApplicationResult` 的 iframe 中。填 `p_application_code$text` 输入框 → 点"查询"。

### 难点2：人员信息弹窗

**问题**：datagrid 新增行后，"姓名"列的放大镜按钮（`.mini-buttonedit-button`）需要先让 cell 进入编辑模式才会出现（作为 `.mini-grid-editwrap` 的子元素）。

**解决方案**：
1. 点击最后一行姓名列 cell → 等 editwrap 出现 → 用 `page.mouse.click()` 点 `.mini-grid-editwrap .mini-buttonedit-button`
2. 弹窗打开后，在包含"身份证号"文字的 iframe 中找到 `query_staffIdentification$text` 输入框
3. 填写身份证号 → 点"查询" → 等3秒 → 双击结果行 → 点"确定" → 弹窗关闭，人员数据代入 datagrid

```python
# 点击cell进入编辑
cell = frame.locator('.mini-grid-row:last-child td').nth(2)
cell.click()
# 等editwrap出现，点button
btn = frame.locator('.mini-grid-editwrap .mini-buttonedit-button:visible').first
box = btn.bounding_box()
page.mouse.click(box['x']+box['width']/2, box['y']+box['height']/2)
```

### 难点3：编码问题

lark-cli 输出使用系统编码（Windows GBK），字段名乱码。**全部使用字段索引**而非字段名：
- `keys[9]` = 需求编号/合作申请单编号
- `keys[10]` = 公司/签约方
- `keys[4]` = 供应商/外包商
- `keys[5]` = 身份证号
- `keys[7]` = 姓名
- `keys[14]` = 校正上岗时间
- `keys[20]` = 是否签署
- `keys[21]` = 未成功提交原因

lark-cli subprocess: `encoding="utf-8", errors="replace"`

### 难点4：提交后弹窗确定按钮

MiniUI 确认弹窗的"确定"按钮可能不在主页面，需在所有 frame 中广泛搜索：
```python
for ctx in [page] + list(page.frames):
    for sel in ['a:has-text("确定")', 'button:has-text("确定")', ...]:
        btn = ctx.locator(sel).first
        if btn.count() > 0: btn.click(force=True)
```

## 关键原则

- **永远不要用 `frame.evaluate("functionName()")` 触发MiniUI弹窗** — 会破坏弹窗状态
- **用 `page.mouse.click()` 产生 trusted 事件**
- **弹窗操作优先在对应 iframe 内进行**
- **字段名一律用索引，避免编码问题**
