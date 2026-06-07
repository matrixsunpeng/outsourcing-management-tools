"""
TAM发布需求模块 - 在新建招聘任务页面填写表单并发布
基于 Ant Design 组件库，表单结构为 ant-form-item + label[title]
流程：选招聘性质 → 点外包申请单编号弹窗选单 → 等待表单动态加载 → 填写其余字段 → 发布
"""

from playwright.sync_api import Page, Frame
from datetime import datetime, timedelta


def fill_and_publish(page: Page, record: dict, auto_yes: bool = False) -> bool:
    """
    在"新建招聘任务"页面填写表单并发布。
    record: 多维表记录字段字典
    auto_yes: True 时跳过交互确认，自动发布
    返回是否发布成功
    """
    try:
        # 1. 选择"招聘性质"为"新增"（radio，默认已选中新增，确认一下）
        print("  [1] 确认招聘性质: 新增")
        _ensure_radio_new(page)

        # 2. 填写"外包申请单编号"弹窗选择
        application_code = str(record.get("合作申请单编号", "")).strip()
        if application_code:
            print(f"  [2] 选择外包申请单编号: {application_code}")
            _select_application_code(page, application_code)
        else:
            print("  [2] [WARN] 无合作申请单编号，跳过")
            return False

        # 等待表单动态加载
        print("  等待表单字段加载...")
        page.wait_for_timeout(3000)

        # 确认表单已加载（检查招聘协同专员字段是否出现）
        _wait_for_form_loaded(page)

        # 3. 招聘协同专员（ant-select 下拉框）
        recruiter = str(record.get("招聘协同专员", "")).strip()
        if not recruiter:
            recruiter = str(record.get("申请人", "")).strip()
        if recruiter:
            print(f"  [3] 选择招聘协同专员: {recruiter}")
            _fill_form_select(page, "招聘协同专员", recruiter)

        # 4. 职位类别（下拉模糊匹配）
        position = str(record.get("岗位", "")).strip()
        if position:
            print(f"  [4] 选择职位类别: {position}")
            _fill_form_select(page, "职位类别", position)

        # 5. 招聘人数
        headcount = record.get("技术合作人员数量", "")
        try:
            headcount = str(int(float(str(headcount).replace(",", ""))))
        except (ValueError, TypeError):
            headcount = "1"
        print(f"  [5] 填写招聘人数: {headcount}")
        _fill_form_input(page, "招聘人数", headcount)

        # 6. 招聘需求截止日期（当天+15天）
        deadline = (datetime.now() + timedelta(days=15)).strftime("%Y/%m/%d")
        print(f"  [6] 填写招聘需求截止日期: {deadline}")
        _fill_form_date(page, "招聘需求截止日期", deadline)

        # 7. 工作年限 - 选择"1-3年"
        print("  [7] 选择工作年限: 1-3年")
        _fill_form_select(page, "工作年限", "1-3年")

        # 8. 学历要求 - 选择"本科"
        print("  [8] 选择学历要求: 本科")
        _fill_form_select(page, "学历要求", "本科")

        # 9. 实际工作地
        work_location = str(record.get("工作地点", "")).strip()
        if work_location:
            print(f"  [9] 选择实际工作地: {work_location}")
            _fill_form_select(page, "实际工作地", work_location)

        # 10. 招聘原因
        work_content = str(record.get("工作内容", "")).strip()
        if work_content:
            print(f"  [10] 填写招聘原因")
            _fill_form_textarea(page, "招聘原因", work_content)

        # 11. 岗位职责
        if work_content:
            print(f"  [11] 填写岗位职责")
            _fill_form_textarea(page, "岗位职责", work_content)

        # 12. 任职要求
        skill_req = str(record.get("技能要求", "")).strip()
        if skill_req:
            print(f"  [12] 填写任职要求")
            _fill_form_textarea(page, "任职要求", skill_req)

        # 13. 是否参与考评 - 选择"参与"
        print("  [13] 选择是否参与考评: 参与")
        _select_form_radio(page, "参与")

        # 14. 招聘渠道（页面下方）- 选中供应商
        supplier = str(record.get("供应商", "")).strip()
        if supplier:
            print(f"  [14] 选择招聘渠道供应商: {supplier}")
            _select_supplier(page, supplier)
            # 勾选后等待 number 输入框从 disabled 变为 enabled
            page.wait_for_timeout(1000)

        # 15. 招聘渠道分配人数
        allocated_count = record.get("分配人数", "")
        try:
            allocated_count = str(int(float(str(allocated_count).replace(",", ""))))
        except (ValueError, TypeError):
            allocated_count = headcount
        if supplier:
            print(f"  [15] 填写供应商分配人数: {allocated_count}")
            _fill_supplier_count(page, supplier, allocated_count)

        page.wait_for_timeout(1000)

        # 16. 提示用户确认后发布
        if not auto_yes:
            print("\n  ====================================")
            print("  请检查浏览器页面中的表单内容！")
            print("  ====================================")
            confirm = input("  确认发布？(Y/N): ").strip().upper()

            if confirm != "Y":
                print("  用户取消发布，跳过当前记录")
                return False
        else:
            print("\n  [自动模式] 跳过确认，直接发布...")

        # 点击"发布"按钮
        print("  正在点击发布按钮...")
        _click_publish(page)

        # 等待提交结果
        page.wait_for_timeout(5000)
        print("  发布操作已执行")
        return True

    except Exception as e:
        print(f"  [ERROR] 填写表单异常: {e}")
        import traceback
        traceback.print_exc()
        return False


# ---- 核心表单操作（基于 Ant Design）----


def _ensure_radio_new(page: Page):
    """确保招聘性质选择"新增"（默认已选，仅确认）"""
    try:
        radio = page.locator('input.ant-radio-input[value="NEW"]')
        if radio.count() > 0 and not radio.first.is_checked():
            radio.first.click(force=True)
    except Exception:
        pass


def _select_application_code(page: Page, code: str):
    """
    点击外包申请单编号的自定义选择组件 → 弹窗 → 输入编号 → 查询 → 选第1条 → 确定
    """
    try:
        # 点击自定义选择组件打开弹窗
        custom_select = page.locator('.index_likeSelect__3RR5d')
        if custom_select.count() > 0:
            custom_select.first.click()
            page.wait_for_timeout(2000)

            # 在弹窗中找到"外包申请单编号"输入框（ant-modal 内的 ant-input）
            modal = page.locator('.ant-modal-body:visible')
            if modal.count() > 0:
                # 找弹窗中的外包申请单编号输入框
                code_input = modal.locator('label[title="外包申请单编号"]')
                if code_input.count() > 0:
                    # 找到同行的 input
                    form_item = code_input.locator('xpath=ancestor::div[contains(@class,"ant-form-item")]')
                    inp = form_item.locator('input.ant-input').first
                    if inp.is_visible(timeout=3000):
                        inp.fill(code)
                        page.wait_for_timeout(500)
                else:
                    # 尝试直接找弹窗中的第一个input
                    inp = modal.locator('input.ant-input').first
                    if inp.is_visible(timeout=3000):
                        inp.fill(code)
                        page.wait_for_timeout(500)

                # 点击弹窗中的"查询"按钮
                query_btn = modal.locator('button:has-text("查询"), button:has-text("查 询")')
                if query_btn.count() > 0:
                    query_btn.first.click()
                    page.wait_for_timeout(3000)

                    # 选中第1条记录（ant-table 行）
                    table_row = modal.locator('.ant-table-row, .ant-table-tbody tr').first
                    if table_row.is_visible(timeout=5000):
                        # 点击行中的radio或checkbox，或直接点击行
                        row_radio = table_row.locator('input[type="radio"], input[type="checkbox"]').first
                        if row_radio.is_visible(timeout=2000):
                            row_radio.click(force=True)
                        else:
                            table_row.click()
                        page.wait_for_timeout(500)
                    else:
                        print("    [WARN] 弹窗中未找到查询结果行")

                    # 点击"确定"按钮
                    ok_btn = page.locator('.ant-modal button.ant-btn-background-ghost:has-text("确定")')
                    if ok_btn.count() > 0:
                        ok_btn.first.click()
                        page.wait_for_timeout(2000)
                    else:
                        ok_btn2 = page.locator('.ant-modal button:has-text("确定")')
                        if ok_btn2.count() > 0:
                            ok_btn2.first.click()
                            page.wait_for_timeout(2000)
            else:
                print("    [WARN] 弹窗未出现")
        else:
            print("    [WARN] 未找到外包申请单编号选择组件")
    except Exception as e:
        print(f"    [WARN] 选择外包申请单编号失败: {e}")


def _wait_for_form_loaded(page: Page, timeout: int = 15000):
    """等待表单字段动态加载完成（选择外包申请单后）"""
    try:
        # 等待招聘协同专员字段出现
        page.locator('label[title="招聘协同专员"], label[title="招聘协同专员:"]').first.wait_for(
            state="visible", timeout=timeout
        )
        print("  表单字段已加载")
    except Exception:
        # 可能字段名不完全匹配，等待一段时间后继续
        page.wait_for_timeout(5000)
        print("  [WARN] 未检测到招聘协同专员字段，继续执行")


def _find_form_item(page: Page, label_title: str) -> "Locator | None":
    """
    根据label的title属性找到对应的ant-form-item
    label[title] 可能带冒号如 "外包申请单编号:"
    """
    # 尝试精确匹配和带冒号匹配
    for title in [label_title, label_title + ":", label_title + "："]:
        label = page.locator(f'label[title="{title}"]')
        if label.count() > 0:
            try:
                if label.first.is_visible(timeout=2000):
                    form_item = label.first.locator('xpath=ancestor::div[contains(@class,"ant-form-item")]')
                    if form_item.count() > 0:
                        return form_item.first
            except Exception:
                continue
    return None


def _fill_form_input(page: Page, label_title: str, value: str):
    """填写 ant-form-item 中的 input 或 ant-input-number"""
    form_item = _find_form_item(page, label_title)
    if form_item:
        # ant-input-number 的 input
        num_input = form_item.locator('input.ant-input-number-input').first
        if num_input.is_visible(timeout=3000):
            num_input.click()
            # ant-input-number 是 React 组件，需要用 JS 设值
            num_input.evaluate(f"""(el) => {{
                var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                nativeInputValueSetter.call(el, '{value}');
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
            }}""")
            page.wait_for_timeout(300)
            num_input.press("Tab")
            return
        # 普通 ant-input
        inp = form_item.locator('input.ant-input').first
        if inp.is_visible(timeout=3000):
            inp.click()
            inp.fill(value)
            inp.press("Tab")
            return
    print(f"    [WARN] 未找到输入框: {label_title}")


def _fill_form_select(page: Page, label_title: str, value: str):
    """
    填写 ant-form-item 中的 ant-select 下拉框
    点击下拉框 → 在搜索框输入文字 → 从下拉选项中匹配选择
    """
    form_item = _find_form_item(page, label_title)
    if not form_item:
        print(f"    [WARN] 未找到下拉框: {label_title}")
        return

    # 点击 ant-select 打开下拉
    select = form_item.locator('.ant-select').first
    if not select.is_visible(timeout=3000):
        print(f"    [WARN] 下拉框不可见: {label_title}")
        return

    select.click()
    page.wait_for_timeout(500)

    # 在搜索框中输入（ant-select 支持搜索）
    search_input = form_item.locator('.ant-select-search__field, input.ant-select-search__field').first
    if search_input.is_visible(timeout=1000):
        search_input.fill(value)
        page.wait_for_timeout(1000)
    else:
        # 非搜索型 select，直接尝试匹配选项
        pass

    # 从下拉选项中匹配选择
    _select_ant_option(page, value)


def _fill_form_date(page: Page, label_title: str, date_str: str):
    """
    填写 ant-form-item 中的日期选择器
    点击文本框 → 弹出日历弹窗 → 全选清空默认日期 → 输入新日期 → 回车确认
    """
    form_item = _find_form_item(page, label_title)
    if form_item:
        date_input = form_item.locator('input.ant-calendar-picker-input, input.ant-input').first
        if date_input.is_visible(timeout=3000):
            # 点击激活日期选择器（弹出日历弹窗）
            date_input.click()
            page.wait_for_timeout(500)
            # 全选默认日期文本
            page.keyboard.press("Control+a")
            page.wait_for_timeout(200)
            # 输入新日期（会替换选中的默认日期）
            page.keyboard.type(date_str, delay=50)
            page.wait_for_timeout(300)
            # 回车确认
            page.keyboard.press("Enter")
            page.wait_for_timeout(500)
            return
    print(f"    [WARN] 未找到日期选择器: {label_title}")


def _fill_form_textarea(page: Page, label_title: str, value: str):
    """填写 ant-form-item 中的 textarea"""
    form_item = _find_form_item(page, label_title)
    if form_item:
        textarea = form_item.locator('textarea').first
        if textarea.is_visible(timeout=3000):
            textarea.fill(value)
            return
        # 尝试 input
        inp = form_item.locator('input.ant-input').first
        if inp.is_visible(timeout=2000):
            inp.fill(value)
            return
    print(f"    [WARN] 未找到文本域: {label_title}")


def _select_form_radio(page: Page, value: str):
    """选择 ant-form-item 中的 radio 选项"""
    try:
        # 找到包含目标文字的 radio-wrapper
        radio = page.locator(f'.ant-radio-wrapper:has-text("{value}")').first
        if radio.is_visible(timeout=3000):
            radio.click()
            return
    except Exception:
        pass
    print(f"    [WARN] 未找到radio选项: {value}")


def _select_ant_option(page: Page, value: str):
    """从 ant-select 下拉选项中匹配选择（模糊）"""
    try:
        # 等待下拉菜单出现
        page.wait_for_timeout(500)
        options = page.locator('.ant-select-dropdown:visible .ant-select-item-option, .ant-select-dropdown:visible li').all()
        # 先精确匹配
        for opt in options:
            try:
                text = opt.text_content().strip()
                if text == value:
                    opt.click()
                    return
            except Exception:
                continue
        # 再模糊匹配
        for opt in options:
            try:
                text = opt.text_content().strip()
                if value in text or text in value:
                    opt.click()
                    return
            except Exception:
                continue
    except Exception:
        pass
    print(f"    [WARN] 下拉选项未匹配: {value}")


def _select_supplier(page: Page, supplier: str):
    """在页面下方选择招聘渠道的供应商（ant-checkbox）"""
    suppliers = supplier.split(",") if "," in supplier else [supplier]
    for s in suppliers:
        s = s.strip()
        if not s:
            continue
        try:
            # 找包含供应商名称的 ant-checkbox-wrapper
            checkbox = page.locator(f'.ant-checkbox-wrapper:has-text("{s}")').first
            if checkbox.is_visible(timeout=3000):
                checkbox.click()
                page.wait_for_timeout(300)
                continue
        except Exception:
            pass
        # 回退：遍历所有checkbox查找
        try:
            page.evaluate(f"""() => {{
                var wrappers = document.querySelectorAll('.ant-checkbox-wrapper');
                for (var w of wrappers) {{
                    if (w.textContent.includes('{s}')) {{
                        var cb = w.querySelector('input[type="checkbox"]');
                        if (cb && !cb.checked) {{ w.click(); return true; }}
                    }}
                }}
                return false;
            }}""")
        except Exception as e:
            print(f"    [WARN] 选择供应商 '{s}' 失败: {e}")


def _fill_supplier_count(page: Page, supplier: str, count: str):
    """
    填写供应商对应的分配人数。
    招聘渠道是 ant-table，每行(tr)有3列(td)：渠道类型 | 招聘渠道(checkbox) | 招聘人数(number)
    checkbox 未勾选时 number 是 disabled，需先勾选再填写。
    """
    try:
        suppliers = supplier.split(",") if "," in supplier else [supplier]
        for s in suppliers:
            s = s.strip()
            if not s:
                continue
            # 用 JS 找到包含供应商名称的 tr，在招聘人数列中找 number 输入框
            # 注意：第一行有rowspan=10的渠道类型td（3个td），后续行只有2个td
            result = page.evaluate(f"""() => {{
                var rows = document.querySelectorAll('.ant-table-tbody tr');
                for (var tr of rows) {{
                    var tds = tr.querySelectorAll('td');
                    // 第一行: tds[0]=渠道类型(rowspan), tds[1]=招聘渠道, tds[2]=招聘人数
                    // 后续行: tds[0]=招聘渠道, tds[1]=招聘人数
                    var nameTd = tds.length >= 3 ? tds[1] : tds[0];
                    var countTd = tds.length >= 3 ? tds[2] : tds[1];
                    if (nameTd && nameTd.textContent.includes('{s}')) {{
                        var numInput = countTd ? countTd.querySelector('.ant-input-number-input') : null;
                        if (numInput) {{
                            // 移除 disabled（checkbox 勾选后应该已启用，但以防万一）
                            numInput.disabled = false;
                            numInput.removeAttribute('disabled');
                            // 也移除父级 ant-input-number 的 disabled class
                            var numWrap = numInput.closest('.ant-input-number');
                            if (numWrap) numWrap.classList.remove('ant-input-number-disabled');
                            numInput.focus();
                            var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                            nativeInputValueSetter.call(numInput, '{count}');
                            numInput.dispatchEvent(new Event('input', {{bubbles: true}}));
                            numInput.dispatchEvent(new Event('change', {{bubbles: true}}));
                            numInput.dispatchEvent(new Event('blur', {{bubbles: true}}));
                            return true;
                        }}
                    }}
                }}
                return false;
            }}""")
            if result:
                print(f"    供应商 '{s}' 分配人数已填写: {count}")
            else:
                print(f"    [WARN] 未找到供应商 '{s}' 的分配人数输入框（可能未勾选或输入框disabled）")
    except Exception as e:
        print(f"    [WARN] 填写供应商分配人数失败: {e}")


def _click_publish(page: Page):
    """点击发布按钮"""
    try:
        # 找到页面中的"发布"按钮（通常是 ant-btn-primary）
        btn = page.locator('button:has-text("发布")').first
        if btn.is_visible(timeout=5000):
            btn.click()
            return
    except Exception:
        pass

    try:
        # 尝试其他选择器
        btn = page.locator('.ant-btn:has-text("发布")').first
        if btn.is_visible(timeout=3000):
            btn.click()
            return
    except Exception:
        pass

    try:
        page.evaluate("""() => {
            var btns = document.querySelectorAll('button, a');
            for (var b of btns) {
                if (b.textContent.trim() === '发布') {
                    b.click();
                    return true;
                }
            }
            return false;
        }""")
    except Exception as e:
        print(f"    [WARN] 点击发布按钮失败: {e}")
