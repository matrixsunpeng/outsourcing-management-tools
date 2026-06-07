"""
续签订单处理流程编排模块
循环处理待办清单，调用交互层进行下单，处理异常和状态回写
"""

import sys
from pathlib import Path
from typing import Optional

# 添加下载模块到路径
sys.path.insert(0, str(Path(__file__).parent / "下载外包续签查询"))

import pandas as pd
from playwright.sync_api import sync_playwright

from 下载外包续签查询.renewal_query_downloader import RenewalQueryDownloader
from 下载外包续签查询.config import USERNAME, PASSWORD, DOWNLOAD_DIR
from renewal_order_submitter import OutsourceContractSubmitter
from utils.excel_parser import ExcelParser
from utils.logger import setup_logger

logger = setup_logger(__name__)


class RenewalOrderProcessor:
    """续签订单处理流程编排"""
    
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
    
    def navigate_to_contract_page(self, page) -> bool:
        """
        从主页导航到外包合同页面
        
        Args:
            page: Playwright Page 对象
            
        Returns:
            bool: 是否成功
        """
        logger.info("=== 导航到外包合同页面 ===")
        
        try:
            page.wait_for_timeout(3000)
            
            # 双击"外包申请"展开子菜单
            logger.info("[菜单] 双击外包申请...")
            try:
                outsource_row = page.locator(".mini-tree-nodetext:has-text('外包申请')").first
                outsource_row.dblclick()
                page.wait_for_timeout(2000)
            except Exception as e:
                logger.warning(f"[菜单] 双击失败，尝试 JS 展开: {e}")
                page.evaluate("""
                    var tree = mini.get("tree1");
                    if (tree) {
                        var nodes = tree.getData();
                        for (var i = 0; i < nodes.length; i++) {
                            if (nodes[i].text && nodes[i].text.includes('外包申请')) {
                                tree.expandNode(nodes[i]);
                                break;
                            }
                        }
                    }
                """)
                page.wait_for_timeout(2000)
            
            # 单击"外包合同"（可能打开新标签页）
            logger.info("[菜单] 单击外包合同...")
            try:
                with page.context.expect_page(timeout=5000) as new_page_info:
                    link = page.locator(".mini-tree-nodetext:has-text('外包合同')").first
                    link.click()
                
                contract_page = new_page_info.value
                contract_page.wait_for_load_state("domcontentloaded")
                contract_page.wait_for_timeout(3000)
                
                logger.info(f"[菜单] 外包合同页面已打开: {contract_page.url}")
                return contract_page
                
            except Exception:
                logger.warning("[菜单] 未检测到新标签页，尝试 iframe...")
                page.wait_for_timeout(3000)
                
                # 检查 iframe
                for frame in page.frames:
                    if frame.url and "contract" in frame.url.lower():
                        logger.info(f"[菜单] 找到外包合同 iframe: {frame.url}")
                        return frame
                
                # 备用方案：使用最后一个非主 frame
                non_main_frames = [f for f in page.frames 
                                  if f != page.main_frame and f.url and "about:blank" not in f.url]
                if non_main_frames:
                    contract_frame = non_main_frames[-1]
                    logger.info(f"[菜单] 使用最后一个 iframe: {contract_frame.url}")
                    return contract_frame
                
                logger.error("[菜单] 无法导航到外包合同页面")
                return None
        
        except Exception as e:
            logger.error(f"[菜单] 导航异常: {e}")
            return None
    
    def process_todo_list(self, todo_df: pd.DataFrame, page,
                          not_renewing_df: Optional[pd.DataFrame] = None,
                          skip_delete: bool = False,
                          resume: bool = False) -> pd.DataFrame:
        """
        逐条处理待办清单

        规则：
        - 相同"待续签申请单"只执行一次
        - 同一"待续签申请单"有多个"技术合作商名称"时，按合作商依次执行，相同组合只执行一次
        - 当 resume=True 时，跳过「反馈」列非空的行（断点续跑）

        Args:
            todo_df: 待办清单 DataFrame
            page: 外包合同 Page/Frame 对象
            not_renewing_df: 离岗不续签清单 DataFrame（用于人员删除）
            skip_delete: 是否跳过离岗不续签人员删除
            resume: 是否启用断点续跑（跳过已有反馈的记录）

        Returns:
            pd.DataFrame: 带有反馈的待办清单
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"开始处理待办清单，共 {len(todo_df)} 条记录")
        if skip_delete:
            logger.info("[人员删除] 已跳过（--skip-delete）")
        elif not_renewing_df is not None:
            logger.info(f"离岗不续签清单包含 {len(not_renewing_df)} 条记录")
        else:
            logger.info("[人员删除] 未提供离岗不续签清单，跳过")
        
        # ── 断点续跑统计 ──
        if resume:
            feedback_col = "反馈" if "反馈" in todo_df.columns else (
                "处理状态" if "处理状态" in todo_df.columns else None
            )
            if feedback_col:
                completed_mask = todo_df[feedback_col].astype(str).str.strip() != ""
                completed_count = int(completed_mask.sum())
                remaining_count = len(todo_df) - completed_count
                logger.info(f"[续跑] 断点续跑模式已开启")
                logger.info(f"[续跑] 已完成: {completed_count} 条 | 剩余: {remaining_count} 条 | 总计: {len(todo_df)} 条")
                if completed_count > 0:
                    sample_completed = todo_df[completed_mask][["待续签申请单", "技术合作商名称", feedback_col]].head(3)
                    for _, srow in sample_completed.iterrows():
                        logger.info(f"[续跑] 跳过: {srow['待续签申请单']} | {srow['技术合作商名称']} → {srow[feedback_col]}")
                    if completed_count > 3:
                        logger.info(f"[续跑] ... 还有 {completed_count - 3} 条已完成")
            else:
                logger.warning("[续跑] 未找到「反馈」列，无法判断已完成项，将从头处理")
                resume = False
        
        logger.info(f"{'='*60}\n")
        
        submitter = OutsourceContractSubmitter(page)
        
        # 记录已处理过的 (申请单, 合作商) 组合，避免重复下单
        processed_combinations = set()
        
        for idx, row in todo_df.iterrows():
            app_no = str(row["待续签申请单"]).strip()
            vendor_name = str(row["技术合作商名称"]).strip()
            work_location = str(row.get("工作地点", "")).strip()
            signing_party = str(row.get("签约方", "")).strip()

            combo_key = (app_no, vendor_name)
            
            # ── 断点续跑：跳过已有反馈的行 ──
            if resume:
                feedback_col = "反馈" if "反馈" in todo_df.columns else (
                    "处理状态" if "处理状态" in todo_df.columns else None
                )
                if feedback_col:
                    existing_feedback = str(row.get(feedback_col, "")).strip()
                    if existing_feedback:
                        logger.info(f"[续跑] 跳过已完成: {app_no} | {vendor_name} → {existing_feedback}")
                        continue
            
            logger.info(f"\n[进度] 处理第 {idx + 1}/{len(todo_df)} 条: {app_no} | {vendor_name}")
            
            # 跳过已处理过的组合
            if combo_key in processed_combinations:
                skip_msg = "跳过（申请单+合作商组合已处理）"
                ExcelParser.update_status(todo_df, idx, skip_msg)
                logger.info(f"[跳过] {app_no} | {vendor_name} - {skip_msg}")
                continue
            
            try:
                success, message = submitter.process_single_order(
                    vendor_name=vendor_name,
                    app_no=app_no,
                    work_location=work_location,
                    not_renewing_df=not_renewing_df if not skip_delete else None,
                    signing_party=signing_party
                )
                
                # 回写反馈
                ExcelParser.update_status(todo_df, idx, message)
                processed_combinations.add(combo_key)
                
                if success:
                    logger.info(f"[成功] {app_no} | {vendor_name} - {message}")
                else:
                    logger.warning(f"[失败] {app_no} | {vendor_name} - {message}")
                
            except Exception as e:
                error_msg = f"异常：{str(e)[:80]}"
                ExcelParser.update_status(todo_df, idx, error_msg)
                logger.error(f"[异常] {app_no} | {vendor_name} - {error_msg}")
        
        logger.info(f"\n{'='*60}")
        logger.info(f"待办清单处理完成")
        logger.info(f"{'='*60}\n")
        
        return todo_df
    
    def execute_full_flow(self, todo_file: str, output_dir: str = ".",
                         not_renewing_df: Optional[pd.DataFrame] = None,
                         skip_delete: bool = False,
                         resume: bool = False) -> str:
        """
        执行完整的下单流程

        Args:
            todo_file: 待办清单文件路径
            output_dir: 输出目录
            not_renewing_df: 离岗不续签清单数据框（可选，用于人员删除）
            skip_delete: 是否跳过离岗不续签人员删除
            resume: 是否启用断点续跑（跳过已有反馈的记录）

        Returns:
            str: 处理结果文件路径
        """
        logger.info("=== 执行完整下单流程 ===")
        
        try:
            # 1. 加载待办清单
            logger.info(f"[流程] 加载待办清单: {todo_file}")
            todo_df = pd.read_excel(todo_file, engine="openpyxl")
            
            if len(todo_df) == 0:
                logger.error("[流程] 待办清单为空")
                raise Exception("待办清单为空")
            
            logger.info(f"[流程] 待办清单加载成功，共 {len(todo_df)} 条记录")
            
            # 确保存在「反馈」列（兼容旧文件中「处理状态」列名）
            if "反馈" not in todo_df.columns:
                if "处理状态" in todo_df.columns:
                    todo_df.rename(columns={"处理状态": "反馈"}, inplace=True)
                else:
                    todo_df["反馈"] = ""
            todo_df["反馈"] = todo_df["反馈"].astype(str).replace("nan", "")
            
            # 2. 启动浏览器并登录
            logger.info("[流程] 启动浏览器...")
            self.downloader.start()
            
            logger.info("[流程] 执行登录...")
            if not self.downloader.login():
                raise Exception("登录失败")
            
            # 3. 导航到外包合同页面
            contract_page = self.navigate_to_contract_page(self.downloader._page)
            if not contract_page:
                raise Exception("无法导航到外包合同页面")
            
            # 4. 逐条处理待办清单（传递不续签清单数据）
            todo_df = self.process_todo_list(todo_df, contract_page, not_renewing_df, skip_delete=skip_delete, resume=resume)
            
            # 5. 保存处理结果
            result_file = ExcelParser.save_result(todo_df, output_dir=output_dir)
            
            logger.info(f"[流程] 处理结果已保存: {result_file}")
            
            return result_file
            
        except Exception as e:
            logger.error(f"[流程] 执行失败: {e}", exc_info=True)
            raise
        
        finally:
            logger.info("[流程] 关闭浏览器...")
            self.downloader.stop()


def main():
    """测试脚本"""
    import argparse
    
    parser = argparse.ArgumentParser(description="续签订单处理工具")
    parser.add_argument("todo_file", help="待办清单文件路径")
    parser.add_argument("--output-dir", help="输出目录", default=".")
    parser.add_argument("--headless", action="store_true", help="隐藏浏览器（无头模式）")
    
    args = parser.parse_args()
    
    try:
        processor = RenewalOrderProcessor(headless=args.headless)
        result_file = processor.execute_full_flow(
            todo_file=args.todo_file,
            output_dir=args.output_dir
        )
        
        logger.info(f"\n=== 流程完成 ===")
        logger.info(f"处理结果: {result_file}")
        
    except Exception as e:
        logger.error(f"流程失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
