"""
工时报表下载自动化工具
使用 Playwright 实现网页自动化操作
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from playwright.sync_api import sync_playwright, Page, Browser, Playwright


class WorkHoursDownloader:
    """工时报表下载器 - 可复用的自动化下载类"""

    # 网站配置
    LOGIN_URL = "https://ims.asiainfo.com/AIOMS/Jsp/main.jsp"

    # 页面元素选择器配置（可根据页面实际结构调整）
    SELECTORS = {
        # 登录相关
        "username_input": "input[name='username'], input[id='username'], input[type='text']",
        "password_input": "input[name='password'], input[id='password'], input[type='password']",
        "login_button": "button[type='submit'], input[type='submit'], button:has-text('登录'), input[value*='登录']",

        # 导航菜单
        "attendance_menu": "text=考勤工时",
        "expand_icon": "text=考勤工时 + , text=+",

        # 工时查询
        "work_hours_query": "text=商务经理工时查询",

        # 查询条件
        "period_start_select": "select[name*='start'], select:first-of-type",
        "period_end_select": "select[name*='end'], select:last-of-type",

        # 操作按钮
        "query_button": "button:has-text('查询'), input[value*='查询']",
        "export_button": "button:has-text('导出'), input[value*='导出']",
    }

    def __init__(
        self,
        username: str,
        password: str,
        download_dir: Optional[str] = None,
        headless: bool = False
    ):
        """
        初始化下载器

        Args:
            username: 登录用户名
            password: 登录密码
            download_dir: 下载文件保存目录，默认为当前目录下的 downloads 文件夹
            headless: 是否无头模式运行（True为后台运行，False为显示浏览器）
        """
        self.username = username
        self.password = password
        self.download_dir = Path(download_dir) if download_dir else Path(__file__).resolve().parent.parent / "downloads"
        self.headless = headless

        # 确保下载目录存在
        self.download_dir.mkdir(parents=True, exist_ok=True)

        # 浏览器相关
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None

    def start(self) -> None:
        """启动浏览器"""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless, args=["--headless=new"] if self.headless else [], downloads_path=str(self.download_dir))
        context = self._browser.new_context(accept_downloads=True)
        self._page = context.new_page()
        print(f"[INFO] 浏览器已启动，下载目录: {self.download_dir}")

    def stop(self) -> None:
        """关闭浏览器"""
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

    def login(self) -> bool:
        """
        登录网站

        Returns:
            bool: 登录是否成功
        """
        print(f"[INFO] 正在访问登录页面: {self.LOGIN_URL}")
        self._page.goto(self.LOGIN_URL, wait_until="networkidle")
        self._page.wait_for_timeout(2000)

        # 查找并填写用户名
        username_input = self._page.locator(self.SELECTORS["username_input"]).first
        if username_input:
            username_input.fill(self.username)
            print(f"[INFO] 已输入用户名: {self.username}")

        # 查找并填写密码
        password_input = self._page.locator(self.SELECTORS["password_input"]).first
        if password_input:
            password_input.fill(self.password)
            print("[INFO] 已输入密码")

        # 点击登录按钮
        login_button = self._page.locator(self.SELECTORS["login_button"]).first
        if login_button:
            login_button.click()
            print("[INFO] 已点击登录按钮")

        # 等待登录完成
        self._page.wait_for_timeout(3000)

        # 检查是否登录成功（检查URL是否变化或是否出现特定元素）
        current_url = self._page.url
        if "main" in current_url or "home" in current_url or "index" in current_url:
            print("[SUCCESS] 登录成功")
            return True
        else:
            print("[WARNING] 登录状态未确认，继续尝试...")
            return True

    def navigate_to_work_hours(self) -> None:
        """导航到工时查询页面"""
        print("[INFO] 正在导航到工时查询页面...")

        # 等待页面加载完成
        self._page.wait_for_timeout(3000)

        try:
            # 找到"考勤工时"文本所在的行
            attendance_row = self._page.locator(".mini-tree-nodetext:has-text('考勤工时')").first
            # 获取其父级 mini-tree-nodetitle 元素
            nodetitle = attendance_row.locator("xpath=ancestor::div[contains(@class, 'mini-tree-nodetitle')]").first
            
            # 在该节点内找到展开图标 mini-tree-node-ecicon
            expand_icon = nodetitle.locator(".mini-tree-node-ecicon").first
            
            # 点击展开图标
            expand_icon.click()
            print("[INFO] 已点击考勤工时前面的展开图标")
            self._page.wait_for_timeout(1500)

        except Exception as e:
            print(f"[DEBUG] 展开菜单时: {e}")
            # 备用方案：尝试通过JavaScript操作mini-tree
            try:
                self._page.evaluate("""
                    var tree = mini.get("tree1");
                    var nodes = tree.getData();
                    for(var i=0; i<nodes.length; i++){
                        if(nodes[i].text == '考勤工时'){
                            tree.expandNode(nodes[i]);
                            break;
                        }
                    }
                """)
                print("[INFO] 通过JS展开了考勤工时菜单")
                self._page.wait_for_timeout(1500)
            except Exception as e2:
                print(f"[DEBUG] JS展开也失败: {e2}")

        # 等待菜单展开
        self._page.wait_for_timeout(2000)

        # 点击【商务经理工时查询】
        try:
            query_link = self._page.locator(".mini-tree-nodetext:has-text('商务经理工时查询')").first
            query_link.click()
            print("[INFO] 已点击【商务经理工时查询】，进入查询页面")
            self._page.wait_for_timeout(2000)
        except Exception as e:
            print(f"[ERROR] 进入工时查询页面失败: {e}")
            raise

    def parse_period(self, period_str: str) -> Tuple[str, str]:
        """
        解析时间段字符串

        Args:
            period_str: 时间段字符串，如 "2024年01月~2024年12月" 或 "2024-01~2024-12"

        Returns:
            Tuple[str, str]: (开始时间, 结束时间) 格式为 "XXXX年XX月"
        """
        # 支持多种格式
        # 格式1: 2024年01月~2024年12月
        # 格式2: 2024-01~2024-12
        # 格式3: 2024年1月~2024年12月

        # 尝试匹配中文格式
        cn_pattern = r'(\d{4})年(\d{1,2})月\s*[~至\-]\s*(\d{4})年(\d{1,2})月'
        match = re.search(cn_pattern, period_str)

        if match:
            start_year, start_month, end_year, end_month = match.groups()
            start = f"{start_year}年{int(start_month):02d}月"
            end = f"{end_year}年{int(end_month):02d}月"
            return start, end

        # 尝试匹配短横线格式
        short_pattern = r'(\d{4})-(\d{2})\s*[~至\-]\s*(\d{4})-(\d{2})'
        match = re.search(short_pattern, period_str)

        if match:
            start_year, start_month, end_year, end_month = match.groups()
            start = f"{start_year}年{start_month}月"
            end = f"{end_year}年{end_month}月"
            return start, end

        raise ValueError(f"无法解析时间段: {period_str}，请使用格式如 '2024年01月~2024年12月'")

    def select_period(self, start_period: str, end_period: str) -> None:
        """
        选择工时查询的时间段

        Args:
            start_period: 开始时间，如 "2024年01月"
            end_period: 结束时间，如 "2024年12月"
        """
        print(f"[INFO] 正在选择时间段: {start_period} ~ {end_period}")

        # 等待页面加载
        self._page.wait_for_timeout(3000)

        # 将时间段转换为下拉选项格式
        def parse_to_option_format(period_str: str) -> str:
            match = re.match(r'(\d{4})年(\d{1,2})月', period_str)
            if match:
                year, month = match.groups()
                return f"{year}{int(month):02d}"
            return period_str

        start_code = parse_to_option_format(start_period)
        end_code = parse_to_option_format(end_period)
        print(f"[DEBUG] 查找时间段代码: 开始={start_code}, 结束={end_code}")

        # 获取工时查询的 iframe
        target_frame = None
        print(f"[DEBUG] 当前页面有 {len(self._page.frames)} 个frame")
        for frame in self._page.frames:
            frame_url = frame.url
            print(f"[DEBUG] Frame URL: {frame_url}")
            if "timeInfo_toQueryTime" in frame_url:
                target_frame = frame
                print(f"[INFO] 找到工时查询iframe: {frame_url}")
                break

        if not target_frame:
            self._page.wait_for_timeout(2000)
            for frame in self._page.frames:
                frame_url = frame.url
                if "timeInfo_toQueryTime" in frame_url:
                    target_frame = frame
                    print(f"[INFO] 找到工时查询iframe: {frame_url}")
                    break

        if not target_frame:
            print("[ERROR] 未找到工时查询iframe")
            raise Exception("未找到工时查询iframe")

        try:
            # 找到时间段相关的 combobox
            combos = target_frame.locator(".mini-combobox").all()
            print(f"[DEBUG] 找到 {len(combos)} 个 combobox")

            def select_combobox_option(frame, combo, code: str) -> bool:
                """点击combobox并在下拉列表中查找并选择选项（支持滚动）"""
                # 点击下拉按钮
                btn = combo.locator(".mini-buttonedit-button").first
                btn.click()
                frame.wait_for_timeout(800)

                # 查找下拉列表容器（用于滚动）
                listbox = frame.locator(".mini-listbox:visible, .mini-listbox-view:visible").first
                if listbox.count() == 0:
                    listbox = frame.locator(".mini-popup:visible .mini-listbox-view").first

                # 先尝试直接查找并点击
                cell = frame.locator(f".mini-listbox:visible td:has-text('{code}')").first
                if cell.count() > 0:
                    cell.click()
                    print(f"[INFO] 已选择: {code}")
                    return True

                # 如果没找到，尝试滚动查找
                if listbox.count() > 0:
                    for i in range(30):  # 最多滚动30次
                        # 向下滚动
                        listbox.evaluate("el => el.scrollTop += 50")
                        frame.wait_for_timeout(200)

                        # 再次查找
                        cell = frame.locator(f".mini-listbox:visible td:has-text('{code}')").first
                        if cell.count() > 0:
                            cell.click()
                            print(f"[INFO] 滚动{i+1}次后找到并选择: {code}")
                            return True

                        # 向上滚动尝试（可能当前在底部）
                        listbox.evaluate("el => el.scrollTop -= 100")
                        frame.wait_for_timeout(200)
                        cell = frame.locator(f".mini-listbox:visible td:has-text('{code}')").first
                        if cell.count() > 0:
                            cell.click()
                            print(f"[INFO] 向上滚动后找到并选择: {code}")
                            return True

                print(f"[WARNING] 未找到选项: {code}")
                return False

            if len(combos) >= 2:
                # 选择开始时间
                select_combobox_option(target_frame, combos[0], start_code)
                self._page.wait_for_timeout(500)

                # 选择结束时间
                select_combobox_option(target_frame, combos[1], end_code)
                self._page.wait_for_timeout(500)

            else:
                print(f"[ERROR] combobox数量不足，找到 {len(combos)} 个")
                raise Exception("未找到足够的时间选择下拉框")

        except Exception as e:
            print(f"[ERROR] 选择时间段失败: {e}")
            raise

    def query_and_export(self) -> Optional[str]:
        """
        执行查询并导出报表

        Returns:
            Optional[str]: 下载文件的路径，失败返回 None
        """
        print("[INFO] 正在查询数据...")

        # 获取工时查询的 iframe
        target_frame = None
        for frame in self._page.frames:
            if "timeInfo_toQueryTime" in frame.url:
                target_frame = frame
                break

        if not target_frame:
            print("[ERROR] 未找到工时查询iframe")
            raise Exception("未找到工时查询iframe")

        # 点击查询按钮
        try:
            query_btn = target_frame.locator("text=查询").first
            query_btn.click()
            print("[INFO] 已点击查询按钮")

            # 等待数据加载
            self._page.wait_for_timeout(5000)
            print("[INFO] 等待数据加载完成...")

        except Exception as e:
            print(f"[ERROR] 查询失败: {e}")
            raise

        # 点击导出按钮
        print("[INFO] 正在导出报表...")
        try:
            # 监听下载事件
            with self._page.expect_download(timeout=60000) as download_info:
                export_btn = target_frame.locator("text=导出").first
                export_btn.click()
                print("[INFO] 已点击导出按钮")

            download = download_info.value

            # 保存文件
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"工时报表_{timestamp}.xlsx"
            save_path = self.download_dir / filename
            download.save_as(save_path)
            # 清理 Playwright 下载产生的临时 UUID 文件
            try:
                download.delete()
            except Exception:
                pass

            print(f"[SUCCESS] 文件已下载: {save_path}")
            return str(save_path)

        except Exception as e:
            print(f"[ERROR] 导出失败: {e}")
            # 尝试检查下载目录是否有新文件
            files = list(self.download_dir.glob("*.xlsx"))
            if files:
                latest_file = max(files, key=lambda f: f.stat().st_mtime)
                print(f"[INFO] 检测到下载文件: {latest_file}")
                return str(latest_file)
            raise

    def download_work_hours_report(
        self,
        period: str,
        start_browser: bool = True
    ) -> Optional[str]:
        """
        下载工时报表（主入口方法）

        Args:
            period: 查询时间段，如 "2024年01月~2024年12月"
            start_browser: 是否自动启动/关闭浏览器

        Returns:
            Optional[str]: 下载文件的路径，失败返回 None
        """
        try:
            if start_browser:
                self.start()

            # 解析时间段
            start_period, end_period = self.parse_period(period)

            # 执行操作流程
            self.login()
            self.navigate_to_work_hours()
            self.select_period(start_period, end_period)
            result = self.query_and_export()

            return result

        except Exception as e:
            print(f"[ERROR] 下载工时报表失败: {e}")
            raise

        finally:
            if start_browser:
                self.stop()


def main():
    """主函数 - 示例用法"""
    import argparse

    parser = argparse.ArgumentParser(description="工时报表下载工具")
    parser.add_argument("-u", "--username", help="登录用户名", required=False)
    parser.add_argument("-p", "--password", help="登录密码", required=False)
    parser.add_argument("-P", "--period", help="查询时间段，如 '2024年01月~2024年12月'", required=False)
    parser.add_argument("-d", "--download-dir", help="下载文件保存目录", default="./downloads")
    parser.add_argument("--headless", action="store_true", help="隐藏浏览器（无头模式）")

    args = parser.parse_args()

    # 如果没有提供参数，使用交互式输入
    username = args.username or input("请输入用户名: ")
    password = args.password or input("请输入密码: ")
    period = args.period or input("请输入查询时间段 (如 2024年01月~2024年12月): ")

    # 创建下载器并执行下载
    with WorkHoursDownloader(
        username=username,
        password=password,
        download_dir=args.download_dir,
        headless=args.headless
    ) as downloader:
        result = downloader.download_work_hours_report(period=period, start_browser=False)
        if result:
            print(f"\n下载成功! 文件位置: {result}")
        else:
            print("\n下载失败，请检查日志")


if __name__ == "__main__":
    main()
