"""
IMS 外包合同页面自动化模块 - 基于 MiniUI 框架的实际页面结构
合同表单加载在主页面 Tab 内的 iframe 中，所有控件使用 MiniUI API 操作
"""

from playwright.sync_api import Page, Frame
import time, sys
# 输出编码保护
def _safe(s):
    return str(s).encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8', errors='replace')


def navigate_to_contract_page(page: Page) -> Page:
    """
    导航到外包合同页面。
    操作: 双击"外包申请" → 单击"外包合同" → 等待 iframe 加载
    """
    print("  正在导航到外包合同页面...")

    # 先回到首页（关闭其他tabs）
    try:
        page.evaluate("""
            var tabs=mini.get('mainTabs');
            if(tabs){
                var all=tabs.getTabs();
                for(var i=all.length-1;i>=0;i--){
                    if(all[i].name!=='first') tabs.removeTab(all[i]);
                }
                tabs.activeTab(tabs.getTab('first'));
            }
        """)
        page.wait_for_timeout(1000)
    except: pass

    # 第一步: 双击"外包申请"展开子节点
    _dblclick_tree_node(page, "外包申请")
    page.wait_for_timeout(3000)

    # 第二步: 单击"外包合同"（重复尝试确保点击）
    for attempt in range(5):
        nodes = page.locator("span.mini-tree-nodetext").all()
        found = False
        for n in nodes:
            try:
                if n.inner_text().strip() == "外包合同":
                    n.click(force=True)
                    found = True
                    break
            except: continue
        if found:
            print(f"  已单击树节点: 外包合同")
            break
        page.wait_for_timeout(1000)
    else:
        print(f"  [WARN] 未找到外包合同节点")

    print("  等待合同页面加载...")
    page.wait_for_timeout(8000)

    # 第三步: 等待并定位合同表单 iframe
    frame = _wait_for_contract_frame(page)
    if frame:
        print(f"  合同 iframe 已就绪")
        return page
    else:
        print("  [WARN] 未找到合同 iframe，假定在当前页面")
        return page


def get_contract_frame(page: Page):
    """获取合同表单所在的 iframe"""
    return _find_contract_frame(page)


def process_contract_group(page: Page, group: dict, auto_yes: bool = False,
                           bitable_token: str = "", table_id: str = "") -> dict:
    """
    处理一个合同组合的完整新签流程。
    返回: {"status": "SUCCESS"|"SKIPPED"|"FAILED", "reason": str, "record_ids": [...]}
    """
    from feishu_update import update_records_signed, update_records_failure

    app_code = group["application_code"]
    signing_party = group["signing_party"]
    supplier = group["supplier"]
    personnel = group["personnel"]
    record_ids = [p["_record_id"] for p in personnel]

    result = {
        "status": "FAILED",
        "reason": "",
        "record_ids": record_ids,
    }

    try:
        frame = _find_contract_frame(page)
        if not frame:
            result["reason"] = "未找到合同表单iframe"
            _write_failure(bitable_token, table_id, record_ids, result["reason"])
            return result

        # Step 1: 选择合作申请单编号
        print(f"  [1] 选择合作申请单编号: {app_code}")
        if not _select_application_code(page, frame, app_code):
            result["reason"] = "选择合作申请单编号失败"
            _write_failure(bitable_token, table_id, record_ids, result["reason"])
            return result

        # Step 2: 填写签约方和技术合作商名称
        print(f"  [2] 填写签约方: {_safe(signing_party)}")
        _fill_contracting_party(frame, signing_party)
        page.wait_for_timeout(500)

        print(f"  [2b] 填写技术合作商名称: {supplier}")
        _fill_tech_coop(frame, supplier)
        page.wait_for_timeout(1000)

        # Step 3: 添加人员
        print(f"  [3] 添加 {len(personnel)} 名人员...")
        failed_persons = _add_personnel(page, frame, personnel)
        if failed_persons:
            print(f"  [WARN] {len(failed_persons)} 名人员添加失败: {failed_persons}")

        # Step 4: 计算成本
        print(f"  [4] 计算成本...")
        if not _calculate_cost(frame):
            print(f"  [WARN] 成本计算可能未完成，继续提交...")

        # Step 5: 提交确认
        print(f"  [5] 提交确认...")
        if auto_yes:
            print("  [自动模式] 自动确认提交")
            confirmed = True
        else:
            try:
                confirm = input("\n  是否提交？(Y/N): ").strip().upper()
                confirmed = (confirm == "Y")
            except EOFError:
                print("  [WARN] 无交互输入，默认跳过提交")
                confirmed = False

        if not confirmed:
            print("  用户跳过提交")
            result["status"] = "SKIPPED"
            result["reason"] = "用户跳过"
            return result

        # Step 6: 保存并提交审批
        success, msg = _submit_contract(page, frame)

        if success:
            print(f"  签署成功!")
            result["status"] = "SUCCESS"
            if bitable_token and table_id:
                update_records_signed(bitable_token, table_id, record_ids, order_no=msg)
        else:
            print(f"  签署失败: {msg}")
            result["status"] = "FAILED"
            result["reason"] = msg
            if bitable_token and table_id:
                update_records_failure(bitable_token, table_id, record_ids, msg)

    except Exception as e:
        import traceback
        traceback.print_exc()
        result["status"] = "FAILED"
        result["reason"] = str(e)
        if bitable_token and table_id:
            _write_failure(bitable_token, table_id, record_ids, str(e))

    return result


def _write_failure(bitable_token: str, table_id: str, record_ids: list[str], reason: str):
    if bitable_token and table_id:
        from feishu_update import update_records_failure
        update_records_failure(bitable_token, table_id, record_ids, reason)


# ==================== Frame 定位 ====================

def _find_contract_frame(page: Page):
    """找到包含外包合同表单的 iframe"""
    # 先尝试找标题为"技术合作订单"的 frame
    for frame in page.frames:
        try:
            title = frame.evaluate("document.title")
            if "技术合作订单" in title:
                return frame
        except Exception:
            continue

    # 再尝试找 URL 中包含 omsOrderApply 的 frame
    for frame in page.frames:
        if "omsOrderApply" in frame.url:
            return frame

    # 回退: 找 body 中包含合同特征文本的 frame
    for frame in page.frames:
        try:
            body = frame.evaluate("document.body.innerText")
            if "合作申请单编号" in body and "技术合作人员信息" in body:
                return frame
        except Exception:
            continue

    return None


def _wait_for_contract_frame(page: Page, timeout: int = 15) -> Frame | None:
    """等待合同 iframe 加载完成，轮询最多 timeout 秒"""
    import time
    for i in range(timeout):
        frame = _find_contract_frame(page)
        if frame:
            print(f"  找到合同 iframe: {frame.url[:80]}")
            return frame
        if i == 0:
            # 首次调试: 打印所有 frame
            for j, f in enumerate(page.frames):
                try:
                    t = f.evaluate("document.title")
                except Exception:
                    t = "(error)"
                print(f"    Frame {j}: title=\"{t}\" url={f.url[:100]}")
        time.sleep(1)
    return None


# ==================== 树菜单导航 ====================

def _dblclick_tree_node(page: Page, node_text: str):
    """在左侧 MiniUI 树中双击指定文本的节点展开子节点"""
    try:
        # 先用 MiniUI API 展开
        try:
            page.evaluate(f"""
                (function() {{
                    var tree = mini.get('tree1');
                    if (tree) {{
                        var nodes = tree.findNodes(function(node) {{
                            return node.text && node.text.trim() === '{node_text}';
                        }});
                        if (nodes.length > 0) tree.expandNode(nodes[0]);
                    }}
                }})()
            """)
        except Exception:
            pass

        # DOM 双击确保触发
        nodes = page.locator("span.mini-tree-nodetext").all()
        for n in nodes:
            try:
                if n.inner_text().strip() == node_text:
                    n.locator("..").locator("..").dblclick(force=True)
                    print(f"  已双击树节点: {node_text}")
                    break
            except Exception:
                continue

        page.wait_for_timeout(1500)
    except Exception as e:
        print(f"  [WARN] 双击树节点 '{node_text}' 失败: {e}")


def _click_tree_node(page: Page, node_text: str):
    """在左侧 MiniUI 树中单击指定文本的节点（必须用 DOM 点击触发 onnodeclick）"""
    # 最多重试3次
    for attempt in range(3):
        try:
            nodes = page.locator("span.mini-tree-nodetext").all()
            for n in nodes:
                try:
                    if n.inner_text().strip() == node_text:
                        n.click(force=True)
                        print(f"  已单击树节点: {node_text}")
                        page.wait_for_timeout(2000)
                        return
                except Exception:
                    continue
            print(f"  [WARN] 未找到树节点 '{node_text}' (尝试 {attempt+1}/3)")
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"  [WARN] 单击树节点 '{node_text}' 失败: {e}")
    print(f"  [ERROR] 3次尝试后仍未找到树节点: {node_text}")


# ==================== 合作申请单编号弹窗选择 ====================

def _select_application_code(page: Page, frame: Frame, code: str) -> bool:
    """
    搜索并选中合作申请单编号。参考 renewal_order_submitter.py 的 search_application 方法。
    先尝试直接输入btnEdit1的text，不行再打开弹窗搜索。
    """
    import time

    def get_form_state():
        """检查表单是否已加载申请单数据"""
        return frame.evaluate("""
            (function() {
                var appId = document.getElementById('appId');
                var applicationId = document.getElementById('applicationId');
                var projectCode = document.getElementById('projectCode');
                var sbuName = document.getElementById('sbuName');
                var hasBusinessData = !!(appId && appId.value || applicationId && applicationId.value ||
                    projectCode && projectCode.value || sbuName && sbuName.value);
                var selectedAppNo = '';
                var inp = document.getElementById('btnEdit1$text');
                if (inp) selectedAppNo = inp.value || '';
                if (!selectedAppNo) {
                    try { var c = mini.get('btnEdit1'); if (c && c.getValue) selectedAppNo = c.getValue() || ''; } catch(e) {}
                }
                var personnelCount = 0;
                try {
                    var grid = mini.get('datagrid1');
                    if (grid && grid.getData) personnelCount = (grid.getData() || []).length;
                } catch(e) {}
                return {
                    loaded: !!selectedAppNo || hasBusinessData,
                    hasBusinessData: hasBusinessData,
                    selectedAppNo: String(selectedAppNo).trim(),
                    projectCode: projectCode ? String(projectCode.value || '').trim() : '',
                    projectName: (function(){var e=document.getElementById('projectName');return e?String(e.value||'').trim():'';})(),
                    sbuName: sbuName ? String(sbuName.value || '').trim() : '',
                    personnelCount: personnelCount
                };
            })()
        """)

    try:
        # === 点击合作申请单编号右端触发图标 ===
        print(f"  [1] 点击触发图标...")
        # 等待btnEdit1出现
        try: frame.locator('#btnEdit1').wait_for(state='visible', timeout=10000)
        except: pass
        box = frame.locator('#btnEdit1').bounding_box()
        if not box:
            # 重试：等3秒再试
            page.wait_for_timeout(3000)
            box = frame.locator('#btnEdit1').bounding_box()
        if box:
            # 点击input最右边（图标在右侧）
            page.mouse.click(box['x'] + box['width'] - 8, box['y'] + box['height'] / 2)
            print(f"    已点右边缘 ({box['x']+box['width']-8:.0f}, {box['y']+box['height']/2:.0f})")
        else:
            print(f"    btnEdit1 bounding_box not found")
            frame.evaluate("showApplicationQueryPage()")
        page.wait_for_timeout(2500)

        # 点确认弹窗的"确定"
        print(f"  [2] 点确定...")
        for ctx in [page] + list(page.frames):
            try:
                btn = ctx.locator('a:has-text("确定"), button:has-text("确定")').first
                if btn.count() > 0 and btn.is_visible(timeout=2000):
                    btn.click(force=True)
                    print(f"    已点确定")
                    break
            except: continue
        page.wait_for_timeout(2000)

        # Step 3: 等待弹窗iframe出现，自动填写code
        import time
        search_f2 = None
        for i in range(15):
            time.sleep(1)
            for f2 in page.frames:
                if 'goToQueryApplicationResult' in f2.url:
                    search_f2 = f2
                    break
            if search_f2:
                print(f"    弹窗iframe已加载({i+1}s)")
                break

        if search_f2:
            # 定位合作申请单编号的input
            target_id = search_f2.evaluate("""(function(){
                function norm(t){return String(t||'').replace(/\\s+/g,'').replace(/[：:]/g,'');}
                var labels = document.querySelectorAll('td,label,span');
                for(var i=0;i<labels.length;i++){
                    var t = norm(labels[i].innerText||labels[i].textContent||'');
                    if(t.indexOf('合作申请单编号')>=0){
                        var td = labels[i].closest('td');
                        if(td && td.nextElementSibling){
                            var inp = td.nextElementSibling.querySelector('input');
                            if(inp) return inp.id || inp.name || 'found';
                        }
                        var tr = labels[i].closest('tr');
                        if(tr){ var inp = tr.querySelector('input[type=text],input:not([type])'); if(inp) return inp.id || inp.name || 'found'; }
                    }
                }
                return '';
            })()""")
            inp = None
            if target_id:
                inp = search_f2.locator(f'[id="{target_id}"]').first
            if not inp or inp.count() == 0:
                inp = search_f2.locator('input[type=text]:visible, input:not([type]):visible').last
            if inp and inp.count() > 0:
                inp.click()
                page.wait_for_timeout(200)
                inp.fill('')
                inp.type(code, delay=60)
                page.wait_for_timeout(500)
                print(f"    已填 {code}")
                # 点击查询
                qb = search_f2.locator('a:has-text("查询")').first
                if qb.count() > 0:
                    qb.click()
                    print(f"    已点查询")
            else:
                print(f"    input未找到")
            # 等待弹窗关闭
            for i in range(30):
                time.sleep(1)
                if not any('goToQueryApplicationResult' in fr.url for fr in page.frames):
                    print(f"    弹窗已关闭({i+1}s)")
                    break
            else:
                print(f"    弹窗30s未关闭")

        # 等待表单加载数据
        for i in range(15):
            time.sleep(1)
            state = get_form_state()
            if state.get('loaded') and state.get('hasBusinessData'):
                print(f"    弹窗选择成功! 项目:{state.get('projectCode')} 人员:{state.get('personnelCount')}")
                # 关闭可能被自动带出的人员信息弹窗
                page.evaluate("""(function(){
                    var wins=document.querySelectorAll('.mini-window,.mini-modal');
                    for(var i=0;i<wins.length;i++){
                        var w=wins[i];
                        if(w.offsetParent!==null && (w.innerText||'').indexOf('人员')>=0){
                            var close=w.querySelector('.mini-tools-close,.mini-panel-tools-close');
                            if(close) close.click();
                        }
                    }
                })()""")
                page.wait_for_timeout(1000)
                return True
        print(f"    表单数据未加载")
        return True  # 即使没检测到也继续

    except Exception as e:
        print(f"  [ERROR]: {e}")
        import traceback; traceback.print_exc()
        return False


def _search_application_in_popup(page: Page, code: str):
    """在 showApplicationQueryPage 打开的弹窗中填写申请单号并查询"""
    try:
        # Step 1: 在弹窗中找到"合作申请单编号"的 input 并填写
        page.evaluate(f"""
            (function() {{
                var windows = document.querySelectorAll('.mini-window');
                for (var w = 0; w < windows.length; w++) {{
                    var win = windows[w];
                    if (win.offsetParent === null) continue;
                    var inputs = win.querySelectorAll('.mini-textbox-input, input[type="text"]');
                    for (var i = 0; i < inputs.length; i++) {{
                        var parent = inputs[i].closest('td');
                        if (parent) {{
                            var row = parent.parentElement;
                            if (row) {{
                                var labelText = row.innerText || row.textContent || '';
                                if (labelText.indexOf('合作申请单') >= 0 || labelText.indexOf('申请单号') >= 0) {{
                                    var ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                    ns.call(inputs[i], '{code}');
                                    inputs[i].dispatchEvent(new Event('input', {{bubbles: true}}));
                                    inputs[i].dispatchEvent(new Event('change', {{bubbles: true}}));
                                    var ke = new KeyboardEvent('keydown', {{key: 'Enter', keyCode: 13, bubbles: true}});
                                    inputs[i].dispatchEvent(ke);
                                    return 'filled';
                                }}
                            }}
                        }}
                    }}
                    // 回退: 弹窗中第一个可见 input
                    for (var j = 0; j < inputs.length; j++) {{
                        if (inputs[j].offsetParent !== null) {{
                            var ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                            ns.call(inputs[j], '{code}');
                            inputs[j].dispatchEvent(new Event('input', {{bubbles: true}}));
                            inputs[j].dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', keyCode: 13, bubbles: true}}));
                            return 'filled fallback';
                        }}
                    }}
                }}
                return 'not found';
            }})()
        """)
        page.wait_for_timeout(2000)

        # Step 2: 点击弹窗内的"查询"按钮
        page.evaluate("""
            (function() {
                var windows = document.querySelectorAll('.mini-window');
                for (var w = 0; w < windows.length; w++) {
                    var win = windows[w];
                    if (win.offsetParent === null) continue;
                    var links = win.querySelectorAll('a.g_a, a.mini-button, button');
                    for (var i = 0; i < links.length; i++) {
                        var text = (links[i].innerText || links[i].textContent || '').trim();
                        if (text === '查询' || text === '查 询') {
                            links[i].click();
                            return true;
                        }
                    }
                }
                return false;
            })()
        """)
        page.wait_for_timeout(3000)

        print(f"  已填写申请单号并查询: {code}")

    except Exception as e:
        print(f"  [WARN] 弹窗搜索失败: {e}")


# ==================== 签约方和技术合作商名称 ====================

def _fill_contracting_party(frame: Frame, signing_party: str):
    """
    填写签约方 (mini-combobox: contractingPartyId)
    用输入+选下拉的方式（参考 select_vendor 模式）
    """
    try:
        # 找combobox的input
        inp = frame.locator('[id="contractingPartyId$text"], input[id*="contractingPartyId"]').first
        if inp.count() > 0:
            inp.click(force=True)
            page = frame.page
            page.wait_for_timeout(300)
            inp.press('Control+a')
            inp.press('Backspace')
            page.wait_for_timeout(200)
            inp.type(signing_party, delay=60)
            page.wait_for_timeout(1200)
            print(f"  签约方已输入: {signing_party}")
            # 选下拉第一项
            dropdown = page.locator('.mini-listbox-item:visible, .mini-combobox-item:visible, .mini-popup li:visible').first
            try:
                if dropdown.is_visible(timeout=2000):
                    dropdown.click()
                    print(f"  签约方下拉已选中")
            except: pass
        else:
            print(f"  [WARN] 签约方input未找到")
    except Exception as e:
        print(f"  [WARN] 签约方失败: {e}")


def _fill_tech_coop(frame: Frame, supplier: str):
    """
    填写技术合作商名称 (mini-combobox: techCoopId)
    用输入+选下拉的方式
    """
    try:
        inp = frame.locator('[id="techCoopId$text"], input[id*="techCoopId"]').first
        if inp.count() > 0:
            inp.click(force=True)
            page = frame.page
            page.wait_for_timeout(300)
            inp.press('Control+a')
            inp.press('Backspace')
            page.wait_for_timeout(200)
            inp.type(supplier, delay=60)
            page.wait_for_timeout(1200)
            print(f"  技术合作商已输入: {supplier}")
            dropdown = page.locator('.mini-listbox-item:visible, .mini-combobox-item:visible, .mini-popup li:visible').first
            try:
                if dropdown.is_visible(timeout=2000):
                    dropdown.click()
                    print(f"  技术合作商下拉已选中")
            except: pass
        else:
            print(f"  [WARN] 技术合作商input未找到")
    except Exception as e:
        print(f"  [WARN] 技术合作商失败: {e}")


# ==================== 人员添加 ====================

def _add_personnel(page: Page, frame: Frame, personnel: list[dict]) -> list[str]:
    """循环添加所有人员，返回失败列表"""
    failed = []
    for i, person in enumerate(personnel):
        name = person.get("name", "?")
        id_number = person.get("id_number", "")
        print(f"    [{i + 1}/{len(personnel)}] 添加人员: {name}")

        if not id_number:
            print(f"    [WARN] 缺少身份证号，跳过")
            failed.append(name)
            continue

        try:
            # 点击"增加"按钮 → addRow()
            _click_add_button(frame)
            page.wait_for_timeout(1000)

            # 在新行中触发姓名 buttonedit → showTechCoopQueryPage
            _click_staff_search_in_last_row(frame)
            page.wait_for_timeout(2000)

            # 在弹窗中搜索人员
            _search_person_in_popup(page, id_number)
            page.wait_for_timeout(2500)

            # 只填校正上岗时间(idx=14)到工作开始日期
            try:
                raw = person.get("_raw", {})
                raw_keys = list(raw.keys())
                work_start = str(raw.get(raw_keys[14], "")).strip() if len(raw_keys) > 14 else ""
                if work_start:
                    work_start = work_start.replace('/', '-').replace('.', '-')[:10]
                    frame.evaluate(f"""
                        var grid=mini.get('datagrid1');
                        if(grid){{
                            var data=grid.getData();
                            if(data.length>0){{
                                grid.updateRow(data[data.length-1], {{workStartDate:'{work_start}'}});
                            }}
                        }}
                    """)
                    print(f"    已填工作开始日期: {work_start}")
            except Exception as e:
                print(f"    工作开始日期填写: {e}")

            print(f"    人员添加完成: {name}")
        except Exception as e:
            print(f"    [ERROR] 添加人员失败: {e}")
            failed.append(name)

    return failed


def _click_add_button(frame: Frame):
    """点击"增加"按钮 - a.mini-button with onclick='addRow()'"""
    try:
        # 先获取当前行数
        prev = frame.evaluate("(function(){var g=mini.get('datagrid1');return g?g.getData().length:-1})()")

        # 通过 onclick 属性找到增加按钮并点击
        result = frame.evaluate("(function(){var links=document.querySelectorAll('a.mini-button');for(var i=0;i<links.length;i++){if(links[i].innerText.trim()==='增加'){links[i].click();return 'clicked';}}if(typeof addRow==='function'){addRow();return 'addRow()';}return false;})()")

        # 等待并检查新行是否出现
        frame.page.wait_for_timeout(1000)
        after = frame.evaluate("(function(){var g=mini.get('datagrid1');return g?g.getData().length:-1})()")
        print(f"    增加按钮: {result}, 行数 {prev} -> {after}")
    except Exception as e:
        print(f"    [WARN] 点击增加按钮失败: {e}")


def _click_staff_search_in_last_row(frame: Frame):
    """v91成功版: 点cell→等editwrap→page.mouse.click点button"""
    try:
        page = frame.page
        cell = frame.locator('.mini-grid-row:last-child td, tr.mini-grid-row:last-child td').nth(2)
        if cell.count() > 0:
            cell.click()
            page.wait_for_timeout(800)
        for i in range(5):
            btn = frame.locator('.mini-grid-editwrap .mini-buttonedit-button:visible').first
            if btn.count() > 0:
                box = btn.bounding_box()
                if box:
                    page.mouse.click(box['x']+box['width']/2, box['y']+box['height']/2)
                    print(f"    已点trigger ({box['x']+box['width']/2:.0f},{box['y']+box['height']/2:.0f})")
                    return
            page.wait_for_timeout(500)
        print(f"    editwrap未现，回退JS")
        frame.evaluate("showTechCoopQueryPage()")
    except Exception as e:
        frame.evaluate("showTechCoopQueryPage()")


def _search_person_in_popup(page: Page, id_number: str):
    """在人员搜索弹窗中找到"身份证号"标签旁的input，填写并查询"""
    try:
        # 找包含"身份证号"的弹窗frame或主页面（等待弹窗加载）
        import time
        target = page
        for i in range(15):
            for f in page.frames:
                try:
                    body = f.evaluate('document.body.innerText')
                    if '身份证号' in body and '查询' in body:
                        target = f
                        break
                except: pass
            if target is not page:
                break
            time.sleep(1)

        # 用JS定位"身份证号"标签旁的input
        target_id = target.evaluate("""(function(){
            function norm(t){return String(t||'').replace(/\\s+/g,'').replace(/[：:]/g,'');}
            var labels = document.querySelectorAll('td,label,span');
            for(var i=0;i<labels.length;i++){
                var t = norm(labels[i].innerText||labels[i].textContent||'');
                if(t.indexOf('身份证号')>=0){
                    var td = labels[i].closest('td');
                    if(td && td.nextElementSibling){
                        var inp = td.nextElementSibling.querySelector('input');
                        if(inp) return inp.id || inp.name || 'found in next td';
                    }
                    var tr = labels[i].closest('tr');
                    if(tr){
                        var inp = tr.querySelector('input[type=text],input:not([type])');
                        if(inp) return inp.id || inp.name || 'found in tr';
                    }
                }
            }
            return '';
        })()""")

        inp = None
        if target_id:
            inp = target.locator(f'[id="{target_id}"]').first
        if not inp or inp.count() == 0:
            inp = target.locator('input[type=text]:visible:not([disabled])').last

        if inp and inp.count() > 0:
            inp.click()
            page.wait_for_timeout(200)
            inp.fill('')
            page.wait_for_timeout(100)
            inp.type(id_number, delay=60)
            page.wait_for_timeout(500)
            print(f"    已填身份证号 {id_number} (target={target_id})")
            # 点查询
            qb = target.locator('a:has-text("查询"):visible').first
            if qb.count() > 0:
                qb.click()
                print(f"    已点查询")
            else:
                inp.press('Enter')
                print(f"    未找到查询，已回车")
            page.wait_for_timeout(3000)
            # 双击搜索结果第一行
            try:
                target.evaluate("""(function(){
                    var rows=document.querySelectorAll('.mini-grid-row,tr.mini-grid-row');
                    for(var i=0;i<rows.length;i++){
                        if(rows[i].offsetParent!==null){
                            rows[i].dispatchEvent(new MouseEvent('dblclick',{bubbles:true,cancelable:true}));
                            return;
                        }
                    }
                })()""")
            except: pass
            page.wait_for_timeout(1000)
            # 点确定（如果弹窗还在）
            try:
                ob = page.locator('a:has-text("确定"):visible').first
                if ob.count() > 0: ob.click()
            except: pass
            print(f"    人员搜索完成")
            # 兜底：直接把身份证号写入datagrid最后一行
            try:
                frame.evaluate(f"""
                    var grid=mini.get('datagrid1');
                    if(grid){{
                        var data=grid.getData();
                        if(data.length>0){{
                            var last=data[data.length-1];
                            grid.updateRow(last,{{staffIdentification:'{id_number}'}});
                        }}
                    }}
                """)
            except: pass

        page.wait_for_timeout(3000)

    except Exception as e:
        print(f"    [WARN] 人员弹窗搜索失败: {e}")


# ==================== 计算成本 ====================

def _calculate_cost(frame: Frame) -> bool:
    """点击"计算成本"按钮 (span.mini-button-text.icon-reload)"""
    try:
        # 先检查 datagrid 是否有数据
        row_count = frame.evaluate("""
            (function() {
                var grid = mini.get('datagrid1');
                if (grid) {
                    var data = grid.getData();
                    return data ? data.length : -1;
                }
                return -1;
            })()
        """)
        print(f"  datagrid 当前行数: {row_count}")

        # 点击"计算成本"——按钮是 span.mini-button-text.icon-reload
        btn = frame.locator('.mini-button-text.icon-reload, a:has-text("计算成本"), [onclick*="compute"]').first
        if btn.count() > 0:
            btn.click(force=True)
            print(f"  已点击计算成本")
        else:
            frame.evaluate("if(typeof compute==='function')compute()")
        print("  已点击计算成本，等待结果...")

        page = frame.page
        for i in range(30):
            page.wait_for_timeout(1000)
            has_value = frame.evaluate("""
                (function() {
                    var ctrl = mini.get('changeOrderAmount');
                    if (ctrl) {
                        var v = ctrl.getValue() || '';
                        if (v && v !== '0' && v !== '0.00') return true;
                    }
                    return false;
                })()
            """)
            if has_value:
                amount = frame.evaluate("mini.get('changeOrderAmount').getValue()")
                print(f"  成本计算完成: 金额 = {amount}")
                return True
            if i % 10 == 9:
                print(f"  等待中... ({i+1}s)")

        print("  [WARN] 成本计算超时，金额未显示")
        return False
    except Exception as e:
        print(f"  [WARN] 计算成本失败: {e}")
        return False


# ==================== 提交 ====================

def _submit_contract(page: Page, frame: Frame) -> tuple[bool, str]:
    """点击"保存并提交审批"，获取弹窗文字判断成功/失败，捕获订单编号"""
    try:
        # 先滚到底部
        frame.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(500)

        # 点击"保存并提交审批"
        btn = frame.locator('a:has-text("保存并提交审批")').first
        if btn.count() > 0:
            btn.click(force=True)
            print("  已点保存并提交审批")
        else:
            frame.evaluate("if(typeof saveAndSubmit==='function')saveAndSubmit()")
        # 等弹窗出现 → 点确定 → 检测错误
        page.wait_for_timeout(2000)
        _click_ok_in_dialog(page)
        page.wait_for_timeout(3000)

        # 检测提交结果
        error = _detect_error(page)
        if error:
            print(f"  提交失败: {error[:80]}")
            _click_ok_in_dialog(page)
            page.wait_for_timeout(1000)
            return False, error[:200]

        # 获取技术合作订单编号
        order_no = ""
        try:
            order_no = frame.evaluate("""(function(){
                var el=document.getElementById('techCoopNumbers');
                if(el&&el.value) return el.value;
                try{var c=mini.get('techCoopNumbers');if(c&&c.getValue) return c.getValue()||'';}catch(e){}
                return '';
            })()""")
        except: pass
        if order_no:
            print(f"  订单编号: {order_no}")

        return True, order_no

    except Exception as e:
        return False, str(e)


def _click_ok_in_dialog(page: Page):
    """在弹窗/对话框中点击确定（广泛搜索所有可能的确定按钮）"""
    try:
        for i in range(10):
            # 搜索所有frame中所有可能的"确定"元素
            for ctx in [page] + list(page.frames):
                for sel in ['a:has-text("确定")', 'button:has-text("确定")',
                            'span:has-text("确定")', '.mini-button:has-text("确定")',
                            '.mini-messagebox-button', 'a.g_a:has-text("确定")',
                            '[onclick*="submit"]', '[onclick*="ok"]',
                            '.mini-window .mini-button:has-text("确定")']:
                    try:
                        btn = ctx.locator(sel).first
                        if btn.count() > 0 and btn.is_visible(timeout=1000):
                            btn.click(force=True, timeout=2000)
                            print("  已点击确定")
                            return
                    except: pass
            page.wait_for_timeout(500)
        # 最后尝试：JS点击所有可见的确定/OK按钮
        page.evaluate("""
            document.querySelectorAll('a,button,span,input').forEach(function(el){
                var t=(el.innerText||el.value||'').trim();
                if((t==='确定'||t==='OK'||t==='确认') && el.offsetParent!==null) el.click();
            });
        """)
        print("  已尝试JS点击确定")
    except Exception as e:
        print(f"  [WARN] 点击确定失败: {e}")


def _detect_error(page: Page) -> str | None:
    """检测页面是否有错误弹窗"""
    try:
        error_text = page.evaluate("""
            (function() {
                var selectors = [
                    '.mini-messagebox-content',
                    '.mini-messagebox .mini-panel-body',
                    '.mini-window .mini-panel-body',
                    '.mini-alert',
                ];
                for (var i = 0; i < selectors.length; i++) {
                    var el = document.querySelector(selectors[i]);
                    if (el && el.offsetParent !== null) {
                        var text = (el.innerText || el.textContent || '').trim();
                        if (text && text.length > 1 && text.length < 500) return text;
                    }
                }
                var dialogs = document.querySelectorAll('.mini-window, .mini-messagebox');
                for (var i = 0; i < dialogs.length; i++) {
                    if (dialogs[i].offsetParent !== null) {
                        var text = (dialogs[i].innerText || dialogs[i].textContent || '').trim();
                        if (text && text.length > 5 && text.length < 500 &&
                            (text.indexOf('错误') >= 0 || text.indexOf('失败') >= 0 ||
                             text.indexOf('异常') >= 0)) {
                            return text;
                        }
                    }
                }
                return '';
            })()
        """)
        if error_text:
            print(f"  检测到错误: {error_text[:200]}")
            return error_text
        return None
    except Exception:
        return None


# ==================== 辅助函数 ====================

def _dismiss_any_popups(page: Page):
    """关闭所有弹窗"""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        page.evaluate("""
            (function() {
                try { var w = mini.get('win1'); if (w && w.destroy) w.destroy(); } catch(e) {}
                try { var w = mini.get('win2'); if (w && w.destroy) w.destroy(); } catch(e) {}
                var closes = document.querySelectorAll('.mini-window .mini-tools-close, .mini-panel-tools-close');
                for (var i = 0; i < closes.length; i++) {
                    if (closes[i].offsetParent !== null) closes[i].click();
                }
            })()
        """)
        page.wait_for_timeout(300)
    except Exception:
        pass
