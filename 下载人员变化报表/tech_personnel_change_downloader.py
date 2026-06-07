"""
技术合作人员变化表下载自动化工具
使用 Playwright 实现网页自动化操作
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from playwright.sync_api import sync_playwright, Page, Browser, Playwright, Frame


class TechPersonnelChangeDownloader:
    """技术合作人员变化表下载器"""

    LOGIN_URL = "https://ims.asiainfo.com/AIOMS/Jsp/main.jsp"

    SELECTORS = {
        "username_input": "input[name='username'], input[id='username'], input[type='text']",
        "password_input": "input[name='password'], input[id='password'], input[type='password']",
        "login_button": "button[type='submit'], input[type='submit'], button:has-text('登录'), input[value*='登录']",
    }

    # MiniUI 控件 ID 映射（技术合作人员变化表页面）
    MINIUI_IDS = {
        "sbu": "p_sbu",
        "begin_date": "p_work_start_date",
        "end_date": "p_work_end_date",
        "status": "p_staff_state",
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
        self.download_dir = Path(download_dir) if download_dir else Path(__file__).resolve().parent.parent / "downloads"
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
        """查找技术合作人员变化表的 iframe（关键词匹配 URL）"""
        possible_keywords = [
            "techPersonChange", "TechPersonChange", "tech_person_change",
            "techCooperation", "TechCooperation", "cooperationPerson",
            "personChange", "PersonChange"
        ]
        for frame in self._page.frames:
            frame_url = frame.url
            if frame == self._page.main_frame or not frame_url or "about:blank" in frame_url:
                continue
            for keyword in possible_keywords:
                if keyword.lower() in frame_url.lower():
                    print(f"[INFO] 找到技术合作人员变化表iframe: {frame_url}")
                    return frame
        return None

    def navigate_to_tech_personnel_change(self) -> Frame:
        """
        导航到技术合作人员变化表页面

        Returns:
            Frame: 技术合作人员变化表 iframe 对象或 Page 对象
        """
        print("[INFO] 正在导航到技术合作人员变化表页面...")
        self._page.wait_for_timeout(3000)

        # 双击"外包报表"展开子菜单
        try:
            outsource_row = self._page.locator(".mini-tree-nodetext:has-text('外包报表')").first
            outsource_row.dblclick()
            print("[INFO] 已双击【外包报表】菜单")
            self._page.wait_for_timeout(2000)
        except Exception as e:
            print(f"[DEBUG] 双击菜单时出错: {e}")
            try:
                self._page.evaluate("""
                    var tree = mini.get("tree1");
                    var nodes = tree.getData();
                    for(var i=0; i<nodes.length; i++){
                        if(nodes[i].text == '外包报表'){
                            tree.expandNode(nodes[i]);
                            break;
                        }
                    }
                """)
                print("[INFO] 通过JS展开了外包报表菜单")
                self._page.wait_for_timeout(2000)
            except Exception as e2:
                print(f"[DEBUG] JS展开也失败: {e2}")

        self._page.wait_for_timeout(2000)

        # 单击"技术合作人员变化表"
        try:
            with self._page.context.expect_page(timeout=5000) as new_page_info:
                link = self._page.locator(".mini-tree-nodetext:has-text('技术合作人员变化表')").first
                link.click()
                print("[INFO] 已单击【技术合作人员变化表】")

            self._query_target = new_page_info.value
            self._query_target.wait_for_load_state("domcontentloaded")
            self._query_target.wait_for_timeout(3000)
            self._query_is_tab = True
            print(f"[SUCCESS] 技术合作人员变化表页面已打开(新标签页): {self._query_target.url}")
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
                raise Exception("未找到技术合作人员变化表的 iframe 或新标签页")

        target_frame.wait_for_load_state("domcontentloaded")
        self._page.wait_for_timeout(3000)

        print(f"[SUCCESS] 已定位到技术合作人员变化表iframe: {target_frame.url}")
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

    def _select_miniui_combobox(self, frame: Frame, control_id: str, target_value: str) -> bool:
        """
        通过 MiniUI API 在 combobox 中单选（模糊匹配）

        Args:
            frame: iframe 对象
            control_id: MiniUI 控件 ID（如 p_sbu_id）
            target_value: 要匹配的值（如 CTC）

        Returns:
            bool: 是否成功
        """
        print(f"[INFO] 正在选择 {control_id}: {target_value}")

        try:
            # 分两步执行：先等待数据加载，再选择
            # 步骤1：等待数据加载完成
            frame.evaluate(f"""(controlId) => {{
                var combo = mini.get(controlId);
                if (!combo) return;
                var data = combo.data || [];
                data = data.filter(function(d) {{ return !d.__NullItem; }});
                if (data.length === 0) {{
                    combo.load();
                }}
            }}""", control_id)
            self._page.wait_for_timeout(2000)

            # 步骤2：选择值
            result = frame.evaluate(f"""(args) => {{
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

                // 使用 flexValue 作为值（该页面的数据结构用 flexValue 做值字段）
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

    def _select_miniui_combobox_by_text(self, frame: Frame, control_id: str, target_value: str) -> bool:
        """
        通过文本输入方式在 MiniUI combobox 中选择值（适用于只能输入的控件）

        Args:
            frame: iframe 对象
            control_id: MiniUI 控件 ID
            target_value: 要输入的值

        Returns:
            bool: 是否成功
        """
        print(f"[INFO] 正在输入 {control_id}: {target_value}")

        try:
            # 找到输入框并输入值
            text_input = frame.locator(f"#{control_id}\\$text, #{control_id} .mini-textbox-input").first
            if text_input.count() > 0:
                text_input.click()
                text_input.fill(target_value)
                self._page.wait_for_timeout(300)
                self._page.keyboard.press("Enter")
                print(f"[SUCCESS] 已输入 {control_id}: {target_value}")
                return True
            else:
                # 直接使用 MiniUI API
                frame.evaluate(f"""(args) => {{
                    var combo = mini.get(args.controlId);
                    if (combo) {{
                        combo.setValue(args.value);
                        combo.setText(args.value);
                    }}
                }}""", {"controlId": control_id, "value": target_value})
                print(f"[SUCCESS] 已通过API设置 {control_id}: {target_value}")
                return True

        except Exception as e:
            print(f"[ERROR] 输入 {control_id} 失败: {e}")
            return False

    # ===================== 输入工作时间 =====================

    def _input_date_range(self, frame: Frame, start_date_str: str, end_date_str: str) -> bool:
        """
        通过 MiniUI API 输入工作时间

        Args:
            frame: iframe 对象
            start_date_str: 开始日期（YYYY年MM月DD日 格式）
            end_date_str: 结束日期（YYYY年MM月DD日 格式）

        Returns:
            bool: 是否成功
        """
        print(f"[INFO] 正在输入工作时间: {start_date_str} ~ {end_date_str}")

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
            # 尝试通过 MiniUI API 设置日期
            result = frame.evaluate(f"""(args) => {{
                var result = {{success: false, begFound: false, endFound: false}};

                // 尝试多种可能的控件 ID
                var begIds = ['p_work_start_date', 'p_begin_date', 'p_start_date', 'begin_date', 'startDate'];
                var endIds = ['p_work_end_date', 'p_end_date', 'end_date', 'endDate'];

                var beg = null;
                var end = null;

                for (var i = 0; i < begIds.length; i++) {{
                    beg = mini.get(begIds[i]);
                    if (beg) {{
                        result.begFound = true;
                        result.begId = begIds[i];
                        break;
                    }}
                }}

                for (var i = 0; i < endIds.length; i++) {{
                    end = mini.get(endIds[i]);
                    if (end) {{
                        result.endFound = true;
                        result.endId = endIds[i];
                        break;
                    }}
                }}

                if (beg) beg.setValue(args.beg);
                if (end) end.setValue(args.end);

                result.success = (beg !== null || end !== null);
                return result;
            }}""", {"beg": beg_val, "end": end_val})

            if result.get("success"):
                print(f"[SUCCESS] 工作时间输入完成: {beg_val} ~ {end_val}")
                print(f"[DEBUG] 使用的控件ID - 开始: {result.get('begId')}, 结束: {result.get('endId')}")
                self._page.wait_for_timeout(500)
                return True
            else:
                # 回退方案：直接在输入框输入
                print("[INFO] 尝试直接在日期输入框输入...")
                beg_input = frame.locator("input[placeholder*='开始'], input[placeholder*='起始']").first
                end_input = frame.locator("input[placeholder*='结束'], input[placeholder*='终止']").first

                if beg_input.count() > 0:
                    beg_input.fill(beg_val)
                if end_input.count() > 0:
                    end_input.fill(end_val)

                return True

        except Exception as e:
            print(f"[ERROR] 输入工作时间失败: {e}")
            return False

    # ===================== 查询与导出 =====================

    def _query_and_export(self, frame: Frame, sbu_name: str = "",
                          status_name: str = "",
                          start_date_str: str = "", end_date_str: str = "") -> Optional[str]:
        """
        在页面中填写条件、查询并导出

        Args:
            frame: 技术合作人员变化表 iframe 对象
            sbu_name: SBU 名称，为空则不筛选
            status_name: 人员状态名称，为空则不筛选
            start_date_str: 开始日期
            end_date_str: 结束日期

        Returns:
            Optional[str]: 下载文件路径，失败返回 None
        """
        print(f"[INFO] 开始查询 [SBU: {sbu_name or '全部'}, 状态: {status_name or '全部'}]...")

        try:
            # 重新获取最新的 frame，防止 detach
            if self._query_is_tab:
                frame = self._query_target
            else:
                frame = self._get_fresh_frame()
            if not frame:
                print("[ERROR] 无法获取查询页面 frame")
                return None
            self._page.wait_for_timeout(2000)

            # 选择 SBU
            if sbu_name:
                if not self._select_miniui_combobox(frame, self.MINIUI_IDS["sbu"], sbu_name):
                    print(f"[WARNING] 未能选择 SBU: {sbu_name}")
                self._page.wait_for_timeout(500)

            # 输入人员状态
            if status_name:
                if not self._select_miniui_combobox_by_text(frame, self.MINIUI_IDS["status"], status_name):
                    print(f"[WARNING] 未能输入人员状态: {status_name}")
                self._page.wait_for_timeout(500)

            # 输入工作时间
            if not self._input_date_range(frame, start_date_str, end_date_str):
                print("[ERROR] 输入工作时间失败")
                return None

            # 点击查询按钮
            try:
                query_btn = frame.locator("a#Query, a#query, button#Query").first
                if query_btn.count() == 0:
                    query_btn = frame.locator("a:has-text('查询'), button:has-text('查询')").first
                query_btn.click()
                print("[INFO] 已点击查询按钮")
                self._page.wait_for_timeout(5000)
                print("[INFO] 等待数据加载完成...")

                # 关闭可能弹出的对话框
                try:
                    frame.evaluate("""() => {
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

            # 点击导出按钮
            print("[INFO] 正在导出 Excel...")
            try:
                with self._page.expect_download(timeout=60000) as download_info:
                    export_btn = frame.locator("a:has-text('导出Excel'), button:has-text('导出Excel')").first
                    export_btn.click()
                    print("[INFO] 已点击导出按钮")

                download = download_info.value

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                sbu_part = sbu_name.replace("/", "_") if sbu_name else "全部SBU"
                status_part = status_name.replace("/", "_") if status_name else "全部状态"
                filename = f"技术合作人员变化表_{sbu_part}_{status_part}_{start_date_str}_{end_date_str}_{timestamp}.xlsx"
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

    def download_tech_personnel_change_reports(
        self,
        sbu_list: Optional[List[str]] = None,
        status_list: Optional[List[str]] = None,
        start_date_str: str = "",
        end_date_str: str = "",
        start_browser: bool = True
    ) -> List[str]:
        """
        下载技术合作人员变化表（主入口方法）

        Args:
            sbu_list: SBU 列表，为空或 None 则不筛选
            status_list: 人员状态列表，为空或 None 则不筛选
            start_date_str: 开始日期（YYYY年MM月DD日格式）
            end_date_str: 结束日期（YYYY年MM月DD日格式）
            start_browser: 是否自动启动浏览器

        Returns:
            List[str]: 下载文件路径列表
        """
        downloaded_files = []

        try:
            if start_browser:
                self.start()

            self.login()

            if not sbu_list:
                sbu_list = [""]  # 空字符串表示不筛选
            if not status_list:
                status_list = [""]  # 空字符串表示不筛选

            total_count = len(sbu_list) * len(status_list)
            current_count = 0

            for sbu in sbu_list:
                for status in status_list:
                    current_count += 1
                    print(f"\n{'='*60}")
                    print(f"[INFO] 处理第 {current_count}/{total_count} 个")
                    print(f"[INFO] SBU: {sbu or '全部'}, 人员状态: {status or '全部'}")
                    print(f"{'='*60}")

                    frame = self.navigate_to_tech_personnel_change()

                    result = self._query_and_export(
                        frame=frame,
                        sbu_name=sbu,
                        status_name=status,
                        start_date_str=start_date_str,
                        end_date_str=end_date_str
                    )

                    if result:
                        downloaded_files.append(result)

                    # 如果还有下一个任务，关闭当前标签页或刷新页面
                    if current_count < total_count:
                        print("[INFO] 等待后继续下一个查询...")
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
            print(f"[ERROR] 下载技术合作人员变化表失败: {e}")
            raise

        finally:
            if start_browser:
                self.stop()


def parse_date_input(date_str: str) -> str:
    """解析日期输入 "2025年1月1日" → "2025年01月01日" """
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

    parser = argparse.ArgumentParser(description="技术合作人员变化表下载工具")
    parser.add_argument("-u", "--username", help="登录用户名", default=USERNAME)
    parser.add_argument("-p", "--password", help="登录密码", default=PASSWORD)
    parser.add_argument("-s", "--sbu", help="SBU列表（逗号分隔），不填则查询全部", default=None)
    parser.add_argument("--status", help="人员状态列表（逗号分隔），不填则查询全部", default=None)
    parser.add_argument("--start", help="开始日期，如 '2025年1月1日'", default=None)
    parser.add_argument("--end", help="结束日期，如 '2025年12月31日'", default=None)
    parser.add_argument("-d", "--download-dir", help="下载目录", default=DOWNLOAD_DIR)
    parser.add_argument("--headless", action="store_true", help="隐藏浏览器（无头模式）")

    args = parser.parse_args()

    # 获取用户名密码
    username = args.username or input("请输入用户名: ")
    password = args.password or input("请输入密码: ")

    # 获取 SBU 列表
    sbu_input = args.sbu if args.sbu is not None else input("请输入SBU（多个用逗号分隔，直接回车不输入）: ").strip()
    sbu_list = [s.strip() for s in re.split(r'[,，]', sbu_input) if s.strip()] if sbu_input else []

    # 获取人员状态列表
    status_input = args.status if args.status is not None else input("请输入人员状态（多个用逗号分隔，直接回车不输入）: ").strip()
    status_list = [s.strip() for s in re.split(r'[,，]', status_input) if s.strip()] if status_input else []

    # 获取日期
    start_input = args.start if args.start is not None else input("请输入开始日期（如 2025年1月1日）: ").strip()
    start_date_str = parse_date_input(start_input)

    end_input = args.end if args.end is not None else input("请输入结束日期（如 2025年12月31日）: ").strip()
    end_date_str = parse_date_input(end_input)

    print(f"\n{'='*60}")
    print(f"  技术合作人员变化表下载工具")
    print(f"{'='*60}")
    print(f"  用户名: {username}")
    print(f"  SBU: {', '.join(sbu_list) if sbu_list else '全部'}")
    print(f"  人员状态: {', '.join(status_list) if status_list else '全部'}")
    print(f"  工作时间: {start_date_str} ~ {end_date_str}")
    print(f"  下载目录: {args.download_dir}")
    print(f"{'='*60}\n")

    with TechPersonnelChangeDownloader(
        username=username,
        password=password,
        download_dir=args.download_dir,
        headless=args.headless
    ) as downloader:
        results = downloader.download_tech_personnel_change_reports(
            sbu_list=sbu_list if sbu_list else None,
            status_list=status_list if status_list else None,
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
