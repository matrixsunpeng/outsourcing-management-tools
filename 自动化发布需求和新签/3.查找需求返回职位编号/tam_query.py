"""
TAM查询招聘任务模块 - 在查询招聘任务页面搜索并匹配职位编号
流程：导航到查询页面 → 设置筛选条件 → 查询 → 遍历第1-2页匹配记录 → 提取职位编号
"""

from playwright.sync_api import Page
from datetime import datetime, timedelta


def navigate_to_query_task(page: Page) -> Page:
    """
    导航到"查询招聘任务"页面。
    路径: 人才招聘 > 招聘任务 > 查询招聘任务
    """
    print("  正在导航到查询招聘任务页面...")

    # 关闭可能的弹窗
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    # 点击左侧功能栏 "人才招聘"（可能已展开）
    try:
        recruit_menu = page.locator('text=人才招聘').first
        if recruit_menu.is_visible(timeout=5000):
            recruit_menu.click()
            page.wait_for_timeout(1000)
            print("  已点击 '人才招聘'")
    except Exception:
        pass

    # 点击 "招聘任务"
    try:
        task_menu = page.locator('text=招聘任务').first
        if task_menu.is_visible(timeout=5000):
            task_menu.click()
            page.wait_for_timeout(1000)
            print("  已点击 '招聘任务'")
    except Exception as e:
        print(f"  [WARN] 点击 '招聘任务' 失败: {e}")

    # 点击 "查询招聘任务"
    _click_menu_item(page, "查询招聘任务")

    page.wait_for_load_state("networkidle", timeout=15000)
    page.wait_for_timeout(2000)
    print("  导航完成")
    return page


def _click_menu_item(page: Page, text: str):
    """点击侧边栏菜单项"""
    selectors = [
        f'text={text}',
        f'a:has-text("{text}")',
        f'span:has-text("{text}")',
        f'li:has-text("{text}")',
        f'.ant-menu-item:has-text("{text}")',
        f'[title="{text}"]',
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=3000):
                el.click()
                page.wait_for_timeout(2000)
                print(f"  已点击 '{text}'")
                return
        except Exception:
            continue

    # JS 回退
    try:
        page.evaluate(f"""() => {{
            var all = document.querySelectorAll('a, span, li, button, div');
            for (var el of all) {{
                if (el.textContent.trim() === '{text}') {{
                    el.click();
                    return true;
                }}
            }}
            return false;
        }}""")
        page.wait_for_timeout(2000)
        print(f"  已通过JS点击 '{text}'")
    except Exception:
        print(f"  [WARN] 未找到 '{text}' 菜单")


def set_filters_and_search(page: Page) -> Page:
    """
    在查询招聘任务页面设置筛选条件并查询。
    - 点击"展开"按钮显示全部筛选条件
    - 发布状态: 选"已发布"
    - 聘用形式: 选"外包"
    - 所属BU: 选"185(亚信科技CMB)"
    - 点击"查询"
    """
    print("  正在设置筛选条件...")

    # 1. 点击"展开"按钮
    try:
        expand_btn = page.locator('button:has-text("展开"), span:has-text("展开"), a:has-text("展开")').first
        if expand_btn.is_visible(timeout=3000):
            expand_btn.click()
            page.wait_for_timeout(1000)
            print("  已点击 '展开'")
    except Exception:
        pass

    # 2. 发布状态 → 选"已发布"（radio/checkbox 组，通常是第2个选项）
    _select_filter_option(page, "已发布")

    # 3. 聘用形式 → 选"外包"（通常是第4个选项）
    _select_filter_option(page, "外包")

    # 4. 所属BU → 输入/选择 "185"
    _select_bu(page, "185")

    # 关闭可能残留的下拉框
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)

    # 5. 点击"查询"按钮
    print("  正在点击查询按钮...")
    clicked = False
    for sel in [
        'button:has-text("查询")',
        'button:has-text("查 询")',
        '.ant-btn:has-text("查询")',
        'button.ant-btn-primary:has-text("查询")',
    ]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=3000):
                btn.click(force=True)
                clicked = True
                print("  已点击查询")
                break
        except Exception:
            continue

    if not clicked:
        try:
            page.evaluate("""() => {
                var btns = document.querySelectorAll('button, a');
                for (var b of btns) {
                    if (b.textContent.trim() === '查询') {
                        b.click();
                        return true;
                    }
                }
                return false;
            }""")
            print("  已通过JS点击查询")
        except Exception as e:
            print(f"  [WARN] 点击查询失败: {e}")

    page.wait_for_load_state("networkidle", timeout=15000)
    page.wait_for_timeout(3000)
    print("  查询完成，等待结果加载...")
    return page


def _select_filter_option(page: Page, option_text: str):
    """选择筛选条件中的选项（radio/checkbox 或 select 下拉）"""
    # 先尝试找包含目标文字的 label/radio/checkbox
    try:
        target = page.locator(f'.ant-radio-wrapper:has-text("{option_text}"), '
                             f'.ant-checkbox-wrapper:has-text("{option_text}"), '
                             f'label:has-text("{option_text}")').first
        if target.is_visible(timeout=2000):
            # 检查是否已被选中
            radio_input = target.locator('input[type="radio"], input[type="checkbox"]').first
            if radio_input.count() > 0 and not radio_input.is_checked():
                target.click()
                page.wait_for_timeout(500)
                print(f"  已选择: {option_text}")
                return
            elif radio_input.count() == 0:
                target.click()
                page.wait_for_timeout(500)
                print(f"  已点击: {option_text}")
                return
            else:
                print(f"  {option_text} 已选中，跳过")
                return
    except Exception:
        pass

    # 通过 JS 查找并点击
    try:
        page.evaluate(f"""() => {{
            var labels = document.querySelectorAll('.ant-radio-wrapper, .ant-checkbox-wrapper, label');
            for (var l of labels) {{
                if (l.textContent.includes('{option_text}')) {{
                    var input = l.querySelector('input');
                    if (input && !input.checked) {{
                        l.click();
                        return 'clicked';
                    }} else if (!input) {{
                        l.click();
                        return 'clicked';
                    }}
                    return 'already_checked';
                }}
            }}
            return 'not_found';
        }}""")
        print(f"  已通过JS选择: {option_text}")
    except Exception as e:
        print(f"  [WARN] 选择 '{option_text}' 失败: {e}")


def _select_bu(page: Page, bu_text: str):
    """在所属BU字段选择185(亚信科技CMB)"""
    # 先尝试找"所属BU"的 ant-select 组件并点击打开
    try:
        # 找到包含"所属BU"文字的区域，向上找 ant-form-item，再找其中的 ant-select
        bu_label = page.locator('text=所属BU').first
        if bu_label.is_visible(timeout=3000):
            form_item = bu_label.locator('xpath=ancestor::div[contains(@class,"ant-form-item")]')
            if form_item.count() > 0:
                select = form_item.locator('.ant-select').first
                if select.count() > 0 and select.is_visible():
                    select.click()
                    page.wait_for_timeout(800)
                    _select_from_dropdown(page, bu_text)
                    page.wait_for_timeout(300)
                    return
    except Exception:
        pass

    # 通过 JS 查找所属BU并操作
    try:
        page.evaluate(f"""() => {{
            var all = document.querySelectorAll('*');
            for (var el of all) {{
                if (el.textContent.trim() === '所属BU' || el.textContent.trim().startsWith('所属BU')) {{
                    var formItem = el.closest('.ant-form-item');
                    if (formItem) {{
                        var select = formItem.querySelector('.ant-select');
                        if (select) {{
                            select.click();
                            return true;
                        }}
                    }}
                }}
            }}
            return false;
        }}""")
        page.wait_for_timeout(1000)
        _select_from_dropdown(page, bu_text)
        page.wait_for_timeout(300)
    except Exception as e:
        print(f"  [WARN] 选择所属BU失败: {e}")


def _select_from_dropdown(page: Page, text: str):
    """从 ant-select 下拉框中模糊匹配选择，选中后关闭下拉框"""
    try:
        page.wait_for_timeout(500)
        # 先尝试在下拉搜索框中输入
        search_input = page.locator('.ant-select-dropdown:visible .ant-select-search__field').first
        if search_input.is_visible(timeout=2000):
            search_input.fill(text)
            page.wait_for_timeout(1000)

        # 选择匹配的选项
        options = page.locator('.ant-select-dropdown:visible .ant-select-item-option, '
                               '.ant-select-dropdown:visible li').all()
        for opt in options:
            try:
                opt_text = opt.text_content().strip()
                if text in opt_text:
                    opt.click()
                    page.wait_for_timeout(500)
                    print(f"  已选择BU: {opt_text}")
                    # 选中后按 Escape 关闭下拉框
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)
                    return
            except Exception:
                continue
    except Exception:
        pass

    # 找不到匹配时也关闭下拉框
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass
    print(f"  [WARN] 下拉框中未匹配到: {text}")


def find_position_for_record(page: Page, record: dict) -> str:
    """
    在查询结果中为一条多维表记录查找匹配的职位编号。
    搜索范围：第1页和第2页。
    策略：以申请单编号为锚点，在它周围的 DOM 区域内提取职位编号和创建时间。
    """
    application_code = str(record.get("合作申请单编号", "")).strip()
    publish_time_str = str(record.get("发布时间", "")).strip()
    supplier = str(record.get("供应商", "")).strip()

    if not application_code:
        print("    [WARN] 记录无合作申请单编号，跳过")
        return ""

    print(f"    查找: 合作申请单编号={application_code}, 发布时间={publish_time_str}, 供应商={supplier}")

    # 确保从第1页开始
    _go_to_page(page, 1)
    page.wait_for_timeout(2000)

    result = _search_and_match(page, application_code, publish_time_str, supplier)
    if result:
        return result

    if _go_to_page(page, 2):
        print("    已翻到第2页，继续查找...")
        page.wait_for_timeout(3000)
        result = _search_and_match(page, application_code, publish_time_str, supplier)
        if result:
            return result

    print(f"    [WARN] 未找到匹配的职位: {application_code}")
    return ""


def _search_and_match(page: Page, application_code: str, publish_time_str: str, supplier: str) -> str:
    """
    在当前页面查找目标申请单编号，提取关联的职位编号和创建时间，验证后返回。
    """
    match_data = page.evaluate(f"""() => {{
        var result = {{position_codes: [], creation_time: ''}};

        // 在页面上找所有包含目标申请单编号的文本节点
        var walker = document.createTreeWalker(
            document.body,
            NodeFilter.SHOW_TEXT,
            null,
            false
        );
        var node;
        while (node = walker.nextNode()) {{
            if (node.textContent.indexOf('{application_code}') === -1) continue;

            // 从这个节点向上找包含"职位编号"和"创建时间"的容器
            var el = node.parentElement;
            for (var level = 0; level < 15; level++) {{
                if (!el || el === document.body) break;
                var text = el.textContent || '';

                // 确认这个容器里同时有申请单号、创建时间
                if (text.indexOf('外包申请单编号') !== -1 && text.indexOf('创建时间') !== -1) {{
                    // 提取职位编号（可能有多个）
                    var posRegex = /职位编号[：:]\\s*(\\d+)/g;
                    var pm;
                    while ((pm = posRegex.exec(text)) !== null) {{
                        if (result.position_codes.indexOf(pm[1]) === -1) {{
                            result.position_codes.push(pm[1]);
                        }}
                    }}

                    // 提取创建时间
                    var tm = text.match(/创建时间[：:]\\s*(\\d{{4}}[-/]\\d{{1,2}}[-/]\\d{{1,2}}\\s+\\d{{1,2}}:\\d{{2}}(?::\\d{{2}})?)/);
                    if (tm) {{
                        result.creation_time = tm[1];
                    }}

                    if (result.position_codes.length > 0) {{
                        return result;
                    }}
                }}
                el = el.parentElement;
            }}
        }}
        return result;
    }}""")

    position_codes = match_data.get("position_codes", [])
    creation_time = match_data.get("creation_time", "")

    if not position_codes:
        return ""

    print(f"    找到职位编号: {position_codes}, 创建时间: {creation_time}")

    # 时间校验
    if publish_time_str and creation_time:
        if not _is_time_within_10_minutes(publish_time_str, creation_time):
            print(f"      时间不匹配: 记录发布时间={publish_time_str}, 页面创建时间={creation_time}")
            return ""
        print(f"      时间匹配: 发布时间≈创建时间({creation_time})")

    # 供应商校验：以申请单编号定位区域 → 点击"查看" → 提取供应商名称
    if supplier:
        page_supplier = _check_supplier(page, application_code)
        if page_supplier:
            safe = page_supplier.replace('\xa0', ' ').replace('　', ' ')
            if supplier in page_supplier or page_supplier in supplier:
                print(f"      供应商匹配: {supplier}")
            else:
                print(f"      [WARN] 供应商不一致: 记录=[{supplier}], 页面内容=[{safe[:100]}]（不阻断匹配）")
        else:
            print(f"      [WARN] 无法获取供应商信息，跳过校验（不阻断匹配）")

    return ",".join(position_codes)


def _check_supplier(page: Page, application_code: str) -> str:
    """
    在包含目标申请单编号的职位区域中点击"查看"按钮，获取供应商名称。
    申请单编号是已知输入，用它定位区域 → 找最近的"查看" → 提取供应商。
    """
    # 用申请单编号定位，找到离它最近的"查看"按钮并标记唯一ID
    marked = page.evaluate(f"""() => {{
        // 计算两个DOM节点之间的距离（通过最近公共祖先）
        function domDistance(el1, el2) {{
            var path = [];
            var cur = el1;
            while (cur) {{
                path.push(cur);
                cur = cur.parentElement;
            }}
            var dist = 0;
            cur = el2;
            while (cur) {{
                var idx = path.indexOf(cur);
                if (idx !== -1) return dist + idx;
                dist++;
                cur = cur.parentElement;
            }}
            return Infinity;
        }}

        var walker = document.createTreeWalker(
            document.body,
            NodeFilter.SHOW_TEXT,
            null,
            false
        );
        var node;
        while (node = walker.nextNode()) {{
            if (node.textContent.indexOf('{application_code}') === -1) continue;

            var startEl = node.parentElement;

            // 向上遍历找包含"外包申请单编号"和"查看"的容器
            var area = startEl;
            var container = null;
            for (var i = 0; i < 20; i++) {{
                if (!area || area === document.body) break;
                var at = area.textContent || '';
                if (at.indexOf('外包申请单编号') !== -1 &&
                    (at.indexOf('查看') !== -1 || at.indexOf('渠道类型') !== -1 || at.indexOf('招聘渠道') !== -1)) {{
                    container = area;
                    break;
                }}
                area = area.parentElement;
            }}

            if (!container) continue;

            // 在容器内找到所有"查看"元素，计算每个与startEl的DOM距离
            var bestViewBtn = null;
            var bestDistance = Infinity;

            function searchViewBtns(root) {{
                var all = root.querySelectorAll('button, a, span, div, [role="button"]');
                for (var j = 0; j < all.length; j++) {{
                    if (all[j].textContent.trim() === '查看') {{
                        var d = domDistance(startEl, all[j]);
                        if (d < bestDistance) {{
                            bestDistance = d;
                            bestViewBtn = all[j];
                        }}
                    }}
                }}
                var kids = root.querySelectorAll('*');
                for (var j = 0; j < kids.length; j++) {{
                    if (kids[j].childNodes.length === 1 && kids[j].textContent.trim() === '查看') {{
                        var d = domDistance(startEl, kids[j]);
                        if (d < bestDistance) {{
                            bestDistance = d;
                            bestViewBtn = kids[j];
                        }}
                    }}
                }}
            }}

            searchViewBtns(container);

            if (bestViewBtn) {{
                bestViewBtn.setAttribute('data-view-target', '{application_code}');
                return 'marked';
            }}
            return 'marked_no_view';
        }}
        return 'not_found';
    }}""")

    if marked == 'not_found':
        return ""
    if marked == 'marked_no_view':
        print(f"      区域内未找到'查看'按钮")
        return ""

    # 先关闭可能残留的弹窗/popover（来自上一条记录的点击）
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass

    # 记录点击前的页面文本和已有的popover元素
    before_text = page.evaluate("""() => document.body.innerText || ''""")
    existing_popovers = page.evaluate("""() => {
        var sel = '.ant-popover:not(.ant-popover-hidden) .ant-popover-inner, '
            + '.ant-tooltip:not(.ant-tooltip-hidden) .ant-tooltip-inner, '
            + '[class*="popover"]:not([class*="hidden"]) [class*="content"], '
            + '[class*="popover"]:not([class*="hidden"]) [class*="inner"], '
            + '[class*="bubble"]:not([class*="hidden"]), '
            + '[class*="tooltip"]:not([class*="hidden"]) [class*="inner"]';
        var pops = document.querySelectorAll(sel);
        var ids = [];
        for (var i = 0; i < pops.length; i++) {
            pops[i].setAttribute('data-previous-popover', 'true');
            ids.push(pops[i].textContent.trim().substring(0, 30));
        }
        return ids;
    }""")

    # 点击已标记的、离申请单编号最近的"查看"按钮
    try:
        view_btn = page.locator(f'[data-view-target="{application_code}"]')
        if view_btn.is_visible(timeout=2000):
            view_btn.click()
            print(f"      '查看'已点击")
        else:
            print(f"      '查看'按钮不可见")
            return ""
    except Exception as e:
        print(f"      点击'查看'失败: {e}")
        return ""

    # 等待色块出现
    page.wait_for_timeout(2000)

    # 查找点击后新出现的 popover/tooltip（排除点击前已存在的）
    supplier = page.evaluate("""(before) => {
        var afterText = document.body.innerText || '';
        var beforeSet = {};
        before.split('\\n').forEach(function(l) { var t = l.trim(); if (t) beforeSet[t] = true; });

        // 优先使用 popover/tooltip 元素的内容，但排除点击前已存在的
        var popSel = '.ant-popover:not(.ant-popover-hidden) .ant-popover-inner, '
            + '.ant-tooltip:not(.ant-tooltip-hidden) .ant-tooltip-inner, '
            + '[class*="popover"]:not([class*="hidden"]) [class*="content"], '
            + '[class*="popover"]:not([class*="hidden"]) [class*="inner"], '
            + '[class*="bubble"]:not([class*="hidden"]), '
            + '[class*="tooltip"]:not([class*="hidden"]) [class*="inner"]';
        var pops = document.querySelectorAll(popSel);
        for (var j = 0; j < pops.length; j++) {
            // 跳过点击前就已存在的popover
            if (pops[j].hasAttribute('data-previous-popover')) continue;
            var text = (pops[j].textContent || '').trim();
            if (text.length >= 2 && text.length <= 50) return text;
        }

        // 找新增的、看起来像公司/供应商名称的行
        var lines = afterText.split('\\n');
        for (var i = 0; i < lines.length; i++) {
            var t = lines[i].trim();
            if (t.length >= 2 && t.length <= 30 &&
                !beforeSet[t] &&
                t !== '查看' &&
                !/^[\\d\\s.,，、。;；:：|/()（）\\-【】]+$/.test(t) &&
                t.indexOf('全选') === -1 &&
                t.indexOf('共') === -1 &&
                t.indexOf('每页') === -1 &&
                t.indexOf('渠道类型') === -1 &&
                t.indexOf('招聘渠道') === -1 &&
                t.indexOf('首页') === -1) {
                return t;
            }
        }
        return '';
    }""", before_text)

    # 关闭弹窗
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass
    for sel in ['.ant-modal-close', '.ant-drawer-close', '.ant-btn:has-text("关闭")', '.ant-btn:has-text("取消")']:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                btn.click()
                page.wait_for_timeout(300)
                break
        except Exception:
            continue

    return supplier.strip() if supplier else ""


def _is_time_within_10_minutes(t1: str, t2: str) -> bool:
    """判断两个时间字符串是否相差不超过10分钟"""
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
    ]
    dt1 = dt2 = None
    for fmt in formats:
        try:
            dt1 = datetime.strptime(t1, fmt)
            break
        except ValueError:
            continue
    for fmt in formats:
        try:
            dt2 = datetime.strptime(t2, fmt)
            break
        except ValueError:
            continue

    if dt1 is None or dt2 is None:
        return False

    diff = abs((dt1 - dt2).total_seconds())
    return diff <= 600  # 10 minutes


def _go_to_page(page: Page, page_num: int) -> bool:
    """翻到指定页码"""
    try:
        # 查找页码按钮
        page_btn = page.locator(f'.ant-pagination-item:has-text("{page_num}"), '
                                f'.ant-pagination-item-{page_num}, '
                                f'li:has-text("{page_num}")').first
        if page_btn.is_visible(timeout=3000):
            page_btn.click()
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(2000)
            print(f"  已翻到第{page_num}页")
            return True
    except Exception:
        pass

    # JS 方式点击
    try:
        result = page.evaluate(f"""() => {{
            var items = document.querySelectorAll('.ant-pagination-item, .ant-pagination li');
            for (var item of items) {{
                if (item.textContent.trim() === '{page_num}') {{
                    item.click();
                    return true;
                }}
            }}
            return false;
        }}""")
        if result:
            page.wait_for_timeout(3000)
            return True
    except Exception:
        pass

    print(f"  [WARN] 未找到第{page_num}页按钮")
    return False
