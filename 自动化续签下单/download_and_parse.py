"""
续签下载与清单生成集成模块
复用 RenewalQueryDownloader，添加下载后的 Excel 解析和待办清单生成
集成人员变更下载和离岗不续签清单生成
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Tuple


# 添加下载模块到路径
sys.path.insert(0, str(Path(__file__).parent / "下载外包续签查询"))

from 下载外包续签查询.renewal_query_downloader import RenewalQueryDownloader
from 下载外包续签查询.application_form_downloader import ApplicationFormDownloader
from 下载外包续签查询.config import USERNAME, PASSWORD, DOWNLOAD_DIR
from utils.excel_parser import ExcelParser
from utils.logger import setup_logger

logger = setup_logger(__name__)


class DownloadAndParseManager:
    """下载与清单生成管理器"""

    def __init__(self, username: str = USERNAME, password: str = PASSWORD,
                 download_dir: str = DOWNLOAD_DIR, headless: bool = False):
        self.username = username
        self.password = password
        self.download_dir = Path(download_dir)
        self.headless = headless
        self.downloader = RenewalQueryDownloader(
            username=username,
            password=password,
            download_dir=str(self.download_dir),
            headless=headless
        )

        # 人员变更下载器（动态导入）
        self.personnel_downloader = None
        # 申请单下载器（延迟初始化，依赖浏览器启动后的 page 对象）
        self.app_form_downloader = None

    def _init_personnel_downloader(self):
        """延迟初始化人员变更下载器"""
        if self.personnel_downloader is None:
            try:
                # 导入人员变更下载器（相对于本模块的同级目录）
                personnel_module_dir = Path(__file__).parent / "下载人员变更"
                if str(personnel_module_dir) not in sys.path:
                    sys.path.insert(0, str(personnel_module_dir))
                from personnel_change_downloader import PersonnelChangeDownloader
                self.personnel_downloader = PersonnelChangeDownloader(
                    username=self.username,
                    password=self.password,
                    download_dir=str(self.download_dir),
                    headless=self.headless
                )
            except Exception as e:
                logger.error(f"初始化人员变更下载器失败: {e}")
                raise

    @staticmethod
    def _parse_date(date_str: str) -> datetime:
        """解析日期字符串，支持 YYYY年MM月DD日 / YYYY-MM-DD / YYYY/MM/DD"""
        normalized = date_str.strip().replace("年", "-").replace("月", "-").replace("日", "")
        normalized = normalized.replace("/", "-").replace(".", "-")
        return datetime.strptime(normalized, "%Y-%m-%d")

    @classmethod
    def _calculate_personnel_date_range(cls, renewal_end_date: str) -> Tuple[str, str]:
        """
        根据续签查询结束日期，计算人员变更下载的申请时间范围。

        规则：
        - 结束时间 = 续签查询的结束时间
        - 开始时间 = 续签查询结束时间早2个月的同一天
          （例如结束时间为 2026年3月31日，则开始时间为 2026年1月31日；
           若目标月无该日则取该月最后一天，如 2月无31日则取2月28/29日）
        """
        if not renewal_end_date:
            raise ValueError("续签查询结束日期不能为空，无法计算人员变更下载时间范围")

        end_date_obj = cls._parse_date(renewal_end_date)

        # 往前推2个月（处理跨年及月末边界）
        month = end_date_obj.month - 2
        year = end_date_obj.year
        if month <= 0:
            month += 12
            year -= 1

        # 处理目标月没有该天的情况（如3月31日 -> 1月31日 ok；但3月31日 -> 1月31日 ok，1月30日ok）
        import calendar
        max_day = calendar.monthrange(year, month)[1]
        day = min(end_date_obj.day, max_day)

        start_date_obj = end_date_obj.replace(year=year, month=month, day=day)
        start_date_str = f"{start_date_obj.year}年{start_date_obj.month:02d}月{start_date_obj.day:02d}日"
        end_date_str = f"{end_date_obj.year}年{end_date_obj.month:02d}月{end_date_obj.day:02d}日"

        return start_date_str, end_date_str

    @classmethod
    def _calculate_app_form_date_range(cls, renewal_end_date: str) -> Tuple[str, str]:
        """
        根据续签查询结束日期，计算申请单下载的申请时间范围。

        规则：
        - 结束时间 = 续签查询的结束时间
        - 开始时间 = 续签查询结束时间早30天
        """
        if not renewal_end_date:
            raise ValueError("续签查询结束日期不能为空，无法计算申请单下载时间范围")

        end_date_obj = cls._parse_date(renewal_end_date)
        start_date_obj = end_date_obj - timedelta(days=30)

        start_date_str = f"{start_date_obj.year}年{start_date_obj.month:02d}月{start_date_obj.day:02d}日"
        end_date_str = f"{end_date_obj.year}年{end_date_obj.month:02d}月{end_date_obj.day:02d}日"

        return start_date_str, end_date_str

    def download_reports(self, sbu_list: Optional[List[str]] = None,
                         start_date: str = "", end_date: str = "") -> List[str]:
        """
        下载续签查询报表

        Args:
            sbu_list: SBU 列表
            start_date: 开始日期（格式: YYYY年MM月DD日）
            end_date: 结束日期（格式: YYYY年MM月DD日）

        Returns:
            List[str]: 下载的文件路径列表
        """
        logger.info("=== 开始下载续签查询报表 ===")

        try:
            results = self.downloader.download_renewal_reports(
                sbu_list=sbu_list,
                start_date_str=start_date,
                end_date_str=end_date,
                start_browser=True
            )

            logger.info(f"下载完成，共 {len(results)} 个文件")
            return results

        except Exception as e:
            logger.error(f"下载失败: {e}", exc_info=True)
            raise

    def download_personnel_change_reports(self, sbu_list: Optional[List[str]] = None,
                                          renewal_end_date: str = "") -> List[str]:
        """
        下载人员变更报表

        规则：
        - 申请时间结束 = 续签查询结束时间
        - 申请时间开始 = 续签查询结束时间早2个月的同一天

        Args:
            sbu_list: SBU 列表
            renewal_end_date: 续签查询结束日期

        Returns:
            List[str]: 下载的文件路径列表
        """
        personnel_start_date, personnel_end_date = self._calculate_personnel_date_range(renewal_end_date)
        logger.info("=== 开始下载人员变更报表 ===")
        logger.info(f"人员变更申请时间范围: {personnel_start_date} ~ {personnel_end_date}")

        try:
            self._init_personnel_downloader()

            results = self.personnel_downloader.download_personnel_change_reports(
                sbu_list=sbu_list,
                start_date_str=personnel_start_date,
                end_date_str=personnel_end_date,
                start_browser=True
            )

            logger.info(f"人员变更报表下载完成，共 {len(results)} 个文件")
            return results

        except Exception as e:
            logger.error(f"人员变更报表下载失败: {e}", exc_info=True)
            raise

    def download_app_form_reports(self, sbu_list: Optional[List[str]] = None,
                                   renewal_end_date: str = "") -> List[str]:
        """
        下载申请单报表

        规则：
        - 申请时间结束 = 续签查询结束时间
        - 申请时间开始 = 续签查询结束时间早30天

        Args:
            sbu_list: SBU 列表
            renewal_end_date: 续签查询结束日期

        Returns:
            List[str]: 下载的文件路径列表
        """
        app_form_start_date, app_form_end_date = self._calculate_app_form_date_range(renewal_end_date)
        logger.info("=== 开始下载申请单报表 ===")
        logger.info(f"申请单申请时间范围: {app_form_start_date} ~ {app_form_end_date}")

        try:
            # 使用已登录的浏览器 page 对象（下载器必须先 start 才能拿到 page）
            if self.downloader._page is None:
                raise Exception("浏览器未启动，请先执行续签查询下载或手动 start")

            self.app_form_downloader = ApplicationFormDownloader(
                page=self.downloader._page,
                download_dir=str(self.download_dir)
            )

            results = []
            sbu_names = sbu_list if sbu_list else [""]
            for sbu in sbu_names:
                result = self.app_form_downloader.download_application_form(
                    sbu_name=sbu,
                    start_date_str=app_form_start_date,
                    end_date_str=app_form_end_date
                )
                if result:
                    results.append(result)

            logger.info(f"申请单报表下载完成，共 {len(results)} 个文件")
            return results

        except Exception as e:
            logger.error(f"申请单报表下载失败: {e}", exc_info=True)
            raise

    def parse_and_generate_todo_list(self, excel_file: str,
                                     output_dir: str = ".",
                                     valid_app_nos: Optional[set] = None) -> Tuple[str, 'pd.DataFrame']:
        """
        解析 Excel 文件并生成待办清单

        Args:
            excel_file: Excel 文件路径
            output_dir: 输出目录
            valid_app_nos: 有效申请单号集合（来自申请单），用于过滤

        Returns:
            Tuple[str, pd.DataFrame]: (待办清单文件路径, 待办清单数据框)
        """
        logger.info(f"=== 开始解析 Excel 文件: {excel_file} ===")

        try:
            # 加载并筛选（传入有效申请单号集合）
            filtered_df = ExcelParser.load_and_filter(excel_file, valid_app_nos=valid_app_nos)

            # 生成待办清单
            todo_df = ExcelParser.generate_todo_list(filtered_df)

            # 保存待办清单
            output_file = ExcelParser.save_todo_list(todo_df, output_dir=output_dir)

            logger.info(f"待办清单生成成功: {output_file}")
            logger.info(f"总记录数: {len(todo_df)}")

            return output_file, todo_df

        except Exception as e:
            logger.error(f"清单生成失败: {e}", exc_info=True)
            raise

    def parse_and_generate_personnel_not_renewing_list(self, excel_file: str,
                                                       audit_date: Optional[str] = None,
                                                       output_dir: str = ".") -> Tuple[str, 'pd.DataFrame']:
        """
        解析人员变更 Excel 文件并生成离岗不续签清单

        Args:
            excel_file: 人员变更 Excel 文件路径
            audit_date: 稽核时间（格式：YYYY-MM-DD或YYYY年MM月DD日）
            output_dir: 输出目录

        Returns:
            Tuple[str, pd.DataFrame]: (离岗不续签清单文件路径, 清单数据框)
        """
        logger.info(f"=== 开始解析人员变更 Excel 文件: {excel_file} ===")
        logger.info(f"稽核时间: {audit_date}")

        try:
            # 加载人员变更数据
            personnel_df = ExcelParser.load_personnel_change(excel_file)

            # 筛选离岗不续签人员
            not_renewing_df = ExcelParser.filter_personnel_not_renewing(
                personnel_df,
                audit_date=audit_date
            )

            # 保存离岗不续签清单
            output_file = ExcelParser.save_personnel_not_renewing_list(
                not_renewing_df,
                output_dir=output_dir
            )

            logger.info(f"离岗不续签清单生成成功: {output_file}")
            logger.info(f"总记录数: {len(not_renewing_df)}")

            return output_file, not_renewing_df

        except Exception as e:
            logger.error(f"离岗不续签清单生成失败: {e}", exc_info=True)
            raise

    def execute_full_pipeline(self, sbu_list: Optional[List[str]] = None,
                              start_date: str = "", end_date: str = "",
                              audit_date: Optional[str] = None,
                              output_dir: str = ".") -> tuple:
        """
        执行完整的下载 -> 解析 -> 双清单生成流程

        Args:
            sbu_list: SBU 列表
            start_date: 开始日期
            end_date: 结束日期
            audit_date: 稽核时间（用于人员变更清单筛选）
            output_dir: 输出目录

        Returns:
            Tuple: (下载文件列表, 待办清单文件路径, 待办清单df, 离岗清单文件路径, 离岗清单df)
        """
        logger.info("=== 执行完整下载与双清单生成流程 ===")

        if not audit_date:
            audit_date = end_date
            logger.info(f"未指定稽核时间，默认使用续签查询结束日期: {audit_date}")

        # 1. 下载续签查询报表（自带浏览器生命周期）
        renewal_files = self.download_reports(sbu_list, start_date, end_date)

        if not renewal_files:
            logger.error("未下载到续签查询报表文件")
            raise Exception("续签查询报表下载失败")

        # 1.5. 下载申请单报表（单独启动浏览器，失败不中断主流程）
        valid_app_nos = None
        try:
            # 为申请单下载单独启动浏览器会话
            self.downloader.start()
            try:
                self.downloader.login()
                app_form_files = self.download_app_form_reports(
                    sbu_list=sbu_list,
                    renewal_end_date=end_date
                )
            finally:
                self.downloader.stop()

            if app_form_files:
                # 合并所有 SBU 的申请单编号
                valid_app_nos = set()
                for app_form_file in app_form_files:
                    try:
                        app_nos = ExcelParser.parse_application_form(app_form_file)
                        valid_app_nos.update(app_nos)
                        logger.info(f"✓ 申请单解析成功: {app_form_file} ({len(app_nos)} 条)")
                    except Exception as e:
                        logger.warning(f"⚠️  申请单解析失败 ({app_form_file}): {e}")
                logger.info(f"✓ 合并后有效合作申请单编号总数: {len(valid_app_nos)}")
            else:
                logger.warning("⚠️  未下载到申请单报表，将不过滤申请单号")
        except Exception as e:
            logger.warning(f"⚠️  申请单模块异常: {e}")
            logger.warning("将继续生成待办清单，但不过滤申请单号")

        # 2. 解析所有续签查询报表并生成合并待办清单（传入有效申请单号集合用于过滤）
        import pandas as pd
        todo_df_list = []
        for excel_file in renewal_files:
            try:
                filtered_df = ExcelParser.load_and_filter(excel_file, valid_app_nos=valid_app_nos)
                todo_df_list.append(filtered_df)
                logger.info(f"✓ 解析完成: {excel_file} ({len(filtered_df)} 条)")
            except Exception as e:
                logger.warning(f"⚠️  解析失败 ({excel_file}): {e}")

        if not todo_df_list:
            raise Exception("所有续签查询报表解析失败")

        combined_df = pd.concat(todo_df_list, ignore_index=True)
        if "合作申请单编号" in combined_df.columns:
            combined_df = combined_df.drop_duplicates(subset=["合作申请单编号"], ignore_index=True)
        logger.info(f"✓ 合并后共 {len(combined_df)} 条记录（已去重）")

        todo_df = ExcelParser.generate_todo_list(combined_df)
        todo_file = ExcelParser.save_todo_list(todo_df, output_dir=output_dir)

        # 3. 下载人员变更报表（可选，失败不中断主流程）
        not_renewing_file = None
        not_renewing_df = None

        try:
            personnel_files = self.download_personnel_change_reports(
                sbu_list=sbu_list,
                renewal_end_date=end_date
            )

            if personnel_files:
                # 合并所有 SBU 的人员变更数据
                personnel_df_list = []
                for personnel_file in personnel_files:
                    try:
                        df_part = ExcelParser.load_personnel_change(personnel_file)
                        personnel_df_list.append(df_part)
                        logger.info(f"✓ 人员变更解析: {personnel_file} ({len(df_part)} 条)")
                    except Exception as e:
                        logger.warning(f"⚠️  人员变更解析失败 ({personnel_file}): {e}")

                if personnel_df_list:
                    import pandas as pd
                    combined_personnel = pd.concat(personnel_df_list, ignore_index=True)
                    if "身份证号" in combined_personnel.columns:
                        combined_personnel = combined_personnel.drop_duplicates(subset=["身份证号"], ignore_index=True)
                    logger.info(f"✓ 人员变更合并: {len(combined_personnel)} 条（已去重）")

                    # 筛选离岗不续签人员
                    not_renewing_df = ExcelParser.filter_personnel_not_renewing(
                        combined_personnel, audit_date=audit_date
                    )
                    not_renewing_file = ExcelParser.save_personnel_not_renewing_list(
                        not_renewing_df, output_dir=output_dir
                    )
                    logger.info(f"✓ 离岗不续签清单: {not_renewing_file} ({len(not_renewing_df)} 条)")
            else:
                logger.warning("⚠️  未下载到人员变更报表，将跳过不续签人员删除功能")
        except Exception as e:
            logger.warning(f"⚠️  人员变更模块异常: {e}")
            logger.warning("将继续执行下单流程，但不删除不续签人员")

        # 清理过程性临时文件（UUID 命名的 Playwright 下载残留）
        try:
            import re
            work_dir = Path(output_dir)
            for f in work_dir.iterdir():
                if f.is_file() and re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', f.name, re.I):
                    try:
                        f.unlink()
                        logger.info(f"已清理临时文件: {f.name}")
                    except Exception:
                        pass
        except Exception:
            pass

        return renewal_files, todo_file, todo_df, not_renewing_file, not_renewing_df


def main():
    """测试脚本"""
    import argparse

    parser = argparse.ArgumentParser(description="下载与清单生成工具")
    parser.add_argument("--sbu", help="SBU（多个用逗号分隔）", default=None)
    parser.add_argument("--start", help="开始日期（格式: 2025年1月1日）", default="2026年3月1日")
    parser.add_argument("--end", help="结束日期（格式: 2025年12月31日）", default="2026年3月31日")
    parser.add_argument("--audit-date", help="稽核时间（格式: 2026-03-31或2026年3月31日）", default=None)
    parser.add_argument("--output-dir", help="输出目录", default=".")
    parser.add_argument("--headless", action="store_true", help="隐藏浏览器（无头模式）")

    args = parser.parse_args()

    sbu_list = None
    if args.sbu:
        sbu_list = [s.strip() for s in args.sbu.split(",")]

    try:
        manager = DownloadAndParseManager(headless=args.headless)
        renewal_files, todo_file, todo_df, not_renewing_file, not_renewing_df = \
            manager.execute_full_pipeline(
                sbu_list=sbu_list,
                start_date=args.start,
                end_date=args.end,
                audit_date=args.audit_date,
                output_dir=args.output_dir
            )

        logger.info("\n=== 流程完成 ===")
        logger.info(f"续签查询文件: {renewal_files}")
        logger.info(f"待办清单: {todo_file} ({len(todo_df)} 条记录)")
        if not_renewing_file and not_renewing_df is not None:
            logger.info(f"离岗不续签清单: {not_renewing_file} ({len(not_renewing_df)} 条记录)")
        else:
            logger.info("离岗不续签清单: 未生成")

    except Exception as e:
        logger.error(f"流程失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
