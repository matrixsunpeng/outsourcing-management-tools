"""
绩效考核下载自动化工具
使用 Playwright 实现网页自动化操作
适配 layui 框架
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from playwright.sync_api import sync_playwright, Page, Browser, Playwright, Frame


class KPIPerformanceDownloader:
    """绩效考核下载器"""

    LOGIN_URL = "https://ims.asiainfo.com/AIOMS/Jsp/main.jsp"

    SELECTORS = {
        "username_input": "input[name='username'], input[id='username'], input[type='text']",
        "password_input": "input[name='password'], input[id='password'], input[type='password']",
        "login_button": "button[type='submit'], input[type='submit'], button:has-text('登录'), input[value*='登录']",
    }

    # layui 控件 ID
    LAYUI_IDS = {
        "quarter": "s_type",    # 季度选择控件ID
        "bu": "bu",             # BU选择控件ID
    }

    def __init__(
        self,
        username: str,
        password: str,
        download_dir: Optional[str] = None,
        headless: bool = False,
        debug: bool = False
    ):
        self.username = username
        self.password = password
        self.download_dir = Path(download_dir) if download_dir else Path(__file__).resolve().parent.parent / "downloads"
        self.headless = headless
        self.DEBUG_MODE = debug
        self.download_dir.mkdir(parents=True, exist_ok=True)

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        self._query_target = None
        self._query_is_tab = False

    def start(self) -> None:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=["--headless=new"] if self.headless else [],
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
        """查找绩效考核的 iframe（关键词匹配 URL）"""
        possible_keywords = [
            "kpi", "KPI", "performance", "Performance",
            "绩效考核", "kpiQuery", "performanceQuery"
        ]
        for frame in self._page.frames:
            frame_url = frame.url
            if frame == self._page.main_frame or not frame_url or "about:blank" in frame_url:
                continue
            for keyword in possible_keywords:
                if keyword.lower() in frame_url.lower():
                    print(f"[INFO] 找到绩效考核iframe: {frame_url}")
                    return frame
        return None

    def navigate_to_kpi_performance(self) -> Frame:
        """
        导航到绩效考核查询页面（iframe）
        路径：KPI绩效考核 → KPI查询 → 绩效考核查询

        Returns:
            Frame: 绩效考核查询 iframe 对象
        """
        print("[INFO] 正在导航到绩效考核查询页面...")
        self._page.wait_for_timeout(3000)

        # 第一步：双击"KPI绩效考核"展开子菜单
        try:
            kpi_row = self._page.locator(".mini-tree-nodetext:has-text('KPI绩效考核')").first
            kpi_row.dblclick()
            print("[INFO] 已双击【KPI绩效考核】菜单")
            self._page.wait_for_timeout(2000)
        except Exception as e:
            print(f"[DEBUG] 双击KPI绩效考核菜单时出错: {e}")

        self._page.wait_for_timeout(1000)

        # 第二步：双击"KPI查询"展开子菜单
        try:
            kpi_query_row = self._page.locator(".mini-tree-nodetext:has-text('KPI查询')").first
            kpi_query_row.dblclick()
            print("[INFO] 已双击【KPI查询】菜单")
            self._page.wait_for_timeout(2000)
        except Exception as e:
            print(f"[DEBUG] 双击KPI查询菜单时出错: {e}")

        self._page.wait_for_timeout(1000)

        # 第三步：单击"绩效考核查询"打开页面
        try:
            with self._page.context.expect_page(timeout=5000) as new_page_info:
                link = self._page.locator(".mini-tree-nodetext:has-text('绩效考核查询')").first
                link.click()
                print("[INFO] 已单击【绩效考核查询】")

            self._query_target = new_page_info.value
            self._query_target.wait_for_load_state("domcontentloaded")
            self._query_target.wait_for_timeout(3000)
            self._query_is_tab = True
            print(f"[SUCCESS] 绩效考核查询页面已打开(新标签页): {self._query_target.url}")
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
                raise Exception("未找到绩效考核查询的 iframe 或新标签页")

        target_frame.wait_for_load_state("domcontentloaded")
        self._page.wait_for_timeout(3000)

        print(f"[SUCCESS] 已定位到绩效考核查询iframe: {target_frame.url}")
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

    # ===================== layui Select 选择 =====================

    def _select_layui_option(self, frame: Frame, select_id: str, target_value: str) -> bool:
        """
        在 layui 框架中选择下拉选项
        支持精确匹配值或模糊匹配选项文本
        
        Args:
            frame: iframe 对象
            select_id: select 元素的 ID
            target_value: 要选择的选项值或文本（如 "121" 或 "CTC"）
        
        Returns:
            bool: 是否成功
        """
        print(f"[INFO] 正在选择 {select_id}: {target_value}")

        try:
            # 智能选择：先尝试精确匹配值，再尝试模糊匹配文本
            result = frame.evaluate("""(args) => {
                var selectId = args.selectId;
                var targetValue = args.targetValue;
                
                var select = document.getElementById(selectId);
                if (!select) {
                    return {success: false, error: '找不到select元素: ' + selectId};
                }
                
                // 获取所有选项
                var options = select.querySelectorAll('option');
                var matchedOption = null;
                var matchedValue = null;
                
                // 1. 先尝试精确匹配值
                for (var i = 0; i < options.length; i++) {
                    if (options[i].value === targetValue) {
                        matchedOption = options[i];
                        matchedValue = targetValue;
                        break;
                    }
                }
                
                // 2. 如果精确匹配失败，尝试模糊匹配文本
                if (!matchedOption) {
                    for (var i = 0; i < options.length; i++) {
                        var text = options[i].text || '';
                        var value = options[i].value || '';
                        // 跳过空值和提示选项
                        if (!value || value === '') continue;
                        // 模糊匹配：文本包含目标值，或目标值包含文本中的关键字
                        if (text.toUpperCase().indexOf(targetValue.toUpperCase()) !== -1) {
                            matchedOption = options[i];
                            matchedValue = value;
                            break;
                        }
                    }
                }
                
                // 3. 尝试从选项文本中提取BU代码（如 "(185)亚信科技CMB" 中的 185）
                if (!matchedOption) {
                    for (var i = 0; i < options.length; i++) {
                        var text = options[i].text || '';
                        var value = options[i].value || '';
                        if (!value || value === '') continue;
                        // 提取括号中的代码
                        var match = text.match(/\\((\\w+)\\)/);
                        if (match && match[1] === targetValue) {
                            matchedOption = options[i];
                            matchedValue = value;
                            break;
                        }
                    }
                }
                
                if (!matchedOption) {
                    // 列出可用选项
                    var available = [];
                    for (var i = 0; i < Math.min(options.length, 20); i++) {
                        if (options[i].value) {
                            available.push({value: options[i].value, text: options[i].text});
                        }
                    }
                    return {success: false, error: '未找到匹配选项', available: available};
                }
                
                // 设置 select 的值
                select.value = matchedValue;
                
                // 触发 change 事件
                var event = new Event('change', { bubbles: true });
                select.dispatchEvent(event);
                
                // 如果有 layui，触发渲染
                if (window.layui) {
                    layui.use('form', function() {
                        var form = layui.form;
                        form.render('select');
                    });
                }
                
                return {success: true, selectedValue: matchedValue, selectedText: matchedOption.text};
            }""", {"selectId": select_id, "targetValue": target_value})

            if result.get("success"):
                print(f"[SUCCESS] 已选择 {select_id}: {result.get('selectedText')} (值: {result.get('selectedValue')})")
                self._page.wait_for_timeout(500)
                return True
            else:
                print(f"[WARNING] 选择失败: {result.get('error')}")
                available = result.get("available", [])
                if available:
                    print(f"[INFO] 可用选项示例:")
                    for opt in available[:10]:
                        print(f"    {opt.get('value')}: {opt.get('text')}")
                return False

        except Exception as e:
            print(f"[ERROR] 选择 {select_id} 失败: {e}")
            return False

    # ===================== 查询与导出 =====================

    def _query_and_export(
        self,
        frame: Frame,
        quarter: str,
        bu_name: str = ""
    ) -> Optional[str]:
        """
        在 iframe 中填写条件、查询并导出

        Args:
            frame: 绩效考核查询 iframe 对象
            quarter: 季度（格式如 202601）
            bu_name: BU 名称或代码，为空则不筛选

        Returns:
            Optional[str]: 下载文件路径，失败返回 None
        """
        print(f"[INFO] 开始查询 [季度: {quarter}]{f' [BU: {bu_name}]' if bu_name else ''}...")

        try:
            # 重新获取最新的 frame，防止 detach
            frame = self._get_fresh_frame()
            if not frame:
                print("[ERROR] 无法获取查询页面 frame")
                return None
            self._page.wait_for_timeout(2000)

            # 调试模式：输出页面信息
            if self.DEBUG_MODE:
                try:
                    html = frame.evaluate("""() => document.body.innerHTML.substring(0, 3000)""")
                    print(f"[DEBUG] 页面HTML片段:\n{html}")
                except Exception:
                    pass

            # 选择季度 (layui select)
            if not self._select_layui_option(frame, self.LAYUI_IDS["quarter"], quarter):
                print(f"[WARNING] 未能选择季度: {quarter}")
            self._page.wait_for_timeout(500)

            # 选择 BU (layui select)
            if bu_name:
                if not self._select_layui_option(frame, self.LAYUI_IDS["bu"], bu_name):
                    print(f"[WARNING] 未能选择 BU: {bu_name}")
                self._page.wait_for_timeout(500)

            # 点击查询按钮
            try:
                query_btn = frame.locator("a[lay-filter='searchForm'], a:has-text('查询')").first
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
                with self._page.expect_download(timeout=60000) as download_info:
                    export_btn = frame.locator("a[lay-event='export'], a:has-text('导出')").first
                    export_btn.click()
                    print("[INFO] 已点击导出按钮")

                download = download_info.value

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                bu_part = bu_name.replace("/", "_") if bu_name else "全部BU"
                filename = f"绩效考核_{quarter}_{bu_part}_{timestamp}.xlsx"
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

    def download_kpi_performance_reports(
        self,
        quarters: List[str],
        bu_list: Optional[List[str]] = None,
        start_browser: bool = True
    ) -> List[str]:
        """
        下载绩效考核报表（主入口方法）
        
        Args:
            quarters: 季度列表，如 ["202601", "202602"]
            bu_list: BU列表，如 ["121", "100"]，为空则查询全部
            start_browser: 是否自动启动浏览器
        
        Returns:
            下载文件路径列表
        """
        downloaded_files = []

        try:
            if start_browser:
                self.start()

            self.login()

            if not bu_list:
                bu_list = [""]  # 空字符串表示不筛选BU

            for q_idx, quarter in enumerate(quarters):
                for b_idx, bu in enumerate(bu_list):
                    print(f"\n{'='*60}")
                    print(f"[INFO] 处理 季度 {q_idx+1}/{len(quarters)}: {quarter}, BU {b_idx+1}/{len(bu_list)}: {bu or '全部'}")
                    print(f"{'='*60}")

                    frame = self.navigate_to_kpi_performance()

                    result = self._query_and_export(
                        frame=frame,
                        quarter=quarter,
                        bu_name=bu
                    )

                    if result:
                        downloaded_files.append(result)

                    # 等待后继续下一个
                    if not (q_idx == len(quarters) - 1 and b_idx == len(bu_list) - 1):
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
            print(f"[ERROR] 下载绩效考核报表失败: {e}")
            raise

        finally:
            if start_browser:
                self.stop()


def parse_quarter_input(quarter_str: str) -> str:
    """
    解析季度输入，确保格式正确
    
    Args:
        quarter_str: 季度字符串，如 "202601"
    
    Returns:
        标准化的季度字符串
    """
    quarter_str = quarter_str.strip()
    match = re.match(r'(\d{4})(0?[1-4])', quarter_str)
    if match:
        year = match.group(1)
        q = int(match.group(2))
        return f"{year}0{q}"
    
    # 检测常见错误格式
    match_wrong = re.match(r'(\d{4})(\d{2})', quarter_str)
    if match_wrong:
        q = int(match_wrong.group(2))
        if q > 4:
            raise ValueError(f"季度格式错误: '{quarter_str}'，季度只能是01-04，您输入的是'{q}'。正确示例: 202601（2026年第一季度）")
    
    raise ValueError(f"无法解析季度: {quarter_str}，请使用格式如 '202601'（表示2026年第一季度，季度只能是01-04）")


def main():
    """主函数 - 交互式输入"""
    try:
        from config import USERNAME, PASSWORD, DOWNLOAD_DIR
    except ImportError:
        USERNAME = ""
        PASSWORD = ""
        DOWNLOAD_DIR = "./downloads"

    import argparse

    parser = argparse.ArgumentParser(description="绩效考核下载工具")
    parser.add_argument("-u", "--username", help="登录用户名", default=USERNAME)
    parser.add_argument("-p", "--password", help="登录密码", default=PASSWORD)
    parser.add_argument("-q", "--quarter", help="季度列表（逗号分隔），如 202601,202602（季度只能是01-04）", default=None)
    parser.add_argument("-s", "--sbu", help="BU列表（逗号分隔），可输入代码如 121,185 或名称如 CTC,CMB，不填则查询全部", default=None)
    parser.add_argument("-d", "--download-dir", help="下载目录", default=DOWNLOAD_DIR)
    parser.add_argument("--headless", action="store_true", help="隐藏浏览器（无头模式）")
    parser.add_argument("--debug", action="store_true", help="调试模式，输出页面控件信息")

    args = parser.parse_args()

    username = args.username or input("请输入用户名: ")
    password = args.password or input("请输入密码: ")

    quarter_input = args.quarter if args.quarter is not None else input("请输入季度（格式：年份+季度，如 202601=2026年Q1，多个用逗号分隔）: ").strip()
    
    # 解析季度
    quarters = []
    for q in re.split(r'[,，]', quarter_input):
        q = q.strip()
        if q:
            try:
                quarters.append(parse_quarter_input(q))
            except ValueError as e:
                print(f"[ERROR] {e}")
                return

    if not quarters:
        print("[ERROR] 必须提供至少一个季度")
        return

    bu_input = args.sbu if args.sbu is not None else input("请输入BU（可输入代码如 121 或名称如 CTC，多个用逗号分隔，直接回车查询全部）: ").strip()
    bu_list = [s.strip() for s in re.split(r'[,，]', bu_input) if s.strip()] if bu_input else []

    print(f"\n{'='*60}")
    print(f"  绩效考核下载工具")
    print(f"{'='*60}")
    print(f"  用户名: {username}")
    print(f"  季度: {', '.join(quarters)}")
    print(f"  BU: {', '.join(bu_list) if bu_list else '全部'}")
    print(f"  下载目录: {args.download_dir}")
    print(f"{'='*60}\n")

    with KPIPerformanceDownloader(
        username=username,
        password=password,
        download_dir=args.download_dir,
        headless=args.headless,
        debug=args.debug
    ) as downloader:
        results = downloader.download_kpi_performance_reports(
            quarters=quarters,
            bu_list=bu_list if bu_list else None,
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
