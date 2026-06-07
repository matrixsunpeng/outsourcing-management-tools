"""
计提&结算下载自动化工具
使用 Playwright 实现网页自动化操作
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from playwright.sync_api import sync_playwright, Page, Browser, Playwright, Frame


class SettlementDownloader:
    """计提&结算下载器 - 可复用的自动化下载类"""

    # 网站配置
    LOGIN_URL = "https://ims.asiainfo.com/AIOMS/Jsp/main.jsp"

    # 页面元素选择器配置
    SELECTORS = {
        # 登录相关
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
        # 新标签页（费用结算单查询页面）
        self._query_frame: Optional[Frame] = None

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

    # ===================== 登录 =====================

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

        current_url = self._page.url
        if "main" in current_url or "home" in current_url or "index" in current_url:
            print("[SUCCESS] 登录成功")
            return True
        else:
            print("[WARNING] 登录状态未确认，继续尝试...")
            return True

    # ===================== 导航 =====================

    def _find_target_frame(self) -> Optional[Frame]:
        """
        查找费用结算单计提与结算金额查询的 iframe

        Returns:
            Optional[Frame]: 目标 iframe，未找到返回 None
        """
        # 已知的可能关键词（根据实际页面 URL 调整）
        possible_keywords = [
            "expenseProvision", "settlement", "jiti", "jiesuan",
            "FeeSettlement", "feeSettle", "outsource", "costSettle", "settleFee"
        ]

        for frame in self._page.frames:
            frame_url = frame.url
            print(f"[DEBUG] Frame URL: {frame_url}")
            # 跳过主页面和空 URL
            if frame == self._page.main_frame or not frame_url or "about:blank" in frame_url:
                continue
            for keyword in possible_keywords:
                if keyword.lower() in frame_url.lower():
                    print(f"[INFO] 找到计提结算查询iframe: {frame_url}")
                    return frame

        return None

    def navigate_to_settlement_query(self) -> Frame:
        """
        导航到费用结算单计提与结算金额查询页面

        步骤：
        1. 双击左侧菜单"外包数据查询"展开子菜单
        2. 单击"费用结算单计提与结算金额查询"
        3. 等待 iframe 加载

        Returns:
            Frame: 查询页面的 iframe 对象
        """
        print("[INFO] 正在导航到费用结算单计提与结算金额查询页面...")

        # 等待页面加载完成
        self._page.wait_for_timeout(3000)

        # 双击"外包数据查询"展开子菜单
        try:
            # 尝试通过 mini-tree 定位
            outsource_row = self._page.locator(".mini-tree-nodetext:has-text('外包数据查询')").first
            outsource_row.dblclick()
            print("[INFO] 已双击【外包数据查询】菜单")
            self._page.wait_for_timeout(2000)
        except Exception as e:
            print(f"[DEBUG] 双击菜单时出错: {e}")
            # 备用方案：通过 JavaScript 展开
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

        # 等待子菜单展开
        self._page.wait_for_timeout(2000)

        # 单击"费用结算单计提与结算金额查询"
        try:
            settlement_link = self._page.locator(
                ".mini-tree-nodetext:has-text('费用结算单计提与结算金额查询')"
            ).first
            settlement_link.click()
            print("[INFO] 已单击【费用结算单计提与结算金额查询】")
            self._page.wait_for_timeout(3000)
        except Exception as e:
            print(f"[ERROR] 点击费用结算单查询菜单失败: {e}")
            raise

        # 查找目标 iframe
        target_frame = self._find_target_frame()

        if not target_frame:
            # 可能 iframe 还没加载完，再等一下重试
            print("[DEBUG] 首次未找到 iframe，等待重试...")
            self._page.wait_for_timeout(3000)
            target_frame = self._find_target_frame()

        if not target_frame:
            # 最后一次：列出所有 frame 供调试
            print(f"[DEBUG] 当前共有 {len(self._page.frames)} 个 frame:")
            for i, frame in enumerate(self._page.frames):
                print(f"[DEBUG]   Frame {i}: {frame.url}")

            # 如果只找到一个非主 frame，就用它
            non_main_frames = [f for f in self._page.frames
                                  if f != self._page.main_frame and f.url and "about:blank" not in f.url]
            if non_main_frames:
                target_frame = non_main_frames[-1]
                print(f"[INFO] 使用最后一个非主 frame: {target_frame.url}")
            else:
                raise Exception("未找到费用结算单查询的 iframe")

        print(f"[SUCCESS] 已定位到查询 iframe: {target_frame.url}")
        self._query_frame = target_frame
        return target_frame

    # ===================== 下拉列表选择 =====================

    def _select_combobox_option(self, page, label_text: str, target_value: str) -> bool:
        """
        在指定标签旁边的 combobox 中选择选项

        策略：通过遍历页面上所有 label/td 文本，找到包含 label_text 的元素，
        然后找到其相邻的 combobox 并选择。

        Args:
            page: 页面/iframe 对象
            label_text: 标签文本（用于定位 combobox），如 "SBU"、"服务类型"
            target_value: 要选择的值，如 "人员类"

        Returns:
            bool: 是否成功选择
        """
        print(f"[INFO] 正在选择 {label_text}: {target_value}")

        try:
            # 找到所有 combobox
            combos = page.locator(".mini-combobox").all()
            print(f"[DEBUG] 找到 {len(combos)} 个 combobox")

            # 策略1：通过 label 关联找 combobox
            # MiniUI 页面通常用 table 布局，label 在一个 td，combobox 在下一个 td
            target_combobox = None

            # 查找所有 td 元素，看哪个包含 label_text
            all_tds = page.locator("td").all()
            for td in all_tds:
                try:
                    td_text = td.text_content().strip()
                    if label_text in td_text and len(td_text) < 50:  # 标签通常很短
                        # 找到包含标签的 td，在其后续兄弟 td 中找 combobox
                        parent_tr = td.locator("xpath=ancestor::tr").first
                        if parent_tr.count() > 0:
                            sibling_combos = parent_tr.locator(".mini-combobox").all()
                            if sibling_combos:
                                target_combobox = sibling_combos[0]
                                print(f"[DEBUG] 通过标签 '{label_text}' 找到关联 combobox（tr 内）")
                                break
                        # 也尝试在同级的 td 中查找
                        next_td = td.locator("xpath=following-sibling::td").first
                        if next_td.count() > 0:
                            next_combos = next_td.locator(".mini-combobox").all()
                            if next_combos:
                                target_combobox = next_combos[0]
                                print(f"[DEBUG] 通过标签 '{label_text}' 找到关联 combobox（相邻 td）")
                                break
                except Exception:
                    continue

            # 策略2：如果策略1失败，尝试直接遍历每个 combobox 检查其选项
            if target_combobox is None:
                print(f"[DEBUG] 策略1未找到 {label_text} 的 combobox，尝试策略2：遍历检查选项...")
                for idx, combo in enumerate(combos):
                    try:
                        # 打开下拉列表
                        btn = combo.locator(".mini-buttonedit-button").first
                        btn.click()
                        page.wait_for_timeout(600)

                        # 检查是否有目标选项
                        cells = page.locator(".mini-listbox:visible td").all()
                        option_texts = []
                        for c in cells[:20]:  # 只检查前20个
                            try:
                                t = c.text_content().strip()
                                if t:
                                    option_texts.append(t)
                            except Exception:
                                continue

                        print(f"[DEBUG] Combobox[{idx}] 选项: {option_texts[:10]}")

                        # 关闭下拉列表（按 Esc）
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(300)

                        if any(target_value in t for t in option_texts):
                            target_combobox = combo
                            print(f"[DEBUG] Combobox[{idx}] 包含选项 '{target_value}'")
                            break
                    except Exception:
                        try:
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(300)
                        except Exception:
                            pass

            if target_combobox is None:
                print(f"[WARNING] 未找到包含 '{target_value}' 的 combobox")
                return False

            # 打开目标 combobox 的下拉列表
            btn = target_combobox.locator(".mini-buttonedit-button").first
            btn.click()
            page.wait_for_timeout(800)

            # 查找下拉列表容器
            listbox = page.locator(".mini-listbox:visible, .mini-listbox-view:visible").first
            if listbox.count() == 0:
                listbox = page.locator(".mini-popup:visible .mini-listbox-view").first

            # 尝试直接查找并点击目标选项
            cell = page.locator(f".mini-listbox:visible td:has-text('{target_value}')").first
            if cell.count() > 0:
                cell.click()
                print(f"[INFO] 已选择 {label_text}: {target_value}")
                page.wait_for_timeout(500)
                return True

            # 如果没找到，尝试滚动查找
            if listbox.count() > 0:
                for i in range(30):
                    listbox.evaluate("el => el.scrollTop += 50")
                    page.wait_for_timeout(200)

                    cell = page.locator(f".mini-listbox:visible td:has-text('{target_value}')").first
                    if cell.count() > 0:
                        cell.click()
                        print(f"[INFO] 滚动{i+1}次后找到并选择 {label_text}: {target_value}")
                        page.wait_for_timeout(500)
                        return True

                    # 尝试向上滚动
                    listbox.evaluate("el => el.scrollTop -= 100")
                    page.wait_for_timeout(200)
                    cell = page.locator(f".mini-listbox:visible td:has-text('{target_value}')").first
                    if cell.count() > 0:
                        cell.click()
                        print(f"[INFO] 向上滚动后找到并选择 {label_text}: {target_value}")
                        page.wait_for_timeout(500)
                        return True

            print(f"[WARNING] 未找到选项: {target_value}")
            # 关闭下拉列表
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            return False

        except Exception as e:
            print(f"[ERROR] 选择 {label_text} 失败: {e}")
            # 确保关闭可能残留的下拉弹窗
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
            except Exception:
                pass
            return False

    # ===================== 月份范围选择 =====================

    def _select_date_range(self, page, start_year: int, start_month: int,
                           end_year: int, end_month: int) -> bool:
        """
        选择月份范围（开始时间 ~ 结束时间）
        直接在文本框中输入日期，格式为 YYYY-MM

        Args:
            page: 页面/iframe 对象
            start_year: 开始年份
            start_month: 开始月份
            end_year: 结束年份
            end_month: 结束月份

        Returns:
            bool: 是否成功选择
        """
        start_str = f"{start_year}-{start_month:02d}"
        end_str = f"{end_year}-{end_month:02d}"
        print(f"[INFO] 正在选择月份范围: {start_str} ~ {end_str}")

        try:
            # 查找"月份范围"标签，定位其对应的两个输入框
            label_el = page.locator("text=月份范围").first
            if label_el.count() == 0:
                print("[ERROR] 未找到'月份范围'标签")
                return False

            # 获取标签所在的行(tr)，在该行中找到所有输入框
            parent_row = label_el.locator("xpath=ancestor::tr").first
            if parent_row.count() == 0:
                parent_row = label_el.locator("xpath=ancestor::table").first

            inputs = []
            if parent_row.count() > 0:
                all_inputs = parent_row.locator("input").all()
                for inp in all_inputs:
                    is_combo = inp.locator("xpath=ancestor::*[contains(@class,'mini-combobox')]").first
                    is_hidden = inp.get_attribute("type") == "hidden"
                    if is_combo.count() == 0 and not is_hidden:
                        inputs.append(inp)

            if len(inputs) < 2:
                parent_table = label_el.locator("xpath=ancestor::table").first
                if parent_table.count() > 0:
                    all_inputs = parent_table.locator("input").all()
                    inputs = []
                    for inp in all_inputs:
                        is_combo = inp.locator("xpath=ancestor::*[contains(@class,'mini-combobox')]").first
                        is_hidden = inp.get_attribute("type") == "hidden"
                        if is_combo.count() == 0 and not is_hidden:
                            inputs.append(inp)

            print(f"[DEBUG] 找到 {len(inputs)} 个文本输入框")

            if len(inputs) >= 2:
                # 清空并输入开始时间
                inputs[0].click()
                inputs[0].fill("")
                inputs[0].type(start_str)
                print(f"[INFO] 已输入开始时间: {start_str}")
                page.wait_for_timeout(300)

                # 触发 blur 事件让控件识别输入值
                inputs[0].dispatch_event("blur")
                page.wait_for_timeout(200)

                # 清空并输入结束时间
                inputs[1].click()
                inputs[1].fill("")
                inputs[1].type(end_str)
                print(f"[INFO] 已输入结束时间: {end_str}")
                page.wait_for_timeout(300)

                # 触发 blur 事件
                inputs[1].dispatch_event("blur")
                page.wait_for_timeout(300)

                print("[SUCCESS] 月份范围选择完成")
                return True
            else:
                print(f"[ERROR] 文本输入框数量不足，找到 {len(inputs)} 个")
                return False

        except Exception as e:
            print(f"[ERROR] 选择月份范围失败: {e}")
            try:
                screenshot_path = self.download_dir / "debug_calendar_error.png"
                page.screenshot(path=str(screenshot_path))
                print(f"[DEBUG] 错误截图已保存: {screenshot_path}")
            except Exception:
                pass
            return False

    # ===================== 查询与导出 =====================

    def _query_and_export(self, frame: Frame, sbu_name: str = "",
                          start_year: int = 0, start_month: int = 0,
                          end_year: int = 0, end_month: int = 0) -> Optional[str]:
        """
        在查询 iframe 中填写条件、查询并导出

        Args:
            frame: 查询页面的 iframe 对象
            sbu_name: SBU 名称，为空则不筛选
            start_year: 开始年份
            start_month: 开始月份
            end_year: 结束年份
            end_month: 结束月份

        Returns:
            Optional[str]: 下载文件路径，失败返回 None
        """
        print(f"[INFO] 开始查询{' [' + sbu_name + ']' if sbu_name else ' (所有SBU)'}...")

        try:
            # 等待 iframe 内容加载
            self._page.wait_for_timeout(3000)

            # 选择 SBU（如果指定了）
            if sbu_name:
                if not self._select_combobox_option(frame, "SBU", sbu_name):
                    print(f"[WARNING] 未能选择 SBU: {sbu_name}")
                # 等待 SBU 下拉弹窗完全关闭
                self._page.wait_for_timeout(800)

            # 选择服务类型 = 人员类
            if not self._select_combobox_option(frame, "服务类型", "人员类"):
                print("[WARNING] 未能选择服务类型")
            # 等待服务类型下拉弹窗完全关闭
            self._page.wait_for_timeout(800)

            # 选择月份范围（日历控件在 iframe 中）
            if not self._select_date_range(frame, start_year, start_month, end_year, end_month):
                print("[ERROR] 选择月份范围失败")
                return None

            self._page.wait_for_timeout(1000)

            # 点击查询按钮（在 iframe 中）
            try:
                query_btn = frame.locator("text=查询").first
                query_btn.click()
                print("[INFO] 已点击查询按钮")
                self._page.wait_for_timeout(5000)
                print("[INFO] 等待数据加载完成...")
            except Exception as e:
                print(f"[ERROR] 查询失败: {e}")
                return None


            # 点击导出Excel按钮（在 iframe 中，但下载事件由主页面捕获）
            print("[INFO] 正在导出 Excel...")
            try:
                with self._page.expect_download(timeout=60000) as download_info:
                    export_btn = frame.locator("text=导出Excel").first
                    if export_btn.count() == 0:
                        export_btn = frame.locator("text=导出").first
                    export_btn.click()
                    print("[INFO] 已点击导出按钮")

                download = download_info.value

                # 生成文件名
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                sbu_part = sbu_name.replace("/", "_") if sbu_name else "全部SBU"
                filename = f"计提结算_{sbu_part}_{start_year}{start_month:02d}-{end_year}{end_month:02d}_{timestamp}.xlsx"
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

    def download_settlement_reports(
        self,
        sbu_list: Optional[List[str]] = None,
        start_year: int = 2025,
        start_month: int = 1,
        end_year: int = 2025,
        end_month: int = 12,
        start_browser: bool = True
    ) -> List[str]:
        """
        下载计提&结算报表（主入口方法）

        Args:
            sbu_list: SBU 名称列表，为空则查询所有 SBU
            start_year: 开始年份
            start_month: 开始月份
            end_year: 结束年份
            end_month: 结束月份
            start_browser: 是否自动启动/关闭浏览器

        Returns:
            List[str]: 下载文件路径列表
        """
        downloaded_files = []

        try:
            if start_browser:
                self.start()

            # 1. 登录
            self.login()

            # 2. 导航到查询页面（只需一次）
            query_page = self.navigate_to_settlement_query()

            if not sbu_list:
                sbu_list = [""]  # 空列表表示不筛选 SBU

            # 3. 逐个 SBU 查询并下载
            for idx, sbu in enumerate(sbu_list):
                print(f"\n{'='*60}")
                print(f"[INFO] 处理第 {idx+1}/{len(sbu_list)} 个: {sbu or '全部SBU'}")
                print(f"{'='*60}")

                result = self._query_and_export(
                    frame=query_page,
                    sbu_name=sbu,
                    start_year=start_year,
                    start_month=start_month,
                    end_year=end_year,
                    end_month=end_month
                )

                if result:
                    downloaded_files.append(result)

                # 如果不是最后一个 SBU，等待后刷新 iframe 准备下一次查询
                if idx < len(sbu_list) - 1:
                    print("[INFO] 等待后继续下一个 SBU...")
                    self._page.wait_for_timeout(2000)
                    # 刷新主页面以清除上一次查询的状态
                    self._page.reload()
                    self._page.wait_for_load_state("domcontentloaded")
                    self._page.wait_for_timeout(3000)
                    # 重新导航到查询页面
                    query_page = self.navigate_to_settlement_query()

            return downloaded_files

        except Exception as e:
            print(f"[ERROR] 下载计提结算报表失败: {e}")
            raise

        finally:
            if start_browser:
                self.stop()


def parse_time_input(time_str: str):
    """
    解析时间输入，支持格式：
    - "2025年3月" → (2025, 3)
    - "2025年03月" → (2025, 3)

    Args:
        time_str: 时间字符串

    Returns:
        tuple: (year, month)

    Raises:
        ValueError: 解析失败
    """
    match = re.match(r'(\d{4})年(\d{1,2})月', time_str.strip())
    if match:
        return int(match.group(1)), int(match.group(2))
    raise ValueError(f"无法解析时间: {time_str}，请使用格式如 '2025年3月'")


def main():
    """主函数 - 交互式输入"""
    # 导入配置
    try:
        from config import USERNAME, PASSWORD, DOWNLOAD_DIR
    except ImportError:
        USERNAME = ""
        PASSWORD = ""
        DOWNLOAD_DIR = "./downloads"

    import argparse

    parser = argparse.ArgumentParser(description="计提&结算下载工具")
    parser.add_argument("-u", "--username", help="登录用户名", default=USERNAME)
    parser.add_argument("-p", "--password", help="登录密码", default=PASSWORD)
    parser.add_argument("-s", "--sbu", help="SBU列表（逗号分隔），不填则查询全部", default=None)
    parser.add_argument("--start", help="开始时间，如 '2025年1月'", default=None)
    parser.add_argument("--end", help="结束时间，如 '2025年12月'", default=None)
    parser.add_argument("-d", "--download-dir", help="下载目录", default=DOWNLOAD_DIR)
    parser.add_argument("--headless", action="store_true", help="隐藏浏览器（无头模式）")

    args = parser.parse_args()

    # 交互式输入（如果命令行未提供）
    username = args.username or input("请输入用户名: ")
    password = args.password or input("请输入密码: ")

    sbu_input = args.sbu if args.sbu is not None else input("请输入SBU（多个用逗号分隔，直接回车不输入）: ").strip()
    sbu_list = [s.strip() for s in re.split(r'[,，]', sbu_input) if s.strip()] if sbu_input else []

    start_input = args.start if args.start is not None else input("请输入开始时间（如 2025年1月）: ").strip()
    start_year, start_month = parse_time_input(start_input)

    end_input = args.end if args.end is not None else input("请输入结束时间（如 2025年12月）: ").strip()
    end_year, end_month = parse_time_input(end_input)

    print(f"\n{'='*60}")
    print(f"  计提&结算下载工具")
    print(f"{'='*60}")
    print(f"  用户名: {username}")
    print(f"  SBU: {', '.join(sbu_list) if sbu_list else '全部'}")
    print(f"  时间范围: {start_year}年{start_month}月 ~ {end_year}年{end_month}月")
    print(f"  下载目录: {args.download_dir}")
    print(f"{'='*60}\n")

    # 创建下载器并执行
    with SettlementDownloader(
        username=username,
        password=password,
        download_dir=args.download_dir,
        headless=args.headless
    ) as downloader:
        results = downloader.download_settlement_reports(
            sbu_list=sbu_list if sbu_list else None,
            start_year=start_year,
            start_month=start_month,
            end_year=end_year,
            end_month=end_month,
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
