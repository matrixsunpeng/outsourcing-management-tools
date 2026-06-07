"""
外包工具箱 — 共享基类
提供所有 IMS 下载模块的公共功能：浏览器生命周期、登录、菜单导航、
MiniUI/Layui 控件交互、导出下载。
"""
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from playwright.sync_api import sync_playwright, Page, Browser, Playwright, Frame

from .utils import now_timestamp, to_iso_date


LOGIN_URL = "https://ims.asiainfo.com/AIOMS/Jsp/main.jsp"

DEFAULT_SELECTORS = {
    "username_input": "input[name='username'], input[id='username'], input[type='text']",
    "password_input": "input[name='password'], input[id='password'], input[type='password']",
    "login_button": "button[type='submit'], input[type='submit'], button:has-text('登录'), input[value*='登录']",
}


class BaseDownloader:
    """IMS 报表下载器基类"""

    # ---- 子类需覆盖 ----
    MENU_PARENT: str = ""       # 左侧树父菜单名
    MENU_CHILD: str = ""        # 左侧树子菜单名
    FRAME_KEYWORDS: List[str] = []  # iframe URL 关键词
    EXPORT_BTN_TEXT: str = "导出"    # 导出按钮文本
    DOWNLOAD_TIMEOUT: int = 60000    # 下载超时（ms）

    def __init__(self, username: str, password: str,
                 download_dir: Optional[str] = None, headless: bool = False):
        self.username = username
        self.password = password
        self.download_dir = Path(download_dir) if download_dir else Path(__file__).resolve().parent.parent / "downloads"
        self.headless = headless
        self.download_dir.mkdir(parents=True, exist_ok=True)

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        self._query_target = None
        self._query_is_tab = False

    # ==================== 浏览器生命周期 ====================

    def start(self) -> None:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            downloads_path=str(self.download_dir)
        )
        context = self._browser.new_context(accept_downloads=True)
        self._page = context.new_page()
        print(f"[INFO] 浏览器已启动，下载目录: {self.download_dir}")

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        print("[INFO] 浏览器已关闭")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    # ==================== 登录 ====================

    def login(self) -> bool:
        print(f"[INFO] 正在访问登录页面: {LOGIN_URL}")
        self._page.goto(LOGIN_URL, wait_until="networkidle")
        self._page.wait_for_timeout(2000)

        self._page.locator(DEFAULT_SELECTORS["username_input"]).first.fill(self.username)
        print(f"[INFO] 已输入用户名: {self.username}")

        self._page.locator(DEFAULT_SELECTORS["password_input"]).first.fill(self.password)
        print("[INFO] 已输入密码")

        self._page.locator(DEFAULT_SELECTORS["login_button"]).first.click()
        print("[INFO] 已点击登录按钮")

        self._page.wait_for_timeout(3000)
        current_url = self._page.url
        if "main" in current_url or "home" in current_url or "index" in current_url:
            print("[SUCCESS] 登录成功")
        else:
            print("[WARNING] 登录状态未确认，继续尝试...")
        return True

    # ==================== 菜单导航 ====================

    def _expand_menu_parent(self) -> None:
        """双击左侧树父菜单展开，带 JS 回退"""
        try:
            self._page.locator(
                f".mini-tree-nodetext:has-text('{self.MENU_PARENT}')"
            ).first.dblclick()
            print(f"[INFO] 已双击【{self.MENU_PARENT}】菜单")
            self._page.wait_for_timeout(2000)
        except Exception as e:
            print(f"[DEBUG] 双击菜单失败: {e}")
            self._page.evaluate(f"""
                var tree = mini.get("tree1");
                if (tree) {{
                    var nodes = tree.getData();
                    for (var i = 0; i < nodes.length; i++) {{
                        if (nodes[i].text == '{self.MENU_PARENT}') {{
                            tree.expandNode(nodes[i]);
                            break;
                        }}
                    }}
                }}
            """)
            print(f"[INFO] 通过JS展开了【{self.MENU_PARENT}】菜单")
            self._page.wait_for_timeout(2000)

    def _click_menu_child_new_tab(self) -> Optional[Page]:
        """单击子菜单，尝试打开新标签页"""
        try:
            with self._page.context.expect_page(timeout=5000) as new_page_info:
                self._page.locator(
                    f".mini-tree-nodetext:has-text('{self.MENU_CHILD}')"
                ).first.click()
                print(f"[INFO] 已单击【{self.MENU_CHILD}】")
            target = new_page_info.value
            target.wait_for_load_state("domcontentloaded")
            target.wait_for_timeout(3000)
            self._query_is_tab = True
            print(f"[SUCCESS] 页面已打开(新标签页): {target.url}")
            return target
        except Exception:
            print("[INFO] 未检测到新标签页，尝试查找 iframe...")
            return None

    def _find_target_frame(self) -> Optional[Frame]:
        """按 FRAME_KEYWORDS 匹配 iframe"""
        for frame in self._page.frames:
            url = frame.url
            if frame == self._page.main_frame or not url or "about:blank" in url:
                continue
            for kw in self.FRAME_KEYWORDS:
                if kw.lower() in url.lower():
                    print(f"[INFO] 找到目标iframe: {url}")
                    return frame
        return None

    def _fallback_frame(self):
        """兜底：取最后一个非主frame，或抛出异常"""
        non_main = [f for f in self._page.frames
                    if f != self._page.main_frame and f.url and "about:blank" not in f.url]
        if non_main:
            frame = non_main[-1]
            print(f"[INFO] 使用最后一个非主frame: {frame.url}")
            return frame
        raise Exception(f"未找到【{self.MENU_CHILD}】的 iframe 或新标签页")

    def navigate(self):
        """标准导航：展开父菜单 → 单击子菜单 → 返回目标（Page 或 Frame）"""
        print(f"[INFO] 正在导航到【{self.MENU_CHILD}】...")
        self._page.wait_for_timeout(3000)

        self._expand_menu_parent()
        self._page.wait_for_timeout(2000)

        target = self._click_menu_child_new_tab()
        if target:
            self._query_target = target
            return target

        # 回退 iframe
        self._query_is_tab = False
        self._page.wait_for_timeout(3000)
        target = self._find_target_frame()
        if not target:
            self._page.wait_for_timeout(3000)
            target = self._find_target_frame()
        if not target:
            target = self._fallback_frame()

        target.wait_for_load_state("domcontentloaded")
        self._page.wait_for_timeout(3000)
        print(f"[SUCCESS] 已定位到iframe: {target.url}")
        self._query_target = target
        return target

    def _get_fresh_frame(self) -> Optional[Frame]:
        """重新获取目标 frame（防止 detach）"""
        self._page.wait_for_timeout(1000)
        frame = self._find_target_frame()
        if frame:
            self._query_target = frame
            return frame
        return None

    def _next_iteration_reset(self):
        """多 SBU 循环中，完成一条后重置页面"""
        self._page.wait_for_timeout(2000)
        if self._query_is_tab and self._query_target:
            try:
                self._query_target.close()
            except Exception:
                pass
        else:
            self._page.reload()
            self._page.wait_for_load_state("domcontentloaded")
            self._page.wait_for_timeout(3000)

    # ==================== MiniUI 控件操作 ====================

    def _select_miniui_combobox(self, target, control_id: str,
                                 target_value: str) -> bool:
        """MiniUI combobox 单选（JS API 模糊匹配）"""
        print(f"[INFO] 正在选择 {control_id}: {target_value}")

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
                if (!matched) {
                    var samples = data.slice(0, 10).map(function(d) {
                        var keys = Object.keys(d);
                        for (var k = 0; k < keys.length; k++) {
                            var val = String(d[keys[k]] || '');
                            if (val && val.length > 1 && !/^[\\d.]+$/.test(val)) return val;
                        }
                        return JSON.stringify(d).substring(0, 80);
                    });
                    return {success: false, error: '未匹配到选项', available: samples};
                }
                var val = matched.flexValue || matched.id || matched.value || '';
                combo.setValue(val);
                return {success: true, selected: JSON.stringify(matched).substring(0, 200)};
            }""", {"controlId": control_id, "targetValue": target_value})

            if result.get("success"):
                print(f"[SUCCESS] 已选择 {control_id}: {result.get('selected')}")
                self._page.wait_for_timeout(500)
                return True
            else:
                available = result.get("available", [])
                print(f"[WARNING] {control_id}: {result.get('error')}")
                if available:
                    print(f"[DEBUG] 可用选项: {available}")
                return False
        except Exception as e:
            print(f"[ERROR] 选择 {control_id} 失败: {e}")
            return False

    def _select_miniui_multi(self, target, control_id: str,
                              target_values: List[str]) -> bool:
        """MiniUI combobox 多选（UI 交互方式：打开下拉→逐个勾选）"""
        print(f"[INFO] 正在多选 {control_id}: {target_values}")

        try:
            # 确保数据已加载
            target.evaluate(f"""(controlId) => {{
                var combo = mini.get(controlId);
                if (!combo) return;
                var data = combo.data || [];
                data = data.filter(function(d) {{ return !d.__NullItem; }});
                if (data.length === 0) combo.load();
            }}""", control_id)
            self._page.wait_for_timeout(2000)

            # 打开下拉
            btn = target.locator(
                f"#{control_id}\\$button, #{control_id} .mini-buttonedit-button"
            ).first
            if btn.count() == 0:
                btn = target.locator(f"#{control_id}\\$text").first
            btn.click()
            print("[INFO] 已打开下拉列表")
            self._page.wait_for_timeout(800)

            # 逐个勾选
            for tv in target_values:
                try:
                    checkbox = target.locator(
                        f".mini-listbox td:has-text('{tv}') .mini-listbox-checkbox"
                    ).first
                    if checkbox.count() == 0:
                        target_td = target.locator(
                            f".mini-listbox td:has-text('{tv}')"
                        ).first
                        if target_td.count() > 0:
                            parent_row = target_td.locator(
                                "xpath=ancestor::tr"
                            ).first
                            if parent_row.count() > 0:
                                checkbox = parent_row.locator(
                                    ".mini-checkbox, .mini-listbox-checkbox"
                                ).first
                    if checkbox.count() > 0:
                        checkbox.click()
                        print(f"[INFO] 已勾选: {tv}")
                        self._page.wait_for_timeout(500)
                    else:
                        print(f"[WARNING] 未找到选项: {tv}")
                        self._scroll_and_retry(target, tv)
                except Exception as e:
                    print(f"[WARNING] 勾选 '{tv}' 失败: {e}")

            self._page.keyboard.press("Escape")
            self._page.wait_for_timeout(300)
            print("[SUCCESS] 多选完成")
            return True
        except Exception as e:
            print(f"[ERROR] 多选 {control_id} 失败: {e}")
            return False

    def _scroll_and_retry(self, target, option_text: str, max_scroll: int = 20):
        """滚动下拉列表查找选项"""
        listbox = target.locator(".mini-listbox:visible").first
        if listbox.count() == 0:
            return
        for _ in range(max_scroll):
            listbox.evaluate("el => el.scrollTop += 50")
            self._page.wait_for_timeout(200)
            cell = target.locator(
                f".mini-listbox:visible td:has-text('{option_text}')"
            ).first
            if cell.count() > 0:
                cell.click()
                print(f"[INFO] 滚动后找到并选择: {option_text}")
                return

    def _close_miniui_popups(self, target) -> None:
        """关闭所有 MiniUI 弹窗/modals"""
        try:
            target.evaluate("""() => {
                document.querySelectorAll('.mini-modal, .mini-window').forEach(function(m) {
                    if (m.style.display !== 'none') m.style.display = 'none';
                });
                try {
                    var wins = mini.gets();
                    for (var i = 0; i < wins.length; i++) {
                        if (wins[i] && wins[i].isVisible && wins[i].isVisible()) {
                            if (wins[i].hide) wins[i].hide();
                            else if (wins[i].close) wins[i].close();
                        }
                    }
                } catch(e) {}
            }""")
            self._page.wait_for_timeout(1000)
        except Exception:
            pass

    def _input_miniui_date(self, target, beg_id: str, end_id: str,
                            start_str: str, end_str: str) -> bool:
        """MiniUI 日期控件输入"""
        beg_val = to_iso_date(start_str)
        end_val = to_iso_date(end_str)
        print(f"[INFO] 输入日期: {beg_val} ~ {end_val}")

        try:
            target.evaluate(f"""(args) => {{
                var beg = mini.get('{beg_id}');
                var end = mini.get('{end_id}');
                if (beg) beg.setValue(args.beg);
                if (end) end.setValue(args.end);
            }}""", {"beg": beg_val, "end": end_val})
            print(f"[SUCCESS] 日期输入完成: {beg_val} ~ {end_val}")
            self._page.wait_for_timeout(500)
            return True
        except Exception as e:
            print(f"[ERROR] 日期输入失败: {e}")
            return False

    # ==================== Layui 控件操作 ====================

    def _select_layui_dropdown(self, frame, select_id: str,
                                target_value: str) -> bool:
        """Layui select 选择（支持精确值匹配和文本模糊匹配）"""
        print(f"[INFO] 正在选择 {select_id}: {target_value}")

        result = frame.evaluate("""(args) => {
            var select = document.getElementById(args.selectId);
            if (!select) return {success: false, error: '找不到select元素'};
            var options = select.querySelectorAll('option');
            var matchedOption = null, matchedValue = null;
            // 1. 精确值匹配
            for (var i = 0; i < options.length; i++) {
                if (options[i].value === args.targetValue) {
                    matchedOption = options[i]; matchedValue = args.targetValue; break;
                }
            }
            // 2. 文本模糊匹配
            if (!matchedOption) {
                for (var i = 0; i < options.length; i++) {
                    var text = options[i].text || '', value = options[i].value || '';
                    if (!value) continue;
                    if (text.toUpperCase().indexOf(args.targetValue.toUpperCase()) !== -1) {
                        matchedOption = options[i]; matchedValue = value; break;
                    }
                }
            }
            // 3. 提取括号内代码匹配 (如 "(185)亚信科技CMB" 中的 185)
            if (!matchedOption) {
                for (var i = 0; i < options.length; i++) {
                    var text = options[i].text || '', value = options[i].value || '';
                    if (!value) continue;
                    var match = text.match(/\\((\\w+)\\)/);
                    if (match && match[1] === args.targetValue) {
                        matchedOption = options[i]; matchedValue = value; break;
                    }
                }
            }
            if (!matchedOption) {
                var available = [];
                for (var i = 0; i < Math.min(options.length, 20); i++) {
                    if (options[i].value) available.push({value: options[i].value, text: options[i].text});
                }
                return {success: false, error: '未找到匹配选项', available: available};
            }
            select.value = matchedValue;
            select.dispatchEvent(new Event('change', {bubbles: true}));
            if (window.layui && layui.form) {
                try { layui.form.render('select'); } catch(e) {}
            }
            return {success: true, selectedValue: matchedValue, selectedText: matchedOption.text};
        }""", {"selectId": select_id, "targetValue": target_value})

        if result.get("success"):
            print(f"[SUCCESS] 已选择 {select_id}: {result.get('selectedText')}")
            self._page.wait_for_timeout(500)
            return True
        else:
            print(f"[WARNING] 选择失败: {result.get('error')}")
            return False

    def _input_layui_date(self, frame, beg_id: str, end_id: str,
                           start_str: str, end_str: str) -> bool:
        """Layui 日期输入（JS 设值 + 移除弹出层）"""
        beg_val = to_iso_date(start_str)
        end_val = to_iso_date(end_str)
        print(f"[INFO] 输入日期: {beg_val} ~ {end_val}")

        try:
            for input_id, val in [(beg_id, beg_val), (end_id, end_val)]:
                frame.evaluate(f"""(v) => {{
                    var el = document.getElementById('{input_id}');
                    if (el) {{
                        el.value = v;
                        el.dispatchEvent(new Event('input', {{bubbles: true}}));
                        el.dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                }}""", val)
                self._page.wait_for_timeout(300)
                # 移除 Layui 日期弹出层
                try:
                    frame.evaluate(
                        "() => { var dp = document.querySelector('.layui-laydate'); if (dp) dp.remove(); }"
                    )
                except Exception:
                    pass
                self._page.wait_for_timeout(200)

            print("[SUCCESS] 日期输入完成")
            return True
        except Exception as e:
            print(f"[ERROR] 日期输入失败: {e}")
            return False

    # ==================== 查询与导出 ====================

    def _click_query_button(self, target, btn_selector: str = "a:has-text('查询')") -> None:
        """点击查询按钮，等待数据加载，关闭弹窗"""
        btn = target.locator(btn_selector).first
        if btn.count() == 0:
            btn = target.locator("a#Query").first
        btn.click()
        print("[INFO] 已点击查询按钮")
        self._page.wait_for_timeout(5000)
        print("[INFO] 等待数据加载完成...")
        self._close_miniui_popups(target)

    def _click_export_and_save(self, target, filename_prefix: str,
                                sbu_name: str = "", start_str: str = "",
                                end_str: str = "") -> Optional[str]:
        """点击导出按钮并保存下载文件"""
        print(f"[INFO] 正在导出...")
        try:
            # 确定下载上下文
            if self._query_is_tab and self._query_target:
                dl_ctx = self._query_target
            else:
                dl_ctx = self._page

            export_btn = target.locator(
                f"a:has-text('{self.EXPORT_BTN_TEXT}')"
            ).first
            if export_btn.count() == 0:
                export_btn = target.locator("a:has-text('导出')").first

            with dl_ctx.expect_download(timeout=self.DOWNLOAD_TIMEOUT) as download_info:
                export_btn.click()
                print(f"[INFO] 已点击导出按钮，等待下载...")

            download = download_info.value
            timestamp = now_timestamp()
            sbu_part = sbu_name.replace("/", "_") if sbu_name else "全部"
            filename = f"{filename_prefix}_{sbu_part}_{start_str}_{end_str}_{timestamp}.xlsx"
            save_path = self.download_dir / filename
            download.save_as(save_path)
            try:
                download.delete()
            except Exception:
                pass
            print(f"[SUCCESS] 文件已下载: {save_path}")
            return str(save_path)
        except Exception as e:
            print(f"[ERROR] 导出失败: {e}")
            files = list(self.download_dir.glob("*.xlsx"))
            if files:
                latest = max(files, key=lambda f: f.stat().st_mtime)
                print(f"[INFO] 检测到下载文件: {latest}")
                return str(latest)
            return None

    # ==================== 主入口模板 ====================

    def run(self, sbu_list: Optional[List[str]] = None,
            start_str: str = "", end_str: str = "",
            start_browser: bool = True) -> List[str]:
        """
        标准执行流程（子类一般不需要覆盖）
        1. 启动浏览器 → 登录 → 循环(SBU) { 导航 → 查询导出 } → 关闭
        """
        downloaded: List[str] = []
        try:
            if start_browser:
                self.start()
            self.login()

            if not sbu_list:
                sbu_list = [""]

            for idx, sbu in enumerate(sbu_list):
                print(f"\n{'='*60}")
                print(f"[INFO] 处理第 {idx+1}/{len(sbu_list)} 个: {sbu or '全部'}")
                print(f"{'='*60}")

                target = self.navigate()
                result = self.query_and_export(
                    target, sbu_name=sbu, start_str=start_str, end_str=end_str
                )
                if result:
                    downloaded.append(result)

                if idx < len(sbu_list) - 1:
                    print("[INFO] 等待后继续下一个...")
                    self._next_iteration_reset()

            return downloaded
        except Exception as e:
            print(f"[ERROR] 下载失败: {e}")
            raise
        finally:
            if start_browser:
                self.stop()

    def query_and_export(self, target, sbu_name: str = "",
                          start_str: str = "", end_str: str = "") -> Optional[str]:
        """
        子类必须覆盖：填写条件 → 查询 → 导出
        返回下载文件路径或 None
        """
        raise NotImplementedError("子类必须实现 query_and_export()")
