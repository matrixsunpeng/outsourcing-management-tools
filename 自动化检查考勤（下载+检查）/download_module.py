"""
数据下载模块 - Playwright 自动化
从 IMS 系统 (https://ims.asiainfo.com) 自动下载:
  1. 工时详细查询（每个供应商3批）
  2. 在岗人员清单
  3. 计提报表

依赖安装: pip install playwright && playwright install chromium
参考: 外包工具箱 common/base_downloader.py 的模式
"""
import os
import re
import time
import calendar
import threading
import traceback
from pathlib import Path
from typing import Optional, List, Callable

from playwright.sync_api import sync_playwright, Page, Browser, Playwright, Frame, Download


LOGIN_URL = "https://ims.asiainfo.com/AIOMS/Jsp/main.jsp"

DEFAULT_SELECTORS = {
    "username_input": "input[name='username'], input[id='username'], input[type='text']",
    "password_input": "input[name='password'], input[id='password'], input[type='password']",
    "login_button": "button[type='submit'], input[type='submit'], button:has-text('登录'), input[value*='登录']",
}


# ===== 工具函数 =====
def get_month_start_end(year_month_str):
    """将 202602 转为 ('2026-02-01', '2026-02-28')"""
    year = int(year_month_str[:4])
    month = int(year_month_str[4:6])
    last_day = calendar.monthrange(year, month)[1]
    return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day:02d}"


def get_period_pattern(year_month_str):
    """生成月份模糊匹配关键字，如 '202602' 用于匹配下拉选项中的 '202602P1'"""
    return year_month_str


# ===== 主下载类 =====
class IMSDataDownloader:
    """IMS系统数据自动下载器（Playwright版）"""

    def __init__(self, download_dir: str, log_func: Optional[Callable] = None,
                 stop_event: Optional[threading.Event] = None):
        self.download_dir = os.path.abspath(download_dir)
        self.log_func = log_func
        self.stop_event = stop_event
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        # 用于多页面/iframe导航
        self._query_target = None
        self._query_is_tab = False
        os.makedirs(self.download_dir, exist_ok=True)

    def log(self, msg: str):
        if self.log_func:
            self.log_func(msg)
        else:
            print(msg)

    def _check_stop(self):
        """检查是否需要停止，是则抛出异常中断执行"""
        if self.stop_event and self.stop_event.is_set():
            self.log("[中断] 用户请求停止，正在退出...")
            raise InterruptedError("用户停止操作")

    # ==================== 浏览器生命周期 ====================

    def start(self):
        """启动浏览器"""
        self.log("[初始化] 正在启动 Chromium 浏览器...")
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=False,
        )
        # 注意：不传 downloads_path，使用 accept_downloads + download.save_as()
        context = self._browser.new_context(accept_downloads=True)
        self._page = context.new_page()
        self.log("[初始化] 浏览器已启动")

    def quit(self):
        """关闭浏览器"""
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._browser = None
        self._page = None
        self._query_target = None
        self.log("[完成] 浏览器已关闭")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.quit()

    def _screenshot_on_error(self, name: str = "error"):
        """异常时截图"""
        try:
            path = os.path.join(self.download_dir, f"debug_{name}.png")
            if self._page:
                self._page.screenshot(path=path)
                self.log(f"[截图] 已保存错误截图: {path}")
        except Exception:
            pass

    # ==================== 登录 ====================

    def login(self, username: str, password: str) -> bool:
        """登录 IMS 系统"""
        self.log(f"[登录] 正在访问 {LOGIN_URL}")
        self._page.goto(LOGIN_URL, wait_until="networkidle")
        self._page.wait_for_timeout(2000)

        self.log("[登录] 正在输入账号密码...")
        # 用户名
        username_input = self._page.locator(DEFAULT_SELECTORS["username_input"]).first
        username_input.fill(username)
        self.log(f"[登录] 已输入用户名: {username}")

        # 密码
        password_input = self._page.locator(DEFAULT_SELECTORS["password_input"]).first
        password_input.fill(password)
        self.log("[登录] 已输入密码")

        # 提交
        login_button = self._page.locator(DEFAULT_SELECTORS["login_button"]).first
        login_button.click()
        self.log("[登录] 已点击登录按钮")

        # 等待登录完成
        self._page.wait_for_timeout(3000)
        # 如果登录后是 SSO 二次跳转，等待更久
        for _ in range(3):
            current_url = self._page.url
            if "main" in current_url or "home" in current_url:
                self.log("[登录] 登录成功")
                return True
            self._page.wait_for_timeout(2000)
        self.log("[登录] 登录状态未确认，继续尝试...")
        return True

    # ==================== 菜单导航（参考 BaseDownloader） ====================

    def _expand_menu_parent(self, parent_name: str):
        """双击左侧树父菜单展开，带 JS 回退"""
        try:
            self._page.locator(
                f".mini-tree-nodetext:has-text('{parent_name}')"
            ).first.dblclick()
            self.log(f"  已双击展开【{parent_name}】")
            self._page.wait_for_timeout(2000)
        except Exception as e:
            self.log(f"  双击菜单失败: {e}，尝试 JS 展开...")
            try:
                self._page.evaluate(f"""
                    var tree = mini.get("tree1");
                    if (tree) {{
                        var nodes = tree.getData();
                        for (var i = 0; i < nodes.length; i++) {{
                            if (nodes[i].text == '{parent_name}') {{
                                tree.expandNode(nodes[i]);
                                break;
                            }}
                        }}
                    }}
                """)
                self.log(f"  通过JS展开了【{parent_name}】")
                self._page.wait_for_timeout(2000)
            except Exception as e2:
                self.log(f"  JS展开也失败: {e2}")

    def _click_menu_child(self, child_name: str, frame_keywords: List[str] = None):
        """
        单击子菜单，返回目标（Page 或 Frame）。
        先尝试新标签页，超时后回退 iframe 扫描。
        """
        frame_keywords = frame_keywords or []
        self.log(f"  正在点击【{child_name}】...")

        # 先尝试新标签页
        target = None
        try:
            with self._page.context.expect_page(timeout=5000) as new_page_info:
                self._page.locator(
                    f".mini-tree-nodetext:has-text('{child_name}')"
                ).first.click()
                self.log(f"  已单击【{child_name}】")
            target = new_page_info.value
            target.wait_for_load_state("domcontentloaded")
            target.wait_for_timeout(3000)
            self._query_is_tab = True
            self.log(f"  页面已在新标签页打开: {target.url[:80]}")
            self._query_target = target
            return target
        except Exception:
            self.log("  未检测到新标签页，尝试查找 iframe...")

        # 回退 iframe
        self._query_is_tab = False
        self._page.wait_for_timeout(3000)

        target = self._find_target_frame(frame_keywords)
        if not target:
            self._page.wait_for_timeout(3000)
            target = self._find_target_frame(frame_keywords)
        if not target:
            # 兜底：取最后一个非主 frame
            target = self._fallback_frame()

        target.wait_for_load_state("domcontentloaded")
        self._page.wait_for_timeout(2000)
        self.log(f"  已定位到 iframe: {target.url[:80]}")
        self._query_target = target
        return target

    def _find_target_frame(self, keywords: List[str]) -> Optional[Frame]:
        """按 URL 关键词匹配 iframe"""
        for frame in self._page.frames:
            url = frame.url
            if frame == self._page.main_frame or not url or "about:blank" in url:
                continue
            for kw in keywords:
                if kw.lower() in url.lower():
                    self.log(f"  找到匹配iframe [{kw}]: {url[:80]}")
                    return frame
        return None

    def _fallback_frame(self) -> Frame:
        """兜底：取最后一个非主 frame"""
        non_main = [f for f in self._page.frames
                    if f != self._page.main_frame and f.url and "about:blank" not in f.url]
        if non_main:
            frame = non_main[-1]
            self.log(f"  使用兜底 frame: {frame.url[:80]}")
            return frame
        raise Exception("未找到任何可用 iframe")

    def _get_active_target(self):
        """获取当前活动的目标（Page 或 Frame）"""
        if self._query_is_tab and self._query_target:
            return self._query_target
        if not self._query_is_tab and self._query_target:
            return self._query_target
        return self._page

    def _next_supplier_reset(self):
        """多供应商循环中，完成一条后重置页面"""
        self._page.wait_for_timeout(1000)
        if self._query_is_tab and self._query_target:
            try:
                self._query_target.close()
            except Exception:
                pass
            self._query_target = None
            self._query_is_tab = False
        else:
            try:
                # 切回主页面
                self._page.reload()
                self._page.wait_for_load_state("domcontentloaded")
                self._page.wait_for_timeout(3000)
            except Exception:
                pass

    # ==================== MiniUI 控件操作 ====================

    def _select_miniui_combobox(self, target, control_id: str,
                                target_value: str) -> bool:
        """
        MiniUI combobox 单选（JS API 模糊匹配）。
        参考: 外包工具箱 BaseDownloader._select_miniui_combobox()
        """
        self.log(f"  选择combobox [{control_id}]: {target_value}")

        try:
            # 步骤1：等待数据加载
            target.evaluate(f"""(controlId) => {{
                var combo = mini.get(controlId);
                if (!combo) return;
                var data = combo.data || [];
                data = data.filter(function(d) {{ return !d.__NullItem; }});
                if (data.length === 0) combo.load();
            }}""", control_id)
            self._page.wait_for_timeout(2000)

            # 步骤2：模糊匹配并选择
            result = target.evaluate("""(args) => {
                var combo = mini.get(args.controlId);
                if (!combo) return {success: false, error: '控件不存在'};
                var data = (combo.data || []).filter(function(d) { return !d.__NullItem; });
                if (data.length === 0) return {success: false, error: '数据为空'};
                var matched = null;
                for (var i = 0; i < data.length; i++) {
                    var keys = Object.keys(data[i]);
                    for (var k = 0; k < keys.length; k++) {
                        var val = String(data[i][keys[k]] || '');
                        if (val && val.length > 1 && val.length < 100 && !/^[\\d.]+$/.test(val)) {
                            if (val === args.targetValue || val.endsWith(args.targetValue)) {
                                matched = data[i]; break;
                            }
                        }
                    }
                    if (matched) break;
                }
                if (!matched) return {success: false, error: '未匹配到选项'};
                var val = matched.flexValue || matched.id || matched.value || '';
                combo.setValue(val);
                return {success: true};
            }""", {"controlId": control_id, "targetValue": target_value})

            if result.get("success"):
                self.log(f"  ✓ 已选择 [{control_id}]: {target_value}")
                self._page.wait_for_timeout(500)
                return True
            else:
                self.log(f"  ⚠ [{control_id}] {result.get('error')}")
                return False
        except Exception as e:
            self.log(f"  ✗ 选择 [{control_id}] 失败: {e}")
            return False

    def _click_miniui_combobox_and_select(self, target, control_id: str,
                                          match_text: str,
                                          fallback_index: int = 0) -> bool:
        """
        MiniUI buttonedit 类型 combobox：click→等下拉→文本匹配点击。
        参考: 外包工具箱 application_form_downloader._select_combobox_by_click()
        """
        self.log(f"  点击combobox [{control_id}] 选择: {match_text}")

        try:
            # 点击 buttonedit 按钮打开下拉
            btn = target.locator(
                f"#{control_id}\\$button, #{control_id} .mini-buttonedit-button"
            ).first
            if btn.count() == 0:
                btn = target.locator(f"#{control_id}\\$text").first
            btn.click()
            self._page.wait_for_timeout(800)

            # 等待下拉列表出现
            target.wait_for_selector(".mini-listbox-item, .mini-listbox td", timeout=5000)
            self._page.wait_for_timeout(500)

            # 文本匹配
            cell = target.locator(
                f".mini-listbox:visible td:has-text('{match_text}')"
            ).first
            if cell.count() > 0:
                cell.click()
                self.log(f"  ✓ 已选择: {match_text}")
                self._page.wait_for_timeout(500)
                return True

            # 滚动查找
            listbox = target.locator(".mini-listbox:visible").first
            if listbox.count() > 0:
                for i in range(20):
                    listbox.evaluate("el => el.scrollTop += 50")
                    self._page.wait_for_timeout(200)
                    cell = target.locator(
                        f".mini-listbox:visible td:has-text('{match_text}')"
                    ).first
                    if cell.count() > 0:
                        cell.click()
                        self.log(f"  ✓ 滚动{i+1}次后选择: {match_text}")
                        self._page.wait_for_timeout(500)
                        return True

            # 按索引选择
            if fallback_index is not None:
                items = target.locator(
                    ".mini-listbox-item, .mini-listbox:visible tr"
                ).all()
                valid = [it for it in items if it.is_visible()]
                if len(valid) > fallback_index:
                    valid[fallback_index].click()
                    self.log(f"  ✓ 按索引{fallback_index}选择")
                    self._page.wait_for_timeout(500)
                    return True

            self.log(f"  ⚠ 未找到选项: {match_text}")
            self._page.keyboard.press("Escape")
            return False
        except Exception as e:
            self.log(f"  ✗ 选择 [{control_id}] 失败: {e}")
            try:
                self._page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    def _input_miniui_date(self, target, beg_id: str, end_id: str,
                           start_str: str, end_str: str) -> bool:
        """MiniUI 日期控件输入"""
        self.log(f"  设置日期: {start_str} ~ {end_str}")
        try:
            target.evaluate(f"""(args) => {{
                var beg = mini.get('{beg_id}');
                var end = mini.get('{end_id}');
                if (beg) beg.setValue(args.beg);
                if (end) end.setValue(args.end);
            }}""", {"beg": start_str, "end": end_str})
            self._page.wait_for_timeout(500)
            return True
        except Exception as e:
            self.log(f"  ✗ 日期输入失败: {e}")
            return False

    def _close_miniui_popups(self, target):
        """关闭所有 MiniUI 弹窗和模态遮罩（增强版）"""
        try:
            # JS 方式：隐藏 modal + 调用 MiniUI API
            target.evaluate("""() => {
                // 1. 隐藏所有 modal 和 window
                var modals = document.querySelectorAll('.mini-modal, .mini-window, .mini-popup');
                for (var i = 0; i < modals.length; i++) {
                    modals[i].style.display = 'none';
                    // 也尝试移除
                    if (modals[i].parentNode) {
                        try { modals[i].parentNode.removeChild(modals[i]); } catch(e) {}
                    }
                }

                // 2. MiniUI API 关闭
                try {
                    if (typeof mini !== 'undefined' && mini.gets) {
                        var wins = mini.gets();
                        for (var j = 0; j < wins.length; j++) {
                            try {
                                if (wins[j] && typeof wins[j].destroy === 'function') wins[j].destroy();
                                else if (wins[j] && typeof wins[j].close === 'function') wins[j].close();
                                else if (wins[j] && typeof wins[j].hide === 'function') wins[j].hide();
                            } catch(e2) {}
                        }
                    }
                } catch(e) {}

                // 3. 清理 body 上的遮罩 class
                try { document.body.classList.remove('mini-modal-open'); } catch(e) {}
            }""")
            target.wait_for_timeout(500)

            # Playwright 方式：点击关闭按钮
            try:
                close_btn = target.locator(
                    ".mini-window:visible .mini-tools-close, "
                    ".mini-panel:visible .mini-tools-close, "
                    ".mini-modal:visible .mini-tools-close"
                ).first
                if close_btn.count() > 0:
                    close_btn.click()
                    target.wait_for_timeout(500)
            except Exception:
                pass

            # 按 Escape 关闭弹窗
            try:
                target.keyboard.press("Escape")
                target.wait_for_timeout(300)
            except Exception:
                pass
        except Exception:
            pass

    def _click_query_button(self, target):
        """查找并点击查询按钮"""
        query_selectors = [
            "a#Query",
            "a:has-text('查询')",
            "button:has-text('查询')",
            "input[value*='查询']",
            "span:has-text('查询')",
            "a.mini-button:has-text('查询')",
            "span.mini-button:has-text('查询')",
            ".mini-button:has-text('查询')",
            "a:has-text('查 询')",
            ".mini-toolbar a:has-text('查询')",
        ]
        for sel in query_selectors:
            try:
                el = target.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    el.click()
                    self.log("  已点击查询按钮")
                    target.wait_for_timeout(3000)
                    return True
            except Exception:
                continue

        # JS 回退：查找所有包含"查询"文本的可点击元素
        try:
            result = target.evaluate("""() => {
                var all = document.querySelectorAll('a, span, button, input, div[class*="btn"]');
                for (var i = 0; i < all.length; i++) {
                    var el = all[i];
                    if (el.offsetHeight === 0) continue;
                    var text = (el.textContent || el.value || '').trim();
                    if (text === '查询' || text === '查 询') {
                        el.click();
                        return true;
                    }
                }
                return false;
            }""")
            if result:
                self.log("  已点击查询按钮（JS）")
                target.wait_for_timeout(3000)
                return True
        except Exception:
            pass

        self.log("  ⚠ 未找到查询按钮，尝试跳过查询直接导出...")
        return False

    def _click_export_button(self, target, btn_text: str = "导出Excel") -> bool:
        """查找并点击导出按钮"""
        export_selectors = [
            f"a:has-text('{btn_text}')",
            f"button:has-text('{btn_text}')",
            f"span:has-text('{btn_text}')",
            "a:has-text('导出')",
            "button:has-text('导出')",
            "span:has-text('导出')",
        ]
        for sel in export_selectors:
            try:
                el = target.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    el.click()
                    self.log(f"  已点击导出按钮: {btn_text}")
                    self._page.wait_for_timeout(1000)
                    return True
            except Exception:
                continue
        self.log(f"  ⚠ 未找到导出按钮: {btn_text}")
        return False

    def _handle_export_confirm_popup(self):
        """
        处理导出确认弹窗（MiniUI messagebox / alert）。
        只处理 .mini-messagebox（确认对话框），不关闭 .mini-window（批次选择窗口）。
        """
        # 处理 MiniUI messagebox 中的确定按钮
        try:
            confirm_btn = self._page.locator(
                ".mini-messagebox:visible button:has-text('确定'), "
                ".mini-messagebox:visible a:has-text('确定'), "
                ".mini-messagebox:visible button:has-text('确认'), "
                ".mini-messagebox:visible a:has-text('确认'), "
                ".mini-messagebox:visible button:has-text('OK')"
            ).first
            if confirm_btn.count() > 0:
                confirm_btn.click()
                self.log("  已点击弹窗确认按钮")
                self._page.wait_for_timeout(1500)
                return True
        except Exception:
            pass

        # 处理浏览器原生 alert/confirm
        try:
            def accept_dialog(dialog):
                self.log(f"  处理浏览器弹窗: {dialog.message}")
                dialog.accept()
            self._page.on("dialog", accept_dialog)
            self._page.wait_for_timeout(500)
            self._page.remove_listener("dialog", accept_dialog)
        except Exception:
            pass
        return False

    # ==================== 下载核心逻辑 ====================

    def _wait_and_save_download(self, download_obj: Download, target_path: str):
        """等待下载完成并保存到指定路径"""
        try:
            # 等下载完成（Playwright 自动管理临时文件）
            download_obj.save_as(target_path)
            self.log(f"  ✓ 文件已保存: {os.path.basename(target_path)}")
            return True
        except Exception as e:
            self.log(f"  ✗ 下载保存失败: {e}")
            return False

    # ==================== 2.1 下载工时详细查询 ====================

    def download_workhours(self, month_str: str, supplier_list: List[str]):
        """
        下载工时详细查询数据。
        对每个供应商，分3批导出（1-10日、11-20日、21-31日）。
        """
        period_pattern = get_period_pattern(month_str)
        self.log(f"\n[工时详细查询] 开始下载，月份={month_str}，供应商数量={len(supplier_list)}")

        # 导航到 商务经理工时查询
        self.log("[工时详细查询] 导航到 考勤工时 > 商务经理工时查询...")
        self._page.wait_for_timeout(2000)
        self._expand_menu_parent("考勤工时")
        self._page.wait_for_timeout(1000)
        target = self._click_menu_child("商务经理工时查询",
                                        frame_keywords=["timeInfo_toQueryTime"])
        self._page.wait_for_timeout(3000)

        for supplier in supplier_list:
            self._check_stop()
            self.log(f"\n[工时详细查询] 正在处理供应商: {supplier}")

            # 重置状态（多供应商循环防污染）
            if supplier != supplier_list[0]:
                self._next_supplier_reset()
                # 重新导航
                self._expand_menu_parent("考勤工时")
                self._page.wait_for_timeout(1000)
                target = self._click_menu_child("商务经理工时查询",
                                                frame_keywords=["timeInfo_toQueryTime"])
                self._page.wait_for_timeout(2000)

            active = self._get_active_target()

            # 验证 active 是否有效，无效则重新获取
            try:
                active.wait_for_timeout(100)
            except Exception:
                self.log("  active target 失效，重新获取...")
                active = self._page
                # 尝试重新在 frames 中找
                for frame in self._page.frames:
                    if frame != self._page.main_frame and "timeInfo" in (frame.url or ""):
                        active = frame
                        self._query_target = frame
                        self._query_is_tab = False
                        self.log(f"  重新定位到 iframe: {frame.url[:80]}")
                        break

            # 设置工时期间
            self.log(f"  设置工时期间: {period_pattern}...")
            try:
                # 策略A: 查找页面上的 MiniUI combobox，按出现顺序取前两个
                combos = active.locator(".mini-combobox").all()
                if len(combos) >= 2:
                    self._select_combobox_by_scroll_click(
                        active, combos[0], period_pattern, "工时期间-起始")
                    self._page.wait_for_timeout(500)
                    self._select_combobox_by_scroll_click(
                        active, combos[1], period_pattern, "工时期间-结束")
                    self._page.wait_for_timeout(500)
                else:
                    # 策略B: 尝试用 JS API 设置已知ID
                    # （实际ID需要通过浏览器调试确定，这里尝试常见ID模式）
                    period_set = False
                    for pid_pattern in ["p_period", "period", "timePeriod",
                                       "p_time_start", "p_time_end"]:
                        try:
                            active.evaluate(f"""() => {{
                                var c = mini.get('{pid_pattern}');
                                if (c) c.setValue('{period_pattern}');
                            }}""")
                            period_set = True
                            break
                        except Exception:
                            continue
                    if period_set:
                        self.log(f"  通过JS API设置期间: {period_pattern}")
                    else:
                        self.log("  ⚠ 无法自动设置工时期间，尝试继续...")
            except Exception as e:
                self.log(f"  ⚠ 设置工时期间异常: {e}")

            # 设置技术合作商 + 触发查询（输入后回车）
            self.log(f"  设置技术合作商: {supplier}...")
            self._type_supplier_and_query(active, supplier)

            # 等待页面loading完成
            self._wait_for_loading(active, timeout=60)

            # 点击导出工时明细（在 iframe/main page 都可能）
            self.log("  点击导出工时明细...")
            self._click_export_workhour_button_new(active)

            # 等待批次导出表格出现
            # 表格可能在主页面或 iframe 内，两者都要搜
            self._page.wait_for_timeout(2000)
            self.log("  等待批次导出表格...")
            table_found = self._wait_for_batch_export_table(active, timeout=10)

            # 逐批导出（3批）
            batch_keywords = [
                ("第一批", "1日~10日"),
                ("第二批", "11日~20日"),
                ("第三批", "21日~31日"),
            ]
            for batch_idx, (batch_keyword, batch_desc) in enumerate(batch_keywords, 1):
                self._check_stop()
                self.log(f"  导出第{batch_idx}批 ({batch_desc})...")

                try:
                    # 步骤1: 在 td.tdHead 中找到批次日期标签，点击其下方对应的 <a> 导出按钮
                    batch_clicked = self._click_batch_export_link(batch_keyword, batch_desc)
                    if not batch_clicked:
                        self.log(f"    ⚠ 未找到第{batch_idx}批导出链接")
                        continue

                    # 步骤2: 等待确认弹窗"您确认导出excel吗？"
                    self.log("    等待确认弹窗...")
                    confirm_appeared = self._wait_for_confirm_export_dialog(timeout=5)
                    if confirm_appeared:
                        self.log("    ✓ 确认弹窗已出现")
                    else:
                        self.log("    ⚠ 确认弹窗未出现，尝试继续...")

                    # 步骤3: 点击"确定"触发下载
                    with self._page.expect_download(timeout=120000) as download_info:
                        self._click_confirm_ok_button()

                    download = download_info.value
                    file_name = f"{supplier}_工时详细查询{batch_idx}-3.xlsx"
                    file_path = os.path.join(self.download_dir, file_name)

                    if os.path.exists(file_path):
                        os.remove(file_path)

                    self._wait_and_save_download(download, file_path)
                    try:
                        download.delete()
                    except Exception:
                        pass

                    self.log(f"    ✓ 第{batch_idx}批下载完成")

                except Exception as e:
                    self.log(f"    ✗ 第{batch_idx}批下载失败: {e}")
                    self._screenshot_on_error(f"workhours_batch{batch_idx}")

                if batch_idx < 3:
                    self._page.wait_for_timeout(1000)

            # 三批全部完成，关闭批次导出弹窗 + 清理所有浮层
            self._close_miniui_popups(self._page)
            self._page.wait_for_timeout(1000)

            self.log(f"  供应商 {supplier} 工时详细查询下载完成")

        self.log("[工时详细查询] 全部下载完成")

    def _wait_for_batch_export_table(self, target=None, timeout: int = 10) -> bool:
        """
        等待批次导出表格出现。搜索所有 frames。
        """
        self.log(f"    等待批次导出表格（最多{timeout}秒）...")
        self._batch_table_scope = self._page
        start = time.time()
        while time.time() - start < timeout:
            self._check_stop()

            # 收集所有要搜索的范围：所有 frame
            scopes = [self._page]
            for frame in self._page.frames:
                if frame != self._page.main_frame:
                    scopes.append(frame)

            for scope in scopes:
                scope_name = "main" if scope == self._page.main_frame or scope == self._page else scope.url[:60]
                try:
                    table = scope.locator(
                        ".mini-window:visible table.tableMainEdit:has(td.tdHead), "
                        "div[class*='window']:visible table.tableMainEdit:has(td.tdHead), "
                        ".mini-popup:visible table.tableMainEdit:has(td.tdHead), "
                        "table.tableMainEdit:has(td.tdHead)"
                    ).first
                    if table.count() > 0 and table.is_visible():
                        self.log(f"    ✓ 批次导出表格已出现（{scope_name}）")
                        self._page.wait_for_timeout(1000)
                        self._debug_dump_batch_table(table)
                        self._batch_table_scope = scope
                        return True

                    # 回退：含 td.tdHead 的表格
                    table = scope.locator("table:has(td.tdHead)").first
                    if table.count() > 0 and table.is_visible():
                        self.log(f"    ✓ 批次导出表格已出现（{scope_name}, 回退）")
                        self._page.wait_for_timeout(1000)
                        self._debug_dump_batch_table(table)
                        self._batch_table_scope = scope
                        return True
                except Exception:
                    pass

            self._page.wait_for_timeout(500)

        self.log("    ⚠ 批次导出表格超时未出现")
        self._debug_scan_all_popups()
        return False

    def _debug_dump_batch_table(self, table):
        """输出批次导出表格的结构信息"""
        try:
            # 找所有 td.tdHead
            head_cells = table.locator("td.tdHead").all()
            self.log(f"    [调试] td.tdHead 数量: {len(head_cells)}")
            for i, cell in enumerate(head_cells):
                try:
                    text = (cell.inner_text() or "").strip()
                    self.log(f"    [调试]   tdHead[{i}]: {text[:120]}")
                except Exception:
                    pass

            # 找所有 <a> 链接
            links = table.locator("a").all()
            self.log(f"    [调试] <a> 链接数量: {len(links)}")
            for i, link in enumerate(links):
                try:
                    if not link.is_visible():
                        continue
                    text = (link.inner_text() or "").strip()
                    href = link.get_attribute("href") or ""
                    onclick = link.get_attribute("onclick") or ""
                    self.log(f"    [调试]   a[{i}]: text='{text[:80]}' href='{href[:80]}' onclick='{onclick[:80]}'")
                except Exception:
                    pass
        except Exception as e:
            self.log(f"    [调试] 表格分析失败: {e}")

    def _click_batch_export_link(self, batch_keyword: str, batch_desc: str) -> bool:
        """
        在 table.tableMainEdit 中找到批次对应的 <a> 导出链接并点击。
        同时搜索主页面 + iframe（_batch_table_scope）。
        """
        # 搜索所有 frames
        scopes = self._get_all_scopes()

        # 策略1: Playwright 定位 td.tdHead → 同行/后续行 <a>
        for search_scope in scopes:
            scope_name = "main" if search_scope == self._page else search_scope.url[:60]
            try:
                all_heads = search_scope.locator("td.tdHead").all()
                for head in all_heads:
                    try:
                        if not head.is_visible():
                            continue
                        head_text = (head.inner_text() or "").strip()
                        if batch_desc not in head_text and batch_keyword not in head_text:
                            continue

                        self.log(f"    找到 tdHead ({scope_name}): {head_text[:100]}")

                        # 方法A: 同tr或后续tr中找 <a>
                        row = head.locator("xpath=ancestor::tr").first
                        if row.count() > 0:
                            # 同 tr
                            link = row.locator("a").first
                            if link.count() > 0 and link.is_visible():
                                link.click()
                                self.log(f"    ✓ 已点击{batch_keyword}导出链接（同行, {scope_name}）")
                                return True

                            # 后续 tr
                            for offset in range(1, 7):
                                next_row = row.locator(f"xpath=following-sibling::tr[{offset}]").first
                                if next_row.count() > 0:
                                    link = next_row.locator("a").first
                                    if link.count() > 0 and link.is_visible():
                                        link.click()
                                        self.log(f"    ✓ 已点击{batch_keyword}导出链接（+{offset}行, {scope_name}）")
                                        return True
                                else:
                                    break

                        # 方法B: 在 table 内按 tdHead 索引
                        table = head.locator("xpath=ancestor::table").first
                        if table.count() > 0:
                            all_visible_heads = [h for h in all_heads if h.is_visible()]
                            links = table.locator("a").all()
                            visible_links = [l for l in links if l.is_visible()]
                            head_index = next((i for i, h in enumerate(all_visible_heads)
                                             if batch_desc in (h.inner_text() or "").strip()
                                             or batch_keyword in (h.inner_text() or "").strip()), -1)
                            if head_index >= 0 and head_index < len(visible_links):
                                visible_links[head_index].click()
                                self.log(f"    ✓ 已点击{batch_keyword}导出链接（排名{head_index}, {scope_name}）")
                                return True
                    except Exception:
                        continue
            except Exception:
                continue

        # 策略2: JS 在两个 scope 中搜索
        for search_scope in scopes:
            try:
                scope_name = "iframe" if search_scope != self._page else "主页面"
                result = search_scope.evaluate(f"""(args) => {{
                    var tables = document.querySelectorAll('table.tableMainEdit');
                    if (tables.length === 0) tables = document.querySelectorAll('table');

                    for (var t = 0; t < tables.length; t++) {{
                        var table = tables[t];
                        if (table.offsetHeight === 0) continue;
                        var heads = table.querySelectorAll('td.tdHead');
                        for (var h = 0; h < heads.length; h++) {{
                            var headText = (heads[h].textContent || '').trim();
                            if (headText.indexOf(args.desc) === -1 && headText.indexOf(args.kw) === -1) continue;

                        // 找到了对应的 tdHead
                        var row = head.closest('tr');
                        if (!row) continue;

                        // 找后续行中的 <a>
                        var next = row.nextElementSibling;
                        var maxDepth = 10;
                        while (next && maxDepth > 0) {{
                            var links = next.querySelectorAll('a');
                            for (var l = 0; l < links.length; l++) {{
                                if (links[l].offsetHeight > 0) {{
                                    links[l].click();
                                    return {{success: true, method: 'js-next-row', text: headText}};
                                }}
                            }}
                            next = next.nextElementSibling;
                            maxDepth--;
                        }}

                        // 如果找不到后续行的 <a>，尝试在同table内按索引
                        var allLinks = table.querySelectorAll('a');
                        var visibleLinks = [];
                        for (var a = 0; a < allLinks.length; a++) {{
                            if (allLinks[a].offsetHeight > 0) visibleLinks.push(allLinks[a]);
                        }}
                        // tdHead 索引对应链接索引
                        var allHeads = table.querySelectorAll('td.tdHead');
                        for (var hh = 0; hh < allHeads.length; hh++) {{
                            if (allHeads[hh] === head && hh < visibleLinks.length) {{
                                visibleLinks[hh].click();
                                return {{success: true, method: 'js-index', idx: hh}};
                            }}
                        }}
                    }}
                }}
                return {{success: false}};
            }}""", {"desc": batch_desc, "kw": batch_keyword})

                if result.get("success"):
                    self.log(f"    ✓ JS点击{batch_keyword}导出（方法: {result.get('method')}）")
                    return True
            except Exception as e:
                self.log(f"    策略2失败: {e}")

        # 策略3: 终极回退——在两个 scope 中收集所有 <a>，按索引点击
        batch_index_map = {"第一批": 0, "第二批": 1, "第三批": 2}
        idx = batch_index_map.get(batch_keyword)
        if idx is not None:
            for search_scope in scopes:
                try:
                    table = search_scope.locator("table.tableMainEdit").first
                    if table.count() == 0:
                        table = search_scope.locator("table:has(td.tdHead)").first
                    if table.count() > 0:
                        all_links = table.locator("a").all()
                        visible_links = [l for l in all_links if l.is_visible()]
                        export_links = []
                        for l in visible_links:
                            try:
                                text = (l.inner_text() or "").strip()
                                onclick = l.get_attribute("onclick") or ""
                                if "导出" in text or "export" in onclick.lower() or "download" in onclick.lower():
                                    export_links.append(l)
                            except Exception:
                                pass
                        if not export_links:
                            export_links = visible_links

                        self.log(f"    表格内找到 {len(export_links)} 个候选链接")
                        if idx < len(export_links):
                            export_links[idx].click()
                            self.log(f"    ✓ 按索引{idx}点击导出链接")
                            return True
                except Exception as e:
                    continue

        return False

    def _debug_dump_dialog_html(self):
        """调试用：将批次弹窗的 HTML 结构和可点击元素写入日志"""
        try:
            # 截图
            screenshot_path = os.path.join(self.download_dir, "debug_batch_dialog.png")
            self._page.screenshot(path=screenshot_path)
            self.log(f"    [调试] 弹窗截图已保存: {screenshot_path}")

            # dump 弹窗内所有包含"导出"的元素
            info = self._page.evaluate("""() => {
                var result = {windows: [], exportElements: []};

                // 找到所有可见 mini-window
                var wins = document.querySelectorAll('.mini-window');
                for (var w = 0; w < wins.length; w++) {
                    var win = wins[w];
                    if (win.style.display === 'none' || win.offsetHeight === 0) continue;
                    result.windows.push({
                        id: win.id || '(no id)',
                        className: win.className,
                        textPreview: (win.textContent || '').trim().substring(0, 300)
                    });
                }

                // 也检查 body 下的弹出层
                var popups = document.querySelectorAll('.mini-popup, .mini-panel, [class*="dialog"], [class*="window"]');
                for (var p = 0; p < popups.length; p++) {
                    var popup = popups[p];
                    if (popup.style.display === 'none' || popup.offsetHeight === 0) continue;
                    var text = (popup.textContent || '').trim();
                    if (text.indexOf('导出') !== -1 && text.indexOf('工时') !== -1) {
                        result.windows.push({
                            id: popup.id || '(no id)',
                            className: popup.className,
                            tagName: popup.tagName,
                            textPreview: text.substring(0, 500)
                        });
                    }
                }

                // 找到所有包含"导出"文本的可见元素
                var all = document.querySelectorAll('a, span, button, div, td');
                for (var i = 0; i < all.length; i++) {
                    var el = all[i];
                    if (el.offsetHeight === 0 || el.offsetWidth === 0) continue;
                    var text = (el.textContent || '').trim();
                    if (text.indexOf('导出') === -1) continue;
                    // 检查是否在可见弹窗内
                    var inWin = false;
                    var parent = el;
                    while (parent) {
                        if (parent.className && String(parent.className).indexOf('mini-window') !== -1) {
                            inWin = true; break;
                        }
                        if (parent.className && String(parent.className).indexOf('mini-popup') !== -1) {
                            inWin = true; break;
                        }
                        parent = parent.parentElement;
                    }
                    result.exportElements.push({
                        tag: el.tagName,
                        id: el.id || '',
                        className: String(el.className || '').substring(0, 80),
                        text: text.substring(0, 120),
                        inWindow: inWin,
                        href: el.href ? el.href.substring(0, 100) : ''
                    });
                }

                return result;
            }""")

            # 输出到日志
            self.log(f"    [调试] 可见弹窗数: {len(info.get('windows', []))}")
            for win in info.get('windows', []):
                self.log(f"    [调试]   弹窗: id={win.get('id')}, class={win.get('className','')}, tag={win.get('tagName','')}")
                self.log(f"    [调试]   内容预览: {win.get('textPreview','')[:200]}")

            export_els = info.get('exportElements', [])
            self.log(f"    [调试] 含'导出'文本的可见元素数: {len(export_els)}")
            for el in export_els:
                self.log(f"    [调试]   <{el['tag']}> id={el['id']} class={el['className']} inWin={el['inWindow']}")
                self.log(f"    [调试]   文本: {el['text']}")

        except Exception as e:
            self.log(f"    [调试] dump失败: {e}")

    def _debug_scan_all_popups(self):
        """
        全面扫描页面：截图 + 查找所有弹出层/弹窗 + 输出含'导出工时'关键字的元素。
        用于诊断导出按钮点击后弹窗是否出现。
        """
        try:
            # 截图
            path = os.path.join(self.download_dir, "debug_after_export_click.png")
            self._page.screenshot(path=path)
            self.log(f"  [扫描] 截图: {path}")

            # JS 全面扫描
            info = self._page.evaluate("""() => {
                var result = {
                    allPopups: [],
                    exportElements: [],
                    batchTexts: [],
                    bodyDialogs: []
                };

                // 1. 所有 position:fixed/absolute 且 z-index > 100 的可见元素（弹窗特征）
                var all = document.querySelectorAll('*');
                for (var i = 0; i < all.length; i++) {
                    var el = all[i];
                    if (el.offsetHeight === 0 || el.offsetWidth === 0) continue;
                    var style = window.getComputedStyle(el);
                    var zIndex = parseInt(style.zIndex) || 0;
                    var pos = style.position;
                    if ((pos === 'fixed' || pos === 'absolute') && zIndex > 100) {
                        var text = (el.textContent || '').trim();
                        if (text.length > 10 && text.length < 1000) {
                            result.allPopups.push({
                                tag: el.tagName,
                                id: el.id || '',
                                cls: String(el.className || '').substring(0, 100),
                                zIndex: zIndex,
                                text: text.substring(0, 200)
                            });
                        }
                    }
                }

                // 2. 包含'工时'和'导出'的元素
                for (var i = 0; i < all.length; i++) {
                    var el = all[i];
                    if (el.offsetHeight === 0 || el.offsetWidth === 0) continue;
                    var text = (el.textContent || '').trim();
                    if (text.indexOf('工时') !== -1 && text.indexOf('导出') !== -1) {
                        result.exportElements.push({
                            tag: el.tagName,
                            id: el.id || '',
                            cls: String(el.className || '').substring(0, 100),
                            text: text.substring(0, 200)
                        });
                    }
                    if (text.indexOf('此月工时') !== -1 || text.indexOf('第一批') !== -1 ||
                        text.indexOf('1日~10日') !== -1 || text.indexOf('全部导出') !== -1) {
                        result.batchTexts.push({
                            tag: el.tagName,
                            id: el.id || '',
                            cls: String(el.className || '').substring(0, 100),
                            text: text.substring(0, 200)
                        });
                    }
                }

                // 3. 检查 mini.gets() 返回的弹窗
                try {
                    var wins = mini.gets();
                    for (var j = 0; j < wins.length; j++) {
                        var w = wins[j];
                        if (w && w.isVisible && w.isVisible()) {
                            var el = w.getEl();
                            result.bodyDialogs.push({
                                uid: w.uid || '',
                                title: (w.title || ''),
                                visible: true,
                                elTag: el ? el.tagName : '?',
                                elId: el ? (el.id || '') : '',
                                text: el ? (el.textContent || '').trim().substring(0, 300) : ''
                            });
                        }
                    }
                } catch(e) {
                    result.bodyDialogs.push({error: String(e)});
                }

                return result;
            }""")

            self.log(f"  [扫描] 高z-index弹出层: {len(info.get('allPopups', []))} 个")
            for p in info.get('allPopups', [])[:5]:
                self.log(f"  [扫描]   <{p['tag']}> id={p['id']} class={p['cls'][:80]} z={p['zIndex']}")
                self.log(f"  [扫描]   文本: {p['text'][:150]}")

            self.log(f"  [扫描] 含'工时+导出'的元素: {len(info.get('exportElements', []))} 个")
            for e in info.get('exportElements', [])[:10]:
                self.log(f"  [扫描]   <{e['tag']}> id={e['id']} class={e['cls'][:80]}")
                self.log(f"  [扫描]   文本: {e['text'][:150]}")

            self.log(f"  [扫描] 含批次关键字('此月工时'/'第一批'/'1日~10日')的元素: {len(info.get('batchTexts', []))} 个")
            for b in info.get('batchTexts', [])[:10]:
                self.log(f"  [扫描]   <{b['tag']}> id={b['id']} class={b['cls'][:80]}")
                self.log(f"  [扫描]   文本: {b['text'][:150]}")

            self.log(f"  [扫描] mini.gets() 弹窗: {len(info.get('bodyDialogs', []))} 个")
            for d in info.get('bodyDialogs', []):
                if 'error' in d:
                    self.log(f"  [扫描]   error: {d['error']}")
                else:
                    self.log(f"  [扫描]   uid={d['uid']} title={d['title']} el={d['elTag']}#{d['elId']}")
                    self.log(f"  [扫描]   文本: {d['text'][:200]}")

        except Exception as e:
            self.log(f"  [扫描] 失败: {e}")

    def _get_all_scopes(self):
        """返回所有可搜索的范围：主页面 + 所有 frame"""
        scopes = [self._page]
        try:
            for frame in self._page.frames:
                if frame != self._page.main_frame and frame != self._page:
                    scopes.append(frame)
        except Exception:
            pass
        return scopes

    def _wait_for_confirm_export_dialog(self, timeout: int = 5) -> bool:
        """
        等待"您确认导出excel吗？"弹窗。搜索所有 frames。
        """
        start = time.time()
        while time.time() - start < timeout:
            self._check_stop()
            for scope in self._get_all_scopes():
                try:
                    msg = scope.locator(
                        ".mini-messagebox:visible:has-text('确认导出'), "
                        ".mini-messagebox:visible:has-text('导出excel'), "
                        ".mini-window:visible:has-text('确认导出'), "
                        ".mini-panel:visible:has-text('确认导出')"
                    ).first
                    if msg.count() > 0:
                        self._confirm_dialog_scope = scope
                        return True
                except Exception:
                    pass
            self._page.wait_for_timeout(300)
        return False

    def _click_confirm_ok_button(self) -> bool:
        """
        点击确认弹窗中的"确定"按钮。搜索所有 frames。
        """
        for scope in self._get_all_scopes():
            # 策略1: Playwright locator
            for sel in [
                ".mini-messagebox:visible button:has-text('确定')",
                ".mini-messagebox:visible a:has-text('确定')",
                ".mini-messagebox:visible span:has-text('确定')",
                ".mini-window:visible button:has-text('确定')",
                ".mini-window:visible a:has-text('确定')",
            ]:
                try:
                    btn = scope.locator(sel).first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click()
                        self.log("    ✓ 已点击确定")
                        return True
                except Exception:
                    continue

            # 策略2: JS 查找
            try:
                result = scope.evaluate("""() => {
                    var all = document.querySelectorAll(
                        'button, a, span, div[class*="btn"], div[class*="button"]');
                    for (var i = 0; i < all.length; i++) {
                        var el = all[i];
                        if (el.offsetHeight === 0) continue;
                        var text = (el.textContent || '').trim();
                        if (text === '确定' || text === '确认' || text === 'OK') {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }""")
                if result:
                    self.log("    ✓ JS方式点击确定")
                    return True
            except Exception:
                pass

            # 策略3: 任何包含"确定"文本的可见可点击元素
            try:
                btn = scope.locator(":visible:has-text('确定')").last
                if btn.count() > 0:
                    btn.click()
                    self.log("    ✓ 通用方式点击确定")
                    return True
            except Exception:
                pass

        self.log("    ⚠ 未找到确定按钮")
        return False

    def _select_combobox_by_scroll_click(self, target, combo_element,
                                         match_text: str, description: str = ""):
        """点击combobox按钮，滚动查找匹配项并选择"""
        try:
            btn = combo_element.locator(".mini-buttonedit-button").first
            btn.click()
            target.wait_for_timeout(800)

            # 查找下拉列表
            listbox = target.locator(".mini-listbox:visible, .mini-listbox-view:visible").first
            if listbox.count() == 0:
                listbox = target.locator(".mini-popup:visible .mini-listbox-view").first

            # 先尝试直接找
            cell = target.locator(f".mini-listbox:visible td:has-text('{match_text}')").first
            if cell.count() > 0:
                cell.click()
                self.log(f"  ✓ [{description}] 已选择: {match_text}")
                return True

            # 滚动查找
            if listbox.count() > 0:
                for i in range(25):
                    listbox.evaluate("el => el.scrollTop += 50")
                    target.wait_for_timeout(200)
                    cell = target.locator(
                        f".mini-listbox:visible td:has-text('{match_text}')"
                    ).first
                    if cell.count() > 0:
                        cell.click()
                        self.log(f"  ✓ [{description}] 滚动后选择: {match_text}")
                        return True

            self.log(f"  ⚠ [{description}] 未找到选项: {match_text}")
            self._page.keyboard.press("Escape")
            return False
        except Exception as e:
            self.log(f"  ✗ [{description}] 选择失败: {e}")
            try:
                self._page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    def _autocomplete_select(self, target, input_locator_str: str,
                             match_text: str, description: str = "",
                             timeout: int = 5) -> bool:
        """
        Autocomplete 选择：点击输入框→逐字输入→等待下拉出现→点击匹配项。

        这是 IMS 系统中最常见的交互模式：输入框输入文本后，
        下方弹出匹配列表，需要点击列表中的选项。

        参数:
            target: Playwright Page/Frame
            input_locator_str: 输入框的定位选择器
            match_text: 要匹配的文本
            description: 描述信息
            timeout: 等待超时秒数
        """
        desc = f"[{description}]" if description else ""
        self.log(f"  {desc} autocomplete: 点击输入框并输入 '{match_text}'")

        try:
            # 步骤1: 找到并点击输入框
            inp = target.locator(input_locator_str).first
            if inp.count() == 0:
                self.log(f"  ⚠ {desc} 未找到输入框: {input_locator_str}")
                return False

            inp.click()
            target.wait_for_timeout(300)

            # 步骤2: 清空后使用 type() 逐字输入（比 fill() 更可靠地触发 autocomplete）
            inp.fill("")
            target.wait_for_timeout(200)

            # 步骤3: type() 模拟逐字输入，带延迟，支持中文，触发 autocomplete
            inp.type(match_text, delay=50)

            # 步骤4: 轮询等待 autocomplete 下拉出现（IMS 响应较慢，最多等5秒）
            self.log(f"  {desc} 等待autocomplete下拉...")
            if self._poll_dropdown_and_click(target, match_text, timeout=5, desc=desc):
                return True

            # 步骤4b: dispatch input 事件再试
            inp.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles: true})); }")
            if self._poll_dropdown_and_click(target, match_text, timeout=3, desc=desc):
                return True

            # 步骤5: 终极回退——扫描所有包含该文本的元素，找到最像下拉项的
            self.log(f"  {desc} 常规策略未命中，使用终极扫描策略...")
            try:
                all_elements = target.locator(f"*:has-text('{match_text}')").all()
                candidates = []
                for el in all_elements:
                    try:
                        if not el.is_visible():
                            continue
                        tag = el.evaluate("el => el.tagName")
                        if tag in ('INPUT', 'TEXTAREA', 'BODY', 'HTML', 'TD', 'TR',
                                   'TABLE', 'TBODY', 'LABEL', 'SPAN'):
                            continue
                        # 下拉项通常是 div/li/a 且高度适中
                        box = el.bounding_box()
                        if box and box['height'] > 15 and box['height'] < 80:
                            candidates.append((box['y'], el))
                    except Exception:
                        continue

                if candidates:
                    # 选 Y 坐标最大的（最下面，通常是匹配项而非标签）
                    candidates.sort(key=lambda x: x[0], reverse=True)
                    # 取Y坐标不同于第一名的（跳过文档中的静态标签）
                    best = candidates[0][1]
                    text = best.inner_text()[:60] if best.inner_text() else ""
                    best.click()
                    target.wait_for_timeout(500)
                    self.log(f"  ✓ {desc} 终极策略选中: {text}")
                    return True
            except Exception as e:
                self.log(f"  {desc} 终极策略失败: {e}")

            # 步骤6: 按 Enter 确认
            inp.press("Enter")
            target.wait_for_timeout(500)
            self.log(f"  {desc} 按Enter确认输入")
            return True

        except Exception as e:
            self.log(f"  ✗ {desc} autocomplete 失败: {e}")
            return False

    def _select_by_label_text(self, target, label_text: str, match_text: str) -> bool:
        """
        通过标签文本定位输入框，使用 autocomplete 方式选择。
        先精确匹配标签，再找同行输入框，然后 autocomplete。
        """
        try:
            # 找到标签文本所在容器
            label_sel = (
                f"td:has-text('{label_text}'), "
                f"label:has-text('{label_text}'), "
                f"span:has-text('{label_text}'), "
                f"th:has-text('{label_text}'), "
                f"div:has-text('{label_text}')"
            )
            label = target.locator(label_sel).first
            if label.count() == 0:
                self.log(f"  ⚠ 未找到标签: {label_text}")
                return False

            # 找同行/同容器内的 input
            row = label.locator("xpath=ancestor::tr | ancestor::td | ancestor::div[contains(@class,'row')]").first
            if row.count() == 0:
                row = target  # 兜底：整个页面

            # 优先找 MiniUI combobox 的 input
            inputs = row.locator(
                ".mini-buttonedit-input, .mini-textbox-input, "
                "input.mini-textbox-border, input[type='text']"
            ).all()
            if not inputs:
                # 找整个页面中标签后面的 input
                inputs = target.locator(
                    f"//*[contains(text(),'{label_text}')]/following::input[1]"
                ).all()

            if inputs:
                inp_sel = None
                for inp in inputs:
                    if inp.is_visible():
                        # 构造唯一选择器
                        inp_id = inp.get_attribute("id")
                        if inp_id:
                            inp_sel = f"#{inp_id}"
                        else:
                            inp_cls = inp.get_attribute("class") or ""
                            inp_sel = f"input.{inp_cls.split()[0]}" if inp_cls else "input"
                        break

                if inp_sel:
                    return self._autocomplete_select(
                        target, inp_sel, match_text, label_text)

            # 如果找不到 input，尝试直接给 combobox 容器做 autocomplete
            combos = row.locator(".mini-combobox, .mini-buttonedit").all()
            if combos:
                for combo in combos:
                    if combo.is_visible():
                        # 先点击 combo 本身的 button 打开下拉
                        btn = combo.locator(".mini-buttonedit-button").first
                        if btn.count() > 0:
                            btn.click()
                            target.wait_for_timeout(800)

                        # 然后找下拉列表
                        return self._click_dropdown_item(target, match_text, label_text)

            self.log(f"  ⚠ 未找到 [{label_text}] 的输入框")
            return False

        except Exception as e:
            self.log(f"  ✗ 通用选择 [{label_text}] 失败: {e}")
            return False

    def _click_dropdown_item(self, target, match_text: str, description: str = "") -> bool:
        """在已打开的下拉列表中点击匹配项"""
        desc = f"[{description}]" if description else ""
        selectors = [
            f".mini-listbox:visible td:has-text('{match_text}')",
            f".mini-listbox-item:has-text('{match_text}')",
            f".mini-popup:visible td:has-text('{match_text}')",
            f".mini-popup:visible div:has-text('{match_text}')",
            f"td:has-text('{match_text}')",
        ]
        for sel in selectors:
            try:
                items = target.locator(sel).all()
                for item in items:
                    if item.is_visible():
                        item.click()
                        self.log(f"  ✓ {desc} 已选中: {match_text}")
                        target.wait_for_timeout(500)
                        return True
            except Exception:
                continue
        self.log(f"  ⚠ {desc} 未找到下拉项: {match_text}")
        return False

    def _poll_dropdown_and_click(self, target, match_text: str,
                                 timeout: int = 5, desc: str = "") -> bool:
        """
        轮询等待 autocomplete 下拉弹出，滚动查找并点击匹配项。
        IMS 的 autocomplete 下拉响应较慢（约3秒），需要耐心等待。
        下拉列表项可能不在可视区，需要滚动。
        """
        # 提取简短关键字（取前6个中文字符作为模糊匹配关键字）
        short_key = match_text[:6] if len(match_text) > 6 else match_text
        self.log(f"  {desc} 等待下拉弹出（关键字: {short_key}）...")

        start = time.time()
        popup_found = False

        while time.time() - start < timeout:
            target.wait_for_timeout(500)

            # 步骤A: 先检测是否有弹出层
            popup_selectors = [
                ".mini-popup:visible",
                ".mini-listbox:visible",
                ".mini-autocomplete-popup:visible",
                ".mini-suggest-popup:visible",
                "div[class*='popup']:visible",
                ".x-boundlist:visible",
            ]
            popup = None
            for psel in popup_selectors:
                try:
                    el = target.locator(psel).first
                    if el.count() > 0 and el.is_visible():
                        popup = el
                        if not popup_found:
                            self.log(f"  {desc} 检测到弹出层: {psel}")
                            popup_found = True
                        break
                except Exception:
                    continue

            if not popup:
                continue

            # 步骤B: 尝试滚动弹出层内容（可能匹配项不在可视区）
            try:
                popup.evaluate("""
                    (el) => {
                        // 尝试多种滚动容器
                        var list = el.querySelector('.mini-listbox-view, .mini-listbox, table, .mini-popup-body');
                        if (list) {
                            list.scrollTop = 0;  // 先滚到顶部
                            // 然后逐步向下滚
                            var maxScroll = list.scrollHeight || 500;
                            for (var s = 0; s < maxScroll; s += 60) {
                                list.scrollTop = s;
                            }
                        }
                        // 也尝试滚 el 本身
                        el.scrollTop = 0;
                    }
                """)
                target.wait_for_timeout(200)
            except Exception:
                pass

            # 步骤C: 用JS直接在弹出层中查找并点击匹配项
            result = popup.evaluate("""(args) => {
                var keyword = args.keyword;
                var fullText = args.fullText;

                // 遍历弹出层中所有可能的下拉项元素
                var items = document.querySelectorAll(
                    '.mini-listbox-item, .mini-listbox td, ' +
                    '.mini-listbox tr, .x-boundlist-item, ' +
                    'td, div[class*="item"], li, tr'
                );

                for (var i = 0; i < items.length; i++) {
                    var el = items[i];
                    if (el.offsetHeight === 0 || el.offsetWidth === 0) continue;
                    var text = (el.textContent || '').trim();
                    if (!text || text.length > 200) continue;

                    // 精确匹配或包含匹配
                    if (text.indexOf(fullText) !== -1 || text.indexOf(keyword) !== -1) {
                        // 确保不是输入框本身
                        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') continue;

                        // 找到后点击
                        el.click();
                        return {found: true, text: text.substring(0, 80)};
                    }
                }

                // 放宽：只要text包含关键词的任意2个连续字符
                if (keyword.length >= 2) {
                    var sub = keyword.substring(0, 4);
                    for (var i = 0; i < items.length; i++) {
                        var el = items[i];
                        if (el.offsetHeight === 0 || el.offsetWidth === 0) continue;
                        var text = (el.textContent || '').trim();
                        if (text.indexOf(sub) !== -1) {
                            if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') continue;
                            el.click();
                            return {found: true, text: text.substring(0, 80), partial: true};
                        }
                    }
                }

                return {found: false, totalItems: items.length};
            }""", {"keyword": short_key, "fullText": match_text})

            if result.get("found"):
                target.wait_for_timeout(500)
                self.log(f"  ✓ {desc} 已选择: {result.get('text', '')}")
                return True

            # 步骤D: 用 Playwright locator 再试一次（可能JS权限不够）
            try:
                # 在popup内找所有可见的 tr/div
                all_items = popup.locator("td, .mini-listbox-item, li, div[class*='item'], tr").all()
                for item in all_items:
                    try:
                        if not item.is_visible():
                            continue
                        text = (item.inner_text() or "").strip()
                        if not text or len(text) > 200:
                            continue
                        if match_text[:8] in text or short_key[:4] in text:
                            item.click()
                            target.wait_for_timeout(500)
                            self.log(f"  ✓ {desc} Playwright点击: {text[:60]}")
                            return True
                    except Exception:
                        continue
            except Exception:
                pass

        if popup_found:
            self.log(f"  {desc} 下拉已出现但{timeout}秒内未找到匹配项 [{short_key}]")
        else:
            self.log(f"  {desc} 下拉未在{timeout}秒内出现")
        return False

    def _autocomplete_by_label(self, target, label_text: str, match_text: str) -> bool:
        """
        通过标签文本找到输入框 → 直接输入文本 → 等待 autocomplete 下拉 → 点击匹配项。
        适配 IMS 商务经理工时查询页面的技术合作商选择。
        """
        self.log(f"  通过标签 [{label_text}] 定位输入框...")

        # 先扫描页面上所有输入框，记录它们的属性以便调试
        all_inputs = target.locator("input[type='text'], .mini-buttonedit-input, .mini-textbox-input").all()
        visible_inputs = [i for i in all_inputs if i.is_visible()]

        self.log(f"  页面可见输入框: {len(visible_inputs)} 个")
        for idx, inp in enumerate(visible_inputs):
            try:
                iid = inp.get_attribute("id") or ""
                iname = inp.get_attribute("name") or ""
                iph = inp.get_attribute("placeholder") or ""
                self.log(f"    [{idx}] id={iid}, name={iname}, placeholder={iph}")
            except Exception:
                pass

        # 策略1: 通过标签文本的 XPath 找最近的 input
        label_xpath = (
            f"//td[contains(text(),'{label_text}')]//following::input[1]",
            f"//label[contains(text(),'{label_text}')]//following::input[1]",
            f"//span[contains(text(),'{label_text}')]//following::input[1]",
            f"//th[contains(text(),'{label_text}')]//following::input[1]",
            f"//*[contains(text(),'{label_text}')]//following::input[not(@type='hidden')][1]",
        )
        for xpath in label_xpath:
            try:
                inp = target.locator(xpath).first
                if inp.count() > 0 and inp.is_visible():
                    inp_id = inp.get_attribute("id") or ""
                    self.log(f"  通过XPath找到输入框: id={inp_id}")
                    return self._autocomplete_select(
                        target, xpath, match_text, label_text)
            except Exception:
                continue

        # 策略2: 找标签所在的 tr/div，然后找里面的 input
        try:
            label = target.locator(
                f"td:has-text('{label_text}'), label:has-text('{label_text}'), "
                f"span:has-text('{label_text}'), th:has-text('{label_text}')"
            ).first
            if label.count() > 0:
                # 找同 tr 内的 input
                row = label.locator("xpath=ancestor::tr").first
                if row.count() > 0:
                    inp = row.locator(
                        "input[type='text'], .mini-buttonedit-input, .mini-textbox-input"
                    ).first
                    if inp.count() > 0 and inp.is_visible():
                        inp_id = inp.get_attribute("id") or ""
                        self.log(f"  在同行找到输入框: id={inp_id}")
                        # 直接操作这个 input
                        inp.click()
                        target.wait_for_timeout(300)
                        inp.press("Control+a")
                        inp.press("Backspace")
                        target.wait_for_timeout(200)
                        inp.fill(match_text)
                        target.wait_for_timeout(1200)
                        if self._click_dropdown_item(target, match_text, label_text):
                            return True
                        # 如果下拉项没点到，尝试 Enter
                        inp.press("Enter")
                        target.wait_for_timeout(500)
                        self.log(f"  已通过Enter确认输入: {match_text}")
                        return True
        except Exception as e:
            self.log(f"  策略2失败: {e}")

        # 策略3: 扫描所有可见 input，找不含"期间/日期/时间"关键词的（排除工时期间输入框）
        self.log(f"  策略3: 扫描所有可见输入框...")
        return self._autocomplete_scan_inputs(target, match_text)

    def _autocomplete_scan_inputs(self, target, match_text: str,
                                  skip_keywords: list = None) -> bool:
        """
        扫描所有可见 input，跳过含特定关键词的，在剩余 input 上做 autocomplete。
        以最后一个候选作为主要目标（合作商输入框通常在后面）。
        """
        skip_keywords = skip_keywords or []
        all_inputs = target.locator(
            "input[type='text'], .mini-buttonedit-input, .mini-textbox-input"
        ).all()
        visible = [i for i in all_inputs if i.is_visible()]

        candidates = []
        for inp in visible:
            try:
                iid = (inp.get_attribute("id") or "").lower()
                iname = (inp.get_attribute("name") or "").lower()
                iph = (inp.get_attribute("placeholder") or "").lower()
                combined = iid + iname + iph
                skip = False
                for kw in skip_keywords:
                    if kw in combined:
                        skip = True
                        break
                if not skip:
                    candidates.append(inp)
            except Exception:
                pass

        self.log(f"  候选输入框: {len(candidates)} 个（已排除含{skip_keywords}的）")

        if not candidates:
            candidates = visible[-3:] if len(visible) >= 3 else visible
            self.log(f"  回退：使用最后 {len(candidates)} 个输入框")

        # 只尝试最后3个候选（合作商输入框通常在表单靠后位置）
        candidates_to_try = candidates[-3:] if len(candidates) > 3 else candidates
        self.log(f"  实际尝试: {len(candidates_to_try)} 个（跳过前{len(candidates) - len(candidates_to_try)}个）")

        for inp in reversed(candidates_to_try):
            try:
                inp_id = inp.get_attribute("id") or "(no id)"
                inp.click()
                target.wait_for_timeout(300)
                inp.fill("")
                target.wait_for_timeout(100)
                # 使用 type() 逐字输入以触发 autocomplete（支持中文）
                inp.type(match_text, delay=50)

                # 轮询等待 autocomplete 下拉（IMS 响应约3秒）
                if self._poll_dropdown_and_click(target, match_text, timeout=5, desc="合作商"):
                    return True

                # 如果还是没找到，dispatch input 事件后再次轮询
                inp.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles: true})); }")
                if self._poll_dropdown_and_click(target, match_text, timeout=3, desc="合作商"):
                    return True

                # Enter 确认作为最后回退
                inp.press("Enter")
                target.wait_for_timeout(500)
                self.log(f"  Enter确认 [{inp_id}]: {match_text}")
                return True
            except Exception as e:
                self.log(f"  尝试 [{inp_id}] 失败: {e}")
                continue

        self.log("  ✗ 所有候选输入框均失败")
        return False

    def _type_supplier_and_query(self, target, supplier: str):
        """
        在技术合作商输入框中输入供应商名称，按回车触发查询。
        不依赖 autocomplete 下拉选择，直接用 Enter 提交表单。
        """
        # 验证 target 是否有效
        try:
            target.wait_for_timeout(100)
        except Exception:
            self.log("  ⚠ target 失效，尝试使用主页面")
            target = self._page

        # 找到合作商输入框（id 含 techCoopId 或标签"技术合作商"后的 input）
        supplier_input = None

        # 策略1: 通过已知 ID 模式查找
        for id_pattern in ["techCoopId$text", "techCoopId"]:
            try:
                el = target.locator(f"#{id_pattern}").first
                if el.count() > 0 and el.is_visible():
                    supplier_input = el
                    break
            except Exception:
                continue

        # 策略2: 通过标签文本查找
        if not supplier_input:
            try:
                # 找 "技术合作商" 标签所在 tr，取其中第一个 input
                label_row = target.locator(
                    "td:has-text('技术合作商'), th:has-text('技术合作商')"
                ).first
                if label_row.count() > 0:
                    row = label_row.locator("xpath=ancestor::tr").first
                    if row.count() > 0:
                        inp = row.locator(
                            "input[type='text'], .mini-buttonedit-input"
                        ).first
                        if inp.count() > 0 and inp.is_visible():
                            supplier_input = inp
            except Exception:
                pass

        # 策略3: 找所有可见 input，用不含"期间/日期/time/begin/end"的最后一个
        if not supplier_input:
            all_inputs = target.locator("input[type='text']").all()
            visible = [i for i in all_inputs if i.is_visible()]
            for inp in reversed(visible):
                try:
                    iid = (inp.get_attribute("id") or "").lower()
                    if not any(kw in iid for kw in ["begin", "end", "date", "time", "period"]):
                        supplier_input = inp
                        break
                except Exception:
                    continue

        if not supplier_input:
            self.log("  ⚠ 未找到合作商输入框")
            return

        # 输入供应商名称
        inp_id = supplier_input.get_attribute("id") or "(no id)"
        self.log(f"  找到合作商输入框 [{inp_id}]，输入 {supplier}")
        supplier_input.click()
        target.wait_for_timeout(300)
        supplier_input.fill("")
        target.wait_for_timeout(100)
        supplier_input.fill(supplier)
        target.wait_for_timeout(500)

        # 按回车触发查询（相当于点击查询按钮）
        self.log("  按回车触发查询...")
        supplier_input.press("Enter")
        target.wait_for_timeout(500)

    def _wait_for_loading(self, target, timeout: int = 60):
        """
        等待页面 loading 完成。
        IMS 查询后会显示 loading 遮罩，需要等它彻底消失。
        分两阶段：先等 loading 出现（证明查询已触发），再等它消失+数据渲染。
        """
        self.log("  等待页面加载...")
        start = time.time()

        loading_selectors = (
            ".mini-loading:visible, .mini-mask:visible, "
            ".mini-messagebox:visible, .loading:visible, "
            ".x-mask-loading:visible, .x-mask:visible, "
            "div[class*='loading']:visible, div[class*='mask']:visible"
        )

        # 阶段1: 等待 loading 出现（证明查询已触发，最多等10秒）
        self.log("  阶段1: 等待loading出现...")
        loading_appeared = False
        while time.time() - start < 10:
            self._check_stop()
            try:
                loading = target.locator(loading_selectors).first
                if loading.count() > 0:
                    self.log("  loading已出现，等待消失...")
                    loading_appeared = True
                    break
            except Exception:
                pass
            target.wait_for_timeout(500)

        if not loading_appeared:
            self.log("  ⚠ 未检测到loading（可能查询响应太快或页面结构不同），等待5秒后继续...")
            target.wait_for_timeout(5000)
            return

        # 阶段2: 等待 loading 消失
        loading_gone_time = None
        while time.time() - start < timeout:
            self._check_stop()
            try:
                loading = target.locator(loading_selectors).first
                if loading.count() == 0:
                    if loading_gone_time is None:
                        loading_gone_time = time.time()
                        self.log("  loading已消失，等待数据渲染...")
                    # loading 消失后需持续3秒不出现才算真消失
                    if time.time() - loading_gone_time >= 3:
                        self.log("  loading确认消失（持续3秒未出现）")
                        break
                else:
                    # loading 还在（或重新出现），重置计时
                    loading_gone_time = None
                target.wait_for_timeout(500)
            except Exception:
                target.wait_for_timeout(500)

        # 阶段3: 等待数据表格渲染完成（loading消失后再等5秒）
        self.log("  阶段3: 等待数据表格渲染（5秒）...")
        target.wait_for_timeout(5000)

        # 确认数据已出现（检查是否有表格行或数据单元格）
        try:
            data_indicators = target.locator(
                ".mini-grid-row, .mini-grid-cell, table tr, "
                ".mini-datagrid-row, tr[class*='row']"
            ).first
            if data_indicators.count() > 0:
                self.log("  ✓ 数据表格已渲染")
            else:
                self.log("  ⚠ 未检测到数据表格，再等3秒...")
                target.wait_for_timeout(3000)
        except Exception:
            target.wait_for_timeout(2000)

        self.log("  页面加载完成")

    def _click_export_workhour_button_new(self, target):
        """点击导出工时明细按钮（增强版，处理弹窗和遮罩）"""
        # 先关闭可能的弹窗
        self._close_miniui_popups(target)
        target.wait_for_timeout(1000)

        export_selectors = [
            "a:has-text('导出工时明细')",
            "button:has-text('导出工时明细')",
            "span:has-text('导出工时明细')",
            "a:has-text('导出工时')",
            "button:has-text('导出工时')",
            "a:has-text('导出')",
        ]
        for sel in export_selectors:
            try:
                el = target.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    el.click()
                    self.log("  ✓ 已点击导出工时明细")
                    target.wait_for_timeout(2000)
                    return True
            except Exception:
                continue

        # JS 方式：查找所有可见元素中包含"导出工时"的
        try:
            target.evaluate("""
                () => {
                    var all = document.querySelectorAll('a, button, span');
                    for (var i = 0; i < all.length; i++) {
                        var el = all[i];
                        if (el.offsetHeight === 0) continue;
                        var text = (el.textContent || '').trim();
                        if (text.indexOf('导出工时') !== -1) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)
            self.log("  ✓ JS方式点击导出工时明细")
            target.wait_for_timeout(2000)
            return True
        except Exception:
            pass

        self.log("  ⚠ 未找到导出工时明细按钮")
        return False

    # ==================== 2.2 下载在岗人员清单 ====================

    def download_staff_list(self, month_str: str):
        """下载在岗人员清单"""
        self._check_stop()
        start_date, end_date = get_month_start_end(month_str)
        self.log(f"\n[在岗人员清单] 开始下载，时间范围: {start_date} ~ {end_date}")

        # 刷新页面清除所有残留弹窗/浮层（工时下载的批次弹窗必须清除）
        self.log("[在岗人员清单] 刷新页面清除弹窗...")
        self._page.reload(wait_until="domcontentloaded")
        self._page.wait_for_timeout(3000)

        # 导航到 技术合作人员变化表
        self.log("[在岗人员清单] 导航到 外包报表 > 技术合作人员变化表...")
        self._expand_menu_parent("外包报表")
        self._page.wait_for_timeout(1000)
        target = self._click_menu_child("技术合作人员变化表",
                                        frame_keywords=["change", "personnel", "tech"])
        self._page.wait_for_timeout(3000)

        active = self._get_active_target()

        # 设置工作时间：MiniUI datepicker，ID 已知
        self.log("  设置工作时间范围...")
        try:
            active.evaluate(f"""(args) => {{
                var beg = mini.get('p_work_start_date');
                var end = mini.get('p_work_end_date');
                if (beg) beg.setValue(args.start);
                if (end) end.setValue(args.end);
            }}""", {"start": start_date, "end": end_date})
            self.log(f"  ✓ 已设置日期: {start_date} ~ {end_date}")
        except Exception as e:
            self.log(f"  ⚠ 日期设置异常: {e}")

        # 设置人员状态：标签"人员状态"后的下拉框，点箭头选"在岗"
        self.log("  设置人员状态为'在岗'...")
        try:
            # 找到"人员状态"标签所在行
            status_label = active.locator(
                "td:has-text('人员状态'), th:has-text('人员状态'), "
                "label:has-text('人员状态'), span:has-text('人员状态')"
            ).first
            if status_label.count() > 0:
                row = status_label.locator("xpath=ancestor::tr").first
                if row.count() > 0:
                    # 找到该行中的 buttonedit 下拉箭头
                    arrow = row.locator(
                        ".mini-buttonedit-button, .mini-trigger, "
                        ".mini-buttonedit-trigger, span[class*='arrow']"
                    ).first
                    if arrow.count() > 0:
                        arrow.click()
                        active.wait_for_timeout(800)
                        # 在下拉列表中找到"在岗"并点击
                        item = active.locator(
                            ".mini-listbox-item:has-text('在岗'), "
                            ".mini-listbox td:has-text('在岗'), "
                            ".mini-popup:visible td:has-text('在岗')"
                        ).first
                        if item.count() > 0 and item.is_visible():
                            item.click()
                            self.log("  ✓ 已选择'在岗'")
                            active.wait_for_timeout(300)
                        else:
                            self.log("  ⚠ 下拉列表中未找到'在岗'选项")
                    else:
                        self.log("  ⚠ 未找到下拉箭头")
            else:
                self.log("  ⚠ 未找到'人员状态'标签")
        except Exception as e:
            self.log(f"  ⚠ 人员状态设置异常: {e}")

        # 查询
        query_clicked = self._click_query_button(active)
        if query_clicked:
            self._wait_for_loading(active, timeout=60)
        else:
            self.log("  ⚠ 查询按钮未找到，不查询直接尝试导出...")
            self._page.wait_for_timeout(3000)

        # 导出
        self.log("  导出Excel...")
        try:
            with self._page.expect_download(timeout=180000) as download_info:
                self._click_export_button(active, "导出Excel")
                self._handle_export_confirm_popup()

            download = download_info.value
            file_path = os.path.join(self.download_dir, "在岗人员清单.xlsx")
            if os.path.exists(file_path):
                os.remove(file_path)
            self._wait_and_save_download(download, file_path)
            try:
                download.delete()
            except Exception:
                pass
            self.log("[在岗人员清单] 下载完成")
        except Exception as e:
            self.log(f"  ✗ 在岗人员清单下载失败: {e}")
            self._screenshot_on_error("staff_list")

    # ==================== 2.3 下载计提报表 ====================

    def download_accrual_report(self, month_str: str):
        """下载计提报表"""
        self._check_stop()
        start_date, end_date = get_month_start_end(month_str)
        self.log(f"\n[计提报表] 开始下载，时间范围: {start_date} ~ {end_date}")

        # 刷新页面清除所有残留弹窗
        self.log("[计提报表] 刷新页面清除弹窗...")
        self._page.reload(wait_until="domcontentloaded")
        self._page.wait_for_timeout(3000)

        # 导航到 计提
        self.log("[计提报表] 导航到 外包数据查询 > 计提...")
        self._expand_menu_parent("外包数据查询")
        self._page.wait_for_timeout(1000)
        target = self._click_menu_child("计提",
                                        frame_keywords=["accrual", "settlement", "计提", "结算"])
        self._page.wait_for_timeout(3000)

        active = self._get_active_target()

        # 设置申请时间
        self.log("  设置申请时间范围...")
        date_set = False
        for beg_id, end_id in [
            ("p_apply_begin_date", "p_apply_end_date"),
            ("p_start_date", "p_end_date"),
            ("p_begin_date", "p_end_date"),
            ("applyStartDate", "applyEndDate"),
        ]:
            if self._input_miniui_date(active, beg_id, end_id, start_date, end_date):
                date_set = True
                break

        if not date_set:
            self.log("  ⚠ 自动设置申请时间失败，尝试通用方式...")
            self._select_by_label_text(active, "申请时间", start_date)

        # 设置单位状态为"审批流程结束"（第5个选项）
        self.log("  设置单位状态为'审批流程结束'...")
        status_set = False
        for sid in ["p_app_state", "p_status", "p_unit_status", "appState"]:
            try:
                result = active.evaluate(f"""(args) => {{
                    var c = mini.get('{sid}');
                    if (!c) return false;
                    var data = (c.data || []).filter(function(d) {{ return !d.__NullItem; }});
                    for (var i = 0; i < data.length; i++) {{
                        var keys = Object.keys(data[i]);
                        for (var k = 0; k < keys.length; k++) {{
                            var val = String(data[i][keys[k]] || '');
                            if (val.indexOf('审批流程结束') !== -1) {{
                                c.setValue(data[i].flexValue || data[i].id || data[i].value);
                                return true;
                            }}
                        }}
                    }}
                    // 回退：按索引选第5个
                    if (data.length >= 5) {{
                        c.setValue(data[4].flexValue || data[4].id || data[4].value);
                        return true;
                    }}
                    return false;
                }}""")
                if result:
                    self.log(f"  ✓ 已设置单位状态")
                    status_set = True
                    break
            except Exception:
                continue

        if not status_set:
            self.log("  ⚠ 自动设置单位状态失败，尝试通用方式...")
            self._select_by_label_text(active, "单位状态", "审批流程结束")

        # 查询
        self._click_query_button(active)
        self._page.wait_for_timeout(5000)

        # 导出
        self.log("  导出Excel...")
        try:
            with self._page.expect_download(timeout=180000) as download_info:
                self._click_export_button(active, "导出Excel")
                self._handle_export_confirm_popup()

            download = download_info.value
            file_path = os.path.join(self.download_dir, "计提报表.xlsx")
            if os.path.exists(file_path):
                os.remove(file_path)
            self._wait_and_save_download(download, file_path)
            try:
                download.delete()
            except Exception:
                pass
            self.log("[计提报表] 下载完成")
        except Exception as e:
            self.log(f"  ✗ 计提报表下载失败: {e}")
            self._screenshot_on_error("accrual_report")


# ===== 便捷调用函数（公共接口保持不变） =====
def run_full_download(username: str, password: str, supplier_list: List[str],
                      month_str: str, download_dir: str,
                      log_func: Optional[Callable] = None,
                      stop_event: Optional[threading.Event] = None):
    """
    执行完整的自动下载流程。
    参数:
        username: 登录账号
        password: 登录密码
        supplier_list: 供应商名称列表
        month_str: 月份字符串，如 "202602"
        download_dir: 下载保存目录
        log_func: 日志回调函数 log_func(message)
        stop_event: 可选，设置后停止下载
    """
    downloader = IMSDataDownloader(download_dir, log_func, stop_event)
    try:
        downloader.start()
        downloader.login(username, password)
        downloader.download_workhours(month_str, supplier_list)
        downloader.download_staff_list(month_str)
        downloader.download_accrual_report(month_str)
        if log_func:
            log_func("[完成] 所有数据下载任务已完成！")
    except InterruptedError:
        if log_func:
            log_func("[中断] 下载已被用户停止")
    except Exception as e:
        downloader._screenshot_on_error("fatal")
        if log_func:
            log_func(f"[错误] 下载过程中出现异常: {e}")
            log_func(f"[错误] 详细信息: {traceback.format_exc()}")
        raise
    finally:
        downloader.quit()
