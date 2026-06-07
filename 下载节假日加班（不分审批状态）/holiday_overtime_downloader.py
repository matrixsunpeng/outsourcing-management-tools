"""
节假日加班下载自动化工具
使用 Playwright 实现网页自动化操作
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from playwright.sync_api import sync_playwright, Page, Browser, Playwright, Frame


class HolidayOvertimeDownloader:
    """节假日加班下载器"""

    LOGIN_URL = "https://ims.asiainfo.com/AIOMS/Jsp/main.jsp"

    SELECTORS = {
        "username_input": "input[name='username'], input[id='username'], input[type='text']",
        "password_input": "input[name='password'], input[id='password'], input[type='password']",
        "login_button": "button[type='submit'], input[type='submit'], button:has-text('登录'), input[value*='登录']",
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

    def _find_holiday_frame(self) -> Optional[Frame]:
        possible_keywords = [
            "holiday", "overtime", "jiari", "jiaban",
            "HolidayOvertime", "holidayOvertime", "outsource"
        ]
        for frame in self._page.frames:
            frame_url = frame.url
            if frame == self._page.main_frame or not frame_url or "about:blank" in frame_url:
                continue
            for keyword in possible_keywords:
                if keyword.lower() in frame_url.lower():
                    print(f"[INFO] 找到节假日加班查询iframe: {frame_url}")
                    return frame
        return None

    def navigate_to_holiday_query(self):
        """
        导航到节假日加班查询页面（iframe 内的 Layui 页面）

        步骤：
        1. 双击左侧菜单"外包数据查询"展开子菜单
        2. 单击"节假日加班查询"
        3. 在 iframe 中定位查询页面

        Returns:
            Frame: 节假日加班查询 iframe 对象
        """
        print("[INFO] 正在导航到节假日加班查询页面...")
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

        # 单击"节假日加班查询"
        # 先尝试新标签页模式
        try:
            with self._page.context.expect_page(timeout=5000) as new_page_info:
                holiday_link = self._page.locator(
                    ".mini-tree-nodetext:has-text('节假日加班查询')"
                ).first
                holiday_link.click()
                print("[INFO] 已单击【节假日加班查询】")

            self._query_target = new_page_info.value
            self._query_target.wait_for_load_state("domcontentloaded")
            self._query_target.wait_for_timeout(3000)
            self._query_is_tab = True
            print(f"[SUCCESS] 节假日加班查询页面已打开(新标签页): {self._query_target.url}")
            return self._query_target

        except Exception:
            print("[INFO] 未检测到新标签页，尝试查找 iframe...")
            self._query_is_tab = False

        # 回退方案：查找 iframe
        self._page.wait_for_timeout(3000)
        target_frame = self._find_holiday_frame()

        if not target_frame:
            print("[DEBUG] 首次未找到 iframe，等待重试...")
            self._page.wait_for_timeout(3000)
            target_frame = self._find_holiday_frame()

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
                raise Exception("未找到节假日加班查询的 iframe 或新标签页")

        # 等待 iframe 内容完全渲染（Layui 需要加载 layui.use）
        target_frame.wait_for_load_state("domcontentloaded")
        self._page.wait_for_timeout(5000)

        print(f"[SUCCESS] 已定位到节假日加班查询iframe: {target_frame.url}")
        self._query_target = target_frame
        return target_frame

    # ===================== 选择 BU =====================

    def _select_bu(self, frame: Frame, bu_name: str) -> bool:
        """
        在 iframe 中选择 BU（Layui select 元素）

        Args:
            frame: iframe 对象
            bu_name: 要选择的 BU 名称

        Returns:
            bool: 是否成功选择
        """
        print(f"[INFO] 正在选择 BU: {bu_name}")

        try:
            # BU 是标准 HTML <select id="bu">
            bu_select = frame.locator("select#bu")
            if bu_select.count() == 0:
                print("[WARNING] 未找到 BU 下拉框")
                return False

            # 列出所有选项
            options = bu_select.locator("option").all()
            option_texts = []
            for opt in options:
                try:
                    t = opt.text_content().strip()
                    if t:
                        option_texts.append(t)
                except Exception:
                    continue
            print(f"[DEBUG] BU 选项: {option_texts[:20]}")

            # 通过 JS 设置 select 的值（支持模糊匹配，如 CTC 匹配 (121)亚信科技CTC）
            matched = frame.evaluate(f"""(buName) => {{
                var select = document.getElementById('bu');
                if (!select) return null;
                var options = select.options;
                for (var i = 0; i < options.length; i++) {{
                    var text = options[i].text.trim();
                    // 精确匹配或模糊匹配（如 CTC 匹配 亚信科技CTC）
                    if (text === buName || options[i].value === buName || text.endsWith(buName)) {{
                        select.value = options[i].value;
                        select.dispatchEvent(new Event('change', {{bubbles: true}}));
                        if (typeof layui !== 'undefined' && layui.form) {{
                            try {{ layui.form.render('select'); }} catch(e) {{}}
                        }}
                        return text;
                    }}
                }}
                return null;
            }}""", bu_name)

            if matched:
                print(f"[SUCCESS] 已选择 BU: {matched}")
                self._page.wait_for_timeout(500)
                return True
            else:
                print(f"[WARNING] BU 选项中未找到 '{bu_name}'")
                return False

        except Exception as e:
            print(f"[ERROR] 选择 BU 失败: {e}")
            return False

    # ===================== 输入日期范围 =====================

    def _input_date_range(self, frame: Frame, start_date_str: str, end_date_str: str) -> bool:
        """
        输入节假日范围（Layui 日期输入框）
        页面使用 layui 日期控件，输入框 id 为 beg 和 end

        Args:
            frame: iframe 对象
            start_date_str: 开始日期
            end_date_str: 结束日期

        Returns:
            bool: 是否成功输入
        """
        print(f"[INFO] 正在输入节假日范围: {start_date_str} ~ {end_date_str}")

        # 将 YYYY年MM月DD日 格式转换为 YYYY-MM-DD 格式（Layui 日期控件要求）
        def to_layui_date(s):
            m = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日?', s)
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            return s

        beg_val = to_layui_date(start_date_str)
        end_val = to_layui_date(end_date_str)
        print(f"[INFO] 转换后的日期格式: {beg_val} ~ {end_val}")

        try:
            # 直接通过 id 定位输入框
            beg_input = frame.locator("input#beg")
            end_input = frame.locator("input#end")

            if beg_input.count() == 0 or end_input.count() == 0:
                print("[ERROR] 未找到日期输入框 (input#beg / input#end)")
                return False

            # 输入开始日期（用 JS 直接设值，避免触发 Layui 日期选择器弹出遮挡）
            frame.evaluate(f"""(val) => {{
                var el = document.getElementById('beg');
                if (el) {{ el.value = val; el.dispatchEvent(new Event('input', {{bubbles:true}})); el.dispatchEvent(new Event('change', {{bubbles:true}})); }}
            }}""", beg_val)
            print(f"[INFO] 已输入开始日期: {beg_val}")
            self._page.wait_for_timeout(300)

            # 关闭可能弹出的 Layui 日期选择器
            try:
                frame.evaluate("""() => {
                    var datepicker = document.querySelector('.layui-laydate');
                    if (datepicker) datepicker.remove();
                }""")
            except Exception:
                pass
            self._page.wait_for_timeout(200)

            # 输入结束日期
            frame.evaluate(f"""(val) => {{
                var el = document.getElementById('end');
                if (el) {{ el.value = val; el.dispatchEvent(new Event('input', {{bubbles:true}})); el.dispatchEvent(new Event('change', {{bubbles:true}})); }}
            }}""", end_val)
            print(f"[INFO] 已输入结束日期: {end_val}")
            self._page.wait_for_timeout(300)

            # 再次关闭可能弹出的日期选择器
            try:
                frame.evaluate("""() => {
                    var datepicker = document.querySelector('.layui-laydate');
                    if (datepicker) datepicker.remove();
                }""")
            except Exception:
                pass

            print("[SUCCESS] 节假日范围输入完成")
            return True

        except Exception as e:
            print(f"[ERROR] 输入节假日范围失败: {e}")
            return False

    # ===================== 查询与导出 =====================

    def _query_and_export(self, frame: Frame, sbu_name: str = "",
                          start_date_str: str = "", end_date_str: str = "") -> Optional[str]:
        """
        在 iframe 中填写条件、查询并导出

        Args:
            frame: 节假日加班查询 iframe 对象
            sbu_name: SBU 名称，为空则不筛选
            start_date_str: 开始日期
            end_date_str: 结束日期

        Returns:
            Optional[str]: 下载文件路径，失败返回 None
        """
        print(f"[INFO] 开始查询{' [' + sbu_name + ']' if sbu_name else ' (所有SBU)'}...")

        try:
            self._page.wait_for_timeout(3000)

            # 选择 BU（如果指定了）
            if sbu_name:
                if not self._select_bu(frame, sbu_name):
                    print(f"[WARNING] 未能选择 BU: {sbu_name}")
                self._page.wait_for_timeout(500)

            # 输入节假日范围
            if not self._input_date_range(frame, start_date_str, end_date_str):
                print("[ERROR] 输入节假日范围失败")
                return None

            self._page.wait_for_timeout(1000)

            # 点击查询按钮
            try:
                # Layui 页面中的查询按钮是 <button> 标签
                query_btn = frame.locator("button:has-text('查询')").first
                if query_btn.count() == 0:
                    query_btn = frame.locator("text=查询").first
                query_btn.click()
                print("[INFO] 已点击查询按钮")
                self._page.wait_for_timeout(5000)
                print("[INFO] 等待数据加载完成...")
            except Exception as e:
                print(f"[ERROR] 查询失败: {e}")
                return None

            # 点击导出按钮
            print("[INFO] 正在导出 Excel...")
            try:
                # 用主页面监听下载事件
                with self._page.expect_download(timeout=60000) as download_info:
                    export_btn = frame.locator(".layui-table-tool a:has-text('导出')").first
                    if export_btn.count() == 0:
                        export_btn = frame.locator("a:has-text('导出')").first
                    if export_btn.count() == 0:
                        export_btn = frame.locator("text=导出").first
                    export_btn.click()
                    print("[INFO] 已点击导出按钮")

                download = download_info.value

                # 生成文件名
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                sbu_part = sbu_name.replace("/", "_") if sbu_name else "全部"
                filename = f"节假日加班_{sbu_part}_{start_date_str}_{end_date_str}_{timestamp}.xlsx"
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
                # 检查下载目录是否有新文件
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

    def download_holiday_overtime_reports(
        self,
        sbu_list: Optional[List[str]] = None,
        start_date_str: str = "",
        end_date_str: str = "",
        start_browser: bool = True
    ) -> List[str]:
        """
        下载节假日加班报表（主入口方法）

        Args:
            sbu_list: SBU 名称列表，为空则查询所有
            start_date_str: 开始日期，格式 YYYY年MM月DD日
            end_date_str: 结束日期，格式 YYYY年MM月DD日
            start_browser: 是否自动启动/关闭浏览器

        Returns:
            List[str]: 下载文件路径列表
        """
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

                frame = self.navigate_to_holiday_query()

                result = self._query_and_export(
                    frame=frame,
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
            print(f"[ERROR] 下载节假日加班报表失败: {e}")
            raise

        finally:
            if start_browser:
                self.stop()


def parse_date_input(date_str: str) -> str:
    """
    解析日期输入，支持格式：
    - "2025年1月1日" → "2025年01月01日"

    Raises:
        ValueError: 解析失败
    """
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

    parser = argparse.ArgumentParser(description="节假日加班下载工具")
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
    print(f"  节假日加班下载工具")
    print(f"{'='*60}")
    print(f"  用户名: {username}")
    print(f"  SBU: {', '.join(sbu_list) if sbu_list else '全部'}")
    print(f"  节假日范围: {start_date_str} ~ {end_date_str}")
    print(f"  下载目录: {args.download_dir}")
    print(f"{'='*60}\n")

    with HolidayOvertimeDownloader(
        username=username,
        password=password,
        download_dir=args.download_dir,
        headless=args.headless
    ) as downloader:
        results = downloader.download_holiday_overtime_reports(
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
