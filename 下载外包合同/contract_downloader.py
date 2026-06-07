"""
外包合同下载自动化工具
使用 Playwright 实现网页自动化操作
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from playwright.sync_api import sync_playwright, Page, Browser, Playwright, Frame


class ContractDownloader:
    """外包合同下载器"""

    LOGIN_URL = "https://ims.asiainfo.com/AIOMS/Jsp/main.jsp"

    SELECTORS = {
        "username_input": "input[name='username'], input[id='username'], input[type='text']",
        "password_input": "input[name='password'], input[id='password'], input[type='password']",
        "login_button": "button[type='submit'], input[type='submit'], button:has-text('登录'), input[value*='登录']",
    }

    # 单据状态多选值
    STATUS_OPTIONS = ["审批流程中", "审批流程结束", "待确认到岗中"]

    # 技术合作种类（单选）
    TECH_COOP_TYPE = "技术合作-II(人员类)"

    # MiniUI 控件 ID 映射（外包合同页面）
    MINIUI_IDS = {
        "sbu": "p_sbu_id",
        "begin_date": "p_apply_begin_date",
        "end_date": "p_apply_end_date",
        "state": "p_state",
        "tech_coop_type": "p_tech_coop_apply_type",
    }

    def __init__(
        self,
        username: str,
        password: str,
        download_dir: Optional[str] = None,
        headless: bool = False
    ):
        self.username = username
        self.password = password
        self.download_dir = (Path(download_dir) if download_dir else Path(__file__).resolve().parent.parent / "downloads").resolve()
        self.headless = headless
        self.download_dir.mkdir(parents=True, exist_ok=True)

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        self._query_target = None
        self._query_is_tab = False

    def start(self) -> None:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless, args=["--headless=new"] if self.headless else [], downloads_path=str(self.download_dir))
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

    # ===================== 登录 =====================

    def login(self) -> bool:
        print(f"[INFO] 正在访问登录页面: {self.LOGIN_URL}")
        self._page.goto(self.LOGIN_URL, wait_until="networkidle")
        self._page.wait_for_timeout(2000)

        username_input = self._page.locator(self.SELECTORS["username_input"]).first
        if username_input:
            username_input.fill(self.username)
            print(f"[INFO] 已输入用户名: {self.username}")

        password_input = self._page.locator(self.SELECTORS["password_input"]).first
        if password_input:
            password_input.fill(self.password)
            print("[INFO] 已输入密码")

        login_button = self._page.locator(self.SELECTORS["login_button"]).first
        if login_button:
            login_button.click()
            print("[INFO] 已点击登录按钮")

        self._page.wait_for_timeout(3000)
        current_url = self._page.url
        if "main" in current_url or "home" in current_url or "index" in current_url:
            print("[SUCCESS] 登录成功")
            return True
        else:
            print("[WARNING] 登录状态未确认，继续尝试...")
            return True

    # ===================== 导航 =====================

    def _find_target_frame(self) -> Optional[Frame]:
        """查找外包合同的 iframe（关键词匹配 URL）"""
        possible_keywords = [
            "contract", "Contract", "outsourceContract",
            "OutsourceContract", "contractQuery", "ContractQuery",
            "contractList", "ContractList", "ht_query", "HT_QUERY",
            "CooperationQuery", "cooperationQuery",
        ]
        for frame in self._page.frames:
            frame_url = frame.url
            if frame == self._page.main_frame or not frame_url or "about:blank" in frame_url:
                continue
            for keyword in possible_keywords:
                if keyword.lower() in frame_url.lower():
                    print(f"[INFO] 找到外包合同iframe: {frame_url}")
                    return frame
        return None

    def navigate_to_contract(self) -> Frame:
        """
        导航到外包合同页面

        Returns:
            Frame: 外包合同 iframe 对象
        """
        print("[INFO] 正在导航到外包合同页面...")
        self._page.wait_for_timeout(3000)

        # 双击"外包数据查询"展开子菜单
        try:
            outsource_row = self._page.locator(".mini-tree-nodetext:has-text('外包数据查询')").first
            outsource_row.dblclick()
            print("[INFO] 已双击【外包数据查询】菜单")
            self._page.wait_for_timeout(2000)
        except Exception as e:
            print(f"[DEBUG] 双击菜单时出错: {e}")
            try:
                self._page.evaluate("""
                    var tree = mini.get("tree1");
                    var nodes = tree.getData();
                    for(var i=0; i<nodes.length; i++){
                        if(nodes[i].text == '外包数据查询'){
                            tree.expandNode(nodes[i]);
                            break;
                        }
                    }
                """)
                print("[INFO] 通过JS展开了外包数据查询菜单")
                self._page.wait_for_timeout(2000)
            except Exception as e2:
                print(f"[DEBUG] JS展开也失败: {e2}")

        self._page.wait_for_timeout(2000)

        # 单击"外包合同"（打开新标签页）
        try:
            with self._page.context.expect_page(timeout=5000) as new_page_info:
                link = self._page.locator(".mini-tree-nodetext:has-text('外包合同')").first
                link.click()
                print("[INFO] 已单击【外包合同】")

            self._query_target = new_page_info.value
            self._query_target.wait_for_load_state("domcontentloaded")
            self._query_target.wait_for_timeout(3000)
            self._query_is_tab = True
            print(f"[SUCCESS] 外包合同页面已打开(新标签页): {self._query_target.url}")
            return self._query_target

        except Exception:
            print("[INFO] 未检测到新标签页，尝试查找 iframe...")
            self._query_is_tab = False

        # 回退方案：查找 iframe
        self._page.wait_for_timeout(3000)
        target_frame = self._find_target_frame()

        if not target_frame:
            print("[DEBUG] 首次未找到 iframe，等待重试...")
            self._page.wait_for_timeout(3000)
            target_frame = self._find_target_frame()

        if not target_frame:
            print(f"[DEBUG] 当前共有 {len(self._page.frames)} 个 frame:")
            for i, frame in enumerate(self._page.frames):
                print(f"[DEBUG]   Frame {i}: {frame.url}")
            non_main_frames = [f for f in self._page.frames
                                  if f != self._page.main_frame and f.url and "about:blank" not in f.url]
            if non_main_frames:
                target_frame = non_main_frames[-1]
                print(f"[INFO] 使用最后一个非主 frame: {target_frame.url}")
            else:
                raise Exception("未找到外包合同的 iframe 或新标签页")

        target_frame.wait_for_load_state("domcontentloaded")
        self._page.wait_for_timeout(3000)

        print(f"[SUCCESS] 已定位到外包合同iframe: {target_frame.url}")
        self._query_target = target_frame
        return target_frame

    def _get_fresh_frame(self) -> Optional[Frame]:
        """重新获取最新的目标 frame（防止 frame detach）"""
        self._page.wait_for_timeout(1000)
        frame = self._find_target_frame()
        if frame:
            self._query_target = frame
            return frame
        return None

    # ===================== MiniUI Combobox 单选 =====================

    def _select_miniui_combobox(self, target, control_id: str, target_value: str) -> bool:
        """
        通过 MiniUI API 在 combobox 中单选（模糊匹配）

        Args:
            target: iframe 或 Page 对象
            control_id: MiniUI 控件 ID
            target_value: 要匹配的值

        Returns:
            bool: 是否成功
        """
        print(f"[INFO] 正在选择 {control_id}: {target_value}")

        try:
            # 等待数据加载完成
            target.evaluate(f"""(controlId) => {{
                var combo = mini.get(controlId);
                if (!combo) return;
                var data = combo.data || [];
                data = data.filter(function(d) {{ return !d.__NullItem; }});
                if (data.length === 0) {{
                    combo.load();
                }}
            }}""", control_id)
            self._page.wait_for_timeout(2000)

            # 选择值
            result = target.evaluate(f"""(args) => {{
                var controlId = args.controlId;
                var targetValue = args.targetValue;
                var combo = mini.get(controlId);
                if (!combo) return {{success: false, error: '控件不存在'}};

                var data = (combo.data || []).filter(function(d) {{ return !d.__NullItem; }});
                if (data.length === 0) {{
                    return {{success: false, error: '数据为空'}};
                }}

                // 模糊匹配
                var matched = null;
                for (var i = 0; i < data.length; i++) {{
                    var keys = Object.keys(data[i]);
                    for (var k = 0; k < keys.length; k++) {{
                        var val = String(data[i][keys[k]] || '');
                        if (val && val.length > 1 && val.length < 100 && !/^[\\d.]+$/.test(val)) {{
                            if (val === targetValue || val.endsWith(targetValue)) {{
                                matched = data[i];
                                break;
                            }}
                        }}
                    }}
                    if (matched) break;
                }}

                if (!matched) {{
                    var samples = data.slice(0, 10).map(function(d) {{
                        var keys = Object.keys(d);
                        for (var k = 0; k < keys.length; k++) {{
                            var val = String(d[keys[k]] || '');
                            if (val && val.length > 1 && !/^[\\d.]+$/.test(val)) return val;
                        }}
                        return JSON.stringify(d).substring(0, 80);
                    }});
                    return {{success: false, error: '未匹配到选项', available: samples}};
                }}

                var val = matched.flexValue || matched.id || matched.value || '';
                combo.setValue(val);
                return {{success: true, selected: JSON.stringify(matched).substring(0, 200), setVal: val}};
            }}""", {"controlId": control_id, "targetValue": target_value})

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

    # ===================== MiniUI Combobox 按索引选择 =====================

    def _select_miniui_by_ui_index(self, target, control_id: str, index: int, label: str = "") -> bool:
        """
        通过 MiniUI API 精确打开指定控件的下拉列表，按索引点击选项

        Args:
            target: iframe 或 Page 对象
            control_id: MiniUI 控件 ID
            index: 选项索引（从0开始）
            label: 用于日志显示的名称

        Returns:
            bool: 是否成功
        """
        print(f"[INFO] 正在选择 {label or control_id}（第{index+1}个选项）...")

        try:
            # 通过 MiniUI API 精确打开指定控件的下拉弹窗，避免定位到相邻控件
            target.evaluate(f"""(controlId) => {{
                var combo = mini.get(controlId);
                if (combo && combo.showPopup) {{
                    combo.showPopup();
                }}
            }}""", control_id)
            self._page.wait_for_timeout(1500)

            # 在该控件专属的下拉弹窗中查找选项行
            # MiniUI 每个控件的 popup 会被添加到 body 末尾，通过 owner 定位
            result = target.evaluate(f"""(args) => {{
                var controlId = args.controlId;
                var idx = args.index;
                var combo = mini.get(controlId);
                if (!combo) return {{success: false, error: '控件不存在'}};

                var popup = combo.popup || combo._popup;
                if (!popup || !popup.el) return {{success: false, error: 'popup不存在'}};

                var popupEl = popup.el;
                var rows = popupEl.querySelectorAll('.mini-listbox-row');
                if (rows.length === 0) rows = popupEl.querySelectorAll('tr');

                if (idx >= rows.length) {{
                    return {{success: false, error: '索引越界', total: rows.length}};
                }}

                // 触发点击
                rows[idx].click();
                return {{success: true, total: rows.length, clickedIndex: idx}};
            }}""", {"controlId": control_id, "index": index})

            if result.get("success"):
                print(f"[SUCCESS] 已选择 {label or control_id}: 第{index+1}个选项（共{result.get('total')}个）")
                self._page.wait_for_timeout(500)
                return True
            else:
                print(f"[WARNING] {label or control_id}: {result.get('error')}")
                try:
                    self._page.keyboard.press("Escape")
                except Exception:
                    pass
                return False

        except Exception as e:
            print(f"[ERROR] 选择 {label or control_id} 失败: {e}")
            return False

    # ===================== MiniUI Combobox 多选（UI交互方式） =====================

    def _select_miniui_multi(self, target, control_id: str, target_values: List[str]) -> bool:
        """
        通过 UI 交互在 MiniUI combobox 中多选
        打开下拉列表 → 逐个勾选选项前的小方格复选框

        Args:
            target: iframe 或 Page 对象
            control_id: MiniUI 控件 ID
            target_values: 要匹配的值列表

        Returns:
            bool: 是否全部成功
        """
        print(f"[INFO] 正在多选 {control_id}: {target_values}")

        try:
            # 等待数据加载
            target.evaluate(f"""(controlId) => {{
                var combo = mini.get(controlId);
                if (!combo) return;
                var data = combo.data || [];
                data = data.filter(function(d) {{ return !d.__NullItem; }});
                if (data.length === 0) {{
                    combo.load();
                }}
            }}""", control_id)
            self._page.wait_for_timeout(2000)

            # 点击 combobox 的按钮打开下拉列表
            combo_btn = target.locator(f"#{control_id}\\$button, #{control_id} .mini-buttonedit-button").first
            if combo_btn.count() == 0:
                combo_btn = target.locator(f"#{control_id}\\$text").first
            if combo_btn.count() == 0:
                print(f"[WARNING] 未找到 {control_id} 的按钮")
                return False

            combo_btn.click()
            print("[INFO] 已打开下拉列表")
            self._page.wait_for_timeout(800)

            # 逐个勾选目标选项
            for tv in target_values:
                try:
                    # 在下拉列表中找到包含目标文本的行，点击其复选框
                    checkbox = target.locator(f".mini-listbox td:has-text('{tv}') .mini-listbox-checkbox").first
                    if checkbox.count() == 0:
                        checkbox = target.locator(f".mini-listbox .mini-checkbox:has-text('{tv}')").first
                    if checkbox.count() == 0:
                        target_td = target.locator(f".mini-listbox td:has-text('{tv}')").first
                        if target_td.count() > 0:
                            parent_row = target_td.locator("xpath=ancestor::tr").first
                            if parent_row.count() > 0:
                                checkbox = parent_row.locator(".mini-checkbox, .mini-listbox-checkbox").first

                    if checkbox.count() > 0:
                        checkbox.click()
                        print(f"[INFO] 已勾选: {tv}")
                        self._page.wait_for_timeout(500)
                    else:
                        print(f"[WARNING] 未找到选项: {tv}")
                        # 尝试滚动查找
                        listbox = target.locator(".mini-listbox:visible").first
                        if listbox.count() > 0:
                            for scroll_i in range(20):
                                listbox.evaluate("el => el.scrollTop += 50")
                                self._page.wait_for_timeout(300)
                                checkbox = target.locator(f".mini-listbox td:has-text('{tv}') .mini-listbox-checkbox").first
                                if checkbox.count() > 0:
                                    checkbox.click()
                                    print(f"[INFO] 滚动后勾选: {tv}")
                                    self._page.wait_for_timeout(500)
                                    break

                except Exception as e:
                    print(f"[WARNING] 勾选 '{tv}' 失败: {e}")

            # 关闭下拉列表
            self._page.wait_for_timeout(300)
            try:
                self._page.keyboard.press("Escape")
                self._page.wait_for_timeout(300)
            except Exception:
                pass

            print("[SUCCESS] 单据状态多选完成")
            return True

        except Exception as e:
            print(f"[ERROR] 多选 {control_id} 失败: {e}")
            return False

    # ===================== 输入申请期间 =====================

    def _input_date_range(self, target, start_date_str: str, end_date_str: str) -> bool:
        """
        通过 MiniUI API 输入申请期间

        Args:
            target: iframe 或 Page 对象
            start_date_str: 开始日期（YYYY年MM月DD日 格式）
            end_date_str: 结束日期（YYYY年MM月DD日 格式）

        Returns:
            bool: 是否成功
        """
        print(f"[INFO] 正在输入申请期间: {start_date_str} ~ {end_date_str}")

        # 转换日期格式 YYYY年MM月DD日 -> YYYY-MM-DD
        def to_date(s):
            m = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日?', s)
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            return s

        beg_val = to_date(start_date_str)
        end_val = to_date(end_date_str)
        print(f"[INFO] 转换后的日期格式: {beg_val} ~ {end_val}")

        try:
            target.evaluate(f"""(args) => {{
                var beg = mini.get('p_apply_begin_date');
                var end = mini.get('p_apply_end_date');
                if (beg) beg.setValue(args.beg);
                if (end) end.setValue(args.end);
            }}""", {"beg": beg_val, "end": end_val})

            print(f"[SUCCESS] 申请期间输入完成: {beg_val} ~ {end_val}")
            self._page.wait_for_timeout(500)
            return True

        except Exception as e:
            print(f"[ERROR] 输入申请期间失败: {e}")
            return False

    # ===================== 清空表单条件 =====================

    def _clear_form(self, target) -> bool:
        """
        清空表单中的已选条件（用于切换 SBU 时重置）

        Args:
            target: iframe 或 Page 对象
        """
        print("[INFO] 正在清空表单条件...")
        try:
            target.evaluate("""() => {
                // 清空 SBU
                var sbu = mini.get('p_sbu_id');
                if (sbu) sbu.setValue('');

                // 清空日期
                var beg = mini.get('p_apply_begin_date');
                var end = mini.get('p_apply_end_date');
                if (beg) beg.setValue('');
                if (end) end.setValue('');

                // 清空技术合作种类
                var tech = mini.get('p_tech_cooperation_type');
                if (tech) tech.setValue('');

                // 清空单据状态
                var state = mini.get('p_state');
                if (state) state.setValue('');
            }""")
            self._page.wait_for_timeout(1000)
            print("[INFO] 表单条件已清空")
            return True
        except Exception as e:
            print(f"[WARNING] 清空表单失败: {e}")
            return False

    # ===================== 查询与导出 =====================

    def _query_and_export(self, target, sbu_name: str = "",
                          start_date_str: str = "", end_date_str: str = "") -> Optional[str]:
        """
        填写条件、查询并导出

        Args:
            target: iframe 或 Page 对象
            sbu_name: SBU 名称，为空则不筛选
            start_date_str: 开始日期
            end_date_str: 结束日期

        Returns:
            Optional[str]: 下载文件路径，失败返回 None
        """
        print(f"[INFO] 开始查询{' [' + sbu_name + ']' if sbu_name else ' (所有)'}...")

        try:
            # 重新获取最新的 frame，防止 detach
            if not self._query_is_tab:
                frame = self._get_fresh_frame()
                if not frame:
                    print("[ERROR] 无法获取查询页面 frame")
                    return None
                target = frame
            self._page.wait_for_timeout(2000)

            # 清空表单条件
            self._clear_form(target)
            self._page.wait_for_timeout(1000)

            # 选择 SBU（如果提供）
            if sbu_name:
                if not self._select_miniui_combobox(target, self.MINIUI_IDS["sbu"], sbu_name):
                    print(f"[WARNING] 未能选择 SBU: {sbu_name}")
                self._page.wait_for_timeout(500)
            else:
                print("[INFO] SBU 未输入，跳过选择")

            # 输入申请期间
            if not self._input_date_range(target, start_date_str, end_date_str):
                print("[ERROR] 输入申请期间失败")
                return None

            # 选择技术合作种类：技术合作-II(人员类)（第二个选项，index=1，UI交互方式）
            if not self._select_miniui_by_ui_index(target, self.MINIUI_IDS["tech_coop_type"], index=2, label="技术合作种类"):
                print(f"[WARNING] 未能选择技术合作种类")
            self._page.wait_for_timeout(500)

            # 多选单据状态
            if not self._select_miniui_multi(target, self.MINIUI_IDS["state"], self.STATUS_OPTIONS):
                print("[WARNING] 部分单据状态未能选择")
            self._page.wait_for_timeout(500)

            # 点击查询按钮
            try:
                query_btn = target.locator("a#Query").first
                if query_btn.count() == 0:
                    query_btn = target.locator("a:has-text('查询')").first
                query_btn.click()
                print("[INFO] 已点击查询按钮")
                self._page.wait_for_timeout(5000)
                print("[INFO] 等待数据加载完成...")

                # 关闭可能弹出的 mini-modal 对话框
                try:
                    target.evaluate("""() => {
                        var modals = document.querySelectorAll('.mini-modal, .mini-window');
                        for (var m of modals) {
                            if (m.style.display !== 'none') {
                                m.style.display = 'none';
                            }
                        }
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
            except Exception as e:
                print(f"[ERROR] 查询失败: {e}")
                return None

            # 点击"导出合同"按钮
            print("[INFO] 正在导出合同...")
            try:
                export_btn = target.locator("a:has-text('导出合同')").first
                if export_btn.count() == 0:
                    export_btn = target.locator("a:has-text('导出')").first

                # 根据目标类型选择正确的上下文来监听下载事件
                if self._query_is_tab and self._query_target:
                    # 新标签页：使用该页面的上下文
                    download_context = self._query_target
                else:
                    # iframe：使用主页面的上下文（因为下载事件在主页面触发）
                    download_context = self._page

                # 全量查询时数据量大，需要更长超时时间
                with download_context.expect_download(timeout=180000) as download_info:
                    export_btn.click()
                    print("[INFO] 已点击导出合同按钮，等待下载完成...")

                download = download_info.value

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                sbu_part = sbu_name.replace("/", "_") if sbu_name else "全部"
                filename = f"外包合同_{sbu_part}_{start_date_str}_{end_date_str}_{timestamp}.xlsx"
                save_path = (self.download_dir / filename).resolve()
                download.save_as(str(save_path))
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
                    latest_file = max(files, key=lambda f: f.stat().st_mtime)
                    print(f"[INFO] 检测到下载文件: {latest_file}")
                    return str(latest_file)
                return None

        except Exception as e:
            print(f"[ERROR] 查询导出流程异常: {e}")
            try:
                screenshot_path = self.download_dir / "debug_error.png"
                self._page.screenshot(path=str(screenshot_path))
                print(f"[DEBUG] 错误截图已保存: {screenshot_path}")
            except Exception:
                pass
            return None

    # ===================== 主入口 =====================

    def download_contract_reports(
        self,
        sbu_list: Optional[List[str]] = None,
        start_date_str: str = "",
        end_date_str: str = "",
        start_browser: bool = True
    ) -> List[str]:
        """下载外包合同报表（主入口方法）"""
        downloaded_files = []

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

                target = self.navigate_to_contract()

                result = self._query_and_export(
                    target=target,
                    sbu_name=sbu,
                    start_date_str=start_date_str,
                    end_date_str=end_date_str
                )

                if result:
                    downloaded_files.append(result)

                if idx < len(sbu_list) - 1:
                    print("[INFO] 等待后继续下一个 SBU...")
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

            return downloaded_files

        except Exception as e:
            print(f"[ERROR] 下载外包合同报表失败: {e}")
            raise

        finally:
            if start_browser:
                self.stop()


def parse_date_input(date_str: str) -> str:
    """解析日期输入 "2025年1月1日" -> "2025年01月01日" """
    match = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日?', date_str.strip())
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        return f"{year}年{month:02d}月{day:02d}日"
    raise ValueError(f"无法解析日期: {date_str}，请使用格式如 '2025年1月1日'")


def main():
    """主函数 - 交互式输入"""
    try:
        from config import USERNAME, PASSWORD, DOWNLOAD_DIR
    except ImportError:
        USERNAME = ""
        PASSWORD = ""
        DOWNLOAD_DIR = "./downloads"

    import argparse

    parser = argparse.ArgumentParser(description="外包合同下载工具")
    parser.add_argument("-u", "--username", help="登录用户名", default=USERNAME)
    parser.add_argument("-p", "--password", help="登录密码", default=PASSWORD)
    parser.add_argument("-s", "--sbu", help="SBU列表（逗号分隔），不填则查询全部", default=None)
    parser.add_argument("--start", help="开始日期，如 '2025年1月1日'", default=None)
    parser.add_argument("--end", help="结束日期，如 '2025年12月31日'", default=None)
    parser.add_argument("-d", "--download-dir", help="下载目录", default=DOWNLOAD_DIR)
    parser.add_argument("--headless", action="store_true", help="隐藏浏览器（无头模式）")

    args = parser.parse_args()

    username = args.username or input("请输入用户名: ")
    password = args.password or input("请输入密码: ")

    sbu_input = args.sbu if args.sbu is not None else input("请输入SBU（多个用逗号分隔，直接回车不输入）: ").strip()
    sbu_list = [s.strip() for s in re.split(r'[,，]', sbu_input) if s.strip()] if sbu_input else []

    start_input = args.start if args.start is not None else input("请输入开始日期（如 2025年1月1日）: ").strip()
    start_date_str = parse_date_input(start_input)

    end_input = args.end if args.end is not None else input("请输入结束日期（如 2025年12月31日）: ").strip()
    end_date_str = parse_date_input(end_input)

    print(f"\n{'='*60}")
    print(f"  外包合同下载工具")
    print(f"{'='*60}")
    print(f"  用户名: {username}")
    print(f"  SBU: {', '.join(sbu_list) if sbu_list else '全部'}")
    print(f"  申请期间: {start_date_str} ~ {end_date_str}")
    print(f"  技术合作种类: {ContractDownloader.TECH_COOP_TYPE}")
    print(f"  单据状态: 审批流程中, 审批流程结束, 待确认到岗中")
    print(f"  下载目录: {args.download_dir}")
    print(f"{'='*60}\n")

    with ContractDownloader(
        username=username,
        password=password,
        download_dir=args.download_dir,
        headless=args.headless
    ) as downloader:
        results = downloader.download_contract_reports(
            sbu_list=sbu_list if sbu_list else None,
            start_date_str=start_date_str,
            end_date_str=end_date_str,
            start_browser=False
        )

    print(f"\n{'='*60}")
    print(f"  下载完成")
    print(f"{'='*60}")
    if results:
        print(f"  共下载 {len(results)} 个文件:")
        for f in results:
            print(f"    - {f}")
    else:
        print("  未成功下载任何文件")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
