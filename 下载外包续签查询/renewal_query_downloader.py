"""
外包续签查询下载自动化工具
使用 Playwright 实现网页自动化操作
"""
import sys
import re
from pathlib import Path
from typing import Optional, List

# 添加父目录到路径，以便导入 common 包
sys.path.insert(0, str(Path(__file__).parent.parent))

from common.base_downloader import BaseDownloader


class RenewalQueryDownloader(BaseDownloader):
    """外包续签查询下载器"""

    MENU_PARENT = "外包数据查询"
    MENU_CHILD = "外包续签查询"
    FRAME_KEYWORDS = [
        "renew", "Renew", "续签", "xuqian",
        "RenewQuery", "renewQuery",
        "OutsourceRenew", "outsourceRenew",
        "TechStaffxqQuery", "xqQuery",
    ]
    EXPORT_BTN_TEXT = "导出待续签人员"
    DOWNLOAD_TIMEOUT = 180000

    MINIUI_IDS = {
        "sbu": "p_sbu_id",
        "begin_date": "p_apply_begin_date",
        "end_date": "p_apply_end_date",
    }

    # ===================== 清空表单 =====================

    def _clear_form(self, target) -> None:
        """清空表单条件（切换 SBU 时重置）"""
        print("[INFO] 正在清空表单条件...")
        try:
            target.evaluate(f"""() => {{
                var sbu = mini.get('{self.MINIUI_IDS["sbu"]}');
                if (sbu) sbu.setValue('');
                var beg = mini.get('{self.MINIUI_IDS["begin_date"]}');
                var end = mini.get('{self.MINIUI_IDS["end_date"]}');
                if (beg) beg.setValue('');
                if (end) end.setValue('');
            }}""")
            self._page.wait_for_timeout(1000)
            print("[INFO] 表单条件已清空")
        except Exception as e:
            print(f"[WARNING] 清空表单失败: {e}")

    # ===================== 查询与导出 =====================

    def query_and_export(self, target, sbu_name: str = "",
                          start_str: str = "", end_str: str = "") -> Optional[str]:
        """填写条件、查询并导出"""
        print(f"[INFO] 开始查询{' [' + sbu_name + ']' if sbu_name else ' (所有)'}...")

        try:
            # 重新获取 frame，防止 detach
            if not self._query_is_tab:
                frame = self._get_fresh_frame()
                if not frame:
                    print("[ERROR] 无法获取查询页面 frame")
                    return None
                target = frame
            self._page.wait_for_timeout(2000)

            # 清空表单
            self._clear_form(target)
            self._page.wait_for_timeout(1000)

            # 选择 SBU
            if sbu_name:
                self._select_miniui_combobox(target, self.MINIUI_IDS["sbu"], sbu_name)
                self._page.wait_for_timeout(500)

            # 输入查询时间
            self._input_miniui_date(target, self.MINIUI_IDS["begin_date"],
                                     self.MINIUI_IDS["end_date"], start_str, end_str)

            # 点击查询
            self._click_query_button(target)
            self._page.wait_for_timeout(2000)

            # 导出
            result = self._click_export_and_save(
                target, "外包续签查询", sbu_name, start_str, end_str
            )
            return result

        except Exception as e:
            print(f"[ERROR] 查询导出流程异常: {e}")
            try:
                self._page.screenshot(path=str(self.download_dir / "debug_error.png"))
            except Exception:
                pass
            return None


def parse_date_input(date_str: str) -> str:
    """解析日期输入 '2025年1月1日' → '2025年01月01日'"""
    from common.utils import parse_date_input as _parse
    return _parse(date_str)


def main():
    from common.utils import parse_date_input, parse_time_input

    try:
        from config import USERNAME, PASSWORD, DOWNLOAD_DIR
    except ImportError:
        USERNAME = ""
        PASSWORD = ""
        DOWNLOAD_DIR = "./downloads"

    import argparse

    parser = argparse.ArgumentParser(description="外包续签查询下载工具")
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
    start_str = parse_date_input(start_input)

    end_input = args.end if args.end is not None else input("请输入结束日期（如 2025年12月31日）: ").strip()
    end_str = parse_date_input(end_input)

    print(f"\n{'='*60}")
    print(f"  外包续签查询下载工具")
    print(f"{'='*60}")
    print(f"  用户名: {username}")
    print(f"  SBU: {', '.join(sbu_list) if sbu_list else '全部'}")
    print(f"  查询时间: {start_str} ~ {end_str}")
    print(f"  下载目录: {args.download_dir}")
    print(f"{'='*60}\n")

    with RenewalQueryDownloader(
        username=username, password=password,
        download_dir=args.download_dir,
        headless=args.headless
    ) as downloader:
        results = downloader.run(
            sbu_list=sbu_list if sbu_list else None,
            start_str=start_str, end_str=end_str,
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
