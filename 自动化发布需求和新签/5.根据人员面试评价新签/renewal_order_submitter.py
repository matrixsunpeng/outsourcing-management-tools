"""
外包合同页面交互层
实现在"外包合同"页面的自动化操作
"""

import sys
from pathlib import Path
from typing import Optional, Tuple
import re

# 添加下载模块到路径
sys.path.insert(0, str(Path(__file__).parent / "下载外包续签查询"))

from playwright.sync_api import Page, Frame
from utils.logger import setup_logger

logger = setup_logger(__name__)


class OutsourceContractSubmitter:
    """外包合同页面操作交互器"""
    
    # CSS 选择器
    SELECTORS = {
        "vendor_combobox": "#techCoopId",        # 技术合作商名称 MiniUI buttonedit（实际控件ID）
        "app_no_input": "#p_app_no",             # 合作申请单编号 input ID（备用）
        "search_button": "a:has-text('查询'), button:has-text('查询'), .fa-search",  # 搜索按钮
        "work_location_input": "#p_work_location",  # 工作地点 input ID
        "calculate_cost_btn": "a:has-text('计算成本'), button:has-text('计算成本')",  # 计算成本按钮
        "order_amount_input": "#p_order_amount",  # 技术合作订单金额 input ID
        "submit_btn": "a:has-text('保存并提交审批'), button:has-text('保存并提交审批')",  # 提交按钮
        "personnel_table": "table[id*='personnel'], div[id*='personnel']",  # 人员信息表格
    }
    
    def __init__(self, page: Page):
        """
        初始化交互器
        
        Args:
            page: Playwright Page 或 Frame 对象
        """
        self.page = page
        self.root_page = page.page if isinstance(page, Frame) else page
        self.current_app_no: Optional[str] = None
        self.current_form_snapshot: Optional[dict] = None

    def _normalize_app_no(self, value: Optional[str]) -> str:
        """标准化申请单号，去除空白并统一大写。"""
        return re.sub(r"\s+", "", str(value or "")).upper().strip()

    def _extract_form_snapshot(self, state: Optional[dict]) -> dict:
        """提取用于校验当前表单是否串单的关键快照。"""
        state = state or {}
        return {
            "selectedAppNo": state.get("selectedAppNo") or "",
            "applicationText": state.get("applicationText") or "",
            "appId": state.get("appId") or "",
            "applicationId": state.get("applicationId") or "",
            "projectCode": state.get("projectCode") or "",
            "projectName": state.get("projectName") or "",
            "sbuName": state.get("sbuName") or "",
            "personnelCount": state.get("personnelCount") or 0,
        }

    def _snapshot_consistent(self, state: Optional[dict], snapshot: Optional[dict] = None) -> bool:
        """判断当前表单是否与已记录快照一致，避免串读上一条记录。"""
        state = state or {}
        snapshot = snapshot or self.current_form_snapshot or {}
        if not snapshot:
            return False

        normalized_selected = self._normalize_app_no(state.get("selectedAppNo"))
        normalized_snapshot_selected = self._normalize_app_no(snapshot.get("selectedAppNo"))
        normalized_application_text = self._normalize_app_no(state.get("applicationText"))
        normalized_snapshot_text = self._normalize_app_no(snapshot.get("applicationText"))

        if normalized_selected and normalized_snapshot_selected and normalized_selected != normalized_snapshot_selected:
            return False
        if normalized_application_text and normalized_snapshot_text and normalized_application_text != normalized_snapshot_text:
            return False

        strong_keys = ["appId", "applicationId", "projectCode", "projectName", "sbuName"]
        matched_keys = 0
        for key in strong_keys:
            state_val = str(state.get(key) or "").strip()
            snapshot_val = str(snapshot.get(key) or "").strip()
            if state_val and snapshot_val:
                if state_val != snapshot_val:
                    return False
                matched_keys += 1

        if matched_keys > 0:
            return True

        if normalized_selected and normalized_snapshot_selected:
            return normalized_selected == normalized_snapshot_selected

        return bool(normalized_application_text and normalized_snapshot_text and normalized_application_text == normalized_snapshot_text)

    def _remember_current_form(self, expected_app_no: Optional[str], state: Optional[dict]) -> None:
        """记录当前成功加载的申请单与表单快照。"""
        snapshot = self._extract_form_snapshot(state)
        self.current_app_no = expected_app_no or snapshot.get("selectedAppNo") or snapshot.get("applicationText") or None
        self.current_form_snapshot = snapshot

    def _clear_current_form(self) -> None:
        """清空上一条记录遗留的申请单状态。"""
        self.current_app_no = None
        self.current_form_snapshot = None

    def _collect_amount_diagnostics(self, expected_app_no: Optional[str] = None) -> dict:
        """采集当前表单的金额相关字段，便于定位提交时真实判空字段。"""
        normalized_expected = self._normalize_app_no(expected_app_no or self.current_app_no)

        try:
            return self.page.evaluate(r"""(args) => {

                function normalizeText(v) {
                    return String(v || '').replace(/\s+/g, '').trim().toUpperCase();
                }

                function normalizeAmount(v) {
                    return String(v || '').replace(/,/g, '').replace(/\s+/g, '').trim();
                }

                function getInputValue(id) {
                    var el = document.getElementById(id);
                    return el ? normalizeAmount(el.value) : '';
                }

                function getFirstVal(ids) {
                    for (var i = 0; i < ids.length; i++) {
                        var val = getInputValue(ids[i]);
                        if (val) return val;
                    }
                    return '';
                }

                var fieldIds = ['p_order_amount', 'orderAmount', 'orderAmountDiffer', 'changeOrderAmount', 'contractMoney'];
                var amountFields = [];

                for (var i = 0; i < fieldIds.length; i++) {
                    var fieldId = fieldIds[i];
                    var miniValue = '';
                    try {
                        var ctrl = window.mini && mini.get(fieldId);
                        if (ctrl && ctrl.getValue) {
                            miniValue = normalizeAmount(ctrl.getValue());
                        }
                    } catch (e) {}

                    var domValue = getFirstVal([
                        fieldId,
                        fieldId + '$text',
                        fieldId + '$value'
                    ]);

                    amountFields.push({
                        field: fieldId,
                        miniValue: miniValue,
                        domValue: domValue,
                        chosenValue: miniValue || domValue
                    });
                }

                var inputs = Array.from(document.querySelectorAll('input[type=text], input:not([type])'));
                var candidates = [];
                for (var j = 0; j < inputs.length; j++) {
                    var id = String(inputs[j].id || '');
                    var name = String(inputs[j].name || '');
                    var key = (id + '|' + name).toLowerCase();
                    if (key.indexOf('amount') >= 0 || key.indexOf('money') >= 0 || key.indexOf('fee') >= 0) {
                        candidates.push({
                            source: 'dom:' + (id || name || ('index' + j)),
                            value: normalizeAmount(inputs[j].value)
                        });
                    }
                }

                var projectCode = getInputValue('projectCode$text') || getInputValue('projectCode');
                var projectName = getInputValue('projectName$text') || getInputValue('projectName');
                var sbuName = getInputValue('sbuName$text') || getInputValue('sbuName');
                var applicationId = getInputValue('applicationId');
                var appId = getInputValue('appId');
                var applicationText = getInputValue('application$text');
                var selectedAppNo = getFirstVal([
                    'btnEdit1$text', 'btnEdit1$value',
                    'renewApplyNo$text', 'renewApplyNo',
                    'renewalApplyNo$text', 'renewalApplyNo',
                    'appNo$text', 'appNo',
                    'applyNo$text', 'applyNo',
                    'p_app_no', 'application$text'
                ]);
                var personnelCount = 0;

                try {
                    if (window.mini && mini.gets) {
                        var grids = mini.gets('datagrid') || [];
                        for (var g = 0; g < grids.length; g++) {
                            if (grids[g] && grids[g].getData) {
                                var data = grids[g].getData() || [];
                                if (data.length > personnelCount) personnelCount = data.length;
                            }
                        }
                    }
                } catch (e) {}

                var expected = normalizeText(args.expectedAppNo || '');
                var normalizedSelected = normalizeText(selectedAppNo);
                var normalizedApplicationText = normalizeText(applicationText);

                return {
                    selectedAppNo: selectedAppNo,
                    applicationText: applicationText,
                    matchesExpected: !expected || (normalizedSelected && normalizedSelected === expected) || (normalizedApplicationText && normalizedApplicationText === expected),
                    appId: appId,
                    applicationId: applicationId,
                    projectCode: projectCode,
                    projectName: projectName,
                    sbuName: sbuName,
                    personnelCount: personnelCount,
                    amountFields: amountFields,
                    candidates: candidates.slice(0, 20)
                };
            }""", {"expectedAppNo": normalized_expected})
        except Exception as e:
            logger.warning(f"[金额] 采集金额字段诊断信息失败: {e}")
            return {"error": str(e)}

    
    def select_vendor(self, vendor_name: str) -> bool:

        """
        在"外包合同"标签页找到"技术合作商名称"后的文本框，直接输入技术合作商名称，
        等待下拉列表出现后点击匹配项（优先精确匹配，否则取第1个非空项）。

        定位策略（按优先级）：
        1. ID 为 p_vendor_id 的 MiniUI combobox 内部文本输入框
        2. 与"技术合作商名称"标签最近的可见 input
        3. 页面上第一个可见 input[type=text] / 无 type 的 input（最后兜底）

        Args:
            vendor_name: 技术合作商名称

        Returns:
            bool: 是否成功
        """
        logger.info(f"=== 选择技术合作商: {vendor_name} ===")

        try:
            self.page.wait_for_timeout(800)

            # ── 步骤 1：定位输入框 ──────────────────────────────────────────
            # 按优先级依次尝试几个选择器，找到第一个可见的
            vendor_input = None
            tried_selectors = []

            candidate_selectors = [
                "input[id='techCoopId$text']",    # MiniUI buttonedit 文本框（实际控件ID）
                "#techCoopId input[type='text']",
                "#techCoopId input",
                "input[id='p_vendor_id$text']",   # 备用（旧选择器）
                "#p_vendor_id input[type='text']",
                "#p_vendor_id input",
                "input[name='p_vendor_id']",
                "input[id*='vendor']",
            ]

            for sel in candidate_selectors:
                try:
                    loc = self.page.locator(sel).first
                    if loc.count() > 0:
                        vendor_input = loc
                        tried_selectors.append(f"命中: {sel}")
                        break
                    tried_selectors.append(f"未找到: {sel}")
                except Exception as ex:
                    tried_selectors.append(f"异常({sel}): {ex}")

            # 若以上均未命中，通过 JS 查找"技术合作商名称"标签旁最近的 input
            # 同时诊断：打印页面所有 input 及 MiniUI 控件信息
            if vendor_input is None:
                logger.info("[技术合作商] CSS 选择器未命中，尝试通过标签定位...")

                # 诊断：列出所有 input 和 MiniUI 信息
                debug_info = self.page.evaluate("""() => {
                    var allInputs = Array.from(document.querySelectorAll('input')).slice(0, 30).map(function(el) {
                        return { id: el.id, name: el.name, type: el.type, cls: el.className.substring(0,40) };
                    });
                    var miniControls = null;
                    try {
                        // 列举所有 MiniUI 控件
                        var allMini = [];
                        if (window.mini && mini.getAll) {
                            var controls = mini.getAll();
                            for (var i = 0; i < Math.min(controls.length, 30); i++) {
                                var c = controls[i];
                                allMini.push(c.id + ' | ' + (c.uiClass||c.type||''));
                            }
                        }
                        miniControls = allMini;
                    } catch(e) { miniControls = 'error: ' + e; }
                    // 找包含"技术合作商"文字的元素
                    var vendorLabels = Array.from(document.querySelectorAll('*')).filter(function(el) {
                        return el.childNodes.length <= 5 && (el.textContent||'').indexOf('技术合作商') >= 0
                            && (el.textContent||'').trim().length < 20;
                    }).map(function(el){ return el.tagName+'#'+(el.id||'')+'.'+(el.className||'').substring(0,20)+'='+el.textContent.trim(); });
                    return { allInputs: allInputs, miniControls: miniControls, vendorLabels: vendorLabels.slice(0,10) };
                }""")
                logger.info(f"[技术合作商] DOM诊断 - inputs: {debug_info.get('allInputs')}")
                logger.info(f"[技术合作商] DOM诊断 - MiniUI控件: {debug_info.get('miniControls')}")
                logger.info(f"[技术合作商] DOM诊断 - 含技术合作商文字的标签: {debug_info.get('vendorLabels')}")
                js_result = self.page.evaluate("""() => {
                    function normalize(t) { return String(t || '').replace(/\\s+/g,'').replace(/[：:]/g,''); }

                    var labels = Array.from(document.querySelectorAll('label,td,th,span,div'));
                    var inputs = Array.from(document.querySelectorAll('input'));
                    var best = null;

                    for (var i = 0; i < labels.length; i++) {
                        if (normalize(labels[i].textContent) !== '技术合作商名称') continue;
                        var lr = labels[i].getBoundingClientRect();
                        for (var j = 0; j < inputs.length; j++) {
                            var inp = inputs[j];
                            var r = inp.getBoundingClientRect();
                            var dx = r.left - lr.right;
                            var dy = Math.abs(r.top - lr.top);
                            if (dx < -20 || dy > 80) continue;
                            var score = 1000 - Math.abs(dx) - dy * 4;
                            if (!best || score > best.score) best = { score: score, id: inp.id, name: inp.name };
                        }
                    }
                    return best;
                }""")

                if js_result:
                    sel_by_js = (
                        f"input#{js_result['id']}" if js_result.get("id")
                        else f"input[name='{js_result['name']}']" if js_result.get("name")
                        else None
                    )
                    if sel_by_js:
                        try:
                            loc = self.page.locator(sel_by_js).first
                            if loc.count() > 0:
                                vendor_input = loc
                                tried_selectors.append(f"JS标签定位: {sel_by_js}")
                        except Exception:
                            pass

            logger.info(f"[技术合作商] 选择器尝试情况: {tried_selectors}")

            if vendor_input is None:
                logger.error("[技术合作商] 未找到技术合作商名称输入框，放弃")
                return False

            # ── 步骤 2：清空并输入技术合作商名称 ───────────────────────────
            # 用 JS 先触发 focus/click，再通过 Playwright 输入
            vendor_input.click(force=True)
            self.page.wait_for_timeout(300)
            vendor_input.press("Control+a")
            vendor_input.press("Delete")
            vendor_input.type(vendor_name, delay=80)   # 逐字符输入，触发输入事件
            logger.info(f"[技术合作商] 已输入: {vendor_name}，等待下拉...")
            self.page.wait_for_timeout(1500)

            # ── 步骤 3：等待并点击下拉选项 ─────────────────────────────────
            # MiniUI combobox 下拉的常见选择器
            dropdown_selectors = [
                ".mini-listbox-item",
                ".mini-combobox-item",
                ".mini-popup li",
                ".mini-popup .mini-listbox-item",
                "ul.mini-listbox li",
                ".x-combo-list-item",
            ]

            clicked_text = None
            for drop_sel in dropdown_selectors:
                try:
                    items = self.page.locator(drop_sel)
                    count = items.count()
                    if count == 0:
                        continue

                    # 收集可见的非空选项
                    visible_items = []
                    for idx in range(count):
                        item = items.nth(idx)
                        if item.is_visible():
                            text = (item.text_content() or "").strip()
                            if text:
                                visible_items.append((idx, item, text))

                    if not visible_items:
                        continue

                    logger.info(f"[技术合作商] 下拉选项({drop_sel}): {[t for _,_,t in visible_items[:5]]}")

                    # 优先精确匹配，次选包含匹配，最后取第1个
                    target_item = None
                    for _, item, text in visible_items:
                        if text == vendor_name:
                            target_item = item
                            break
                    if target_item is None:
                        for _, item, text in visible_items:
                            if vendor_name in text or text in vendor_name:
                                target_item = item
                                break
                    if target_item is None:
                        target_item = visible_items[0][1]

                    target_item.scroll_into_view_if_needed()
                    target_item.click()
                    clicked_text = (target_item.text_content() or "").strip()
                    logger.info(f"[技术合作商] 已点击下拉项: {clicked_text}")
                    self.page.wait_for_timeout(600)
                    break
                except Exception as ex:
                    logger.debug(f"[技术合作商] 下拉尝试({drop_sel}) 异常: {ex}")
                    continue

            if clicked_text is None:
                # 下拉未出现或点击失败 —— 补一个 Enter/Tab，尽量触发 buttonedit/autocomplete 的选中动作
                try:
                    vendor_input.press("Enter")
                    self.page.wait_for_timeout(300)
                except Exception:
                    pass
                try:
                    vendor_input.press("Tab")
                    self.page.wait_for_timeout(300)
                except Exception:
                    pass

                current_val = vendor_input.input_value() or ""
                if current_val and (vendor_name in current_val or current_val in vendor_name):
                    logger.info(f"[技术合作商] 未出现下拉但输入框已有值: {current_val}，视为成功")
                    return True
                logger.warning(f"[技术合作商] 未成功点击下拉选项，当前值: {current_val}")
                return False


            return True

        except Exception as e:
            logger.error(f"[技术合作商] 异常: {e}")
            return False
    
    def search_application(self, app_no: str) -> bool:
        """
        搜索并真正选中合作申请单。

        注意：该页面的"合作申请单"看起来像普通文本框，但实际是 buttonedit，
        仅填入 `application$text` 往往不会回填隐藏 ID，后续项目/金额字段也不会加载。
        因此这里会按"输入 -> 校验是否已加载 -> 必要时打开弹框查询并选中结果"的方式处理。

        Args:
            app_no: 合作申请单编号（待续签申请单）

        Returns:
            bool: 是否成功选中并加载申请单
        """
        logger.info(f"=== 搜索申请单: {app_no} ===")

        try:
            self._clear_current_form()
            self.page.wait_for_timeout(1000)

            def get_state(expected_app_no: Optional[str] = None) -> dict:
                return self.page.evaluate("""(args) => {
                    function getVal(id) {
                        var el = document.getElementById(id);
                        return el ? String(el.value || '').trim() : '';
                    }
                    function normalize(text) {
                        return String(text || '').replace(/\\s+/g, '').trim();
                    }
                    function getFirstVal(ids) {
                        for (var i = 0; i < ids.length; i++) {
                            var val = getVal(ids[i]);
                            if (val) return val;
                        }
                        return '';
                    }

                    var projectCode = getVal('projectCode$text') || getVal('projectCode');
                    var projectName = getVal('projectName$text') || getVal('projectName');
                    var sbuName = getVal('sbuName$text') || getVal('sbuName');
                    var appId = getVal('appId');
                    var applicationId = getVal('applicationId');
                    var applicationText = getVal('application$text');
                    var selectedAppNo = getFirstVal([
                        'btnEdit1$text', 'btnEdit1$value',
                        'renewApplyNo$text', 'renewApplyNo',
                        'renewalApplyNo$text', 'renewalApplyNo',
                        'appNo$text', 'appNo',
                        'applyNo$text', 'applyNo',
                        'p_app_no', 'application$text'
                    ]);
                    var personnelCount = 0;

                    try {
                        if (window.mini && mini.gets) {
                            var grids = mini.gets('datagrid') || [];
                            for (var i = 0; i < grids.length; i++) {
                                if (grids[i] && grids[i].getData) {
                                    var data = grids[i].getData() || [];
                                    if (data.length > personnelCount) personnelCount = data.length;
                                }
                            }
                        }
                    } catch (e) {}

                    var expected = normalize(args.expectedAppNo || '');
                    var normalizedSelected = normalize(selectedAppNo);

                    var hasBusinessData = !!(appId || applicationId || projectCode || projectName || personnelCount > 0);

                    return {
                        loaded: !!(selectedAppNo || hasBusinessData),
                        hasBusinessData: hasBusinessData,
                        applicationText: applicationText,
                        selectedAppNo: selectedAppNo,
                        matchesExpected: !expected || (normalizedSelected && normalizedSelected === expected),
                        appId: appId,
                        applicationId: applicationId,
                        projectCode: projectCode,
                        projectName: projectName,
                        sbuName: sbuName,
                        personnelCount: personnelCount,
                    };

                }""", {"expectedAppNo": expected_app_no or ""})

            def _state_changed(before_state: Optional[dict], current_state: dict) -> bool:
                if not before_state:
                    return True
                keys = [
                    'selectedAppNo', 'appId', 'applicationId',
                    'projectCode', 'projectName', 'sbuName', 'personnelCount'
                ]
                for key in keys:
                    if (before_state.get(key) or '') != (current_state.get(key) or ''):
                        return True
                return False

            def try_wait_loaded(label: str, expected_app_no: Optional[str] = None,
                                before_state: Optional[dict] = None,
                                rounds: int = 6, wait_ms: int = 800) -> bool:
                for _ in range(rounds):
                    state = get_state(expected_app_no)
                    changed = _state_changed(before_state, state)
                    matches_expected = state.get("matchesExpected")
                    selected_app_no = state.get("selectedAppNo")
                    valid_loaded = bool(
                        state.get("loaded") and (
                            matches_expected or
                            (not expected_app_no and changed) or
                            (expected_app_no and not selected_app_no and changed)
                        ) and (changed or matches_expected)
                    )
                    if valid_loaded:
                        logger.info(
                            f"[搜索] {label}后申请单已加载: "
                            f"selectedAppNo={state.get('selectedAppNo')}, "
                            f"appId={state.get('appId')}, applicationId={state.get('applicationId')}, "
                            f"projectCode={state.get('projectCode')}, projectName={state.get('projectName')}, "
                            f"人员数={state.get('personnelCount')}"
                        )
                        return True
                    self.page.wait_for_timeout(wait_ms)
                state = get_state(expected_app_no)
                logger.info(
                    f"[搜索] {label}后仍未加载: selectedAppNo={state.get('selectedAppNo')}, "
                    f"applicationText={state.get('applicationText')}, matchesExpected={state.get('matchesExpected')}, "
                    f"appId={state.get('appId')}, applicationId={state.get('applicationId')}, "
                    f"projectCode={state.get('projectCode')}, projectName={state.get('projectName')}, "
                    f"人员数={state.get('personnelCount')}"
                )
                return False


            before_state = get_state()

            popup_targets = [("当前上下文", self.page)]
            if self.root_page is not self.page:
                popup_targets.append(("顶层页面", self.root_page))


            def detect_popup_context():
                script = """() => {
                    function isVisible(el) {
                        if (!el) return false;
                        var style = window.getComputedStyle(el);
                        var rect = el.getBoundingClientRect();
                        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                    }

                    function summarize(el) {
                        var style = window.getComputedStyle(el);
                        var rect = el.getBoundingClientRect();
                        var text = String(el.textContent || '').replace(/\\s+/g, ' ').trim();
                        var inputs = Array.from(el.querySelectorAll("input:not([type='hidden']):not([type='checkbox']):not([type='radio'])")).filter(isVisible);

                        var btns = Array.from(el.querySelectorAll('a, button, span, input[type=button], input[type=submit]')).filter(isVisible);
                        return {
                            tag: el.tagName || '',
                            id: el.id || '',
                            cls: String(el.className || '').substring(0, 80),
                            z: parseInt(style.zIndex || '0', 10) || 0,
                            area: Math.round(rect.width * rect.height),
                            position: style.position || '',
                            inputCount: inputs.length,
                            buttonCount: btns.length,
                            text: text.substring(0, 120)
                        };
                    }

                    var selectors = '.mini-window, .mini-popup, .mini-modal, [role="dialog"], .mini-panel';
                    var candidates = Array.from(document.querySelectorAll(selectors))
                        .filter(isVisible)
                        .map(function(el) {
                            var info = summarize(el);
                            info.el = el;
                            return info;
                        })
                        .sort(function(a, b) {
                            if (b.z !== a.z) return b.z - a.z;
                            return b.area - a.area;
                        });

                    var matched = null;
                    for (var i = 0; i < candidates.length; i++) {
                        var c = candidates[i];
                        var looksPopup = c.cls.indexOf('mini-window') >= 0 || c.cls.indexOf('mini-popup') >= 0 || c.cls.indexOf('mini-modal') >= 0 || c.z >= 1000 || c.position === 'fixed';
                        var looksSearch = c.text.indexOf('申请单') >= 0 || c.text.indexOf('查询') >= 0 || (c.inputCount > 0 && c.buttonCount > 0);
                        var looksGridOnly = c.id === 'datagrid1' && c.inputCount === 0;
                        if (looksPopup && looksSearch && !looksGridOnly) {
                            matched = c;
                            break;
                        }
                    }

                    return {
                        success: !!matched,
                        popup: matched ? summarize(matched.el) : null,
                        candidates: candidates.slice(0, 8).map(function(c) {
                            return {
                                tag: c.tag,
                                id: c.id,
                                cls: c.cls,
                                z: c.z,
                                area: c.area,
                                position: c.position,
                                inputCount: c.inputCount,
                                buttonCount: c.buttonCount,
                                text: c.text
                            };
                        })
                    };
                }"""

                seen = []
                for target_name, target in popup_targets:
                    try:
                        probe = target.evaluate(script)
                    except Exception as ex:
                        seen.append({"target": target_name, "error": str(ex)})
                        continue

                    seen.append({
                        "target": target_name,
                        "success": probe.get("success"),
                        "popup": probe.get("popup"),
                        "candidates": probe.get("candidates"),
                    })
                    if probe.get("success"):
                        return target_name, target, probe, seen

                return None, None, None, seen

            # 步骤1：优先按"申请单"相关标签就近定位真实输入框，而不是盲信固定 ID

            app_input = None
            app_input_id = None

            locate_result = self.page.evaluate("""() => {
                function isVisible(el) {
                    if (!el) return false;
                    var style = window.getComputedStyle(el);
                    var rect = el.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                }
                function norm(text) {
                    return String(text || '').replace(/\\s+/g, '').replace(/[：:]/g, '');

                }

                var labels = Array.from(document.querySelectorAll('label, td, th, span, div'))
                    .filter(function(el) {
                        return isVisible(el) && el.childNodes.length <= 5 && norm(el.textContent).indexOf('申请单') >= 0;
                    });
                var inputs = Array.from(document.querySelectorAll("input:not([type='hidden'])"))
                    .filter(isVisible);

                var preferredTexts = ['待续签申请单', '合作申请单编号', '合作申请单', '申请单编号', '申请单'];
                var best = null;
                var debugLabels = [];
                var labelCells = [];

                for (var i = 0; i < labels.length; i++) {
                    var labelText = norm(labels[i].textContent);
                    if (!labelText || labelText.length > 20) continue;
                    debugLabels.push(labelText);

                    var nextCell = labels[i].nextElementSibling;
                    if (nextCell) {
                        labelCells.push({
                            labelText: labelText,
                            nextCellHtml: (nextCell.innerHTML || '').replace(/\\s+/g, ' ').trim().substring(0, 300),

                            nextCellNodes: Array.from(nextCell.querySelectorAll('*')).slice(0, 15).map(function(el) {
                                return el.tagName + '#' + (el.id || '') + '.' + String(el.className || '').substring(0, 30) + '|' + String(el.textContent || '').trim().substring(0, 20);
                            })
                        });
                    }

                    var lr = labels[i].getBoundingClientRect();
                    for (var j = 0; j < inputs.length; j++) {
                        var inp = inputs[j];
                        var ir = inp.getBoundingClientRect();
                        var dx = ir.left - lr.right;
                        var dy = Math.abs(ir.top - lr.top);
                        if (dx < -30 || dy > 80) continue;

                        var score = 1000 - Math.abs(dx) - dy * 4;
                        for (var p = 0; p < preferredTexts.length; p++) {
                            if (labelText === preferredTexts[p]) {
                                score += 500 - p * 50;
                                break;
                            }
                        }
                        if ((inp.id || '') === 'application$text') score -= 200;
                        if (!best || score > best.score) {
                            best = {
                                score: score,
                                labelText: labelText,
                                inputId: inp.id || '',
                                inputName: inp.name || '',
                                inputClass: String(inp.className || '')
                            };
                        }
                    }
                }

                return {
                    best: best,
                    debugLabels: debugLabels.slice(0, 12),
                    labelCells: labelCells.slice(0, 6),
                    debugInputs: inputs.slice(0, 15).map(function(inp) {
                        return (inp.id || '') + '|' + (inp.name || '') + '|' + String(inp.className || '').substring(0, 30);
                    })
                };

            }""")

            logger.info(
                f"[搜索] 申请单定位诊断 - labels={locate_result.get('debugLabels')} | "
                f"inputs={locate_result.get('debugInputs')} | best={locate_result.get('best')} | "
                f"labelCells={locate_result.get('labelCells')}"
            )


            best_input = locate_result.get("best") or {}
            if best_input.get("inputId"):
                app_input_id = best_input.get("inputId")
                app_input = self.page.locator(f"input[id='{app_input_id}']").first
            elif best_input.get("inputName"):
                app_input = self.page.locator(f"input[name='{best_input.get('inputName')}']").first

            if (app_input is None) or app_input.count() == 0:
                for sel in [
                    "input[id='btnEdit1$text']",
                    "input[id='renewApplyNo$text']",
                    "input[id='renewalApplyNo$text']",
                    "input[id='appNo$text']",
                    "input[id='applyNo$text']",
                    "input[id*='apply'][id$='$text']",
                    "input[id*='app'][id$='$text']",
                    "input[id*='application'][id$='$text']",
                    "input[id='application$text']",
                ]:

                    try:
                        loc = self.page.locator(sel).first
                        if loc.count() > 0:
                            app_input = loc
                            app_input_id = sel.split("'")[1] if "id='" in sel else None
                            logger.info(f"[搜索] 回退选择器命中: {sel}")
                            break
                    except Exception:
                        continue

            input_editable = False
            if app_input is not None and app_input.count() > 0:
                input_editable = self.page.evaluate("""(args) => {
                    var inp = args.inputId ? document.getElementById(args.inputId) : null;
                    if (!inp && args.inputName) inp = document.querySelector("input[name='" + args.inputName + "']");
                    if (!inp) return false;
                    return !inp.readOnly && !inp.disabled;
                }""", {"inputId": app_input_id, "inputName": best_input.get("inputName")})

            if app_input is not None and app_input.count() > 0 and input_editable:
                app_input.click(force=True)
                self.page.wait_for_timeout(200)
                app_input.press("Control+a")
                app_input.press("Delete")
                app_input.type(app_no, delay=60)
                current_val = app_input.input_value() or ""
                logger.info(f"[搜索] 已在申请单文本框输入: {app_no} | inputId={app_input_id} | 当前值={current_val}")
                self.page.wait_for_timeout(500)

                self.page.evaluate("""(args) => {
                    var inp = args.inputId ? document.getElementById(args.inputId) : null;
                    if (inp) {
                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                        inp.dispatchEvent(new Event('blur', { bubbles: true }));
                    }
                }""", {"inputId": app_input_id})

                try:
                    app_input.press("Enter")
                except Exception:
                    pass
                self.page.wait_for_timeout(500)
                try:
                    app_input.press("Tab")
                except Exception:
                    pass

                if try_wait_loaded("直接输入", expected_app_no=app_no, before_state=before_state, rounds=4, wait_ms=700):
                    self._remember_current_form(app_no, get_state(app_no))
                    return True
            elif app_input is not None and app_input.count() > 0:
                logger.info(f"[搜索] 申请单控件为只读/按钮式控件，按业务要求直接打开弹框选择: inputId={app_input_id}")



            # 步骤2：如果单纯输入没触发加载，则点击该输入框对应的 buttonedit 按钮打开弹框

            logger.info("[搜索] 直接输入未触发加载，尝试打开申请单弹框...")
            popup_btn_result = {"success": False, "error": "未执行点击"}
            control_id = app_input_id.split("$")[0] if app_input_id and "$" in app_input_id else app_input_id

            click_selectors = []
            if control_id:
                click_selectors.extend([
                    f"#{control_id} .mini-buttonedit-button",
                    f"#{control_id} .mini-buttonedit-icon",
                    f"#{control_id}",
                ])
            if app_input_id:
                click_selectors.extend([
                    f"input[id='{app_input_id}']",
                    f"input[id='{app_input_id}'] + span",
                ])

            for sel in click_selectors:
                try:
                    btn = self.page.locator(sel).first
                    if btn.count() > 0:
                        btn.click(force=True)
                        popup_btn_result = {"success": True, "selector": sel}
                        logger.info(f"[搜索] 已点击申请单控件: {sel}")
                        break
                except Exception as ex:
                    popup_btn_result = {"success": False, "error": str(ex), "selector": sel}
                    continue

            if not popup_btn_result.get("success"):
                popup_btn_result = self.page.evaluate("""(args) => {
                    var inp = args.inputId ? document.getElementById(args.inputId) : null;
                    if (!inp && args.inputName) inp = document.querySelector("input[name='" + args.inputName + "']");
                    if (!inp) return { success: false, error: '未找到申请单输入框' };

                    var parent = inp.closest('.mini-buttonedit') || inp.parentElement;
                    var btn = null;
                    if (parent) {
                        btn = parent.querySelector('.mini-buttonedit-button, .mini-buttonedit-icon');
                    }
                    if (!btn) {
                        var sib = inp.nextElementSibling;
                        while (sib) {
                            var cls = String(sib.className || '');
                            if (cls.indexOf('mini-buttonedit-button') >= 0 || cls.indexOf('mini-buttonedit-icon') >= 0) {
                                btn = sib;
                                break;
                            }
                            sib = sib.nextElementSibling;
                        }
                    }
                    if (!btn && parent) btn = parent;
                    if (!btn) return { success: false, error: '未找到申请单对应按钮', inputId: inp.id || '', inputName: inp.name || '' };
                    btn.click();
                    return { success: true, inputId: inp.id || '', inputName: inp.name || '' };
                }""", {"inputId": app_input_id, "inputName": best_input.get("inputName")})

            if not popup_btn_result.get("success"):
                logger.error(f"[搜索] 无法打开申请单弹框: {popup_btn_result.get('error')}")
                return False

            popup_context_name = None
            popup_target = None
            popup_probe = None
            popup_seen = []

            for _ in range(8):
                popup_context_name, popup_target, popup_probe, popup_seen = detect_popup_context()
                if popup_target is not None:
                    break
                self.page.wait_for_timeout(500)

            if popup_target is None:
                logger.error(f"[弹框] 未检测到申请单弹框: {popup_seen}")
                return False

            logger.info(
                f"[弹框] 已定位到申请单弹框，所在上下文={popup_context_name} | "
                f"popup={popup_probe.get('popup')} | candidates={popup_probe.get('candidates')}"
            )

            interaction_target = popup_target
            interaction_context_name = popup_context_name
            frame_probes = []
            popup_info = (popup_probe or {}).get("popup") or {}

            if popup_info.get("inputCount", 0) == 0:
                for _ in range(8):
                    frame_probes = []
                    for frame in self.root_page.frames:
                        if frame == self.root_page.main_frame:
                            continue
                        if isinstance(self.page, Frame) and frame == self.page:
                            continue
                        try:
                            probe = frame.evaluate("""() => {
                                function isVisible(el) {
                                    if (!el) return false;
                                    var style = window.getComputedStyle(el);
                                    var rect = el.getBoundingClientRect();
                                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                                }
                                function norm(text) {
                                    return String(text || '').replace(/\\s+/g, '').replace(/[：:]/g, '');
                                }
                                var inputs = Array.from(document.querySelectorAll("input:not([type='hidden']):not([type='checkbox']):not([type='radio'])")).filter(function(el) {
                                    return isVisible(el) && !el.disabled;
                                });
                                var labels = Array.from(document.querySelectorAll('label, td, th, span, div')).filter(function(el) {
                                    return isVisible(el) && norm(el.textContent).indexOf('合作申请单编号') >= 0;
                                });
                                return {
                                    url: location.href,
                                    title: document.title || '',
                                    inputCount: inputs.length,
                                    labelCount: labels.length,
                                    bodyText: String(document.body ? document.body.textContent || '' : '').replace(/\\s+/g, ' ').trim().substring(0, 160),
                                    inputs: inputs.slice(0, 8).map(function(el) {
                                        return (el.id || '') + '|' + (el.name || '') + '|' + (el.placeholder || '') + '|' + (el.readOnly ? 'readonly' : 'editable');
                                    }),
                                    labels: labels.slice(0, 8).map(function(el) { return norm(el.textContent); })
                                };
                            }""")
                            probe["frameName"] = frame.name
                            probe["frameUrl"] = frame.url
                            frame_probes.append(probe)
                            if probe.get("labelCount") or probe.get("inputCount"):
                                interaction_target = frame
                                interaction_context_name = f"顶层页面-弹框iframe({frame.name or frame.url})"
                                break
                        except Exception as ex:
                            frame_probes.append({"frameName": getattr(frame, 'name', ''), "frameUrl": getattr(frame, 'url', ''), "error": str(ex)})
                            continue
                    if interaction_target is not popup_target:
                        break
                    self.page.wait_for_timeout(400)

            if interaction_target is not popup_target:
                logger.info(f"[弹框] 已切换到弹框内 iframe 继续操作: {interaction_context_name} | frameProbes={frame_probes}")
            else:
                logger.info(f"[弹框] 将继续在 {interaction_context_name} 中尝试查询 | frameProbes={frame_probes}")

            # 步骤3：在弹框中找到"合作申请单编号"，输入待续签申请单并点击"查询"
            popup_query_result = interaction_target.evaluate("""(args) => {

                function isVisible(el) {
                    if (!el) return false;
                    var style = window.getComputedStyle(el);
                    var rect = el.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                }

                function norm(text) {
                    return String(text || '').replace(/\\s+/g, '').replace(/[：:]/g, '');

                }

                function pickDialog() {
                    var selectors = '.mini-window, .mini-popup, .mini-modal, [role="dialog"], .mini-panel';
                    var candidates = Array.from(document.querySelectorAll(selectors))
                        .filter(isVisible)
                        .map(function(el) {
                            var style = window.getComputedStyle(el);
                            var rect = el.getBoundingClientRect();
                            var text = String(el.textContent || '').replace(/\\s+/g, ' ').trim();

                            return {
                                el: el,
                                z: parseInt(style.zIndex || '0', 10) || 0,
                                area: rect.width * rect.height,
                                cls: String(el.className || ''),
                                text: text,
                                inputCount: Array.from(el.querySelectorAll("input:not([type='hidden']):not([type='checkbox']):not([type='radio'])")).filter(isVisible).length
                            };
                        })
                        .sort(function(a, b) {
                            if (b.z !== a.z) return b.z - a.z;
                            return b.area - a.area;
                        });

                    for (var i = 0; i < candidates.length; i++) {
                        var c = candidates[i];
                        var looksPopup = c.cls.indexOf('mini-window') >= 0 || c.cls.indexOf('mini-popup') >= 0 || c.cls.indexOf('mini-modal') >= 0 || c.z >= 1000;
                        var looksSearch = c.text.indexOf('合作申请单编号') >= 0 || c.text.indexOf('申请单') >= 0 || c.text.indexOf('查询') >= 0 || c.inputCount > 0;
                        if (looksPopup && looksSearch) return c.el;
                    }
                    return candidates.length ? candidates[0].el : null;
                }

                var dialog = pickDialog();
                if (!dialog) {
                    return { success: false, error: '未找到弹框节点' };
                }

                var root = document;
                var labels = Array.from(root.querySelectorAll('label, td, th, span, div')).filter(function(el) {
                    if (!isVisible(el)) return false;
                    var t = norm(el.textContent);
                    return t === '合作申请单编号' || t === '申请单编号';
                });
                var inputs = Array.from(root.querySelectorAll("input:not([type='hidden']):not([type='checkbox']):not([type='radio'])"))
                    .filter(function(el) { return isVisible(el) && !el.readOnly && !el.disabled; });

                var targetInput = null;
                var matchedLabel = '';
                var preferredSelectors = [
                    "input[id='p_application_code$text']",
                    "input[name='p_application_code']",
                    "input[id*='application_code']",
                    "input[id*='apply'][id$='$text']",
                    "input[id*='app'][id$='$text']"
                ];
                for (var s = 0; s < preferredSelectors.length && !targetInput; s++) {
                    var candidate = root.querySelector(preferredSelectors[s]);
                    if (candidate && isVisible(candidate) && !candidate.readOnly && !candidate.disabled) {
                        targetInput = candidate;
                        matchedLabel = 'selector:' + preferredSelectors[s];
                    }
                }

                for (var i = 0; i < labels.length && !targetInput; i++) {
                    var label = labels[i];
                    matchedLabel = norm(label.textContent);
                    var cell = label.closest('td, th');
                    if (cell && cell.nextElementSibling) {
                        var siblingInput = cell.nextElementSibling.querySelector("input:not([type='hidden']):not([type='checkbox']):not([type='radio'])");
                        if (siblingInput && isVisible(siblingInput) && !siblingInput.readOnly && !siblingInput.disabled) {
                            targetInput = siblingInput;
                            break;
                        }
                    }
                    var lr = label.getBoundingClientRect();
                    for (var j = 0; j < inputs.length; j++) {
                        var inp = inputs[j];
                        var ir = inp.getBoundingClientRect();
                        var dx = ir.left - lr.right;
                        var dy = Math.abs(ir.top - lr.top);
                        if (dx < -30 || dy > 60) continue;
                        targetInput = inp;
                        break;
                    }
                }

                if (!targetInput) {
                    targetInput = inputs.find(function(el) {
                        var key = ((el.id || '') + '|' + (el.name || '') + '|' + (el.placeholder || '') + '|' + (el.className || '')).toLowerCase();
                        return key.indexOf('p_application_code') >= 0 || key.indexOf('application_code') >= 0 || key.indexOf('apply') >= 0 || key.indexOf('app') >= 0;
                    }) || inputs[0];
                }

                if (!targetInput) {
                    return {
                        success: false,
                        error: '弹框中未找到可输入的申请单文本框',
                        labelTexts: labels.slice(0, 8).map(function(el) { return norm(el.textContent); }),
                        inputs: inputs.slice(0, 12).map(function(el) { return (el.id || '') + '|' + (el.name || '') + '|' + (el.placeholder || ''); })
                    };
                }

                targetInput.focus();
                targetInput.click();
                targetInput.value = '';
                targetInput.dispatchEvent(new Event('input', { bubbles: true }));
                targetInput.dispatchEvent(new Event('change', { bubbles: true }));
                targetInput.value = args.appNo;
                targetInput.dispatchEvent(new Event('input', { bubbles: true }));
                targetInput.dispatchEvent(new Event('change', { bubbles: true }));
                targetInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                targetInput.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
                targetInput.dispatchEvent(new Event('blur', { bubbles: true }));

                var btns = Array.from(root.querySelectorAll('a, button, span, input[type=button], input[type=submit]')).filter(isVisible);
                var queryBtn = btns.find(function(el) {
                    var text = norm(el.textContent || el.value || '');
                    return text === '查询';
                }) || btns.find(function(el) {
                    var text = norm(el.textContent || el.value || '');
                    return text.indexOf('查询') >= 0;
                });


                if (queryBtn) {
                    try { queryBtn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); } catch (e) {}
                    try { queryBtn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true })); } catch (e) {}
                    queryBtn.click();
                } else {
                    try {
                        targetInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                        targetInput.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
                    } catch (e) {}
                }

                return {
                    success: true,
                    inputId: targetInput.id || '',
                    inputName: targetInput.name || '',
                    inputValue: targetInput.value || '',
                    matchedLabel: matchedLabel,
                    clickedQuery: !!queryBtn,
                    queryText: queryBtn ? String(queryBtn.textContent || queryBtn.value || '').trim() : '',
                    dialogText: String(dialog.textContent || '').replace(/\\s+/g, ' ').trim().substring(0, 160)
                };

            }""", {"appNo": app_no})

            if not popup_query_result.get("success"):
                logger.error(f"[弹框] 输入/查询失败: {popup_query_result}")
                return False

            logger.info(
                f"[弹框] 已在{interaction_context_name}输入申请单并点击查询: "
                f"inputId={popup_query_result.get('inputId')} | "
                f"inputValue={popup_query_result.get('inputValue')} | "
                f"matchedLabel={popup_query_result.get('matchedLabel')} | "
                f"clickedQuery={popup_query_result.get('clickedQuery')} | queryText={popup_query_result.get('queryText')}"
            )

            interaction_target.wait_for_timeout(3200)

            if try_wait_loaded("弹框查询", expected_app_no=app_no, before_state=before_state, rounds=10, wait_ms=700):
                self._remember_current_form(app_no, get_state(app_no))
                return True


            popup_context_name, popup_target, popup_probe, popup_seen = detect_popup_context()
            logger.error(
                f"[搜索] 已按弹框路径输入申请单并点击查询，但申请单仍未加载 | "
                f"interactionContext={interaction_context_name} | "
                f"popupAfterQueryContext={popup_context_name} | popupAfterQuery={popup_probe} | seen={popup_seen}"
            )

            return False


        except Exception as e:
            logger.error(f"[搜索] 异常: {e}")
            return False

    
    def get_first_personnel_work_location(self) -> Optional[str]:
        """
        从技术合作人员信息表中获取第一条记录的工作地点。
        扫描所有 frame（人员 datagrid 可能不在 self.page 中），
        先尝试 MiniUI datagrid API，再尝试 HTML table 表头匹配。

        Returns:
            Optional[str]: 工作地点，如果无记录返回 None
        """
        logger.info("=== 获取人员工作地点 ===")

        try:
            self.page.wait_for_timeout(1000)

            # 收集所有可访问的 frame（与 delete_personnel_by_id_card 同逻辑）
            root_page = self.root_page if hasattr(self, 'root_page') else (
                self.page.page if isinstance(self.page, Frame) else self.page
            )
            all_frames = list(set(root_page.frames))
            logger.info(f"[工作地点] 扫描 {len(all_frames)} 个 frame...")

            for fi, frame in enumerate(all_frames):
                try:
                    result = frame.evaluate("""() => {
                        // 策略1: MiniUI datagrid — 找含身份证号的 grid，取第一行的"工作地点"
                        if (typeof mini !== 'undefined' && mini.gets) {
                            var grids = mini.gets('datagrid');
                            for (var g = 0; g < grids.length; g++) {
                                var grid = grids[g];
                                if (!grid || !grid.getData) continue;
                                var data = grid.getData();
                                if (!data || data.length === 0) continue;

                                // 确认此 grid 含身份证号（即人员表）
                                var hasIdCard = false;
                                for (var r = 0; r < Math.min(data.length, 3); r++) {
                                    for (var key in data[r]) {
                                        if (/^\\d{17}[\\dXx]$/.test(String(data[r][key] || '').trim())) {
                                            hasIdCard = true; break;
                                        }
                                    }
                                    if (hasIdCard) break;
                                }
                                if (!hasIdCard) continue;

                                // 在第一行中查找"工作地点"字段
                                for (var key in data[0]) {
                                    if (key.indexOf('地点') >= 0 || key.indexOf('location') >= 0 || key.indexOf('Location') >= 0) {
                                        return { success: true, location: data[0][key], source: 'datagrid', field: key };
                                    }
                                }

                                // datagrid 无"地点"字段 — 记录字段名供诊断
                                return { success: false, error: 'datagrid无地点字段', keys: Object.keys(data[0]).join(',') };
                            }
                        }

                        // 策略2: HTML table — 通过表头 th 定位"工作地点"列
                        var tables = document.querySelectorAll('table');
                        for (var t = 0; t < tables.length; t++) {
                            var rows = tables[t].querySelectorAll('tbody tr, tr');
                            if (rows.length === 0) continue;

                            // 确认含身份证号
                            var hasIdCard = false;
                            for (var r = 0; r < Math.min(rows.length, 3); r++) {
                                if (/\\d{17}[\\dXx]/.test(rows[r].textContent || '')) { hasIdCard = true; break; }
                            }
                            if (!hasIdCard) continue;

                            // 在 th 中找"工作地点"
                            var ths = tables[t].querySelectorAll('th');
                            var locIdx = -1;
                            for (var h = 0; h < ths.length; h++) {
                                var thTxt = (ths[h].textContent || '').trim();
                                if (thTxt.indexOf('工作地点') >= 0 || thTxt.indexOf('地点') >= 0) {
                                    locIdx = h; break;
                                }
                            }

                            if (locIdx >= 0) {
                                var cells = rows[0].querySelectorAll('td');
                                if (locIdx < cells.length) {
                                    return { success: true, location: cells[locIdx].textContent.trim(), source: 'table-th' };
                                }
                            }

                            // 表头无"地点" — 返回第一个 td 做备用
                            var cells = rows[0].querySelectorAll('td');
                            if (cells.length > 0) {
                                return { success: true, location: cells[0].textContent.trim(), source: 'table-first-td' };
                            }
                        }

                        return null;  // 此 frame 无人员数据
                    }""")

                    if result is None:
                        continue  # 此 frame 无人员数据，看下一个

                    if result.get("success"):
                        location = result.get("location", "").strip()
                        if location:
                            logger.info(f"[工作地点] frame[{fi}] 获取成功: {location} (来源={result.get('source')})")
                            return location
                        else:
                            logger.warning(f"[工作地点] frame[{fi}] 值为空 (来源={result.get('source')})")
                    else:
                        logger.info(f"[工作地点] frame[{fi}] 有人员但无地点字段: {result.get('error')}, keys={result.get('keys','')}")

                except Exception as e:
                    continue

            logger.warning("[工作地点] 所有 frame 中均未获取到工作地点")
            return None

        except Exception as e:
            logger.error(f"[工作地点] 异常: {e}")
            return None
    
    def fill_work_location(self, location: str) -> bool:
        """
        填充工作地点字段
        
        Args:
            location: 工作地点值
            
        Returns:
            bool: 是否成功
        """
        logger.info(f"=== 填充工作地点: {location} ===")
        
        try:
            self.page.wait_for_timeout(500)
            
            # 尝试通过 MiniUI textbox
            self.page.evaluate(f"""() => {{
                var input = mini.get('p_work_location');
                if (input) {{
                    input.setValue('{location}');
                }}
            }}""")
            
            logger.info("[工作地点] 填充成功")
            return True
            
        except Exception as e:
            logger.error(f"[工作地点] 异常: {e}")
            return False
    
    def calculate_cost(self) -> Tuple[bool, str]:
        """
        点击计算成本按钮，并检测点击后是否出现弹窗。

        规则：
        - 点击后若出现任何弹窗（无论内容），点击弹窗上的"取消"按钮，
          返回 (False, 弹窗内容) 作为错误，上层不应再继续提交
        - 点击后无弹窗，返回 (True, '')

        Returns:
            Tuple[bool, str]: (是否无弹窗成功, 弹窗内容/错误描述；成功时为空字符串)
        """
        logger.info("=== 点击计算成本 ===")

        def _click_popup_cancel() -> str:
            """点击弹窗上的取消按钮，返回被关闭的弹窗文本；若无弹窗则返回空字符串"""
            return self.page.evaluate("""() => {
                function isVisible(el) {
                    if (!el) return false;
                    var style = window.getComputedStyle(el);
                    var rect = el.getBoundingClientRect();
                    return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                }
                function normalize(text) {
                    return String(text || '').replace(/\\s+/g, ' ').trim();
                }

                var selectors = [
                    '.mini-messagebox', '.mini-modal', '.mini-window', '.mini-popup',
                    '.ui-dialog', '.dialog', '[role="dialog"]'
                ];
                var seen = [];
                var popups = [];
                for (var s = 0; s < selectors.length; s++) {
                    var els = document.querySelectorAll(selectors[s]);
                    for (var i = 0; i < els.length; i++) {
                        var el = els[i];
                        if (!isVisible(el)) continue;
                        if (seen.indexOf(el) >= 0) continue;
                        seen.push(el);
                        var style = window.getComputedStyle(el);
                        var rect = el.getBoundingClientRect();
                        var text = normalize(el.textContent || el.innerText || '');
                        if (!text) continue;
                        popups.push({
                            el: el,
                            text: text,
                            zIndex: parseInt(style.zIndex || '0', 10) || 0,
                            area: Math.round(rect.width * rect.height)
                        });
                    }
                }
                popups.sort(function(a, b) {
                    if (b.zIndex !== a.zIndex) return b.zIndex - a.zIndex;
                    return b.area - a.area;
                });
                if (!popups.length) return '';

                var popup = popups[0];
                var popupText = popup.text.substring(0, 300);
                // 优先点取消，没有取消则点关闭/确定
                var buttons = Array.from(popup.el.querySelectorAll(
                    'a, button, span, input[type=button], input[type=submit]'
                )).filter(isVisible);
                var cancelBtn = null;
                var confirmBtn = null;
                for (var j = 0; j < buttons.length; j++) {
                    var text = normalize(buttons[j].textContent || buttons[j].value || '');
                    var cls = String(buttons[j].className || '');
                    if (text.indexOf('取消') >= 0 || cls.indexOf('mini-messagebox-cancel') >= 0) {
                        cancelBtn = buttons[j];
                    }
                    if (text.indexOf('确定') >= 0 || text.indexOf('确认') >= 0 || cls.indexOf('mini-messagebox-ok') >= 0) {
                        confirmBtn = buttons[j];
                    }
                }
                var toClick = cancelBtn || confirmBtn;
                if (toClick) {
                    toClick.click();
                }
                return popupText;
            }""")

        try:
            self.page.wait_for_timeout(500)

            calc_btn = self.page.locator(self.SELECTORS["calculate_cost_btn"]).first
            if calc_btn.count() == 0:
                logger.error("[成本] 未找到计算成本按钮")
                return False, "计算成本失败：未找到计算成本按钮"

            calc_btn.click()
            # 先等基础时间让异步请求发出
            self.page.wait_for_timeout(2000)

            # 检测是否出现弹窗（HC不足、人员明细超限等）
            popup_text = _click_popup_cancel()
            if popup_text:
                logger.warning(f"[成本] 点击计算成本后出现弹窗，已点取消: {popup_text}")
                return False, popup_text

            # 轮询等待金额字段非空（解决人员多时异步计算延迟导致的竞态条件）
            # 关键：页面有两个金额字段，时序不同！
            #   - orderAmount：前端 MiniUI 先回填（用户能看到"订单金额"显示出来）
            #   - p_order_amount：框架异步计算真正完成后才写入（服务器校验用这个！）
            # 必须等 p_order_amount 自然出现，否则提前提交必定报"金额不能为空"
            #
            # 分两阶段：
            #   阶段A：等 orderAmount 出现（说明前端已开始响应）
            #   阶段B：继续等 p_order_amount 出现（框架异步完成，这才是提交安全点）
            # 如果阶段B超时，再尝试手动同步作为最后手段
            max_wait_seconds = 30
            poll_interval_ms = 800
            
            phase_a_done = False  # orderAmount 已出现
            phase_b_done = False  # p_order_amount 已出现
            manual_sync_attempted = False
            
            for attempt in range(max_wait_seconds):
                status = self.page.evaluate("""() => {
                    function clean(v) { return String(v||'').replace(/,/g,'').trim(); }
                    
                    // 读 changeOrderAmount（浏览器显示的"技术合作订单金额"，最准确）
                    var changeOrderAmt = '';
                    try {
                        var cc = window.mini && mini.get('changeOrderAmount');
                        if (cc && cc.getValue) changeOrderAmt = clean(cc.getValue());
                    } catch(e){}
                    if (!changeOrderAmt) {
                        var el0 = document.getElementById('changeOrderAmount$text');
                        if (el0) changeOrderAmt = clean(el0.value);
                    }
                    
                    // 读 orderAmount（备用）
                    var orderAmt = '';
                    try {
                        var c = window.mini && mini.get('orderAmount');
                        if (c && c.getValue) orderAmt = clean(c.getValue());
                    } catch(e){}
                    if (!orderAmt) {
                        var el1 = document.getElementById('orderAmount$text');
                        if (el1) orderAmt = clean(el1.value);
                    }
                    
                    // 读 p_order_amount（这是提交校验用的关键字段！）
                    var pOrderAmt = '';
                    try {
                        var pc = window.mini && mini.get('p_order_amount');
                        if (pc && pc.getValue) pOrderAmt = clean(pc.getValue());
                    } catch(e){}
                    if (!pOrderAmt) {
                        var el2 = document.getElementById('p_order_amount');
                        if (el2) pOrderAmt = clean(el2.value);
                    }
                    
                    return {
                        changeOrderAmount: changeOrderAmt,
                        orderAmount: orderAmt,
                        p_order_amount: pOrderAmt,
                        orderReady: !!(changeOrderAmt || orderAmt) && parseFloat(changeOrderAmt || orderAmt) > 0,
                        pOrderReady: !!pOrderAmt && parseFloat(pOrderAmt) > 0
                    };
                }""")
                
                o_ready = status.get("orderReady", False)
                po_ready = status.get("pOrderReady", False)
                
                if o_ready and not phase_a_done:
                    phase_a_done = True
                    display_amt = status.get('changeOrderAmount') or status.get('orderAmount')
                    logger.info(f"[成本] 阶段A✅ 技术合作订单金额已出现: {display_amt}，继续等待 p_order_amount...")
                
                if po_ready:
                    phase_b_done = True
                    logger.info(f"[成本] 阶段B✅ p_order_amount已出现: {status['p_order_amount']}（轮询第{attempt+1}次，可安全提交）")
                    return True, ""
                
                # 阶段A还没完成 → 继续轮询
                if not o_ready:
                    self.page.wait_for_timeout(poll_interval_ms)
                    continue
                
                # 阶段A已完成但阶段B未完成（orderAmount有了但p_order_amount还没有）
                # 这是正常状态——框架异步计算还在进行中
                if attempt % 5 == 4:  # 每4秒打一次日志避免刷屏
                    logger.debug(f"[成本] ...等待p_order_amount回填中... (第{attempt+1}次, orderAmount={status['orderAmount']})")
                
                self.page.wait_for_timeout(poll_interval_ms)
            
            # === 超时退出 ===
            # p_order_amount 在30秒内始终没有出现
            # 此时 changeOrderAmount / orderAmount 可能有值也可能没有
            final_check = self.page.evaluate("""() => {
                function clean(v) { return String(v||'').replace(/,/g,'').trim(); }
                var coa = ''; 
                try { var cc=mini&&mini.get('changeOrderAmount'); if(cc&&cc.getValue)coa=clean(cc.getValue()); }catch(e){}
                if(!coa){var e0=document.getElementById('changeOrderAmount$text');if(e0)coa=clean(e0.value);}
                var oa = ''; 
                try { var c=mini&&mini.get('orderAmount'); if(c&&c.getValue)oa=clean(c.getValue()); }catch(e){} 
                if(!oa){var e=document.getElementById('orderAmount$text');if(e)oa=clean(e.value);}
                var pa = '';
                try { var pc=mini&&mini.get('p_order_amount'); if(pc&&pc.getValue)pa=clean(pc.getValue()); }catch(e){}
                if(!pa){var e2=document.getElementById('p_order_amount');if(e2)pa=clean(e2.value);}
                return {changeOrderAmount: coa, orderAmount: oa, p_order_amount: pa};
            }""")

            final_coa = final_check.get('changeOrderAmount', '')
            final_oa = final_check.get('orderAmount', '')
            final_pa = final_check.get('p_order_amount', '')
            display_final = final_coa or final_oa
            
            # changeOrderAmount 或 orderAmount 有值但 p_order_amount 始终没出现
            if display_final:
                logger.warning(f"[成本] ⚠️ 30秒内 p_order_amount 未自然回填（技术合作订单金额={display_final}）")
                logger.warning("[成本] 尝试手动将 orderAmount 写入 p_order_amount 作为最后手段...")
                
                sync_detail = self.page.evaluate("""(val) => {
                    var results = [];
                    
                    // 策略1：MiniUI 控件设值
                    try {
                        var ctrl = window.mini && mini.get('p_order_amount');
                        if (ctrl && ctrl.setValue) { ctrl.setValue(val); results.push({m:'mini', ok:true, got:ctrl.getValue?ctrl.getValue():''}); }
                        else { results.push({m:'mini', ok:false, r:'no_ctrl'}); }
                    } catch(e) { results.push({m:'mini', ok:false, e:String(e)}); }
                    
                    // 策略2：DOM 直接写（已有元素）
                    ['p_order_amount','p_order_amount$text'].forEach(function(id) {
                        var el = document.getElementById(id);
                        if(el) { el.value=val; results.push({m:'dom.'+id, ok:true}); }
                    });
                    
                    // 策略3：如果元素不存在，动态创建 hidden input 并插入表单
                    var poEl = document.getElementById('p_order_amount');
                    if (!poEl) {
                        try {
                            var newInput = document.createElement('input');
                            newInput.type = 'hidden';
                            newInput.id = 'p_order_amount';
                            newInput.name = 'p_order_amount';  // 提交时服务器按 name 取值
                            newInput.value = val;
                            document.body.appendChild(newInput);
                            results.push({m:'dom.create', ok:true, msg:'created_hidden_input'});
                            
                            // 同时尝试用 MiniUI 注册
                            try { if(window.mini && mini.parse) mini.parse(document.body); } catch(ex2){}
                        } catch(createErr) {
                            results.push({m:'dom.create', ok:false, e:String(createErr)});
                        }
                        
                        // 再试一次读回
                        poEl = document.getElementById('p_order_amount');
                    }
                    
                    // 验证
                    var fv='';
                    try{var fc=window.mini&&mini.get('p_order_amount');if(fc&&fc.getValue)fv=fc.getValue();}catch(e){}
                    if(!fv && poEl) fv = poEl.value;
                    return {results:results, finalVal:fv};
                }""", final_oa)
                
                if sync_detail.get("finalVal"):
                    logger.info(f"[成本] ✅ 手动同步成功！p_order_amount={sync_detail['finalVal']}")
                    return True, ""
                else:
                    logger.error(f"[成本] ❌ 手动同步也失败！detail={sync_detail['results']}")
                    return False, f"技术合作订单金额：p_order_amount 在30秒内未回填（技术合作订单金额={display_final}），手动写入也无效"
            
            # changeOrderAmount 和 orderAmount 都没有
            return False, "技术合作金额为空，请检查计算是否正常"

        except Exception as e:
            logger.error(f"[成本] 异常: {e}")
            return False, f"计算成本异常: {str(e)[:80]}"
    
    def get_personnel_table_data(self) -> Optional[list]:
        """
        从技术合作人员信息表中获取所有行的数据
        包括身份证号等关键字段
        
        Returns:
            Optional[list]: 人员记录列表，每条记录为字典格式
        """
        logger.info("=== 获取人员信息表数据 ===")
        
        try:
            result = self.page.evaluate("""() => {
                var records = [];
                
                // 尝试通过 MiniUI datagrid 获取
                var grids = mini.gets('datagrid');
                for (var i = 0; i < grids.length; i++) {
                    var grid = grids[i];
                    if (grid && grid.getData) {
                        var data = grid.getData();
                        if (data && data.length > 0) {
                            return {
                                success: true,
                                source: 'datagrid',
                                records: data
                            };
                        }
                    }
                }
                
                // 备用方案：解析HTML表格
                var table = document.querySelector('table');
                if (table) {
                    var rows = table.querySelectorAll('tbody tr');
                    if (rows.length > 0) {
                        for (var r = 0; r < rows.length; r++) {
                            var cells = rows[r].querySelectorAll('td');
                            if (cells.length > 0) {
                                var record = {};
                                for (var c = 0; c < cells.length; c++) {
                                    record['col_' + c] = cells[c].textContent.trim();
                                }
                                records.push(record);
                            }
                        }
                        return {
                            success: true,
                            source: 'html_table',
                            records: records
                        };
                    }
                }
                
                return {success: false, error: '未找到人员信息表'};
            }""")
            
            if result.get("success"):
                records = result.get("records", [])
                logger.info(f"[人员表] 获取成功，共 {len(records)} 条记录，来源: {result.get('source')}")
                return records
            else:
                logger.warning(f"[人员表] 获取失败: {result.get('error')}")
                return None
                
        except Exception as e:
            logger.error(f"[人员表] 异常: {e}")
            return None
    
    def delete_personnel_by_id_card(self, id_card_list: list) -> Tuple[int, list]:
        """
        根据身份证号从人员信息表中删除记录
        
        操作方式：
        1. 在人员信息 datagrid 中找到身份证号匹配的行
        2. 勾选该行首列复选框
        3. 点击"删除"按钮
        4. 弹出确认对话框后点击"确定"
        
        Args:
            id_card_list: 要删除的身份证号列表
            
        Returns:
            Tuple[int, list]: (删除成功数, 删除成功的身份证号列表)
        """
        logger.info(f"=== 删除不续签人员（身份证号: {id_card_list}） ===")
        
        if not id_card_list or len(id_card_list) == 0:
            logger.info("[删除] 无需删除的人员")
            return 0, []
        
        try:
            deleted_count = 0
            deleted_ids = []
            
            # ── 定位人员 datagrid 所在的正确 frame ──
            # ★ 优先在 self.page（当前操作的合同表单 frame）中查找
            # 原因：每个合作商的 iframe 同名但不销毁，全 frame 扫描会命中旧合作商的残留数据
            operation_frame = None
            root_page = self.root_page if hasattr(self, 'root_page') else (
                self.page.page if isinstance(self.page, Frame) else self.page
            )
            
            # 诊断 JS（提取为字符串避免重复）
            _diag_js = """() => {
                try {
                    if (typeof mini !== 'undefined' && mini.gets) {
                        var grids = mini.gets('datagrid');
                        for (var g = 0; g < grids.length; g++) {
                            var grid = grids[g];
                            if (!grid || !grid.getData) continue;
                            var data = grid.getData();
                            if (data.length === 0) continue;
                            var el = grid.getEl ? grid.getEl() : (grid.el || null);
                            var gridId = el ? el.id : '';
                            var hasIdCard = false;
                            for (var r = 0; r < Math.min(data.length, 5); r++) {
                                var row = data[r];
                                for (var key in row) {
                                    var val = String(row[key] || '').trim();
                                    if (/^\\d{17}[\\dXx]$/.test(val)) { hasIdCard = true; break; }
                                }
                                if (hasIdCard) break;
                            }
                            if (hasIdCard) {
                                return { found: true, source: 'miniui-datagrid', gridId: gridId, dataLen: data.length };
                            }
                        }
                    }
                    var tables = document.querySelectorAll('table');
                    for (var t = 0; t < tables.length; t++) {
                        var html = tables[t].textContent || '';
                        if (/\\d{17}[\\dXx]/.test(html)) {
                            var rows = tables[t].querySelectorAll('tbody tr');
                            var matchCount = 0;
                            for (var r = 0; r < rows.length; r++) {
                                if (/\\d{17}[\\dXx]/.test(rows[r].textContent || '')) matchCount++;
                            }
                            if (matchCount > 0) {
                                return { found: true, source: 'html-table', tableIndex: t, matchRows: matchCount };
                            }
                        }
                    }
                    var bodyText = document.body ? document.body.textContent : '';
                    if (/\\d{17}[\\dXx]/.test(bodyText)) {
                        return { found: true, source: 'body-text', textLen: bodyText.length };
                    }
                    return { found: false };
                } catch(e) { return { found: false, error: e.message }; }
            }"""

            logger.info("[删除] 等待人员数据加载...")
            self.page.wait_for_timeout(2000)

            # ★ 第一步：优先在 self.page（当前操作 frame）中查找
            diag_result = None
            try:
                diag_result = self.page.evaluate(_diag_js)
                if diag_result.get("found"):
                    operation_frame = self.page
                    data_len = diag_result.get('dataLen') or diag_result.get('matchRows', '?')
                    logger.info(
                        f"[删除] ✓ 在当前操作 frame (self.page) 中找到人员数据 "
                        f"(来源={diag_result.get('source')}, 数据量={data_len})"
                    )
            except Exception as e:
                logger.info(f"[删除] 当前 frame 诊断失败: {e}")

            # ★ 第二步：self.page 中未找到，回退到全 frame 扫描
            if operation_frame is None:
                logger.info("[删除] 当前 frame 未找到人员数据，回退到全 frame 扫描...")
                all_frames = list(set(root_page.frames))
                frames_diag = []
                for f in all_frames:
                    try:
                        f_url = f.url[:80] if f.url else "about:blank"
                        frames_diag.append(f_url)
                    except:
                        pass
                logger.info(f"[删除] 共找到 {len(all_frames)} 个 frame: {frames_diag}")
                
                frame_candidates = []
                for fi, frame in enumerate(all_frames):
                    try:
                        d = frame.evaluate(_diag_js)
                        frame_url = frame.url[:80] if frame.url else "about:blank"
                        logger.info(f"[删除] frame[{fi}] {frame_url}: {d}")
                        if d.get("found"):
                            data_len = d.get('dataLen') or d.get('matchRows', 0)
                            frame_candidates.append((fi, frame, frame_url, d))
                    except Exception as e:
                        logger.info(f"[删除] frame[{fi}] 访问失败: {e}")
                
                # 从候选中选第一个（或按数据量匹配当前页面）
                if frame_candidates:
                    first_fi, first_frame, first_url, first_diag = frame_candidates[0]
                    operation_frame = first_frame
                    diag_result = first_diag
                    data_len = first_diag.get('dataLen') or first_diag.get('matchRows', '?')
                    logger.info(
                        f"[删除] ✓ 全 frame 扫描找到 {len(frame_candidates)} 个候选，"
                        f"选择 frame[{first_fi}]: {first_url} "
                        f"(来源={first_diag.get('source')}, 数据量={data_len})"
                    )
            
            if operation_frame is None:
                # 重试：先等3秒，再优先查 self.page，然后全 frame 扫描
                logger.warning("[删除] 未找到身份证号数据，再等待3秒重试...")
                self.page.wait_for_timeout(3000)
                
                # 重试1：先查 self.page
                try:
                    diag_result = self.page.evaluate(_diag_js)
                    if diag_result.get("found"):
                        operation_frame = self.page
                        data_len = diag_result.get('dataLen') or diag_result.get('matchRows', '?')
                        logger.info(f"[删除] ✓ 重试在 self.page 中找到人员数据 (来源={diag_result.get('source')}, 数据量={data_len})")
                except:
                    pass
                
                # 重试2：全 frame 扫描
                if operation_frame is None:
                    all_frames = list(set(root_page.frames))
                    for fi, frame in enumerate(all_frames):
                        try:
                            diag_result = frame.evaluate(_diag_js)
                            if diag_result.get("found"):
                                operation_frame = frame
                                data_len = diag_result.get('dataLen') or diag_result.get('matchRows', '?')
                                frame_url = frame.url[:80] if frame.url else "about:blank"
                                logger.info(f"[删除] ✓ 重试在 frame[{fi}] 中找到人员数据: {frame_url} (数据量={data_len})")
                                break
                        except:
                            pass
            
            if operation_frame is None:
                logger.error("[删除] 所有 frame 均未找到身份证号数据，无法删除人员！")
                logger.error(f"[删除] 请检查：1) 人员数据是否已渲染 2) 身份证号格式是否正确 3) 是否需要先手动展开人员面板")
                return 0, []
            
            # 使用正确的 frame 执行后续操作
            work_frame = operation_frame
            data_source = diag_result.get("source", "unknown")
            logger.info(f"[删除] 使用 frame 执行操作: {work_frame.url[:80]} (数据来源={data_source})")

            # ── 根据数据来源选择不同的删除策略 ──
            if data_source == "html-table":
                # 策略A：人员数据在普通 HTML table 中（非 MiniUI datagrid）
                # 直接用 Playwright locator 操作，按身份证号文本匹配行
                deleted_count, deleted_ids = self._delete_via_html_table(
                    work_frame, id_card_list
                )
            else:
                # 策略B：人员数据在 MiniUI datagrid 中（原有逻辑）
                deleted_count, deleted_ids = self._delete_via_miniui_datagrid(
                    work_frame, id_card_list
                )
            
            return deleted_count, deleted_ids
            
        except Exception as e:
            logger.error(f"[删除] 异常: {e}")
            import traceback
            traceback.print_exc()
            return 0, []
    
    def _delete_via_html_table(self, work_frame: "Frame", id_card_list: list) -> Tuple[int, list]:
        """通过 HTML table 定位并删除人员（优化：先批量提取页面身份证号，set交集后只操作匹配项）

        性能优化思路：
        - 原方案：外层循环 id_card_list（最多279条）× 内层扫描每行 = O(279 × N)
        - 新方案：JS 一次性提取页面上所有身份证号 O(N) → Python set 交集 O(min(279,N)) → 只对匹配项执行删除
        - 当页面100人、清单279条时，从 27900 次比对降到 ~100 次提取 + ~3 次删除操作

        滚动加载优化（2026-04-24）：
        - 人员多时有下拉滚动条，DOM 只渲染可见行 → 比对不完整
        - 优先用 MiniUI datagrid API getData() 获取完整数据（内存中全量）
        - 若不可用，滚动容器到底部触发懒加载，多次滚动直到行数稳定
        """
        import re

        # ── Phase 0: 优先通过 MiniUI datagrid API 获取完整人员列表 ──
        # 修复：mini 对象可能在任意 frame 中（不一定在 work_frame），
        # 需遍历所有 frame 查找含身份证号的 datagrid
        logger.info(f"[删除] [Phase 0] 尝试 MiniUI datagrid API 获取完整人员列表...")

        miniui_result = None
        miniui_source_frame = None

        # 收集所有可尝试的 frame（work_frame + root_page.frames）
        # 注意：self.page 可能是 Frame 对象（没有 .frames），只有 Page 才有 .frames
        try_frames = set()
        try_frames.add(id(work_frame))
        frame_map = {}
        frame_map[id(work_frame)] = work_frame

        # root_page 是 Page 对象，有 .frames 属性
        if hasattr(self, 'root_page') and self.root_page:
            for f in self.root_page.frames:
                try_frames.add(id(f))
                frame_map[id(f)] = f

        for fid in try_frames:
            f = frame_map.get(fid)
            if f is None:
                continue
            try:
                result = f.evaluate("""() => {
                    if (typeof mini === 'undefined' || !mini.gets) return null;
                    var grids = mini.gets('datagrid');
                    for (var g = 0; g < grids.length; g++) {
                        var grid = grids[g];
                        if (!grid || !grid.getData) continue;
                        var data = grid.getData();
                        if (!data || data.length === 0) continue;

                        // 确认此 grid 含身份证号
                        var hasIdCard = false;
                        for (var r = 0; r < Math.min(data.length, 5); r++) {
                            for (var key in data[r]) {
                                if (/^\\d{17}[\\dXx]$/.test(String(data[r][key] || '').trim())) {
                                    hasIdCard = true; break;
                                }
                            }
                            if (hasIdCard) break;
                        }
                        if (!hasIdCard) continue;

                        // 提取所有身份证号（完整数据，不受滚动限制）
                        var idCards = [];
                        for (var r = 0; r < data.length; r++) {
                            for (var key in data[r]) {
                                var val = String(data[r][key] || '').trim();
                                var m = val.match(/^(\\d{17}[\\dXx])$/);
                                if (m) { idCards.push({idCard: m[1], rowIndex: r}); break; }
                            }
                        }
                        // 检测是否有分页（通过 pager 或 loadData/total）
                        var hasPager = false;
                        var pagerTotal = 0;
                        try {
                            // 方式1: grid 自带的 pager
                            if (grid.getPager) {
                                var pager = grid.getPager();
                                if (pager && pager.getTotal) {
                                    pagerTotal = pager.getTotal();
                                    hasPager = pagerTotal > data.length;
                                }
                            }
                            // 方式2: mini.gets('pager') 找对应 pager
                            if (!hasPager && mini.gets) {
                                var pagers = mini.gets('pager');
                                for (var pi = 0; pi < pagers.length; pi++) {
                                    var pp = pagers[pi];
                                    if (pp.getTotal) {
                                        var pt = pp.getTotal();
                                        if (pt > 0) { pagerTotal = pt; hasPager = pt > data.length; break; }
                                    }
                                }
                            }
                            // 方式3: grid.total 属性
                            if (!hasPager && grid.total) {
                                pagerTotal = parseInt(grid.total) || 0;
                                if (pagerTotal > data.length) hasPager = true;
                            }
                            // 方式4: grid.data 中可能有 total 属性
                            if (!hasPager && grid.data && typeof grid.data === 'object') {
                                if (grid.data.total) {
                                    pagerTotal = parseInt(grid.data.total) || 0;
                                    if (pagerTotal > data.length) hasPager = true;
                                }
                            }
                        } catch(pagerEx) {}

                        return { source: 'miniui', total: data.length, idCards: idCards, hasPager: hasPager, pagerTotal: pagerTotal };
                    }
                    return null;
                }""")
                if result and result.get('source') == 'miniui' and len(result.get('idCards', [])) > 0:
                    miniui_result = result
                    miniui_source_frame = f
                    logger.info(
                        f"[删除] [Phase 0] 在 frame 中找到 MiniUI datagrid: "
                        f"共 {result['total']} 行, {len(result['idCards'])} 条身份证号"
                    )
                    break
            except Exception as e:
                # 静默跳过不可访问的 frame
                pass

        page_id_cards = []  # 统一为 [{idCard, ...}, ...] 格式

        if miniui_result and miniui_result.get('source') == 'miniui':
            page_id_cards = list(miniui_result["idCards"])
            pager_total = miniui_result.get('pagerTotal', 0) or 0
            data_total = miniui_result.get('total', 0) or 0
            has_pager = miniui_result.get('hasPager', False)

            logger.info(
                f"[删除] [Phase 0] MiniUI datagrid 返回: "
                f"当前页 {data_total} 行, {len(page_id_cards)} 条身份证号, "
                f"分页总条数={pager_total}, hasPager={has_pager}"
            )

            # ★ Phase 0.5: 如果 MiniUI datagrid 有分页（getData 只返回当前页），
            #    需要通过 pager API 逐页切换并采集
            if has_pager and pager_total > data_total:
                logger.info(
                    f"[删除] [Phase 0.5] 检测到分页! "
                    f"当前页 {data_total} 条 < 分页总数 {pager_total} 条, 开始翻页采集..."
                )
                seen_ids = set(item["idCard"] for item in page_id_cards)
                source_frame = miniui_source_frame or work_frame
                page_num = 1

                while len(seen_ids) < pager_total:
                    page_num += 1
                    logger.info(f"[删除] [Phase 0.5] 翻到第 {page_num} 页...")

                    # 通过 MiniUI pager API 翻到下一页
                    turned = source_frame.evaluate("""() => {
                        try {
                            if (typeof mini === 'undefined' || !mini.gets) return { turned: false };

                            // 方式1: 通过 grid.gotoPage 翻页（如果 datagrid 绑定了 pager）
                            var grids = mini.gets('datagrid');
                            for (var g = 0; g < grids.length; g++) {
                                var grid = grids[g];
                                if (!grid || !grid.getData) continue;
                                var data = grid.getData();
                                if (!data || data.length === 0) continue;

                                // 检查此 grid 含身份证号（与之前同样的判断）
                                var hasIdCard = false;
                                for (var r = 0; r < Math.min(data.length, 5); r++) {
                                    for (var key in data[r]) {
                                        if (/^\\d{17}[\\dXx]$/.test(String(data[r][key] || '').trim())) {
                                            hasIdCard = true; break;
                                        }
                                    }
                                    if (hasIdCard) break;
                                }
                                if (!hasIdCard) continue;

                                // 通过 pager 翻页
                                var pagers = mini.gets('pager');
                                for (var pi = 0; pi < pagers.length; pi++) {
                                    var pager = pagers[pi];
                                    // 尝试 nextPage
                                    if (typeof pager.nextPage === 'function') {
                                        pager.nextPage();
                                        return { turned: true, method: 'pager.nextPage' };
                                    }
                                    // 尝试 setPage(pageIndex + 1)
                                    if (typeof pager.setPageIndex === 'function') {
                                        var currentIdx = pager.getPageIndex ? pager.getPageIndex() : 0;
                                        pager.setPageIndex(currentIdx + 1);
                                        return { turned: true, method: 'pager.setPageIndex' };
                                    }
                                    // 尝试通过 grid.reload + URL 参数
                                }

                                // 方式2: 直接通过 datagrid 的 reload/eload 翻页
                                if (typeof grid.reload === 'function') {
                                    grid.reload();
                                }
                                return { turned: false, method: 'no-pager-api' };
                            }
                        } catch(ex) {
                            return { turned: false, error: String(ex) };
                        }
                        return { turned: false };
                    }""")

                    if not turned or not turned.get('turned'):
                        logger.info(
                            f"[删除] [Phase 0.5] MiniUI pager API 翻页失败"
                            f" ({turned.get('method', '?')} {turned.get('error', '')})，"
                            f"尝试 DOM 方式点击下一页..."
                        )
                        # 降级到 DOM 方式点击下一页（与 Phase 1.5 相同的逻辑）
                        clicked = work_frame.evaluate("""() => {
                            // 方式2: 通过 DOM 找 mini-pager 中的"下一页"按钮
                            var pagerBars = document.querySelectorAll('.mini-pager, .mini-pager-bar');
                            for (var p = 0; p < pagerBars.length; p++) {
                                var nextEls = pagerBars[p].querySelectorAll('[class*="next"], [class*="Next"]');
                                for (var n = 0; n < nextEls.length; n++) {
                                    nextEls[n].click();
                                    return { clicked: true, method: 'miniui-pager-dom-next' };
                                }
                                var spans = pagerBars[p].querySelectorAll('span, a, div');
                                for (var s = 0; s < spans.length; s++) {
                                    var stxt = (spans[s].textContent || '').trim();
                                    if (stxt === '下一页' || stxt === '»' || stxt === '>' || stxt === 'next' || stxt === 'Next') {
                                        spans[s].click();
                                        return { clicked: true, method: 'miniui-pager-dom-text' };
                                    }
                                }
                            }
                            // 方式3: 通用
                            var allEls = document.querySelectorAll('a, span, div, button');
                            for (var i = 0; i < allEls.length; i++) {
                                var txt = (allEls[i].textContent || '').trim();
                                if (txt === '下一页' || txt === 'Next' || txt === 'next' || txt === '>' || txt === '»') {
                                    allEls[i].click();
                                    return { clicked: true, method: 'generic' };
                                }
                            }
                            return { clicked: false };
                        }""")

                        if not clicked or not clicked.get('clicked'):
                            logger.info(f"[删除] [Phase 0.5] DOM 方式也找不到下一页按钮，停止翻页")
                            break
                        logger.info(f"[删除] [Phase 0.5] 通过 {clicked.get('method', '?')} 点击了下一页")
                    else:
                        logger.info(f"[删除] [Phase 0.5] 通过 {turned.get('method', '?')} 翻页成功")

                    source_frame.wait_for_timeout(2000)  # 等待翻页后数据加载

                    # 从 source_frame 重新用 MiniUI API 提取当前页数据
                    new_result = source_frame.evaluate("""() => {
                        if (typeof mini === 'undefined' || !mini.gets) return null;
                        var grids = mini.gets('datagrid');
                        for (var g = 0; g < grids.length; g++) {
                            var grid = grids[g];
                            if (!grid || !grid.getData) continue;
                            var data = grid.getData();
                            if (!data || data.length === 0) continue;
                            var hasIdCard = false;
                            for (var r = 0; r < Math.min(data.length, 5); r++) {
                                for (var key in data[r]) {
                                    if (/^\\d{17}[\\dXx]$/.test(String(data[r][key] || '').trim())) {
                                        hasIdCard = true; break;
                                    }
                                }
                                if (hasIdCard) break;
                            }
                            if (!hasIdCard) continue;
                            var idCards = [];
                            for (var r = 0; r < data.length; r++) {
                                for (var key in data[r]) {
                                    var val = String(data[r][key] || '').trim();
                                    var m = val.match(/^(\\d{17}[\\dXx])$/);
                                    if (m) { idCards.push({idCard: m[1], rowIndex: r}); break; }
                                }
                            }
                            return { total: data.length, idCards: idCards };
                        }
                        return null;
                    }""")

                    new_count = 0
                    if new_result and new_result.get('idCards'):
                        for card in new_result['idCards']:
                            if card['idCard'] not in seen_ids:
                                seen_ids.add(card['idCard'])
                                page_id_cards.append(card)
                                new_count += 1

                    logger.info(
                        f"[删除] [Phase 0.5] 第 {page_num} 页: "
                        f"getData 返回 {new_result['total'] if new_result else 0} 行, "
                        f"新增 {new_count} 条, 累计 {len(seen_ids)}/{pager_total} 条"
                    )

                    if new_count == 0:
                        logger.info(f"[删除] [Phase 0.5] 本页无新增记录，停止翻页")
                        break

                    # 安全上限：最多翻 50 页
                    if page_num >= 50:
                        logger.warning(f"[删除] [Phase 0.5] 已翻 {page_num} 页，达到安全上限，停止")
                        break

                logger.info(
                    f"[删除] [Phase 0.5] 翻页完成，共采集 {len(page_id_cards)} 条身份证号"
                )
            else:
                logger.info(
                    f"[删除] [Phase 0] MiniUI datagrid 无分页或数据已完整: "
                    f"共 {len(page_id_cards)} 条身份证号"
                )
        else:
            # MiniUI 不可用 — 滚动加载 + DOM 提取
            logger.info("[删除] [Phase 0] MiniUI datagrid 不可用（所有 frame 均未找到），进入滚动加载模式...")

            # 通用滚动策略：扫描所有可滚动元素（包括 MiniUI 虚拟滚动的 overflow:hidden），
            # 逐步 scrollBy 触发懒加载
            def _scroll_step():
                """逐步滚动所有可滚动容器一步（scrollBy 500px），返回触发了滚动的容器数量"""
                return work_frame.evaluate("""() => {
                    var scrolled = 0;
                    var all = document.querySelectorAll('*');
                    for (var i = 0; i < all.length; i++) {
                        var el = all[i];
                        var tag = el.tagName;
                        if (tag === 'IFRAME' || tag === 'SCRIPT' || tag === 'STYLE' || tag === 'HEAD') continue;
                        var overflow = window.getComputedStyle(el).overflowY;
                        // 同时检测 auto/scroll/hidden（MiniUI 虚拟滚动常用 hidden）
                        if (overflow !== 'auto' && overflow !== 'scroll' && overflow !== 'visible' && overflow !== 'hidden') continue;
                        // 检查是否有可滚动内容（允许隐藏滚动条的容器）
                        if (el.scrollHeight <= el.clientHeight + 2) continue;
                        el.scrollBy(0, 500);
                        scrolled++;
                    }
                    return scrolled;
                }""")

            def _count_visible_id_cards():
                return work_frame.evaluate("""() => {
                    var count = 0;
                    var tables = document.querySelectorAll('table');
                    for (var t = 0; t < tables.length; t++) {
                        var rows = tables[t].querySelectorAll('tbody tr, tr');
                        for (var r = 0; r < rows.length; r++) {
                            if (/\\d{17}[\\dXx]/.test(rows[r].textContent || '')) count++;
                        }
                    }
                    return count;
                }""")

            def _diagnose_scroll_containers():
                """诊断：列出所有可滚动容器的信息"""
                return work_frame.evaluate("""() => {
                    var info = [];
                    var all = document.querySelectorAll('*');
                    for (var i = 0; i < all.length; i++) {
                        var el = all[i];
                        var tag = el.tagName;
                        if (tag === 'IFRAME' || tag === 'SCRIPT' || tag === 'STYLE' || tag === 'HEAD') continue;
                        var overflow = window.getComputedStyle(el).overflowY;
                        if (overflow !== 'auto' && overflow !== 'scroll' && overflow !== 'hidden') continue;
                        if (el.scrollHeight <= el.clientHeight + 2) continue;
                        info.push({
                            tag: tag,
                            id: el.id || '',
                            cls: (el.className || '').toString().substring(0, 60),
                            scrollH: el.scrollHeight,
                            clientH: el.clientHeight,
                            scrollTop: el.scrollTop,
                            overflowY: overflow
                        });
                    }
                    return info;
                }""")

            # 诊断：输出当前所有可滚动容器信息
            containers = _diagnose_scroll_containers()
            if containers:
                logger.info(f"[删除] [滚动] 诊断: 发现 {len(containers)} 个可滚动容器:")
                for c in containers:
                    logger.info(
                        f"  - <{c['tag']}> id={c['id']} cls={c['cls']} "
                        f"scrollH={c['scrollH']} clientH={c['clientH']} scrollTop={c['scrollTop']}"
                    )
            else:
                logger.info("[删除] [滚动] 诊断: 未发现可滚动容器（所有内容已完全展示）")

            # 多轮逐步滚动直到行数不再增长
            prev_count = 0
            stable_rounds = 0
            for scroll_round in range(15):  # 最多15轮（每轮500px，最多7500px）
                scrolled_count = _scroll_step()
                work_frame.wait_for_timeout(1200)  # 等待懒加载AJAX完成
                current_count = _count_visible_id_cards()
                logger.info(f"[删除] [滚动] 第{scroll_round+1}轮: 可见 {current_count} 条记录 (滚动了 {scrolled_count} 个容器)")
                if current_count == prev_count:
                    stable_rounds += 1
                    if stable_rounds >= 2:
                        logger.info(f"[删除] [滚动] 连续2轮行数稳定 ({current_count})，停止滚动")
                        break
                else:
                    stable_rounds = 0
                prev_count = current_count

            # ── Phase 1: DOM 提取 ──
            logger.info(f"[删除] [优化] 开始 DOM 提取身份证号（清单共 {len(id_card_list)} 条待比对）...")

            page_id_cards = work_frame.evaluate("""() => {
                var results = [];

                var tables = document.querySelectorAll('table');
                for (var t = 0; t < tables.length; t++) {
                    var rows = tables[t].querySelectorAll('tbody tr, tr');
                    for (var r = 0; r < rows.length; r++) {
                        var text = rows[r].textContent || '';
                        var match = text.match(/(\\d{17}[\\dXx])/);
                        if (match) {
                            // 提取"序号"：取行内第一个"合理数值" td（≤99999，排除18位身份证号）
                            var seqNo = 0;
                            var cells = rows[r].querySelectorAll('td, th');
                            for (var c = 0; c < cells.length; c++) {
                                var cellText = (cells[c].textContent || '').trim();
                                // 序号应为1~5位纯数字（排除身份证号等长数字）
                                if (/^\\d{1,5}$/.test(cellText) && parseInt(cellText) <= 99999) {
                                    seqNo = parseInt(cellText);
                                    break;
                                }
                            }
                            results.push({
                                idCard: match[1],
                                tableIndex: t,
                                rowIndex: r,
                                seqNo: seqNo,
                                rowText: text.trim().substring(0, 120)
                            });
                        }
                    }
                }
                return results;
            }""")

            # 记录当前页最大序号（用于判断总条数）
            current_max_seq = max((item.get("seqNo", 0) for item in page_id_cards), default=0)
            logger.info(f"[删除] [优化] 页面共找到 {len(page_id_cards)} 条含身份证号的记录，当前页最大序号={current_max_seq}")

            # ── Phase 1.5: 分页遍历 ──
            # ★ 核心改进：不再依赖 pager 的"共X条"（会匹配到其他 datagrid 的 pager，如万联的138条）
            # 改为纯增量采集模式：检测"下一页"按钮是否可点 → 有就翻 → 翻后无新数据就停
            # 总条数用序号最大值确认（每行"序号"列的最后一条值 = 总记录数）
            has_next_page = work_frame.evaluate("""() => {
                // 找到包含身份证号的table
                var idCardTable = null;
                var allTables = document.querySelectorAll('table');
                for (var t = 0; t < allTables.length; t++) {
                    var rows = allTables[t].querySelectorAll('tbody tr, tr');
                    for (var r = 0; r < rows.length; r++) {
                        if (/\\d{17}[\\dXx]/.test(rows[r].textContent || '')) {
                            idCardTable = allTables[t]; break;
                        }
                    }
                    if (idCardTable) break;
                }
                if (!idCardTable) return false;

                // 从table父级查找关联pager中的"下一页"按钮
                function findNearbyPager(el) {
                    var current = el;
                    for (var depth = 0; depth < 5 && current; depth++) {
                        if (current === document.body || current === document.documentElement) break;
                        var pagers = current.querySelectorAll('.mini-pager, .mini-pager-bar');
                        for (var i = 0; i < pagers.length; i++) {
                            var pel = pagers[i];
                            var pelText = (pel.textContent || '').trim();
                            // 验证确实是分页pager（有页码或"条"字样）
                            if (/第\\s*\\d+\\s*\\/\\s*\\d+\\s*页/.test(pelText) ||
                                /共\\s*\\d+\\s*条/.test(pelText)) {
                                // 检查是否有"下一页"可点（不是 disabled 状态）
                                var spans = pel.querySelectorAll('span, a, div');
                                for (var s = 0; s < spans.length; s++) {
                                    var stxt = (spans[s].textContent || '').trim();
                                    var cls = (spans[s].className || '');
                                    if ((stxt === '下一页' || stxt === '\\u00bb' || stxt === '>') &&
                                        cls.indexOf('disabled') < 0 &&
                                        cls.indexOf('mini-disabled') < 0) {
                                        return true;
                                    }
                                }
                                var nextEls = pel.querySelectorAll('[class*="next"], [class*="Next"]');
                                for (var n = 0; n < nextEls.length; n++) {
                                    var ncls = nextEls[n].className || '';
                                    if (ncls.indexOf('disabled') < 0 && ncls.indexOf('mini-disabled') < 0) {
                                        return true;
                                    }
                                }
                                return false; // 找到了pager但下一页disabled
                            }
                        }
                        current = current.parentElement;
                    }
                    return null;
                }
                var result = findNearbyPager(idCardTable);
                if (result === false) return false;
                if (result === true) return true;

                // 兜底：mini API
                try {
                    if (typeof mini !== 'undefined' && mini.gets) {
                        var pagers = mini.gets('pager');
                        for (var i = 0; i < pagers.length; i++) {
                            var el = pagers[i].getEl ? pagers[i].getEl() : null;
                            if (!el) continue;
                            var sp = el.querySelectorAll('span');
                            for (var s = 0; s < sp.length; s++) {
                                if (sp[s].textContent.indexOf('\\u4e0b\\u4e00\\u9875') >= 0 &&
                                    (sp[s].className || '').indexOf('disabled') < 0) {
                                    return true;
                                }
                            }
                        }
                    }
                } catch(e) {}
                return false;
            }""")

            logger.info(f"[删除] [分页] 下一页按钮检测: {has_next_page}")

            if has_next_page:
                # 纯增量翻页采集：翻到没新数据就停
                seen_ids = set(item["idCard"] for item in page_id_cards)
                global_max_seq = current_max_seq
                page_num = 1
                no_new_count = 0

                while no_new_count < 2 and page_num < 50:
                    page_num += 1
                    logger.info(f"[删除] [分页] 翻到第 {page_num} 页...")

                    # 点击下一页
                    clicked = work_frame.evaluate("""() => {
                        var idCardTable = null;
                        var allTables = document.querySelectorAll('table');
                        for (var t = 0; t < allTables.length; t++) {
                            var rows = allTables[t].querySelectorAll('tbody tr, tr');
                            for (var r = 0; r < rows.length; r++) {
                                if (/\\d{17}[\\dXx]/.test(rows[r].textContent || '')) {
                                    idCardTable = allTables[t]; break;
                                }
                            }
                            if (idCardTable) break;
                        }

                        function findNearbyPager(el) {
                            var current = el;
                            for (var depth = 0; depth < 5 && current; depth++) {
                                if (current === document.body || current === document.documentElement) break;
                                var pagers = current.querySelectorAll('.mini-pager, .mini-pager-bar');
                                for (var i = 0; i < pagers.length; i++) {
                                    var pel = pagers[i];
                                    var pelText = (pel.textContent || '').trim();
                                    if (/共\\s*\\d+\\s*条/.test(pelText) || /第\\s*\\d+\\s*\\/\\s*\\d+\\s*页/.test(pelText)) {
                                        return pagers[i];
                                    }
                                }
                                current = current.parentElement;
                            }
                            return null;
                        }

                        var targetPager = null;
                        if (idCardTable) {
                            targetPager = findNearbyPager(idCardTable);
                        }

                        if (targetPager) {
                            var nextEls = targetPager.querySelectorAll('[class*="next"], [class*="Next"]');
                            for (var n = 0; n < nextEls.length; n++) {
                                var ncls = nextEls[n].className || '';
                                if (ncls.indexOf('disabled') < 0 && ncls.indexOf('mini-disabled') < 0) {
                                    nextEls[n].click();
                                    return { clicked: true, method: 'nearby-pager-next' };
                                }
                            }
                            var spans = targetPager.querySelectorAll('span, a, div');
                            for (var s = 0; s < spans.length; s++) {
                                var stxt = (spans[s].textContent || '').trim();
                                var scls = spans[s].className || '';
                                if ((stxt === '下一页' || stxt === '\\u00bb' || stxt === '>') &&
                                    scls.indexOf('disabled') < 0 && scls.indexOf('mini-disabled') < 0) {
                                    spans[s].click();
                                    return { clicked: true, method: 'nearby-pager-text' };
                                }
                            }
                        }

                        try {
                            if (typeof mini !== 'undefined' && mini.gets) {
                                var pagers = mini.gets('pager');
                                for (var i = 0; i < pagers.length; i++) {
                                    var el = pagers[i].getEl ? pagers[i].getEl() : null;
                                    if (!el) continue;
                                    var sp = el.querySelectorAll('span');
                                    for (var s = 0; s < sp.length; s++) {
                                        if (sp[s].textContent.indexOf('\\u4e0b\\u4e00\\u9875') >= 0) {
                                            sp[s].click();
                                            return { clicked: true, method: 'miniui-pager-fallback' };
                                        }
                                    }
                                }
                            }
                        } catch(e) {}
                        return { clicked: false };
                    }""")

                    if not clicked or not clicked.get('clicked'):
                        logger.info(f"[删除] [分页] 未找到可点击的下一页按钮，停止翻页")
                        break

                    logger.info(f"[删除] [分页] 通过 {clicked.get('method', '?')} 点击了下一页")
                    work_frame.wait_for_timeout(1500)

                    # 提取当前页身份证号 + 序号
                    new_cards = work_frame.evaluate("""() => {
                        var results = [];
                        var tables = document.querySelectorAll('table');
                        for (var t = 0; t < tables.length; t++) {
                            var rows = tables[t].querySelectorAll('tbody tr, tr');
                            for (var r = 0; r < rows.length; r++) {
                                var text = rows[r].textContent || '';
                                var match = text.match(/(\\d{17}[\\dXx])/);
                                if (match) {
                                    var seqNo = 0;
                                    var cells = rows[r].querySelectorAll('td, th');
                                    for (var c = 0; c < cells.length; c++) {
                                        var cellText = (cells[c].textContent || '').trim();
                                        if (/^\\d{1,5}$/.test(cellText) && parseInt(cellText) <= 99999) {
                                            seqNo = parseInt(cellText);
                                            break;
                                        }
                                    }
                                    results.push({
                                        idCard: match[1],
                                        tableIndex: t,
                                        rowIndex: r,
                                        seqNo: seqNo,
                                        rowText: text.trim().substring(0, 120)
                                    });
                                }
                            }
                        }
                        return results;
                    }""")

                    new_count = 0
                    for card in new_cards:
                        if card["idCard"] not in seen_ids:
                            seen_ids.add(card["idCard"])
                            page_id_cards.append(card)
                            new_count += 1
                            if card.get("seqNo", 0) > global_max_seq:
                                global_max_seq = card["seqNo"]

                    logger.info(
                        f"[删除] [分页] 第 {page_num} 页: 新增 {new_count} 条，"
                        f"累计 {len(seen_ids)} 条，序号最大值={global_max_seq}"
                    )

                    if new_count == 0:
                        no_new_count += 1
                        logger.info(f"[删除] [分页] 本页无新增记录 ({no_new_count}/2)")
                    else:
                        no_new_count = 0

                logger.info(
                    f"[删除] [分页] 翻页完成，共采集 {len(page_id_cards)} 条身份证号，"
                    f"序号最大值={global_max_seq}（来源: seq-no）"
                )
            else:
                logger.info(f"[删除] [分页] 未检测到分页或已在最后一页，当前页数据即为全量")

        # ── Phase 2: Python set 交集，找出需要删除的 ──
        target_set = set(str(ic).strip() for ic in id_card_list)
        page_set = set(item["idCard"] for item in page_id_cards)
        to_delete_ids = target_set & page_set

        # ★ 诊断：打印双方实际值（用于排查科学计数法/精度问题）
        logger.info(f"[删除] [诊断] 清单传入的身份证号: {list(target_set)}")
        logger.info(f"[删除] [诊断] 页面提取到的身份证号: {list(page_set)}")
        if target_set and page_set and not to_delete_ids:
            # 双方都有值但交集为空 → 很可能是精度不匹配，展示差异
            for t in target_set:
                for p in page_set:
                    if len(t) == len(p):
                        diff_pos = [(i, (t[i] if i < len(t) else ''), (p[i] if i < len(p) else ''))
                                     for i in range(min(len(t), len(p))) if (t[i] if i < len(t) else '') != (p[i] if i < len(p) else '')]
                        if diff_pos:
                            logger.warning(f"[删除] [诊断] 疑似同位但不同值: 清单='{t}' vs 页面='{p}' | 差异位={diff_pos[:5]}")

        skipped_by_filter = len(target_set) - len(to_delete_ids)
        logger.info(
            f"[删除] [优化] set交集结果: 清单{len(target_set)}条 ∩ 页面{len(page_set)}条"
            f" = 需删除{len(to_delete_ids)}条 (跳过不在页面的{skipped_by_filter}条)"
        )

        if not to_delete_ids:
            logger.info("[删除] [优化] 当前页面无需要删除的人员")
            return 0, []

        # 构建反向索引：身份证号 → 页面行信息
        page_index = {item["idCard"]: item for item in page_id_cards}

        # ── Phase 3: 批量勾选所有匹配行，然后一次性删除 ──
        deleted_count = 0
        deleted_ids = []

        # 判断数据来源模式
        miniui_mode = miniui_result is not None and miniui_result.get('source') == 'miniui'

        logger.info(f"[删除] [批量] 开始批量勾选 {len(to_delete_ids)} 条匹配记录（模式={('miniui-api' if miniui_mode else 'dom-locator')}）...")

        checked_rows = 0

        if miniui_mode:
            # ── MiniUI 模式：如果有分页，需要逐页翻页 + 勾选 ──
            # 分页时 grid.getData() 只返回当前页数据，必须翻到包含目标行的页才能勾选
            has_pager = miniui_result.get('hasPager', False)
            pager_total = miniui_result.get('pagerTotal', 0) or 0
            grid_source = miniui_source_frame or work_frame

            if has_pager and pager_total > 0:
                # ★ 分页模式：逐页翻页 + 勾选
                logger.info(
                    f"[删除] [MiniUI] 分页模式，pagerTotal={pager_total}，"
                    f"逐页翻页勾选 {len(to_delete_ids)} 条目标..."
                )
                remaining_ids = set(to_delete_ids)
                checked_rows = 0
                check_page = 0

                while remaining_ids:
                    check_page += 1
                    logger.info(f"[删除] [MiniUI] 第 {check_page} 页，剩余 {len(remaining_ids)} 条待勾选")

                    # 从当前页的 grid 数据中查找匹配的行并勾选
                    check_result = grid_source.evaluate("""(args) => {
                        var targetIds = args.targetIds;
                        if (typeof mini === 'undefined' || !mini.gets) return {checked: 0, error: 'no-mini'};

                        var grids = mini.gets('datagrid');
                        var grid = null;
                        for (var g = 0; g < grids.length; g++) {
                            var g2 = grids[g];
                            if (!g2 || !g2.getData) continue;
                            var d = g2.getData();
                            if (!d || d.length === 0) continue;
                            var ok = false;
                            for (var r = 0; r < Math.min(d.length, 3); r++) {
                                for (var k in d[r]) {
                                    if (/^\\d{17}[\\dXx]$/.test(String(d[r][k]||'').trim())) { ok=true; break; }
                                }
                                if (ok) break;
                            }
                            if (ok) { grid = g2; break; }
                        }
                        if (!grid) return {checked: 0, error: 'no-grid'};

                        var allData = grid.getData();
                        var idSet = {};
                        for (var r = 0; r < allData.length; r++) {
                            for (var k in allData[r]) {
                                var m = String(allData[r][k]||'').trim().match(/^(\\d{17}[\\dXx])$/);
                                if (m) idSet[m[1]] = r;
                            }
                        }

                        var checked = 0;
                        var found = [];
                        for (var t = 0; t < targetIds.length; t++) {
                            var tid = targetIds[t];
                            if (idSet[tid] !== undefined) {
                                try {
                                    var rIdx = idSet[tid];
                                    if (grid.checkRow) {
                                        grid.checkRow(rIdx);
                                        checked++;
                                        found.push(tid);
                                    }
                                } catch(e) {}
                            }
                        }
                        return {checked: checked, found: found, totalRows: allData.length};
                    }""", {"targetIds": list(remaining_ids)})

                    page_checked = check_result.get("checked", 0)
                    page_found = check_result.get("found", [])
                    checked_rows += page_checked
                    remaining_ids -= set(page_found)
                    logger.info(
                        f"[删除] [MiniUI] 第 {check_page} 页: "
                        f"勾选 {page_checked} 条, 剩余 {len(remaining_ids)} 条"
                    )

                    if not remaining_ids:
                        break  # 全部勾选完

                    # 翻到下一页
                    turned = grid_source.evaluate("""() => {
                        try {
                            if (typeof mini === 'undefined' || !mini.gets) return { turned: false };
                            var pagers = mini.gets('pager');
                            for (var pi = 0; pi < pagers.length; pi++) {
                                var pager = pagers[pi];
                                if (typeof pager.nextPage === 'function') {
                                    pager.nextPage();
                                    return { turned: true, method: 'pager.nextPage' };
                                }
                                if (typeof pager.setPageIndex === 'function') {
                                    var currentIdx = pager.getPageIndex ? pager.getPageIndex() : 0;
                                    pager.setPageIndex(currentIdx + 1);
                                    return { turned: true, method: 'pager.setPageIndex' };
                                }
                            }
                        } catch(ex) {}
                        return { turned: false };
                    }""")

                    if not turned or not turned.get('turned'):
                        # 尝试 DOM 点击
                        clicked = work_frame.evaluate("""() => {
                            var pagerBars = document.querySelectorAll('.mini-pager, .mini-pager-bar');
                            for (var p = 0; p < pagerBars.length; p++) {
                                var nextEls = pagerBars[p].querySelectorAll('[class*="next"], [class*="Next"]');
                                for (var n = 0; n < nextEls.length; n++) {
                                    nextEls[n].click();
                                    return { clicked: true, method: 'dom-next' };
                                }
                                var spans = pagerBars[p].querySelectorAll('span, a, div');
                                for (var s = 0; s < spans.length; s++) {
                                    var stxt = (spans[s].textContent || '').trim();
                                    if (stxt === '下一页' || stxt === '»' || stxt === '>') {
                                        spans[s].click();
                                        return { clicked: true, method: 'dom-text' };
                                    }
                                }
                            }
                            return { clicked: false };
                        }""")
                        if not clicked or not clicked.get('clicked'):
                            logger.warning(f"[删除] [MiniUI] 无法翻到下一页，停止。剩余 {len(remaining_ids)} 条未勾选")
                            break
                        logger.info(f"[删除] [MiniUI] 通过 DOM {clicked.get('method')} 翻到下一页")
                    else:
                        logger.info(f"[删除] [MiniUI] 通过 {turned.get('method')} 翻到下一页")

                    grid_source.wait_for_timeout(2000)

                    if check_page >= 50:
                        logger.warning(f"[删除] [MiniUI] 翻页勾选已达50页上限，停止")
                        break

                logger.info(f"[删除] [MiniUI] 分页勾选完成: 共勾选 {checked_rows} 条")
                deleted_ids = list(to_delete_ids - remaining_ids)
            else:
                # ★ 无分页模式：一次性从 getData 全量匹配并勾选
                check_result = (miniui_source_frame or work_frame).evaluate("""(args) => {
                    var targetIds = args.targetIds;
                    if (typeof mini === 'undefined' || !mini.gets) return {checked: 0, error: 'no-mini'};

                    var grids = mini.gets('datagrid');
                    var grid = null;
                    for (var g = 0; g < grids.length; g++) {
                        var g2 = grids[g];
                        if (!g2 || !g2.getData) continue;
                        var d = g2.getData();
                        if (!d || d.length === 0) continue;
                        var ok = false;
                        for (var r = 0; r < Math.min(d.length, 3); r++) {
                            for (var k in d[r]) {
                                if (/^\\d{17}[\\dXx]$/.test(String(d[r][k]||'').trim())) { ok=true; break; }
                            }
                            if (ok) break;
                        }
                        if (ok) { grid = g2; break; }
                    }
                    if (!grid) return {checked: 0, error: 'no-grid'};

                    var allData = grid.getData();
                    var idSet = {};
                    for (var r = 0; r < allData.length; r++) {
                        for (var k in allData[r]) {
                            var m = String(allData[r][k]||'').trim().match(/^(\\d{17}[\\dXx])$/);
                            if (m) idSet[m[1]] = r;
                        }
                    }

                    var checked = 0;
                    for (var t = 0; t < targetIds.length; t++) {
                        var tid = targetIds[t];
                        if (idSet[tid] !== undefined) {
                            try {
                                var rIdx = idSet[tid];
                                if (grid.checkRow) { grid.checkRow(rIdx); checked++; }
                                else if (grid.select) { grid.select(rIdx); checked++; }
                            } catch(e) {}
                        }
                    }
                    return {checked: checked, totalRows: allData.length};
                }""", {"targetIds": list(to_delete_ids)})

                checked_rows = check_result.get("checked", 0)
                logger.info(f"[删除] [MiniUI] grid API 勾选了 {checked_rows}/{len(to_delete_ids)} 条（totalRows={check_result.get('totalRows','?')}）")
                deleted_ids = list(to_delete_ids)
        else:
            # ── DOM 模式：通过 Playwright locator 勾选 ──
            for del_id in to_delete_ids:
                try:
                    row_info = page_index[del_id]
                    ti = row_info["tableIndex"]
                    ri = row_info["rowIndex"]

                    table_el = work_frame.locator("table").nth(ti)
                    row_el = table_el.locator("tbody tr, tr").nth(ri)

                    cb_clicked = False
                    cb_selectors = [
                        "input[type='checkbox']",
                        ".mini-grid-checkbox",
                        ".mini-checkbox",
                        "td:first-child input",
                        "td:first-child .mini-checkbox",
                    ]
                    for sel in cb_selectors:
                        cb = row_el.locator(sel).first
                        if cb.count() > 0:
                            try:
                                cb.click(force=True)
                                cb_clicked = True
                                break
                            except:
                                continue

                    if not cb_clicked:
                        row_el.click(force=True)

                    checked_rows += 1
                    deleted_ids.append(del_id)

                except Exception as e:
                    logger.warning(f"[删除] [批量] 勾选 {del_id} 时出错: {e}")

            logger.info(f"[删除] [批量] 已勾选 {checked_rows}/{len(to_delete_ids)} 条记录")

        if checked_rows == 0:
            logger.info("[删除] [批量] 无成功勾选的记录")
            return 0, []

        # 勾选完成后短暂等待，确保UI状态更新
        work_frame.wait_for_timeout(800)

        # Step B: 点击"删除"按钮（只点一次）
        try:
            del_btn = work_frame.locator("a:has-text('删除'), button:has-text('删除')").first
            if del_btn.count() == 0:
                logger.warning("[删除] [批量] 未找到删除按钮")
                return 0, []

            logger.info(f"[删除] [批量] 点击删除按钮（一次性删除 {checked_rows} 条）...")
            del_btn.click()
            work_frame.wait_for_timeout(1500)
        except Exception as e:
            logger.error(f"[删除] [批量] 点击删除按钮失败: {e}")
            return 0, []

        # Step C: 处理确认弹窗（只确认一次）
        confirm_btns = work_frame.locator(
            "button:has-text('确定'), button:has-text('确认'), "
            "a:has-text('确定'), a:has-text('确认')"
        )
        if confirm_btns.count() > 0:
            try:
                confirm_text = confirm_btns.first.inner_text()
                logger.info(f"[删除] [批量] 确认弹窗: {confirm_text}")
                confirm_btns.first.click()
                work_frame.wait_for_timeout(1000)
                deleted_count = checked_rows
                logger.info(f"[删除] ✓ 批量删除完成，共删除 {deleted_count} 条记录")
            except Exception as e:
                logger.error(f"[删除] [批量] 确认弹窗处理失败: {e}")
        else:
            # 某些系统可能不需要确认弹窗，点击删除后直接完成
            deleted_count = checked_rows
            logger.info(f"[删除] ✓ 批量删除完成（无确认弹窗），共删除 {deleted_count} 条")

        return deleted_count, deleted_ids
    
    def _delete_via_miniui_datagrid(self, work_frame: "Frame", id_card_list: list) -> Tuple[int, list]:
        """通过 MiniUI datagrid API 定位并删除人员（原有逻辑）"""
        deleted_count = 0
        deleted_ids = []
        
        for id_card in id_card_list:
            id_card = str(id_card).strip()
            
            # 采集人员表信息（诊断 + 找行定位）——在正确的 frame 中执行
            diag = work_frame.evaluate("""(args) => {
                var idCard = args.idCard;
                
                function isVisible(el) {
                    if (!el) return false;
                    var style = window.getComputedStyle(el);
                    var rect = el.getBoundingClientRect();
                    return style && style.display !== 'none' 
                           && style.visibility !== 'hidden' 
                           && rect.width > 0 && rect.height > 0;
                }
                
                // ── 1) 通过 MiniUI datagrid 查找行 ──
                try {
                    var grids = mini.gets('datagrid');
                    for (var g = 0; g < grids.length; g++) {
                        var grid = grids[g];
                        if (!grid || !grid.getData) continue;
                        var data = grid.getData();
                        var rowIdx = -1;
                        for (var r = 0; r < data.length; r++) {
                            var row = data[r];
                            for (var key in row) {
                                if (String(row[key] || '').trim() === idCard) {
                                    rowIdx = r;
                                    break;
                                }
                            }
                            if (rowIdx >= 0) break;
                        }
                        if (rowIdx < 0) continue;
                        
                        // 尝试找到行对应的 DOM tr
                        var gridEl = grid.getEl ? grid.getEl() : grid.el;
                        var trs = (gridEl || document).querySelectorAll('.mini-grid-row');
                        var targetTr = null;
                        for (var i = 0; i < trs.length; i++) {
                            var attrIdx = trs[i].getAttribute('data-index') 
                                       || trs[i].getAttribute('idx');
                            if (attrIdx !== null && parseInt(attrIdx) === rowIdx) {
                                targetTr = trs[i];
                                break;
                            }
                            if (trs[i].className 
                                && trs[i].className.indexOf('mini-grid-row') >= 0) {
                                var visibleIdx = -1;
                                for (var j = 0; j <= i; j++) {
                                    if (trs[j].className.indexOf('mini-grid-row') >= 0 
                                        && trs[j].style.display !== 'none'
                                        && isVisible(trs[j])) {
                                        visibleIdx++;
                                    }
                                }
                                if (visibleIdx === rowIdx) {
                                    targetTr = trs[i];
                                    break;
                                }
                            }
                        }
                        
                        var checkboxClicked = false;
                        if (targetTr) {
                            var cb = targetTr.querySelector('input[type="checkbox"]');
                            if (!cb) cb = targetTr.querySelector('.mini-grid-checkbox');
                            if (!cb) cb = targetTr.querySelector('td:first-child input');
                            if (!cb) cb = targetTr.querySelector('td:first-child .mini-checkbox');
                            if (cb) {
                                cb.click();
                                checkboxClicked = true;
                            }
                        }
                        
                        if (!checkboxClicked && grid.checkRow) {
                            grid.checkRow(rowIdx);
                            checkboxClicked = true;
                        }
                        
                        return {
                            success: true,
                            method: checkboxClicked ? 'datagrid-check' : 'datagrid-nocb',
                            rowIndex: rowIdx,
                            gridId: gridEl ? gridEl.id : '',
                            foundTr: !!targetTr,
                            dataLen: data.length,
                            trCount: trs.length,
                            sampleRow: rowIdx < data.length ? JSON.stringify(data[rowIdx]).substring(0, 300) : ''
                        };
                    }
                } catch(e) {
                    return { success: false, error: 'mini grid error: ' + e.message };
                }
                
                // ── 2) 备用：HTML table 找行 ──
                var tables = document.querySelectorAll('table');
                for (var t = 0; t < tables.length; t++) {
                    var rows = tables[t].querySelectorAll('tbody tr');
                    for (var r = 0; r < rows.length; r++) {
                        var tr = rows[r];
                        if (!isVisible(tr)) continue;
                        if ((tr.textContent || '').indexOf(idCard) >= 0) {
                            var cb = tr.querySelector('input[type="checkbox"]') 
                                  || tr.querySelector('.mini-checkbox')
                                  || tr.querySelector('td:first-child input');
                            if (cb) {
                                cb.click();
                                return { success: true, method: 'html-checkbox', rowIndex: r };
                            }
                            tr.click();
                            return { success: true, method: 'html-click', rowIndex: r };
                        }
                    }
                }
                
                return { success: false, error: '未在页面找到该身份证对应行' };
            }""", {"idCard": id_card})
            
            if not diag.get("success"):
                logger.info(f"[删除] 页面未找到身份证 {id_card} 对应行，跳过")
                continue
            
            method = diag.get("method", "")
            row_idx = diag.get("rowIndex", "?")
            logger.info(
                f"[删除] 找到行 index={row_idx}（方式={method}）| "
                f"foundTr={diag.get('foundTr')} | dataLen={diag.get('dataLen')} | "
                f"trCount={diag.get('trCount')} | "
                f"sampleRow={diag.get('sampleRow', '')}"
            )
            
            if method == 'datagrid-nocb':
                logger.warning("[删除] datagrid 方式找到了行但未点击到复选框，尝试备用定位...")
                try:
                    grid_el = work_frame.locator("#personnelInfoGrid, .mini-datagrid, table.mini-grid").first
                    if grid_el.count() > 0:
                        rows_loc = grid_el.locator(".mini-grid-row:visible, tr")
                        for ri in range(rows_loc.count()):
                            row_text = rows_loc.nth(ri).inner_text()
                            if id_card in row_text:
                                cb_loc = rows_loc.nth(ri).locator(
                                    "input[type='checkbox'], .mini-grid-checkbox, "
                                    "td:first-child input, td:first-child .mini-checkbox"
                                ).first
                                if cb_loc.count() > 0:
                                    cb_loc.click()
                                    logger.info(f"[删除] Playwright 备用方式点击复选框成功 (row={ri})")
                                else:
                                    rows_loc.nth(ri).click()
                                    logger.info(f"[删除] Playwright 备用方式点击行成功 (row={ri})")
                                break
                except Exception as e:
                    logger.warning(f"[删除] Playwright 备用定位复选框失败: {e}")
            
            work_frame.wait_for_timeout(800)
            
            # 点击页面上的"删除"按钮（在正确的 frame 中）
            del_btn = work_frame.locator("a:has-text('删除'), button:has-text('删除')").first
            if del_btn.count() == 0:
                logger.warning(f"[删除] 未找到删除按钮，跳过 {id_card}")
                continue
            
            logger.info("[删除] 正在点击删除按钮...")
            del_btn.click()
            work_frame.wait_for_timeout(1500)
            
            # 处理可能弹出的确认对话框（在正确的 frame 中）
            try:
                confirm_btn = work_frame.locator(
                    "button:has-text('确定'), button:has-text('确认'), "
                    "a:has-text('确定'), a:has-text('确认')"
                ).first
                if confirm_btn.count() > 0:
                    confirm_text = confirm_btn.inner_text()
                    confirm_btn.click()
                    logger.info(f"[删除] 已点击确认按钮（文本: {confirm_text}）")
                    work_frame.wait_for_timeout(1000)
            except Exception as e:
                logger.warning(f"[删除] 确认弹窗处理异常（继续）: {e}")
            
            logger.info(f"[删除] 身份证 {id_card} 对应记录已删除")
            deleted_count += 1
            deleted_ids.append(id_card)
            work_frame.wait_for_timeout(500)
        
        logger.info(f"[删除] 完成，共删除 {deleted_count} 条记录")
        return deleted_count, deleted_ids

    def verify_order_amount(self) -> bool:
        """
        验证技术合作订单金额是否已回填，并确认金额属于当前申请单。

        这里不只看单一字段，而是轮询多个可能的金额字段；同时把当前页面状态与
        `search_application()` 成功时记录的申请单快照做一致性校验，避免误读上一条记录残留的金额。

        Returns:
            bool: 当前申请单金额大于 0 返回 True
        """
        logger.info("=== 验证订单金额 ===")

        try:
            expected_app_no = self._normalize_app_no(self.current_app_no)
            snapshot = self.current_form_snapshot or {}

            if not expected_app_no and not snapshot:
                logger.warning("[金额] 当前未记录申请单快照，拒绝校验金额，避免串单误判")
                return False

            result = {}
            for idx in range(12):
                result = self.page.evaluate("""(args) => {
                    function normalizeText(v) {
                        return String(v || '').replace(/\s+/g, '').trim().toUpperCase();
                    }

                    function normalizeAmount(v) {
                        return String(v || '').replace(/,/g, '').replace(/\s+/g, '').trim();
                    }

                    function getVal(id) {
                        var el = document.getElementById(id);
                        return el ? String(el.value || '').trim() : '';
                    }

                    function getFirstVal(ids) {
                        for (var i = 0; i < ids.length; i++) {
                            var val = getVal(ids[i]);
                            if (val) return val;
                        }
                        return '';
                    }

                    var candidates = [];
                    var positiveCandidate = null;

                    try {
                        var miniIds = ['changeOrderAmount', 'p_order_amount', 'orderAmount', 'orderAmountDiffer', 'contractMoney'];
                        for (var i = 0; i < miniIds.length; i++) {
                            var ctrl = window.mini && mini.get(miniIds[i]);
                            if (ctrl && ctrl.getValue) {
                                candidates.push({
                                    source: 'mini:' + miniIds[i],
                                    value: normalizeAmount(ctrl.getValue())
                                });
                            }
                        }
                    } catch (e) {}

                    var inputs = Array.from(document.querySelectorAll('input[type=text], input:not([type])'));
                    for (var j = 0; j < inputs.length; j++) {
                        var id = String(inputs[j].id || '');
                        var name = String(inputs[j].name || '');
                        var key = (id + '|' + name).toLowerCase();
                        if (key.indexOf('amount') >= 0 || key.indexOf('money') >= 0 || key.indexOf('fee') >= 0) {
                            candidates.push({
                                source: 'dom:' + (id || name || ('index' + j)),
                                value: normalizeAmount(inputs[j].value)
                            });
                        }
                    }

                    for (var k = 0; k < candidates.length; k++) {
                        var val = candidates[k].value;
                        if (val && !isNaN(parseFloat(val)) && parseFloat(val) > 0) {
                            positiveCandidate = {
                                source: candidates[k].source,
                                amount: val
                            };
                            break;
                        }
                    }

                    var projectCode = getVal('projectCode$text') || getVal('projectCode');
                    var projectName = getVal('projectName$text') || getVal('projectName');
                    var sbuName = getVal('sbuName$text') || getVal('sbuName');
                    var applicationId = getVal('applicationId');
                    var appId = getVal('appId');
                    var applicationText = getVal('application$text');
                    var selectedAppNo = getFirstVal([
                        'btnEdit1$text', 'btnEdit1$value',
                        'renewApplyNo$text', 'renewApplyNo',
                        'renewalApplyNo$text', 'renewalApplyNo',
                        'appNo$text', 'appNo',
                        'applyNo$text', 'applyNo',
                        'p_app_no', 'application$text'
                    ]);
                    var personnelCount = 0;

                    try {
                        if (window.mini && mini.gets) {
                            var grids = mini.gets('datagrid') || [];
                            for (var g = 0; g < grids.length; g++) {
                                if (grids[g] && grids[g].getData) {
                                    var data = grids[g].getData() || [];
                                    if (data.length > personnelCount) personnelCount = data.length;
                                }
                            }
                        }
                    } catch (e) {}

                    var expected = normalizeText(args.expectedAppNo || '');
                    var normalizedSelected = normalizeText(selectedAppNo);
                    var normalizedApplicationText = normalizeText(applicationText);
                    var hasBusinessData = !!(projectCode || projectName || applicationId || appId || personnelCount > 0);

                    return {
                        hasPositiveAmount: !!positiveCandidate,
                        amount: positiveCandidate ? positiveCandidate.amount : '',
                        method: positiveCandidate ? positiveCandidate.source : '',
                        error: (projectCode || projectName || applicationId || appId)
                            ? '申请单已加载，但金额尚未回填'
                            : '申请单可能未成功加载，导致金额为空',
                        hasBusinessData: hasBusinessData,
                        applicationText: applicationText,
                        selectedAppNo: selectedAppNo,
                        matchesExpected: !expected || (normalizedSelected && normalizedSelected === expected) || (normalizedApplicationText && normalizedApplicationText === expected),
                        appId: appId,
                        applicationId: applicationId,
                        projectCode: projectCode,
                        projectName: projectName,
                        sbuName: sbuName,
                        personnelCount: personnelCount,
                        candidates: candidates.slice(0, 12),
                        allTextInputs: inputs.slice(0, 20).map(function(el) {
                            return (el.id || '') + '|' + (el.name || '') + '|' + String(el.value || '').substring(0, 20);
                        })
                    };
                }""", {"expectedAppNo": expected_app_no})

                snapshot_consistent = self._snapshot_consistent(result, snapshot)
                current_matches = bool(
                    result.get("matchesExpected") or
                    ((not self._normalize_app_no(result.get("selectedAppNo"))) and snapshot_consistent) or
                    ((not expected_app_no) and snapshot_consistent)
                )

                if result.get("hasPositiveAmount") and current_matches:
                    logger.info(
                        f"[金额] 金额验证成功: {result.get('amount')} "
                        f"(方式: {result.get('method')}, selectedAppNo={result.get('selectedAppNo')}, "
                        f"projectCode={result.get('projectCode')}, projectName={result.get('projectName')}, "
                        f"snapshotConsistent={snapshot_consistent})"
                    )
                    return True

                if result.get("hasPositiveAmount") and not current_matches:
                    logger.warning(
                        f"[金额] 检测到正金额但当前表单与目标申请单不一致，忽略本次结果: "
                        f"amount={result.get('amount')} | selectedAppNo={result.get('selectedAppNo')} | "
                        f"applicationText={result.get('applicationText')} | matchesExpected={result.get('matchesExpected')} | "
                        f"snapshotConsistent={snapshot_consistent} | projectCode={result.get('projectCode')}"
                    )

                if idx < 11:
                    self.page.wait_for_timeout(1000)

            logger.warning(
                f"[金额] 金额验证失败: {result.get('error')} | "
                f"expectedAppNo={expected_app_no} | selectedAppNo={result.get('selectedAppNo')} | "
                f"applicationText={result.get('applicationText')} | matchesExpected={result.get('matchesExpected')} | "
                f"snapshotConsistent={self._snapshot_consistent(result, snapshot)} | "
                f"appId={result.get('appId')} | applicationId={result.get('applicationId')} | "
                f"projectCode={result.get('projectCode')} | projectName={result.get('projectName')} | "
                f"候选金额字段={result.get('candidates')} | 所有文本框={result.get('allTextInputs')}" 
            )
            return False

        except Exception as e:
            logger.error(f"[金额] 异常: {e}")
            return False

    
    def submit_for_approval(self) -> Tuple[bool, str]:
        """
        点击保存并提交审批按钮，按以下规则处理弹窗：

        规则：
        1. 点击提交后出现"人员明细超过申请单总HC!"等非确认弹窗 → 关弹窗，返回 (False, 合同未签署 + 弹窗内容)
        2. 点击提交后出现"是否确认保存并提交订单?"类确认弹窗 → 点"确认"
           - 确认后若出现"超过剩余金额"弹窗：
             提取"剩余金额X"，读取当前"技术合作订单金额"（changeOrderAmount），
             若 abs(当前 - X) < 1000，则取消弹窗，将金额改为 X 后重新提交；
             否则关弹窗，返回 (False, 合同未签署 + 弹窗内容)
           - 确认后若出现"预算/费用不足"弹窗且不足额 ≤ 1000：
             取消弹窗，扣减不足额后重新提交；否则返回失败
           - 确认后无弹窗 → 返回 (True, 合同签署)
        3. 点击提交后无弹窗 → 返回 (True, 合同签署)

        注意：判断"确认弹窗"只看弹窗文字是否含提交确认关键词，
              不以按钮内容判断，避免 HC 不足等提示弹窗被误判为确认弹窗。

        Returns:
            Tuple[bool, str]: (是否成功, 反馈文本)
        """
        import math
        import re as _re

        logger.info("=== 提交审批 ===")

        def _get_popup_info() -> dict:
            """检测当前是否有弹窗，返回弹窗信息字典"""
            return self.page.evaluate("""() => {
                function isVisible(el) {
                    if (!el) return false;
                    var style = window.getComputedStyle(el);
                    var rect = el.getBoundingClientRect();
                    return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                }
                function normalize(text) {
                    return String(text || '').replace(/\s+/g, ' ').trim();
                }
                var selectors = [
                    '.mini-messagebox', '.mini-modal', '.mini-window', '.mini-popup',
                    '.ui-dialog', '.dialog', '[role="dialog"]'
                ];
                var seen = [], popups = [];
                for (var s = 0; s < selectors.length; s++) {
                    var els = document.querySelectorAll(selectors[s]);
                    for (var i = 0; i < els.length; i++) {
                        var el = els[i];
                        if (!isVisible(el) || seen.indexOf(el) >= 0) continue;
                        seen.push(el);
                        var text = normalize(el.textContent || el.innerText || '');
                        if (!text) continue;
                        var st = window.getComputedStyle(el);
                        var rect = el.getBoundingClientRect();
                        popups.push({
                            el: el, text: text,
                            zIndex: parseInt(st.zIndex || '0', 10) || 0,
                            area: Math.round(rect.width * rect.height)
                        });
                    }
                }
                popups.sort(function(a, b) {
                    return b.zIndex !== a.zIndex ? b.zIndex - a.zIndex : b.area - a.area;
                });
                if (!popups.length) return { hasPopup: false };
                var popup = popups[0];
                var popupText = popup.text.substring(0, 300);
                var compactText = popupText.replace(/\s+/g, '');
                var submitConfirmKeywords = [
                    '是否提交', '确认提交', '是否保存并提交', '是否继续提交',
                    '提交审批', '确定要提交', '是否提交审批', '保存并提交审批', '保存及提交审批',
                    '是否确认保存并提交订单', '确认保存并提交订单', '保存并提交订单', '确定是否确认保存并提交订单'
                ];

                var isConfirm = submitConfirmKeywords.some(function(k) { return compactText.indexOf(k) >= 0; });
                var buttons = Array.from(popup.el.querySelectorAll(
                    'a, button, span, input[type=button], input[type=submit]'
                )).filter(isVisible).map(function(b) {
                    return normalize(b.textContent || b.value || '');
                }).filter(function(t) { return !!t; });
                // "HC不足"/"人员明细超过申请单总HC"等只有"确定"按钮的提示弹窗，
                // 不能仅靠按钮判断为确认弹窗，必须同时匹配关键词才算确认弹窗
                return {
                    hasPopup: true,
                    isConfirmDialog: isConfirm,
                    popupText: popupText,
                    buttons: buttons.slice(0, 8)
                };
            }""")

        def _click_confirm() -> bool:
            """点击确认类弹窗上的"确认"按钮，返回是否成功点击。"""
            result = self.page.evaluate("""() => {
                function isVisible(el) {
                    if (!el) return false;
                    var style = window.getComputedStyle(el);
                    var rect = el.getBoundingClientRect();
                    return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                }
                function normalize(text) { return String(text || '').replace(/\s+/g, ' ').trim(); }
                function collectPopups() {
                    var selectors = ['.mini-messagebox', '.mini-modal', '.mini-window', '.mini-popup', '.ui-dialog', '.dialog', '[role="dialog"]'];
                    var seen = [], popups = [];
                    for (var s = 0; s < selectors.length; s++) {
                        var els = document.querySelectorAll(selectors[s]);
                        for (var i = 0; i < els.length; i++) {
                            var el = els[i];
                            if (!isVisible(el) || seen.indexOf(el) >= 0) continue;
                            seen.push(el);
                            var text = normalize(el.textContent || el.innerText || '');
                            if (!text) continue;
                            var st = window.getComputedStyle(el);
                            popups.push({ el: el, text: text, zIndex: parseInt(st.zIndex || '0', 10) || 0 });
                        }
                    }
                    popups.sort(function(a, b) { return b.zIndex - a.zIndex; });
                    return popups;
                }

                var popups = collectPopups();
                for (var p = 0; p < popups.length; p++) {
                    var btns = Array.from(popups[p].el.querySelectorAll('a, button, span, input[type=button], input[type=submit]')).filter(isVisible);

                    for (var j = 0; j < btns.length; j++) {
                        var t = normalize(btns[j].textContent || btns[j].value || '');
                        if (t === '确认' || t.indexOf('确认') >= 0) {
                            btns[j].click();
                            return { clicked: true, text: t, mode: 'confirm' };
                        }
                    }

                    for (var k = 0; k < btns.length; k++) {
                        var t2 = normalize(btns[k].textContent || btns[k].value || '');
                        var c2 = String(btns[k].className || '');
                        if (c2.indexOf('mini-messagebox-ok') >= 0 || t2 === '确定' || t2.indexOf('确定') >= 0) {
                            btns[k].click();
                            return { clicked: true, text: t2, mode: 'ok' };
                        }
                    }
                }
                return { clicked: false };
            }""")
            return bool(result and result.get('clicked'))

        def _wait_loading(max_wait: int = 15) -> None:
            """检测并等待 Loading/正在加载 弹窗消失。
            提交确认后系统常显示 'Loading正在加载，请稍等...' 这类加载提示，
            不应将其误判为错误弹窗。"""
            import time as _time
            start = _time.time()
            while _time.time() - start < max_wait:
                info = self.page.evaluate("""() => {
                    function isVisible(el) {
                        if (!el) return false;
                        var style = window.getComputedStyle(el);
                        var rect = el.getBoundingClientRect();
                        return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                    }
                    function normalize(text) { return String(text || '').replace(/\s+/g, ' ').trim(); }
                    var selectors = ['.mini-messagebox', '.mini-modal', '.mini-window', '.mini-popup', '.ui-dialog', '.dialog', '[role="dialog"]'];
                    var seen = [], popups = [];
                    for (var s = 0; s < selectors.length; s++) {
                        var els = document.querySelectorAll(selectors[s]);
                        for (var i = 0; i < els.length; i++) {
                            var el = els[i];
                            if (!isVisible(el) || seen.indexOf(el) >= 0) continue;
                            seen.push(el);
                            var text = normalize(el.textContent || el.innerText || '');
                            if (!text) continue;
                            popups.push({ el: el, text: text });
                        }
                    }
                    if (!popups.length) return { loading: false };
                    // 检查是否是加载提示
                    var txt = popups[0].text.replace(/\\s+/g, '');
                    var loadingKeywords = ['loading', '正在加载', '请稍等', '加载中', '处理中', '提交中', '保存中'];
                    var isLoading = loadingKeywords.some(function(k) { return txt.toLowerCase().indexOf(k.toLowerCase()) >= 0; });
                    return { loading: isLoading, text: popups[0].text.substring(0, 200) };
                }""")
                is_loading = info.get("loading", False)
                if not is_loading:
                    logger.info(f"[提交] Loading已消失（等待 {_time.time() - start:.1f}s）")
                    return
                logger.info(f"[提交] 检测到Loading弹窗，继续等待... ({info.get('text', '')[:60]})")
                self.page.wait_for_timeout(1500)

            # 超时仍未消失，尝试点击关闭
            logger.warning(f"[提交] Loading等待超时({max_wait}s)，尝试关闭")
            self.page.evaluate("""() => {
                function isVisible(el) {
                    if (!el) return false;
                    var style = window.getComputedStyle(el);
                    var rect = el.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                }
                var selectors = ['.mini-messagebox', '.mini-modal', '.mini-window'];
                for (var s = 0; s < selectors.length; s++) {
                    var els = document.querySelectorAll(selectors[s]);
                    for (var i = 0; i < els.length; i++) {
                        if (!isVisible(els[i])) continue;
                        var btns = els[i].querySelectorAll('a, button, span');
                        for (var j = 0; j < btns.length; j++) {
                            var t = (btns[j].textContent || '').trim();
                            if (t === '确定' || t === '确认') { btns[j].click(); return; }
                        }
                    }
                }
            }""")
            self.page.wait_for_timeout(1000)

        def _cancel_popup() -> str:
            """关闭当前弹窗（优先点"取消"，没有取消则点确定/确认），返回弹窗内容。"""
            return self.page.evaluate("""() => {
                function isVisible(el) {
                    if (!el) return false;
                    var style = window.getComputedStyle(el);
                    var rect = el.getBoundingClientRect();
                    return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                }
                function normalize(text) { return String(text || '').replace(/\s+/g, ' ').trim(); }
                var selectors = ['.mini-messagebox', '.mini-modal', '.mini-window', '.mini-popup', '.ui-dialog', '.dialog', '[role="dialog"]'];
                var seen = [], popups = [];
                for (var s = 0; s < selectors.length; s++) {
                    var els = document.querySelectorAll(selectors[s]);
                    for (var i = 0; i < els.length; i++) {
                        var el = els[i];
                        if (!isVisible(el) || seen.indexOf(el) >= 0) continue;
                        seen.push(el);
                        var text = normalize(el.textContent || el.innerText || '');
                        if (!text) continue;
                        var st = window.getComputedStyle(el);
                        popups.push({ el: el, text: text, zIndex: parseInt(st.zIndex || '0', 10) || 0 });
                    }
                }
                popups.sort(function(a, b) { return b.zIndex - a.zIndex; });
                if (!popups.length) return '';
                var popup = popups[0];
                var popupText = popup.text.substring(0, 300);
                var btns = Array.from(popup.el.querySelectorAll('a, button, span, input[type=button], input[type=submit]')).filter(isVisible);
                // 优先点取消
                for (var j = 0; j < btns.length; j++) {
                    var t = normalize(btns[j].textContent || btns[j].value || '');
                    var c = String(btns[j].className || '');
                    if (t.indexOf('取消') >= 0 || c.indexOf('mini-messagebox-cancel') >= 0) { btns[j].click(); return popupText; }
                }
                // 没有取消则点确定/确认
                for (var k = 0; k < btns.length; k++) {
                    var t2 = normalize(btns[k].textContent || btns[k].value || '');
                    var c2 = String(btns[k].className || '');
                    if (t2.indexOf('确定') >= 0 || t2.indexOf('确认') >= 0 || c2.indexOf('mini-messagebox-ok') >= 0) { btns[k].click(); return popupText; }
                }
                return popupText;
            }""")

        def _extract_shortage(popup_text: str):
            """
            从弹窗文本中提取与"预算/费用/剩余金额"相关的不足信息。

            规则（2026-04-24 重构）：
            - "剩余金额X" 模式 → 直接返回 X（剩余金额），由上层做差额比较
            - "预算不足/费用不足" 模式 → 提取不足额数字返回
            - 不匹配 → 返回 None

            返回值约定：
            - float: 提取到的数值（剩余金额或不足额）
            - None: 不匹配
            """
            budget_keywords = ['预算不足', '费用不足', '超出预算', '预算超出', '不足额',
                                '剩余金额', '剩余预算', '超过了关联的申请单剩余金额']
            compact = popup_text.replace(' ', '')
            if not any(k in compact for k in budget_keywords):
                return None

            # 尝试提取数字
            nums = _re.findall(r'[\d]+(?:[.,]\d+)?', compact)
            if not nums:
                return None

            shortage_str = nums[-1].replace(',', '')
            try:
                shortage_num = float(shortage_str)
            except ValueError:
                return None

            # "剩余金额X" 模式：直接返回 X（剩余金额）
            # 不再计算 shortage = current - remaining，避免 current 读错导致误判
            if '剩余金额' in compact:
                return shortage_num  # 这就是剩余金额

            return shortage_num

        def _read_order_amount() -> Optional[float]:
            """读取页面上"技术合作订单金额"字段的当前值，返回 float 或 None。
            优先读 changeOrderAmount（浏览器显示的"技术合作订单金额"），再读 orderAmount。"""
            try:
                raw = self.page.evaluate(r"""() => {
                    function normalizeAmount(v) {
                        return String(v || '').replace(/,/g, '').replace(/\s+/g, '').trim();
                    }
                    // changeOrderAmount 是浏览器显示的"技术合作订单金额"，优先读
                    var fieldIds = ['changeOrderAmount', 'orderAmount', 'p_order_amount', 'contractMoney', 'orderAmountDiffer'];
                    for (var i = 0; i < fieldIds.length; i++) {
                        var fid = fieldIds[i];
                        var miniVal = '';
                        try {
                            var ctrl = window.mini && mini.get(fid);
                            if (ctrl && ctrl.getValue) miniVal = normalizeAmount(ctrl.getValue());
                        } catch(e) {}
                        if (miniVal && miniVal !== '0') return miniVal;
                        var el = document.getElementById(fid) || document.getElementById(fid + '$text');
                        if (el) {
                            var v = normalizeAmount(el.value);
                            if (v && v !== '0') return v;
                        }
                    }
                    return '';
                }""")
                if raw:
                    return float(str(raw).replace(',', ''))
            except Exception as e:
                logger.warning(f"[提交] 读取订单金额失败: {e}")
            return None

        def _write_order_amount(new_amount: int) -> bool:
            """将 new_amount 写入页面"技术合作订单金额"字段，返回是否写入成功。"""
            try:
                result = self.page.evaluate("""(newVal) => {
                    function trySet(fid, val) {
                        try {
                            var ctrl = window.mini && mini.get(fid);
                            if (ctrl && ctrl.setValue) {
                                ctrl.setValue(val);
                                if (ctrl.fireEvent) ctrl.fireEvent('valuechanged', { value: val });
                                return true;
                            }
                        } catch(e) {}
                        var el = document.getElementById(fid) || document.getElementById(fid + '$text');
                        if (el) {
                            el.value = val;
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                            el.dispatchEvent(new Event('blur', { bubbles: true }));
                            return true;
                        }
                        return false;
                    }
                    var fieldIds = ['orderAmount', 'changeOrderAmount', 'p_order_amount', 'contractMoney', 'orderAmountDiffer'];
                    for (var i = 0; i < fieldIds.length; i++) {
                        if (trySet(fieldIds[i], newVal)) return fieldIds[i];
                    }
                    return null;
                }""", str(new_amount))
                if result:
                    logger.info(f"[提交] 金额回填成功，字段={result}，新金额={new_amount}")
                    return True
                logger.warning(f"[提交] 未找到可写入的金额字段")
                return False
            except Exception as e:
                logger.warning(f"[提交] 写入金额失败: {e}")
                return False

        try:
            submit_btn = self.page.locator(self.SELECTORS["submit_btn"]).first
            if submit_btn.count() == 0:
                logger.error("[提交] 未找到提交按钮")
                return False, "合同未签署：未找到保存并提交审批按钮"

            amount_diag = self._collect_amount_diagnostics(self.current_app_no)
            if amount_diag.get("error"):
                logger.warning(f"[提交前金额] 采集失败: {amount_diag.get('error')}")
            else:
                snapshot_consistent = self._snapshot_consistent(amount_diag, self.current_form_snapshot)
                logger.info(
                    f"[提交前金额] expectedAppNo={self._normalize_app_no(self.current_app_no)} | "
                    f"selectedAppNo={amount_diag.get('selectedAppNo')} | applicationText={amount_diag.get('applicationText')} | "
                    f"matchesExpected={amount_diag.get('matchesExpected')} | snapshotConsistent={snapshot_consistent} | "
                    f"金额字段={amount_diag.get('amountFields')} | 候选金额字段={amount_diag.get('candidates')}"
                )

            # ── 提交前：确保 p_order_amount 不为空 ──────────────────────
            # 服务器校验 p_order_amount，如果为空会报"技术合作订单金额不能为空"
            # 使用更强力的多重写入策略
            _sync_result = self.page.evaluate(r"""() => {
                function getVal(id) {
                    var el = document.getElementById(id);
                    return el ? String(el.value || '').replace(/,/g, '').trim() : '';
                }
                
                var pOrderAmountBefore = getVal('p_order_amount');
                var orderAmount = getVal('orderAmount');
                
                // 如果 p_order_amount 已有有效值，无需操作
                if (pOrderAmountBefore && pOrderAmountBefore !== '0') {
                    return { synced: true, orderAmount: orderAmount, pOrderAmountBefore: pOrderAmountBefore, reason: 'already_set' };
                }
                
                if (!orderAmount || orderAmount === '0') {
                    return { synced: false, orderAmount: orderAmount, pOrderAmountBefore: pOrderAmountBefore, reason: 'no_source' };
                }
                
                // 多重写入策略
                var setCount = 0;
                
                // 1. MiniUI 控件
                try {
                    var ctrl = window.mini && mini.get('p_order_amount');
                    if (ctrl && ctrl.setValue) { ctrl.setValue(orderAmount); setCount++; }
                } catch(e) {}
                
                // 2. DOM 元素（多种可能 ID）
                ['p_order_amount', 'p_order_amount$text', 'p_order_amount$value'].forEach(function(tid) {
                    var el = document.getElementById(tid);
                    if (el) { el.value = orderAmount; setCount++; }
                });
                
                // 3. 按 name 查找
                document.querySelectorAll('[name*="p_order"], [name*="orderAmount"]').forEach(function(nel) {
                    var nm = nel.getAttribute('name') || '';
                    if (nm.indexOf('p_order') >= 0 || nm === 'orderAmount') {
                        nel.value = orderAmount; setCount++;
                    }
                });
                
                // 4. 如果元素不存在，动态创建 hidden input
                if (!document.getElementById('p_order_amount')) {
                    try {
                        var newEl = document.createElement('input');
                        newEl.type = 'hidden';
                        newEl.id = 'p_order_amount';
                        newEl.name = 'p_order_amount';
                        newEl.value = orderAmount;
                        document.body.appendChild(newEl);
                        setCount++;
                        try { if(window.mini && mini.parse) mini.parse(document.body); } catch(ex){}
                    } catch(ce) {}
                }
                
                // 最终验证
                var finalVal = getVal('p_order_amount');
                try {
                    var fc = window.mini && mini.get('p_order_amount');
                    if (fc && fc.getValue) finalVal = fc.getValue();
                } catch(e){}
                
                return {
                    synced: !!finalVal,
                    orderAmount: orderAmount,
                    pOrderAmountBefore: pOrderAmountBefore,
                    setCount: setCount,
                    finalVal: finalVal
                };
            }""")
            if _sync_result.get('synced'):
                logger.info(f"[提交前] ✅ p_order_amount已就绪: {_sync_result.get('finalVal')}（来源:{_sync_result.get('reason', 'synced')}，写入{_sync_result.get('setCount', 0)}处）")
            else:
                # p_order_amount 同步失败 → 提交必定报"金额为空"，直接拦截
                detail_msg = (f"orderAmount={_sync_result.get('orderAmount')}, "
                              f"setCount={_sync_result.get('setCount', 0)}, "
                              f"reason={_sync_result.get('reason', 'unknown')}")
                logger.error(f"[提交前] ❌ p_order_amount 同步失败！{detail_msg}，拦截提交避免无效报错")
                return False, "合同未签署：技术合作订单金额同步失败（p_order_amount写入后仍为空），请检查页面表单状态"

            # ── 第一次提交 ──────────────────────────────────────────────
            submit_btn.click()
            self.page.wait_for_timeout(2000)

            # 最多允许：3次确认弹窗点击 + 1次不足额扣减后重新提交
            shortage_deducted = False  # 记录是否已做过不足额扣减提交

            for _round in range(1, 8):
                popup = _get_popup_info()

                # ── 无弹窗 → 合同签署 ──────────────────────────────────
                if not popup.get("hasPopup"):
                    label = "（无弹窗）" if _round == 1 else "（确认/调整后）"
                    logger.info(f"[提交] 提交成功{label}")
                    return True, "合同签署"

                popup_text = popup.get("popupText", "")
                is_confirm = popup.get("isConfirmDialog", False)

                # ── 优先检查是否为 Loading/正在加载 弹窗 → 等待消失 ──
                _compact_text = popup_text.replace(' ', '').replace('\n', '')
                _loading_kws = ['loading', '正在加载', '请稍等', '加载中', '处理中', '提交中', '保存中']
                _is_loading = any(k in _compact_text.lower() for k in _loading_kws)
                if _is_loading:
                    logger.info(f"[提交] 第{_round}轮检测到Loading弹窗，等待消失: {popup_text[:60]}")
                    self.page.wait_for_timeout(2000)
                    continue

                # ── 规则1/2-前半：确认弹窗 → 点"确认" ──────────────────
                if is_confirm:
                    logger.info(f"[提交] 第{_round}轮检测到确认弹窗，点击确认: {popup_text[:80]}")
                    if not _click_confirm():
                        logger.error("[提交] 未能点击确认按钮")
                        closed = _cancel_popup()
                        return False, f"合同未签署：未能点击确认弹窗（{(closed or popup_text)[:80]}）"
                    self.page.wait_for_timeout(1500)

                    # ── 确认后可能出现 "Loading/正在加载" 提示，等待其消失 ──
                    _wait_loading()
                    continue  # 继续检测下一轮弹窗

                # ── 规则2-后半：确认后出现非确认弹窗 ─────────────────────
                # 先判断是否是"预算/费用不足"或"超过剩余金额"
                shortage = _extract_shortage(popup_text)
                if shortage is not None and not shortage_deducted:
                    is_remaining_mode = '剩余金额' in popup_text.replace(' ', '')

                    if is_remaining_mode:
                        # "剩余金额X" 模式：比较 abs(当前显示金额 - 剩余金额) < 1000
                        remaining = shortage  # _extract_shortage 直接返回剩余金额
                        current_amount = _read_order_amount()
                        logger.info(
                            f"[提交] 弹窗剩余金额={remaining}, 当前显示金额={current_amount}"
                        )
                        if current_amount is not None and abs(current_amount - remaining) < 1000:
                            new_amount = int(remaining)
                            logger.info(
                                f"[提交] 差额={abs(current_amount - remaining):.0f} < 1000，"
                                f"将技术合作订单金额改为剩余金额 {new_amount} 后重新提交"
                            )
                            # 1. 取消弹窗
                            _cancel_popup()
                            self.page.wait_for_timeout(800)
                            # 2. 直接将剩余金额写入 changeOrderAmount（技术合作订单金额）和 p_order_amount
                            write_detail = self.page.evaluate("""(val) => {
                                var targets = ['changeOrderAmount', 'p_order_amount'];
                                var results = [];
                                for (var i = 0; i < targets.length; i++) {
                                    var fid = targets[i];
                                    var ok = false;
                                    try {
                                        var ctrl = window.mini && mini.get(fid);
                                        if (ctrl && ctrl.setValue) {
                                            ctrl.setValue(val);
                                            if (ctrl.fireEvent) ctrl.fireEvent('valuechanged', { value: val });
                                            ok = true;
                                        }
                                    } catch(e) {}
                                    if (!ok) {
                                        var el = document.getElementById(fid) || document.getElementById(fid + '$text');
                                        if (el) { el.value = val; ok = true; }
                                    }
                                    results.push(fid + '=' + ok);
                                }
                                return results.join(', ');
                            }""", str(new_amount))
                            logger.info(f"[提交] 金额回填成功，changeOrderAmount + p_order_amount = {new_amount}，detail={write_detail}")
                            self.page.wait_for_timeout(800)
                            shortage_deducted = True
                            # 3. 重新点提交
                            logger.info(f"[提交] 金额调整为 {new_amount}，重新点击保存并提交审批")
                            submit_btn2 = self.page.locator(self.SELECTORS["submit_btn"]).first
                            if submit_btn2.count() == 0:
                                return False, "合同未签署：调整金额后未找到提交按钮"
                            submit_btn2.click()
                            self.page.wait_for_timeout(2000)
                            continue
                        else:
                            reason = "无法读取当前金额" if current_amount is None else f"差额={abs(current_amount - remaining):.0f}>=1000"
                            logger.warning(f"[提交] 剩余金额模式不满足自动调整条件: {reason}")
                    else:
                        # "预算不足/费用不足" 模式：不足额 <= 1000 时扣减
                        if shortage <= 1000:
                            shortage_int = math.ceil(shortage)
                            logger.info(
                                f"[提交] 检测到不足额={shortage}（取整={shortage_int}），尝试扣减金额后重新提交: {popup_text[:80]}"
                            )
                            _cancel_popup()
                            self.page.wait_for_timeout(800)
                            current_amount = _read_order_amount()
                            if current_amount is None:
                                logger.error("[提交] 无法读取当前订单金额，放弃自动扣减")
                                return False, f"合同未签署：检测到不足额但无法读取当前金额，请手动处理（{popup_text[:100]}）"
                            new_amount = int(math.ceil(current_amount)) - shortage_int
                            if new_amount <= 0:
                                logger.error(f"[提交] 扣减后金额={new_amount}≤0，放弃自动扣减")
                                return False, f"合同未签署：扣减不足额后金额异常（{popup_text[:100]}）"
                            if not _write_order_amount(new_amount):
                                return False, f"合同未签署：不足额扣减回填失败，请手动处理（{popup_text[:100]}）"
                            self.page.wait_for_timeout(800)
                            shortage_deducted = True
                            logger.info(f"[提交] 金额由 {current_amount} 调整为 {new_amount}，重新点击保存并提交审批")
                            submit_btn2 = self.page.locator(self.SELECTORS["submit_btn"]).first
                            if submit_btn2.count() == 0:
                                return False, "合同未签署：扣减金额后未找到提交按钮"
                            submit_btn2.click()
                            self.page.wait_for_timeout(2000)
                            continue

                # ── 规则1 / 规则2-后半（不符合不足额条件）→ 关弹窗报失败 ──
                logger.warning(f"[提交] 提交后出现非确认弹窗: {popup_text[:120]}")
                closed = _cancel_popup()
                return False, f"合同未签署：{(closed or popup_text)[:150]}"

            # 超过最大轮次
            popup = _get_popup_info()
            popup_text = popup.get("popupText", "")
            logger.warning(f"[提交] 超过最大处理轮次，仍有弹窗: {popup_text[:80]}")
            if popup.get("hasPopup"):
                _cancel_popup()
            return False, f"合同未签署：提交流程超过最大重试轮次（{(popup_text or '未知原因')[:100]}）"

        except Exception as e:
            error_msg = f"提交审批失败：{str(e)[:80]}"
            logger.error(f"[提交] 异常: {e}")
            return False, error_msg


    
    def click_new_order(self) -> bool:
        """
        检查当前页面是否已是新建合同表单页（含"技术合作商名称"），
        若不是（当前在列表页），则点击"增加"/"新增"/"新建"按钮进入表单。

        Returns:
            bool: 成功进入表单页返回 True
        """
        logger.info("=== 确认/进入新建合同表单 ===")
        try:
            self.page.wait_for_timeout(1000)

            # 先检查是否在提交成功后的自动跳转页面，如果是则先处理跳转
            if self._is_on_redirect_page():
                logger.info("[新增] 当前在提交成功后的跳转页面，先返回列表...")
                self._handle_redirect_page()
                self.page.wait_for_timeout(2000)

            # 检查是否已在表单页（有"技术合作商名称"或"保存并提交审批"按钮）
            # 同时验证存在可编辑的文本输入框（排除跳转后的只读/hidden状态）
            already_on_form = self.page.evaluate("""() => {
                function isVisible(el) {
                    if (!el) return false;
                    var s = window.getComputedStyle(el);
                    var r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                }
                // 判断是否在表单页
                var hasVendorLabel = Array.from(document.querySelectorAll('*'))
                    .filter(isVisible)
                    .some(function(el) {
                        return el.childNodes.length <= 3
                            && (el.textContent || '').trim().replace(/\\s+/g,'').replace(/[：:]/g,'') === '技术合作商名称';
                    });
                var hasSubmitBtn = Array.from(document.querySelectorAll('a,button'))
                    .filter(isVisible)
                    .some(function(el) {
                        var text = (el.textContent || '').trim();
                        return text === '保存并提交审批' || text === '保存及提交审批';
                    });

                // 关键校验：必须有可编辑的文本输入框（排除 hidden/readonly）
                // 跳转后页面可能有标签但所有 input 都是 hidden 或 readonly
                var hasEditableInput = Array.from(document.querySelectorAll('input')).some(function(inp) {
                    if (!isVisible(inp)) return false;
                    if (inp.type === 'hidden' || inp.type === 'submit' || inp.type === 'button') return false;
                    if (inp.readOnly || inp.disabled) return false;
                    return true;
                });

                return (hasVendorLabel || hasSubmitBtn) && hasEditableInput;
            }""")

            if already_on_form:
                logger.info("[新增] 当前已是合同表单页，直接操作")
                return True

            # 不在表单页，需要点击"增加"/"新增"/"新建"按钮
            js_click = self.page.evaluate("""() => {
                function isVisible(el) {
                    var s = window.getComputedStyle(el);
                    var r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                }
                var keywords = ['增加', '新增', '新建', 'Add', 'New'];
                var els = Array.from(document.querySelectorAll('a,button,input[type=button],input[type=submit]'))
                    .filter(isVisible);
                for (var i = 0; i < els.length; i++) {
                    var text = (els[i].textContent || els[i].value || '').trim();
                    for (var k = 0; k < keywords.length; k++) {
                        if (text === keywords[k] || text.startsWith(keywords[k])) {
                            els[i].click();
                            return { found: true, text: text };
                        }
                    }
                }
                return { found: false };
            }""")

            if js_click.get("found"):
                logger.info(f"[新增] 点击按钮「{js_click.get('text')}」，等待表单加载...")
                self.page.wait_for_timeout(2500)
                return True

            # 还是找不到，打印页面所有按钮供调试
            all_btns = self.page.evaluate("""() => {
                function isVisible(el) {
                    var s = window.getComputedStyle(el);
                    var r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                }
                return Array.from(document.querySelectorAll('a,button')).filter(isVisible)
                    .map(function(el){ return (el.textContent||'').trim().substring(0,20)+' | '+(el.className||'').substring(0,30); })
                    .slice(0, 20);
            }""")

            # 兜底：尝试通过点击"外包合同"菜单项重新导航到列表页
            logger.warning(f"[新增] 未找到入口按钮（页面按钮: {all_btns}），尝试重新导航...")
            nav_attempted = self.page.evaluate("""() => {
                function isVisible(el) {
                    var s = window.getComputedStyle(el);
                    var r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                }
                // 查找左侧菜单中的"外包合同"
                var items = Array.from(document.querySelectorAll('.mini-tree-nodetext,.mini-tree-node')).filter(isVisible);
                for (var i = 0; i < items.length; i++) {
                    var t = (items[i].textContent || '').trim();
                    if (t === '外包合同' || t.indexOf('外包合同') >= 0) {
                        items[i].click();
                        return true;
                    }
                }
                return false;
            }""")
            if nav_attempted:
                logger.info("[新增] 已点击外包合同菜单，等待页面加载...")
                self.page.wait_for_timeout(4000)
                # 递归调用自身再试一次
                return self.click_new_order()

            logger.error(f"[新增] 未找到入口按钮且无法重新导航，页面按钮: {all_btns}")
            return False

        except Exception as e:
            logger.error(f"[新增] 异常: {e}")
            return False

    def _is_on_redirect_page(self) -> bool:
        """检测当前是否在提交成功后的自动跳转倒计时页面"""
        result = self.page.evaluate("""() => {
            function isVisible(el) {
                var s = window.getComputedStyle(el);
                var r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            }
            var btns = Array.from(document.querySelectorAll('a,button')).filter(isVisible);
            var texts = btns.map(function(b){ return (b.textContent||'').trim(); });
            // 成功提交后通常有"点击取消自动跳转"/"点击跳转"等按钮
            return texts.some(function(t){ 
                return t.indexOf('取消自动跳转') >= 0 || t === '点击跳转' || t.indexOf('即将跳转') >= 0;
            });
        }""")
        return bool(result)

    def _handle_redirect_page(self) -> None:
        """处理提交成功后的自动跳转页面：点击'跳转'或等待跳转"""
        logger.info("[跳转页] 检测到提交成功后的跳转页面，处理中...")
        # 尝试点击"跳转"链接立即跳转到列表页
        clicked = self.page.evaluate("""() => {
            function isVisible(el) {
                var s = window.getComputedStyle(el);
                var r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            }
            var btns = Array.from(document.querySelectorAll('a,button,span')).filter(isVisible);
            // 优先点"点击跳转"
            for (var i = 0; i < btns.length; i++) {
                var t = (btns[i].textContent||'').trim();
                if (t === '点击跳转' || t.indexOf('跳转') >= 0) { btns[i].click(); return true; }
            }
            return false;
        }""")
        if clicked:
            logger.info("[跳转页] 已点击'跳转'按钮")
            self.page.wait_for_timeout(3000)
        else:
            logger.info("[跳转页] 未找到跳转按钮，等待自动跳转...")
            self.page.wait_for_timeout(5000)

    def _relocate_contract_context(self, nav_page) -> None:
        """
        导航到外包合同后，重新定位合同页面的上下文（iframe/标签页）并更新 self.page。
        
        这一步至关重要！导航后页面上下文会变：
        - 可能打开新标签页（Playwright context.pages 会多一个）
        - 可能在原页面内刷新了 iframe
        如果不更新 self.page，后续操作（click_new_order、select_vendor 等）会在旧页面上执行导致失败
        """
        candidates = []  # 收集候选上下文
        
        try:
            # 1. 检查是否有新标签页弹出
            all_pages = nav_page.context.pages
            if len(all_pages) > 1:
                # 找最新的非 root_page 的页面
                for p in reversed(all_pages):
                    if p != self.root_page and p != nav_page:
                        logger.info(f"[导航-定位] 发现新标签页: {p.url}")
                        p.wait_for_load_state("domcontentloaded")
                        p.wait_for_timeout(2000)
                        # 在新标签页里找合同 iframe
                        contract_ctx = self._find_contract_frame_in_page(p)
                        candidates.append((p, contract_ctx or p))
            
            # 2. 在原 nav_page 上找所有可能的 iframe
            for frame in nav_page.frames:
                url = frame.url or ''
                if url and 'about:blank' not in url and frame != nav_page.main_frame:
                    candidates.append((nav_page, frame))
            
            # 3. 把 nav_page 自身也作为候选
            candidates.append((nav_page, nav_page))
            
            # === 验证每个候选上下文是否真的有"新增"按钮（列表页特征）===
            for parent_page, ctx in candidates:
                try:
                    btn_check = ctx.evaluate("""() => {
                        function isVisible(el) {
                            var s = window.getComputedStyle(el);
                            var r = el.getBoundingClientRect();
                            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                        }
                        var btns = Array.from(document.querySelectorAll('a,.mini-button')).filter(isVisible);
                        return {
                            count: btns.length,
                            texts: btns.slice(0, 10).map(function(b) { return (b.textContent||b.value||'').trim().substring(0,20); }),
                            hasNewBtn: btns.some(function(b) { 
                                var t = (b.textContent||b.value||'').trim(); 
                                return t.indexOf('新增') >= 0 || t === '+' || b.id.indexOf('add') >= 0; 
                            })
                        };
                    }""")
                    has_new = btn_check.get('hasNewBtn', False)
                    btn_count = btn_check.get('count', 0)
                    
                    ctx_info = f"type={type(ctx).__name__}, url={getattr(ctx,'url','N/A')[:80]}"
                    logger.info(f"[导航-定位] 候选验证: {ctx_info} → buttons={btn_count}, hasNewBtn={has_new}")
                    
                    if has_new or btn_count >= 2:
                        self.page = ctx
                        logger.info(f"[导航-定位] ✅ 已切换到有效上下文（hasNew={has_new}）")
                        return
                        
                except Exception as ve:
                    logger.debug(f"[导航-定位] 候选验证异常: {ve}")
                    continue
            
            # 所有候选都没通过验证 → 用最后一个有按钮的
            for parent_page, ctx in candidates:
                try:
                    btn_count = ctx.evaluate("""() => {
                        return document.querySelectorAll('a,button').length;
                    }""")
                    if btn_count and btn_count > 0:
                        self.page = ctx
                        logger.warning(f"[导航-定位] ⚠️ 未找到理想上下文，使用最后可用的（buttons={btn_count}）")
                        return
                except:
                    continue
            
            # 最终兜底
            self.page = nav_page
            logger.warning("[导航-定位] ⚠️ 所有候选均无效，使用根页面")
            
        except Exception as e:
            logger.warning(f"[导航-定位] 重定位异常: {e}，保持原 page 不变")

    def _find_contract_frame_in_page(self, page) -> Optional['Frame']:
        """在指定页面中查找外包合同相关的 iframe"""
        for frame in page.frames:
            url = frame.url or ''
            # 合同相关 URL 关键字
            if any(kw in url.lower() for kw in ['contract', 'orderapply', 'directorder']):
                return frame
        
        # 备用：找非主框架且非 about:blank 的最后一个 frame
        non_main_frames = [f for f in page.frames 
                          if f != page.main_frame 
                          and f.url 
                          and 'about:blank' not in f.url]
        if non_main_frames:
            return non_main_frames[-1]
        
        return None

    def go_back_to_list(self) -> None:
        """
        提交完成后重新导航到外包合同列表页（跟人工操作一致）。
        
        不再处理各种异常状态（跳转倒计时、返回按钮等），
        而是直接点左侧菜单「外包合同」重新导航，干净可靠。
        """
        logger.info("=== 返回列表页（重新导航到外包合同） ===")
        self._clear_current_form()
        
        # ★ 主动清理：移除合同页面区域的所有旧 iframe，防止下一个合作商误命中残留数据
        # （换合作商时 iframe 同名但不销毁，旧合作商的人员表格 frame 会残留）
        _nav_page = self.root_page if self.root_page else self.page
        try:
            removed = _nav_page.evaluate("""() => {
                var count = 0;
                // 移除主内容区域的所有 iframe（合同列表/表单都在 iframe 中）
                var iframes = document.querySelectorAll('iframe');
                iframes.forEach(function(iframe) {
                    try {
                        iframe.remove();
                        count++;
                    } catch(e) {}
                });
                // 同时清理 MiniUI 可能持有的 window 引用
                if (typeof mini !== 'undefined') {
                    try {
                        var panels = document.querySelectorAll('.mini-panel,.mini-tabs-body,.mini-fit');
                        panels.forEach(function(panel) {
                            var innerFrames = panel.querySelectorAll('iframe');
                            innerFrames.forEach(function(f) { 
                                try { f.remove(); count++; } catch(e) {}
                            });
                        });
                    } catch(e) {}
                }
                return count;
            }""")
            if removed > 0:
                logger.info(f"[清理] 已移除 {removed} 个旧 iframe，页面已清空")
            else:
                logger.info("[清理] 未发现旧 iframe（页面已是干净状态）")
        except Exception as e:
            logger.warning(f"[清理] iframe 清理异常（不影响后续流程）: {e}")
        
        # 等待清理后 DOM 稳定
        _nav_page.wait_for_timeout(1000)
        
        try:
            # 方式1：通过左侧 MiniUI 树形菜单点击"外包合同"
            nav_result = _nav_page.evaluate("""() => {
                try {
                    var nodes = document.querySelectorAll('.mini-tree-nodetext');
                    for (var i = 0; i < nodes.length; i++) {
                        var t = (nodes[i].textContent || '').trim();
                        if (t === '外包合同' || t.indexOf('外包合同') >= 0) {
                            nodes[i].click();
                            return { ok: true, method: 'menu-click' };
                        }
                    }
                    return { ok: false, error: '未找到外包合同菜单项' };
                } catch(e) {
                    return { ok: false, error: e.message || String(e) };
                }
            }""")
            
            if nav_result.get("ok"):
                logger.info(f"[导航] 已点击外包合同菜单，等待页面加载...")
                # 点击后等待页面刷新（可能是原地加载或打开新标签）
                _nav_page.wait_for_timeout(4000)
                
                # === 关键：重新定位合同页面的上下文并更新 self.page ===
                # 导航后页面可能变了（新标签/新iframe），self.page 必须更新
                # 否则下一条记录的 click_new_order 等操作会在旧的失效上下文上执行
                self._relocate_contract_context(_nav_page)
                
                logger.info("[导航] ✅ 已回到外包合同列表页")
                return
            
            logger.warning(f"[导航] 菜单点击失败: {nav_result.get('error')}，尝试备用方案...")
            
        except Exception as e:
            logger.warning(f"[导航] 异常: {e}")
        
        # 备用方式：用 JS 直接展开树 + 点击（同样在 root_page 上操作）
        try:
            _nav_page.evaluate("""
                var tree = mini && mini.get('tree1');
                if (tree) {
                    var nodes = tree.getData();
                    for (var i = 0; i < nodes.length; i++) {
                        if (nodes[i].text && nodes[i].text.indexOf('外包申请') >= 0) {
                            tree.expandNode(nodes[i]);
                        }
                        if (nodes[i].text && nodes[i].text.indexOf('外包合同') >= 0) {
                            tree.selectNode(nodes[i]);
                            break;
                        }
                    }
                }
            """)
            _nav_page.wait_for_timeout(4000)
            self._relocate_contract_context(_nav_page)
            logger.info("[导航] ✅ 备用方案成功：MiniUI树操作已执行")
        except Exception as e2:
            logger.warning(f"[导航] 备用方案也失败: {e2}，下一条处理可能会受影响")

    def process_single_order(self, vendor_name: str, app_no: str, 
                             work_location: str, not_renewing_df: Optional['pd.DataFrame'] = None) -> Tuple[bool, str]:
        """
        处理单条订单的完整流程

        流程：
        0. 点击"新增"按钮，进入新建合同表单
        1. 选择技术合作商
        2. 搜索申请单（人员数据此时已渲染）
        3. 填充工作地点（从人员表第一条记录读取，在删除人员之前执行）
        4. 删除不续签人员（可选，必须在搜索申请单后、计算成本前执行）
        5. 计算成本（若删除了人员，需重新计算）
        6. 验证金额
        7. 提交审批
        8. 返回列表页（为下一条做准备）
        
        Args:
            vendor_name: 技术合作商名称
            app_no: 合作申请单编号
            work_location: 工作地点
            not_renewing_df: 离岗不续签清单数据框（用于人员比对和删除）
            
        Returns:
            Tuple[bool, str]: (是否成功, 反馈文本)
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"处理订单: {vendor_name} | {app_no}")
        logger.info(f"{'='*60}")
        
        try:
            self._clear_current_form()

            # 0. 点击"新增"，进入新建合同表单
            if not self.click_new_order():
                return False, "新增失败：未找到新增按钮，请确认当前页面为外包合同列表页"

            # 1. 选择技术合作商
            if not self.select_vendor(vendor_name):
                return False, f"技术合作商选择失败: {vendor_name}"
            
            # 2. 搜索申请单
            if not self.search_application(app_no):
                return False, f"申请单搜索失败: {app_no}"
            
            # 3. 填充工作地点（直接使用Excel传入值）
            if work_location:
                if not self.fill_work_location(work_location):
                    return False, f"工作地点填充失败: {work_location}"
            else:
                logger.warning("[工作地点] work_location 为空，跳过填充")
            
            # 4. 删除不续签人员（申请单搜索成功后人员数据已渲染，在计算成本前执行）
            deleted_count = 0
            deleted_ids = []
            if not_renewing_df is not None and len(not_renewing_df) > 0:
                id_card_col = None
                for col_name in ["身份证", "身份证号", "idCard", "证件号", "ID"]:
                    if col_name in not_renewing_df.columns:
                        id_card_col = col_name
                        break
                
                if id_card_col:
                    id_card_list = not_renewing_df[id_card_col].dropna().astype(str).tolist()
                    deleted_count, deleted_ids = self.delete_personnel_by_id_card(id_card_list)
                    if deleted_count > 0:
                        logger.info(f"[人员删除] 成功删除 {deleted_count} 条不续签人员记录")
                else:
                    logger.warning("[人员删除] 离岗清单中未找到身份证列，跳过人员删除")
            
            # 5. 计算成本
            #    - 出现弹窗（任何内容）→ 合同未签署 + 弹窗内容，浏览器后退
            #    - 若已删除人员，成本会自动反映最新人员数量
            cost_ok, cost_msg = self.calculate_cost()
            if not cost_ok:
                self.go_back_to_list()
                return False, f"合同未签署：{cost_msg}"

            # 6. 验证金额
            #    - 金额为空或为0 → 合同未签署，浏览器后退
            if not self.verify_order_amount():
                self.go_back_to_list()
                return False, "合同未签署：技术合作订单金额为空或为0，请手动检查"

            
            # 7. 提交审批（返回 (bool, 反馈文本)）

            submit_ok, submit_msg = self.submit_for_approval()

            # 8. 无论成功失败，返回列表页（为下一条记录做准备）
            self.go_back_to_list()

            if not submit_ok:
                return False, submit_msg
            
            # 构造最终反馈
            final_msg = submit_msg

            if deleted_count > 0 and deleted_ids:
                # 通过身份证号从离岗清单反查姓名
                deleted_names = []
                if id_card_col and not_renewing_df is not None:
                    name_col = None
                    for col_name in ["技术合作人员", "姓名", "人员姓名", "name"]:
                        if col_name in not_renewing_df.columns:
                            name_col = col_name
                            break
                    if name_col:
                        id_to_name = dict(zip(
                            not_renewing_df[id_card_col].astype(str),
                            not_renewing_df[name_col].astype(str)
                        ))
                        deleted_names = [id_to_name.get(did, did) for did in deleted_ids]
                if not deleted_names:
                    deleted_names = deleted_ids
                names_str = "、".join(deleted_names)
                final_msg += f"（已删除 {deleted_count} 条不续签人员：{names_str}）"
            
            logger.info(f"反馈: {final_msg}")
            return True, final_msg
            
        except Exception as e:
            error_msg = f"异常：{str(e)[:80]}"
            logger.error(error_msg)
            return False, error_msg


def main():
    """测试脚本"""
    print("OutsourceContractSubmitter 模块加载成功")


if __name__ == "__main__":
    main()
