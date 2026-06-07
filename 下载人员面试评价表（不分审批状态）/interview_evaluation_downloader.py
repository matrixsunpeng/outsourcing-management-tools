"""
人员面试评价表下载自动化工具
使用 Playwright 实现网页自动化操作
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from playwright.sync_api import sync_playwright, Page, Browser, Playwright, Frame


class InterviewEvaluationDownloader:
    """人员面试评价表下载器"""

    LOGIN_URL = "https://ims.asiainfo.com/AIOMS/Jsp/main.jsp"

    SELECTORS = {
        "username_input": "input[name='username'], input[id='username'], input[type='text']",
        "password_input": "input[name='password'], input[id='password'], input[type='password']",
        "login_button": "button[type='submit'], input[type='submit'], button:has-text('登录'), input[value*='登录']",
    }

    def __init__(self, username: str, password: str, download_dir: Optional[str] = None, headless: bool = False):
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
        print("[SUCCESS] 登录成功")
        return True

    # ===================== 导航 =====================

    def _find_target_frame(self) -> Optional[Frame]:
        possible_keywords = [
            "interview", "evaluation", "interviewEval",
            "msrpInterview", "InterviewEval", "面试评价",
            "resume_evaluation", "resumeEvaluation"
        ]
        for frame in self._page.frames:
            frame_url = frame.url
            if frame == self._page.main_frame or not frame_url or "about:blank" in frame_url:
                continue
            for keyword in possible_keywords:
                if keyword.lower() in frame_url.lower():
                    return frame
        return None

    def navigate_to_page(self) -> Frame:
        """导航到人员面试评价表页面"""
        print("[INFO] 正在导航到人员面试评价表页面...")
        self._page.wait_for_timeout(3000)

        # 双击"招聘过程管理"
        try:
            menu_row = self._page.locator(".mini-tree-nodetext:has-text('招聘过程管理')").first
            menu_row.dblclick()
            print("[INFO] 已双击【招聘过程管理】菜单")
            self._page.wait_for_timeout(2000)
        except Exception as e:
            print(f"[DEBUG] 双击菜单出错: {e}")
            try:
                self._page.evaluate("""
                    var tree = mini.get("tree1");
                    var nodes = tree.getData();
                    for(var i=0; i<nodes.length; i++){
                        if(nodes[i].text == '招聘过程管理'){ tree.expandNode(nodes[i]); break; }
                    }
                """)
                self._page.wait_for_timeout(2000)
            except Exception:
                pass

        self._page.wait_for_timeout(2000)

        # 单击"人员面试评价表"
        try:
            with self._page.context.expect_page(timeout=5000) as new_page_info:
                link = self._page.locator(".mini-tree-nodetext:has-text('人员面试评价表')").first
                link.click()
                print("[INFO] 已单击【人员面试评价表】")
            self._query_target = new_page_info.value
            self._query_target.wait_for_load_state("domcontentloaded")
            self._query_target.wait_for_timeout(3000)
            self._query_is_tab = True
            print(f"[SUCCESS] 页面已打开(新标签页)")
            return self._query_target
        except Exception:
            self._query_is_tab = False

        # 回退：查找 iframe
        self._page.wait_for_timeout(3000)
        target_frame = self._find_target_frame()
        if not target_frame:
            self._page.wait_for_timeout(3000)
            target_frame = self._find_target_frame()
        if not target_frame:
            non_main = [f for f in self._page.frames if f != self._page.main_frame and f.url and "about:blank" not in f.url]
            if non_main:
                target_frame = non_main[-1]
            else:
                raise Exception("未找到人员面试评价表的 iframe")
        target_frame.wait_for_load_state("domcontentloaded")
        self._page.wait_for_timeout(5000)
        print(f"[SUCCESS] 已定位到iframe: {target_frame.url}")
        self._query_target = target_frame
        return target_frame

    def _get_fresh_frame(self) -> Optional[Frame]:
        self._page.wait_for_timeout(1000)
        frame = self._find_target_frame()
        if frame:
            self._query_target = frame
            return frame
        return None

    # ===================== 选择 BU（Layui select） =====================

    def _select_bu(self, frame: Frame, bu_name: str) -> bool:
        print(f"[INFO] 正在选择 BU: {bu_name}")
        try:
            matched = frame.evaluate(f"""(buName) => {{
                var select = document.getElementById('bu');
                if (!select) return null;
                var options = select.options;
                for (var i = 0; i < options.length; i++) {{
                    var text = options[i].text.trim();
                    if (text === buName || text.endsWith(buName)) {{
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

    # ===================== 输入申请期间 =====================

    def _input_date_range(self, frame: Frame, start_date_str: str, end_date_str: str) -> bool:
        print(f"[INFO] 正在输入申请期间: {start_date_str} ~ {end_date_str}")

        def to_date(s):
            m = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日?', s)
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            return s

        beg_val = to_date(start_date_str)
        end_val = to_date(end_date_str)
        print(f"[INFO] 转换后: {beg_val} ~ {end_val}")

        try:
            frame.evaluate(f"""(val) => {{
                var el = document.getElementById('beg');
                if (el) {{ el.value = val; el.dispatchEvent(new Event('input', {{bubbles:true}})); el.dispatchEvent(new Event('change', {{bubbles:true}})); }}
            }}""", beg_val)
            print(f"[INFO] 已输入开始日期: {beg_val}")
            self._page.wait_for_timeout(300)

            # 关闭 Layui 日期选择器
            try:
                frame.evaluate("() => { var dp = document.querySelector('.layui-laydate'); if (dp) dp.remove(); }")
            except Exception:
                pass
            self._page.wait_for_timeout(200)

            frame.evaluate(f"""(val) => {{
                var el = document.getElementById('end');
                if (el) {{ el.value = val; el.dispatchEvent(new Event('input', {{bubbles:true}})); el.dispatchEvent(new Event('change', {{bubbles:true}})); }}
            }}""", end_val)
            print(f"[INFO] 已输入结束日期: {end_val}")
            self._page.wait_for_timeout(300)

            try:
                frame.evaluate("() => { var dp = document.querySelector('.layui-laydate'); if (dp) dp.remove(); }")
            except Exception:
                pass

            print("[SUCCESS] 申请期间输入完成")
            return True
        except Exception as e:
            print(f"[ERROR] 输入申请期间失败: {e}")
            return False

    # ===================== 查询与导出 =====================

    def _query_and_export(self, frame: Frame, bu_name: str = "",
                          start_date_str: str = "", end_date_str: str = "") -> Optional[str]:
        print(f"[INFO] 开始查询{' [' + bu_name + ']' if bu_name else ' (所有)'}...")

        try:
            frame = self._get_fresh_frame()
            if not frame:
                print("[ERROR] 无法获取 frame")
                return None
            self._page.wait_for_timeout(2000)

            # 选择 BU
            if bu_name:
                if not self._select_bu(frame, bu_name):
                    print(f"[WARNING] 未能选择 BU: {bu_name}")
                self._page.wait_for_timeout(500)

            # 输入申请期间
            if not self._input_date_range(frame, start_date_str, end_date_str):
                print("[ERROR] 输入申请期间失败")
                return None

            self._page.wait_for_timeout(1000)

            # 点击查询
            try:
                query_btn = frame.locator("a.layui-btn:has-text('查询')").first
                if query_btn.count() == 0:
                    query_btn = frame.locator("a:has-text('查询')").first
                query_btn.click()
                print("[INFO] 已点击查询按钮")
                self._page.wait_for_timeout(5000)
                print("[INFO] 等待数据加载完成...")
            except Exception as e:
                print(f"[ERROR] 查询失败: {e}")
                return None

            # 点击导出
            print("[INFO] 正在导出...")
            try:
                with self._page.expect_download(timeout=60000) as download_info:
                    export_btn = frame.locator("button.layui-btn:has-text('导出')").first
                    if export_btn.count() == 0:
                        export_btn = frame.locator("button:has-text('导出')").first
                    if export_btn.count() == 0:
                        export_btn = frame.locator("a:has-text('导出')").first
                    export_btn.click()
                    print("[INFO] 已点击导出按钮")

                download = download_info.value
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                bu_part = bu_name.replace("/", "_") if bu_name else "全部"
                filename = f"面试评价表_{bu_part}_{start_date_str}_{end_date_str}_{timestamp}.xlsx"
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
            print(f"[ERROR] 查询导出异常: {e}")
            return None

    # ===================== 主入口 =====================

    def download_reports(self, bu_list: Optional[List[str]] = None,
                         start_date_str: str = "", end_date_str: str = "",
                         start_browser: bool = True) -> List[str]:
        """下载人员面试评价表（主入口）"""
        downloaded_files = []

        try:
            if start_browser:
                self.start()

            self.login()

            if not bu_list:
                bu_list = [""]

            for idx, bu in enumerate(bu_list):
                print(f"\n{'='*60}")
                print(f"[INFO] 处理第 {idx+1}/{len(bu_list)} 个: {bu or '全部'}")
                print(f"{'='*60}")

                frame = self.navigate_to_page()
                result = self._query_and_export(frame=frame, bu_name=bu,
                                                start_date_str=start_date_str,
                                                end_date_str=end_date_str)

                if result:
                    downloaded_files.append(result)

                if idx < len(bu_list) - 1:
                    print("[INFO] 等待后继续下一个 BU...")
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
            print(f"[ERROR] 下载失败: {e}")
            raise

        finally:
            if start_browser:
                self.stop()


def parse_date_input(date_str: str) -> str:
    match = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日?', date_str.strip())
    if match:
        return f"{int(match.group(1))}年{int(match.group(2)):02d}月{int(match.group(3)):02d}日"
    raise ValueError(f"无法解析日期: {date_str}，请使用格式如 '2025年1月1日'")


def main():
    try:
        from config import USERNAME, PASSWORD, DOWNLOAD_DIR
    except ImportError:
        USERNAME = ""
        PASSWORD = ""
        DOWNLOAD_DIR = "./downloads"

    import argparse

    parser = argparse.ArgumentParser(description="人员面试评价表下载工具")
    parser.add_argument("-u", "--username", help="登录用户名", default=USERNAME)
    parser.add_argument("-p", "--password", help="登录密码", default=PASSWORD)
    parser.add_argument("-s", "--sbu", help="BU列表（逗号分隔），不填则查询全部", default=None)
    parser.add_argument("--start", help="开始日期，如 '2025年1月1日'", default=None)
    parser.add_argument("--end", help="结束日期，如 '2025年12月31日'", default=None)
    parser.add_argument("-d", "--download-dir", help="下载目录", default=DOWNLOAD_DIR)
    parser.add_argument("--headless", action="store_true", help="隐藏浏览器（无头模式）")

    args = parser.parse_args()

    username = args.username or input("请输入用户名: ")
    password = args.password or input("请输入密码: ")

    bu_input = args.sbu if args.sbu is not None else input("请输入BU（多个用逗号分隔，直接回车不输入）: ").strip()
    bu_list = [s.strip() for s in re.split(r'[,，]', bu_input) if s.strip()] if bu_input else []

    start_input = args.start if args.start is not None else input("请输入开始日期（如 2025年1月1日）: ").strip()
    start_date_str = parse_date_input(start_input)

    end_input = args.end if args.end is not None else input("请输入结束日期（如 2025年12月31日）: ").strip()
    end_date_str = parse_date_input(end_input)

    print(f"\n{'='*60}")
    print(f"  人员面试评价表下载工具")
    print(f"{'='*60}")
    print(f"  用户名: {username}")
    print(f"  BU: {', '.join(bu_list) if bu_list else '全部'}")
    print(f"  申请期间: {start_date_str} ~ {end_date_str}")
    print(f"  下载目录: {args.download_dir}")
    print(f"{'='*60}\n")

    with InterviewEvaluationDownloader(
        username=username, password=password,
        download_dir=args.download_dir, headless=args.headless
    ) as downloader:
        results = downloader.download_reports(
            bu_list=bu_list if bu_list else None,
            start_date_str=start_date_str, end_date_str=end_date_str,
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
