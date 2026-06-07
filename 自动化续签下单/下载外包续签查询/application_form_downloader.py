"""
申请单查询下载自动化工具
在"外包数据查询 → 申请单"页面按条件查询并导出Excel
与 RenewalQueryDownloader 共用浏览器会话（已登录状态）
"""

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List


class ApplicationFormDownloader:
    """申请单页面下载器 —— 依赖外部传入已登录的 Page 对象"""

    def __init__(self, page, download_dir: str):
        """
        Args:
            page: 已登录的 Playwright Page 对象
            download_dir: 下载文件保存目录
        """
        self._page = page
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._query_target = None
        self._query_is_tab = False

    # ===================== 导航 =====================

    def navigate_to_application_form(self):
        """
        从主页导航到"申请单"页面：
        左侧功能树 → 双击"外包数据查询" → 单击"申请单"
        """
        print("[INFO] 正在导航到申请单页面...")
        self._page.wait_for_timeout(2000)

        # ── 诊断：列出当前树中所有可见节点 ──
        tree_diag = self._page.evaluate("""() => {
            try {
                var tree = mini.get('tree1');
                if (!tree) return {error: 'tree1 not found'};
                var nodes = tree.getData();
                var list = [];
                function walk(arr, depth) {
                    for (var i = 0; i < arr.length; i++) {
                        var n = arr[i];
                        list.push({depth: depth, text: n.text || '', id: n.id || '',
                                    expanded: !!n.expanded, children: (n.children || []).length});
                        if (n.children && n.children.length) walk(n.children, depth + 1);
                    }
                }
                walk(nodes, 0);
                return {success: true, nodes: list};
            } catch(e) { return {error: e.message || String(e)}; }
        }""")
        print(f"[INFO] 树节点诊断: {tree_diag}")

        # 双击"外包数据查询"展开子菜单
        try:
            outsource_row = self._page.locator(
                ".mini-tree-nodetext:has-text('外包数据查询')"
            ).first
            outsource_row.dblclick()
            print("[INFO] 已双击【外包数据查询】菜单")
            self._page.wait_for_timeout(2000)
        except Exception as e:
            print(f"[DEBUG] 双击菜单失败，尝试JS展开: {e}")
            try:
                self._page.evaluate("""
                    var tree = mini.get("tree1");
                    var nodes = tree.getData();
                    for (var i = 0; i < nodes.length; i++) {
                        if (nodes[i].text && nodes[i].text.indexOf('外包数据查询') >= 0) {
                            tree.expandNode(nodes[i]);
                            break;
                        }
                    }
                """)
                print("[INFO] 通过JS展开了外包数据查询菜单")
                self._page.wait_for_timeout(2000)
            except Exception as e2:
                print(f"[DEBUG] JS展开也失败: {e2}")

        # ── 展开后再次诊断 ──
        tree_diag2 = self._page.evaluate("""() => {
            try {
                var tree = mini.get('tree1');
                if (!tree) return {error: 'tree1 not found'};
                var nodes = tree.getData();
                var list = [];
                function walk(arr, depth) {
                    for (var i = 0; i < arr.length; i++) {
                        var n = arr[i];
                        list.push({depth: depth, text: n.text || '', id: n.id || '',
                                    expanded: !!n.expanded, children: (n.children || []).length});
                        if (n.children && n.children.length) walk(n.children, depth + 1);
                    }
                }
                walk(nodes, 0);
                return {success: true, nodes: list};
            } catch(e) { return {error: e.message || String(e)}; }
        }""")
        print(f"[INFO] 展开后树节点诊断: {tree_diag2}")

        # 单击"申请单"——尝试多种方式
        target_opened = False
        # 方式1：CSS选择器 + expect_page
        try:
            with self._page.context.expect_page(timeout=5000) as new_page_info:
                link = self._page.locator(
                    ".mini-tree-nodetext:has-text('申请单')"
                ).first
                link.click()
                print("[INFO] 方式1: 已单击【申请单】")

            self._query_target = new_page_info.value
            self._query_target.wait_for_load_state("domcontentloaded")
            self._query_target.wait_for_timeout(3000)
            self._query_is_tab = True
            target_opened = True
            print(f"[SUCCESS] 申请单页面已打开(新标签页): {self._query_target.url}")
        except Exception as e1:
            print(f"[INFO] 方式1失败（expect_page超时）: {e1}")

        # 方式2：用JS查找并点击树节点
        if not target_opened:
            try:
                js_result = self._page.evaluate("""() => {
                    var tree = mini.get('tree1');
                    if (!tree) return {ok: false, error: 'tree1 not found'};
                    var nodes = tree.getData();
                    function findAndClick(arr, path) {
                        for (var i = 0; i < arr.length; i++) {
                            var t = (arr[i].text || '').trim();
                            if (t === '申请单' || t.indexOf('申请单') >= 0) {
                                tree.selectNode(arr[i]);
                                return {ok: true, text: t, path: path + ' > ' + t};
                            }
                            if (arr[i].children && arr[i].children.length) {
                                var r = findAndClick(arr[i].children, path + ' > ' + t);
                                if (r && r.ok) return r;
                            }
                        }
                        return null;
                    }
                    var r = findAndClick(nodes, 'root');
                    return r || {ok: false, error: '未找到申请单节点'};
                }""")
                print(f"[INFO] 方式2 JS查找: {js_result}")
                if js_result.get("ok"):
                    self._page.wait_for_timeout(3000)
                    # 检查是否有新标签页或新iframe
                    if len(self._page.context.pages) > 1:
                        for p in self._page.context.pages:
                            if p != self._page:
                                self._query_target = p
                                self._query_is_tab = True
                                target_opened = True
                                print(f"[SUCCESS] 方式2: 申请单页面已打开(检测到新标签页)")
                                break
            except Exception as e2:
                print(f"[INFO] 方式2失败: {e2}")

        if target_opened:
            return self._query_target

        # 回退：查找 iframe
        print("[INFO] 未检测到新标签页，尝试查找 iframe...")
        self._page.wait_for_timeout(3000)
        for frame in self._page.frames:
            frame_url = frame.url
            if frame == self._page.main_frame or not frame_url or "about:blank" in frame_url:
                continue
            if any(kw in frame_url.lower() for kw in ["application", "apply", "appform"]):
                print(f"[INFO] 找到申请单 iframe: {frame_url}")
                self._query_target = frame
                self._query_is_tab = False
                return frame

        # 最终兜底：取最后一个有内容的 iframe
        non_main_frames = [
            f for f in self._page.frames
            if f != self._page.main_frame and f.url and "about:blank" not in f.url
        ]
        if non_main_frames:
            self._query_target = non_main_frames[-1]
            print(f"[INFO] 使用最后一个非主 frame: {self._query_target.url}")
            self._query_is_tab = False
            return self._query_target

        raise Exception("未找到申请单页面的 iframe 或新标签页")

    def _get_target(self):
        """返回当前操作目标（Page 或 Frame）"""
        if self._query_is_tab and self._query_target:
            return self._query_target
        # 重新获取 frame 防止 detach
        for frame in self._page.frames:
            frame_url = frame.url
            if frame == self._page.main_frame or not frame_url or "about:blank" in frame_url:
                continue
            if any(kw in frame_url.lower() for kw in ["application", "apply", "appform"]):
                self._query_target = frame
                return frame
        return self._query_target or self._page

    # ===================== 查询条件填写 =====================

    def _fill_date_range(self, target, start_str: str, end_str: str) -> bool:
        """
        填写申请时间。尝试多种 MiniUI 控件ID + DOM直接操作。
        """
        print(f"[INFO] 填写申请时间: {start_str} ~ {end_str}")

        def _to_date(s):
            m = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日?', s)
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            return s

        beg_val = _to_date(start_str)
        end_val = _to_date(end_str)

        result = target.evaluate("""(args) => {
            var beg = args.beg;
            var end = args.end;

            // 尝试常见ID
            var begIds = ['p_apply_begin_date', 'p_apply_start_date', 'applyBeginDate',
                         'applyStartDate', 'beginDate', 'startDate', 'p_begin_date'];
            var endIds = ['p_apply_end_date', 'applyEndDate', 'endDate', 'p_end_date'];

            function trySet(ids, val) {
                for (var i = 0; i < ids.length; i++) {
                    try {
                        var ctrl = mini.get(ids[i]);
                        if (ctrl && ctrl.setValue) { ctrl.setValue(val); return ids[i]; }
                    } catch(e) {}
                    var el = document.getElementById(ids[i]);
                    if (el) { el.value = val; return ids[i] + '(dom)'; }
                }
                return null;
            }

            var begOk = trySet(begIds, beg);
            var endOk = trySet(endIds, end);

            // 兜底：遍历所有 datepicker / textbox，匹配"申请时间"标签
            if (!begOk || !endOk) {
                var labels = document.querySelectorAll('label, td, th, span, div');
                var dateInputs = [];
                for (var j = 0; j < labels.length; j++) {
                    var t = (labels[j].textContent || '').replace(/\\s+/g, '');
                    if (t.indexOf('申请时间') >= 0 || t.indexOf('申请日期') >= 0) {
                        var cell = labels[j].closest('td');
                        if (cell && cell.nextElementSibling) {
                            var inputs = cell.nextElementSibling.querySelectorAll('input');
                            if (inputs.length >= 2) {
                                if (!begOk) {
                                    inputs[0].value = beg;
                                    begOk = 'dom-label-start';
                                }
                                if (!endOk) {
                                    inputs[1].value = end;
                                    endOk = 'dom-label-end';
                                }
                            }
                        }
                        break;
                    }
                }
            }

            return {begOk: begOk, endOk: endOk};
        }""", {"beg": beg_val, "end": end_val})

        print(f"[INFO] 日期填写结果: {result}")
        self._page.wait_for_timeout(500)
        return bool(result.get("begOk") and result.get("endOk"))

    def _select_combobox_by_index(self, target, control_id: str, index: int) -> bool:
        """
        按索引选择 combobox 项。
        对 buttonedit+combobox+popupedit 类型控件，使用点击触发下拉→点击选项的方式
        （确保 UI 更新），再用 MiniUI API setValue 作为备选。
        """
        print(f"[INFO] 选择 {control_id}[{index}]...")

        # 方式1：Click-triggered dropdown selection（更可靠，触发所有UI事件）
        try:
            # 先尝试找到并点击控件按钮打开下拉
            btn_selectors = [
                f"#{control_id} .mini-buttonedit-button",
                f"#{control_id} .mini-buttonedit-icon",
                f"span#{control_id} .mini-buttonedit-button",
                f"span#{control_id}",
                f"#{control_id}",
            ]
            clicked = False
            for sel in btn_selectors:
                try:
                    btn = target.locator(sel).first
                    if btn.count() > 0:
                        btn.click()
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                # JS方式点击
                target.evaluate(f"""(cid) => {{
                    var el = document.getElementById(cid);
                    if (!el) el = document.querySelector('#' + cid + ' .mini-buttonedit-button');
                    if (!el) el = document.querySelector('#' + cid + ' .mini-buttonedit-icon');
                    if (el) el.click();
                    else {{
                        var combo = mini.get(cid);
                        if (combo && combo.showPopup) combo.showPopup();
                    }}
                }}""", control_id)

            self._page.wait_for_timeout(1000)

            # 在下拉列表中选择第 index 项
            dropdown_items = target.locator(".mini-listbox-item, .mini-combobox-item, .mini-popup li")
            count = dropdown_items.count()
            if count > 0 and index < count:
                item = dropdown_items.nth(index)
                item_text = (item.text_content() or "").strip()
                item.scroll_into_view_if_needed()
                item.click()
                print(f"[SUCCESS] {control_id} 已点击下拉第{index}项: {item_text}")
                self._page.wait_for_timeout(500)
                return True
            elif count == 0:
                print(f"[INFO] {control_id} 下拉列表为空或未出现，尝试MiniUI API...")
        except Exception as e:
            print(f"[INFO] {control_id} 点击下拉方式失败: {e}，尝试MiniUI API...")

        # 方式2：MiniUI API setValue（备用）
        result = target.evaluate("""(args) => {
            var combo = mini.get(args.controlId);
            if (!combo) return {success: false, error: '控件不存在: ' + args.controlId};

            var data = (combo.data || []).filter(function(d) { return !d.__NullItem; });
            if (data.length === 0) {
                try { combo.load(); } catch(e) {}
                data = (combo.data || []).filter(function(d) { return !d.__NullItem; });
            }
            if (data.length === 0) {
                return {success: false, error: '数据为空', controlId: args.controlId};
            }
            if (args.index >= data.length) {
                return {success: false, error: '索引越界: ' + args.index + ' >= ' + data.length,
                        available: data.slice(0, 10).map(function(d) {
                            for (var k in d) {
                                var v = String(d[k] || '');
                                if (v && v.length > 1 && !/^[\\d.]+$/.test(v)) return v;
                            }
                            return JSON.stringify(d).substring(0, 60);
                        })};
            }

            var item = data[args.index];
            var val = item.flexValue || item.id || item.value || '';
            combo.setValue(val);
            // 触发值变更事件
            try { if (combo.doValueChanged) combo.doValueChanged(); } catch(e) {}
            try { combo.fire('valuechanged'); } catch(e) {}
            var label = '';
            for (var k in item) {
                var v = String(item[k] || '');
                if (v && v.length > 1 && !/^[\\d.]+$/.test(v)) { label = v; break; }
            }
            return {success: true, index: args.index, label: label, setVal: val};
        }""", {"controlId": control_id, "index": index})

        if result.get("success"):
            print(f"[SUCCESS] {control_id} MiniUI API 已选择第{index}项: {result.get('label')}")
            self._page.wait_for_timeout(300)
            return True
        else:
            print(f"[WARNING] {control_id}: {result.get('error')}")
            if result.get("available"):
                print(f"[DEBUG] 可用选项: {result['available']}")
            return False

    def _select_combobox_by_click(self, target, control_id: str,
                                    match_text: str = "", fallback_index: int = -1) -> bool:
        """
        通过点击打开下拉 → 文本匹配或索引选择 → 点击选项。
        适用于 buttonedit+combobox+popupedit 类型控件。
        """
        print(f"[INFO] 点击选择 {control_id}: text='{match_text}' index={fallback_index}")

        # 步骤1：点击控件打开下拉
        open_selectors = [
            f"span#{control_id} .mini-buttonedit-button",
            f"#{control_id} .mini-buttonedit-button",
            f"span#{control_id} .mini-buttonedit-icon",
            f"span#{control_id}",
        ]
        opened = False
        for sel in open_selectors:
            try:
                btn = target.locator(sel).first
                if btn.count() > 0:
                    btn.click(force=True)
                    opened = True
                    print(f"[INFO] {control_id} 已点击: {sel}")
                    break
            except Exception as e:
                continue

        if not opened:
            # JS 方式
            try:
                target.evaluate(f"""(cid) => {{
                    var el = document.getElementById(cid);
                    if (!el) el = document.querySelector('span#' + cid + ' .mini-buttonedit-button');
                    if (!el) el = document.querySelector('#' + cid + ' .mini-buttonedit-button');
                    if (el) {{ el.click(); return; }}
                    var combo = mini.get(cid);
                    if (combo && combo.showPopup) combo.showPopup();
                }}""", control_id)
                print(f"[INFO] {control_id} JS方式点击")
            except Exception as e:
                print(f"[ERROR] {control_id} 无法打开下拉: {e}")
                return False

        # 步骤2：等待下拉出现
        self._page.wait_for_timeout(1200)

        # 步骤3：在弹出列表中找匹配项
        item_selectors = [
            ".mini-popup .mini-listbox-item",
            ".mini-popup tr",  # 有些 popup 用 table
            ".mini-listbox-item",
            ".mini-combobox-item",
            ".mini-popup li",
            "ul.mini-listbox li",
        ]

        for retry in range(3):
            if retry > 0:
                self._page.wait_for_timeout(800)

            for item_sel in item_selectors:
                try:
                    items = target.locator(item_sel)
                    count = items.count()
                    if count == 0:
                        continue

                    # 收集可见项
                    visible = []
                    for i in range(count):
                        try:
                            item = items.nth(i)
                            if item.is_visible():
                                text = (item.text_content() or "").strip()
                                if text:
                                    visible.append((i, item, text))
                        except Exception:
                            pass

                    if not visible:
                        continue

                    print(f"[INFO] {control_id} 下拉项({item_sel}): {[t for _,_,t in visible]}")

                    # 按文本匹配
                    target_item = None
                    if match_text:
                        for _, item, text in visible:
                            if text == match_text or match_text in text:
                                target_item = item
                                break
                    # 按索引
                    if target_item is None and fallback_index >= 0:
                        for idx, item, text in visible:
                            if idx == fallback_index:
                                target_item = item
                                break

                    if target_item:
                        target_item.scroll_into_view_if_needed()
                        try:
                            target_item.click()
                        except Exception:
                            target_item.click(force=True)
                        clicked_text = (target_item.text_content() or "").strip()
                        print(f"[SUCCESS] {control_id} 已选择: {clicked_text}")
                        self._page.wait_for_timeout(500)
                        return True

                except Exception as e:
                    continue

        print(f"[WARNING] {control_id} 下拉选项中未找到匹配项")
        return False

    def _select_combobox_by_text(self, target, control_id: str, target_value: str) -> bool:
        """通过 MiniUI API 按文本模糊匹配选择 combobox 项"""
        print(f"[INFO] 选择 {control_id} → {target_value}")
        result = target.evaluate("""(args) => {
            var combo = mini.get(args.controlId);
            if (!combo) return {success: false, error: '控件不存在: ' + args.controlId};

            var data = (combo.data || []).filter(function(d) { return !d.__NullItem; });
            if (data.length === 0) {
                try { combo.load(); } catch(e) {}
                data = (combo.data || []).filter(function(d) { return !d.__NullItem; });
            }

            var matched = null;
            for (var i = 0; i < data.length; i++) {
                var keys = Object.keys(data[i]);
                for (var k = 0; k < keys.length; k++) {
                    var val = String(data[i][keys[k]] || '');
                    if (val && val.length > 1 && val.length < 200 && !/^[\\d.]+$/.test(val)) {
                        if (val === args.value || val.indexOf(args.value) >= 0) {
                            matched = data[i]; break;
                        }
                    }
                }
                if (matched) break;
            }
            if (!matched) {
                var samples = data.slice(0, 8).map(function(d) {
                    for (var k in d) {
                        var v = String(d[k] || '');
                        if (v && v.length > 1 && !/^[\\d.]+$/.test(v)) return v;
                    }
                    return JSON.stringify(d).substring(0, 60);
                });
                return {success: false, error: '未匹配', available: samples};
            }
            var val = matched.flexValue || matched.id || matched.value || '';
            combo.setValue(val);
            var label = '';
            for (var k in matched) {
                var v = String(matched[k] || '');
                if (v && v.length > 1 && !/^[\\d.]+$/.test(v)) { label = v; break; }
            }
            return {success: true, label: label, setVal: val};
        }""", {"controlId": control_id, "value": target_value})

        if result.get("success"):
            print(f"[SUCCESS] {control_id} 已选择: {result.get('label')}")
            self._page.wait_for_timeout(300)
            return True
        else:
            print(f"[WARNING] {control_id}: {result.get('error')}")
            if result.get("available"):
                print(f"[DEBUG] 可用选项: {result['available']}")
            return False

    def _find_combobox_ids(self, target) -> dict:
        """
        诊断：在申请单页面找到所有 MiniUI combobox，通过标签文字识别控件ID。
        返回 {label: controlId} 映射。
        """
        result = target.evaluate("""() => {
            function norm(text) {
                return String(text || '').replace(/\\s+/g, '').replace(/[：:]/g, '');
            }

            // 找到所有包含关键词的标签
            var labels = document.querySelectorAll('label, td, th, span, div');
            var keywordMap = {};
            var keywords = ['技术合作种类', '单据状态', 'SBU', '申请时间'];

            for (var i = 0; i < labels.length; i++) {
                var t = norm(labels[i].textContent || '');
                for (var k = 0; k < keywords.length; k++) {
                    if (t === norm(keywords[k]) || t.indexOf(norm(keywords[k])) >= 0) {
                        // 在标签所在行/区域中找 MiniUI combobox
                        var row = labels[i].closest('tr, .mini-row, .form-row, td');
                        var scope = row || labels[i].parentElement;
                        if (!scope) continue;

                        // 找同区域内可能的 combobox input
                        var inputs = scope.querySelectorAll('input');
                        for (var j = 0; j < inputs.length; j++) {
                            var id = inputs[j].id || '';
                            if (id) {
                                // 去掉 $text 后缀得到 controlId
                                var cid = id.replace('$text', '').replace('$value', '');
                                if (cid && !keywordMap[keywords[k]]) {
                                    // 验证是否为 MiniUI 控件
                                    try {
                                        var ctrl = mini.get(cid);
                                        if (ctrl) {
                                            keywordMap[keywords[k]] = cid;
                                        }
                                    } catch(e) {}
                                }
                            }
                        }
                    }
                }
            }

            // 也尝试列举所有 MiniUI combobox
            var allCombos = [];
            try {
                if (typeof mini !== 'undefined') {
                    // 遍历页面元素找 MiniUI 控件
                    var allInputs = document.querySelectorAll('input');
                    var seen = {};
                    for (var x = 0; x < allInputs.length; x++) {
                        var cid = (allInputs[x].id || '').replace('$text', '').replace('$value', '');
                        if (cid && !seen[cid]) {
                            seen[cid] = true;
                            try {
                                var c = mini.get(cid);
                                if (c && c.uiClass === 'combobox') {
                                    allCombos.push({id: cid, type: c.uiClass});
                                }
                            } catch(e) {}
                        }
                    }
                }
            } catch(e) {}

            return {keywordMap: keywordMap, allCombos: allCombos};
        }""")
        print(f"[INFO] 控件诊断 - keywordMap: {result.get('keywordMap')}")
        print(f"[INFO] 控件诊断 - allCombos: {result.get('allCombos')}")
        return result

    def _query_and_export(self, sbu_name: str = "",
                          start_date_str: str = "", end_date_str: str = "") -> Optional[str]:
        """
        在申请单页面填写条件、查询、导出。
        使用已知的 MiniUI 控件 ID 直接操作。
        """
        print(f"[INFO] 开始申请单查询{' [' + sbu_name + ']' if sbu_name else ' (所有)'}...")

        target = self._get_target()
        self._page.wait_for_timeout(3000)

        # 每次查询前强制刷新页面，确保表单处于干净状态
        # 修复：多 SBU 场景下 MiniUI 控件可能残留上次查询的状态
        try:
            target.evaluate("location.reload()")
            self._page.wait_for_timeout(4000)
            target = self._get_target()
            self._page.wait_for_timeout(2000)
            print("[INFO] 页面已刷新，表单状态已重置")
        except Exception as e:
            print(f"[INFO] 页面刷新失败，继续使用当前页面: {e}")

        # ── 转换日期 ──
        def _to_date(s):
            m = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日?', s)
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            return s
        beg_val = _to_date(start_date_str)
        end_val = _to_date(end_date_str)

        # ── 1) 申请时间 ──
        print(f"[INFO] 填写申请时间: {beg_val} ~ {end_val}")
        target.evaluate(f"""(args) => {{
            var ids = ['p_apply_begin_date', 'p_apply_end_date', 'applyBeginDate', 'applyEndDate',
                       'beginDate', 'endDate', 'p_begin_date', 'p_end_date'];
            function trySet(ctrlId, val) {{
                try {{
                    var c = mini.get(ctrlId);
                    if (c && c.setValue) {{ c.setValue(val); return true; }}
                }} catch(e) {{}}
                var el = document.getElementById(ctrlId);
                if (el) {{ el.value = val; return true; }}
                return false;
            }}
            var begOk = false, endOk = false;
            for (var i = 0; i < ids.length; i += 2) {{
                if (!begOk) begOk = trySet(ids[i], args.beg);
                if (!endOk) endOk = trySet(ids[i+1], args.end);
                if (begOk && endOk) break;
            }}
            // DOM兜底：找"申请时间"标签右侧的两个input
            if (!begOk || !endOk) {{
                var labels = document.querySelectorAll('label, td, th, span, div');
                for (var j = 0; j < labels.length; j++) {{
                    var t = (labels[j].textContent || '').replace(/\\s+/g, '');
                    if (t.indexOf('申请时间') < 0) continue;
                    var row = labels[j].closest('tr, td');
                    if (!row) continue;
                    var inputs = row.querySelectorAll('input:not([type=hidden])');
                    var visibleInputs = Array.from(inputs).filter(function(el) {{
                        return el.offsetWidth > 0 && !el.readOnly;
                    }});
                    if (visibleInputs.length >= 2) {{
                        if (!begOk) {{ visibleInputs[0].value = args.beg; begOk = true; }}
                        if (!endOk) {{ visibleInputs[1].value = args.end; endOk = true; }}
                        break;
                    }}
                }}
            }}
            return {{begOk: begOk, endOk: endOk}};
        }}""", {"beg": beg_val, "end": end_val})
        self._page.wait_for_timeout(500)

        # ── 2) 技术合作种类: p_coop_type → 第3项(实际2项,取"技术合作-||") ──
        print("[INFO] 选择技术合作种类")
        self._select_combobox_by_click(target, "p_coop_type", match_text="技术合作-||", fallback_index=1)

        # ── 3) 单据状态: p_app_state → "审批流程结束" ──
        print("[INFO] 选择单据状态: 审批流程结束")
        p_app_ok = self._select_combobox_by_click(target, "p_app_state", match_text="审批流程结束", fallback_index=4)
        if not p_app_ok:
            print("[INFO] 点击方式选择单据状态失败，尝试 MiniUI API...")
            p_app_ok = self._select_combobox_by_text(target, "p_app_state", "审批流程结束")
        if not p_app_ok:
            print("[WARNING] 单据状态选择可能未生效，继续尝试后续步骤...")

        # ── 4) SBU ──
        if sbu_name:
            print(f"[INFO] 选择SBU: {sbu_name}")
            sbu_result = self._select_combobox_by_text(target, "p_sbu_id", sbu_name)
            if not sbu_result:
                print("[WARNING] SBU选择失败，尝试备用ID...")
                for cid in ["p_sbu", "sbuId", "sbu"]:
                    if self._select_combobox_by_text(target, cid, sbu_name):
                        break
        else:
            print("[INFO] SBU未输入，跳过")

        # ── 点击查询 ──
        print("[INFO] 点击查询按钮...")
        try:
            query_btn = target.locator("a#Query").first
            if query_btn.count() == 0:
                query_btn = target.locator("a:has-text('查询')").first
            if query_btn.count() == 0:
                query_btn = target.locator("button:has-text('查询')").first
            query_btn.scroll_into_view_if_needed()
            self._page.wait_for_timeout(500)
            query_btn.click()
            print("[INFO] 已点击查询按钮")
            self._page.wait_for_timeout(5000)
        except Exception as e:
            print(f"[ERROR] 点击查询失败: {e}")
            return None

        # ── 点击导出Excel ──
        print("[INFO] 正在导出Excel...")
        try:
            export_btn = target.locator("a:has-text('导出Excel')").first
            if export_btn.count() == 0:
                export_btn = target.locator("a:has-text('导出')").first
            if export_btn.count() == 0:
                export_btn = target.locator("button:has-text('导出Excel')").first

            download_context = (
                self._query_target if self._query_is_tab and self._query_target
                else self._page
            )

            with download_context.expect_download(timeout=180000) as download_info:
                export_btn.click()
                print("[INFO] 已点击导出Excel按钮，等待下载完成...")

            download = download_info.value
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            sbu_part = sbu_name.replace("/", "_") if sbu_name else "全部"
            filename = f"申请单_{sbu_part}_{start_date_str}_{end_date_str}_{timestamp}.xlsx"
            save_path = self.download_dir / filename
            download.save_as(save_path)
            try:
                download.delete()
            except Exception:
                pass
            print(f"[SUCCESS] 申请单已下载: {save_path}")
            return str(save_path)

        except Exception as e:
            print(f"[ERROR] 导出失败: {e}")
            # 检查下载目录中是否有最近的文件
            files = list(self.download_dir.glob("申请单_*.xlsx"))
            files.extend(list(self.download_dir.glob("*.xlsx")))
            if files:
                latest_file = max(files, key=lambda f: f.stat().st_mtime)
                print(f"[INFO] 检测到下载文件: {latest_file}")
                return str(latest_file)
            return None

    # ===================== 主入口 =====================

    def download_application_form(
        self,
        sbu_name: str = "",
        start_date_str: str = "",
        end_date_str: str = ""
    ) -> Optional[str]:
        """
        下载申请单报表（主入口方法）

        Args:
            sbu_name: SBU 名称（与续签查询一致）
            start_date_str: 申请时间开始（结束时间前30天）
            end_date_str: 申请时间结束（同续签查询结束时间）

        Returns:
            Optional[str]: 下载文件路径，失败返回 None
        """
        try:
            # 关闭上一轮打开的标签页/iframe，确保每次拿到干净的查询页
            if self._query_is_tab and self._query_target:
                try:
                    self._query_target.close()
                    print("[INFO] 已关闭上一轮申请单标签页")
                except Exception:
                    pass
            self._query_target = None
            self._query_is_tab = False

            self.navigate_to_application_form()
            result = self._query_and_export(
                sbu_name=sbu_name,
                start_date_str=start_date_str,
                end_date_str=end_date_str
            )
            return result
        except Exception as e:
            print(f"[ERROR] 申请单下载失败: {e}")
            try:
                screenshot_path = self.download_dir / "debug_app_form_error.png"
                self._page.screenshot(path=str(screenshot_path))
                print(f"[DEBUG] 错误截图已保存: {screenshot_path}")
            except Exception:
                pass
            return None
