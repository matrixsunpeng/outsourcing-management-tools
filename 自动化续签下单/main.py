"""
续签自动下单工具 - 主入口脚本
完整自动化处理：下载 -> 清单生成 -> 下单 -> 结果输出
支持稽核时间参数用于人员变更清单筛选
"""

import sys
import argparse
from pathlib import Path

from download_and_parse import DownloadAndParseManager
from renewal_order_processor import RenewalOrderProcessor
from utils.logger import setup_logger

logger = setup_logger(__name__)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="续签自动下单工具 - 完整自动化流程",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 完整流程：下载 -> 清单 -> 下单（包含人员变更和删除逻辑）
  python main.py --sbu "部门A/部门B" --start "2026年3月1日" --end "2026年3月31日" \\
                 --audit-date "2026-03-31"

  # 仅下载并生成清单（包含离岗不续签清单）
  python main.py --start "2026年3月1日" --end "2026年3月31日" \\
                 --audit-date "2026-03-31" --output-dir results/ --download-only

  # 仅处理已有的待办清单（需同时提供离岗清单文件）
  python main.py --process-only results/待办订单清单_20260331_150000.xlsx \\
                 --not-renewing-file results/离岗不续签清单_20260331_150000.xlsx

  # 处理待办清单但跳过人员删除（即使提供了离岗清单也不删除）
  python main.py --process-only results/待办订单清单_20260331_150000.xlsx \\
                 --not-renewing-file results/离岗不续签清单_20260331_150000.xlsx \\
                 --skip-delete

  # 断点续跑：从上次中断处继续（跳过已有反馈的记录）
  python main.py --process-only results/待办订单清单_已处理_20260331_150000.xlsx \\
                 --not-renewing-file results/离岗不续签清单_20260331_150000.xlsx \\
                 --resume

  # 如需隐藏浏览器（无头模式），加 --headless
        """
    )
    
    parser.add_argument("--sbu", help="SBU 名称（多个用逗号分隔），默认全部", default=None)
    parser.add_argument("--start", help="开始日期（格式: 2026年3月1日），默认本月1日", default=None)
    parser.add_argument("--end", help="结束日期（格式: 2026年3月31日），默认今日", default=None)
    parser.add_argument("--audit-date", help="稽核时间（格式: 2026-03-31 或 2026年3月31日），用于人员变更清单筛选", default=None)
    parser.add_argument("--output-dir", help="输出目录（清单和结果文件），默认当前目录", default=".")
    parser.add_argument("--download-only", action="store_true", help="仅下载并生成清单，不执行下单")
    parser.add_argument("--process-only", help="仅处理指定的待办清单文件（跳过下载阶段）")
    parser.add_argument("--not-renewing-file", help="指定离岗不续签清单文件路径（仅在 --process-only 时使用）")
    parser.add_argument("--skip-delete", action="store_true", help="跳过离岗不续签人员删除（即使提供了清单也不执行删除操作）")
    parser.add_argument("--resume", action="store_true", help="断点续跑：跳过已有反馈的记录，从中断处继续（仅限 --process-only 模式）")
    parser.add_argument("--headless", action="store_true", help="隐藏浏览器（无头模式）")
    parser.add_argument("--username", help="IMS 用户名", default=None)
    parser.add_argument("--password", help="IMS 密码", default=None)

    args = parser.parse_args()

    # 凭据：命令行未传则交互询问
    username = args.username or input("请输入 IMS 用户名: ").strip()
    password = args.password or input("请输入 IMS 密码: ").strip()
    if not username or not password:
        logger.error("用户名或密码不能为空")
        sys.exit(1)

    logger.info("="*60)
    logger.info("  续签自动下单工具（支持人员变更）")
    logger.info("="*60)
    
    try:
        # 输出目录
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # ========== 分支1：仅处理待办清单 ==========
        if args.process_only:
            logger.info(f"\n[模式] 仅处理模式: {args.process_only}")
            
            todo_file = args.process_only
            if not Path(todo_file).exists():
                logger.error(f"待办清单文件不存在: {todo_file}")
                sys.exit(1)
            
            logger.info(f"[模式] 加载待办清单: {todo_file}")
            
            # 加载离岗不续签清单（如果提供，且未指定跳过删除）
            not_renewing_df = None
            if args.skip_delete:
                logger.info("[模式] --skip-delete 已指定，跳过离岗不续签人员删除")
            elif args.not_renewing_file:
                if not Path(args.not_renewing_file).exists():
                    logger.warning(f"离岗不续签清单文件不存在: {args.not_renewing_file}，将跳过人员删除")
                else:
                    try:
                        import pandas as pd
                        not_renewing_df = pd.read_excel(args.not_renewing_file)
                        logger.info(f"[模式] 加载离岗不续签清单: {args.not_renewing_file} ({len(not_renewing_df)} 条记录)")
                    except Exception as e:
                        logger.warning(f"加载离岗不续签清单失败: {e}，将跳过人员删除")
            
            # 执行下单流程
            processor = RenewalOrderProcessor(headless=args.headless, username=username, password=password)
            result_file = processor.execute_full_flow(
                todo_file=todo_file,
                output_dir=str(output_dir),
                not_renewing_df=not_renewing_df,
                skip_delete=args.skip_delete,
                resume=args.resume
            )
            
            logger.info(f"\n{'='*60}")
            logger.info(f"[完成] 处理结果文件: {result_file}")
            logger.info(f"{'='*60}\n")
            
            return
        
        # ========== 分支2：下载 + 清单生成 ==========
        logger.info("[模式] 下载与清单生成模式")
        
        # SBU：命令行未传则交互询问，空白回车 = 全部
        # args.sbu is None → 未提供（需询问），"" → 显式传空=全部
        sbu_list = None
        if args.sbu is not None:
            sbu_list = [s.strip() for s in args.sbu.split(",") if s.strip()] or None
            logger.info(f"[参数] SBU: {sbu_list if sbu_list else '全部（默认）'}")
        else:
            sbu_input = input("请输入 SBU（多个用逗号间隔，直接回车默认全部）: ").strip()
            if sbu_input:
                sbu_list = [s.strip() for s in sbu_input.split(",") if s.strip()]
                logger.info(f"[参数] SBU: {sbu_list}")
            else:
                logger.info("[参数] SBU: 全部（默认）")

        # 日期范围：命令行未传则交互询问
        start_date = args.start
        end_date = args.end
        
        if not start_date:
            start_date = input("请输入开始日期（格式：2026年3月1日）: ").strip()
            if not start_date:
                logger.error("[参数] 开始日期不能为空")
                sys.exit(1)
        
        if not end_date:
            end_date = input("请输入结束日期（格式：2026年3月31日）: ").strip()
            if not end_date:
                logger.error("[参数] 结束日期不能为空")
                sys.exit(1)
        
        # 稽核时间：未显式指定时，交互询问（可直接回车使用结束日期）
        audit_date = args.audit_date
        if not audit_date:
            audit_date_input = input(f"请输入稽核时间（格式：2026-03-31，直接回车则使用续签查询结束日期 {end_date}）: ").strip()
            audit_date = audit_date_input if audit_date_input else end_date
        
        logger.info(f"[参数] 日期范围: {start_date} ~ {end_date}")
        logger.info(f"[参数] 稽核时间: {audit_date}")
        logger.info(f"[参数] 输出目录: {output_dir}")
        
        # 执行下载与清单生成（包括人员变更清单）
        manager = DownloadAndParseManager(headless=args.headless, username=username, password=password)
        renewal_files, todo_file, todo_df, not_renewing_file, not_renewing_df = \
            manager.execute_full_pipeline(
                sbu_list=sbu_list,
                start_date=start_date,
                end_date=end_date,
                audit_date=audit_date,
                output_dir=str(output_dir)
            )
        
        logger.info(f"\n[下载] 续签查询文件: {renewal_files}")
        logger.info(f"[清单] 待办清单: {todo_file}")
        if not_renewing_file:
            logger.info(f"[清单] 离岗不续签清单: {not_renewing_file}")
            logger.info(f"[统计] 离岗不续签人员数: {len(not_renewing_df)}")
        else:
            logger.info(f"[清单] 离岗不续签清单: 未生成（人员变更模块可选）")
        logger.info(f"[统计] 待办记录数: {len(todo_df)}")
        
        # ========== 分支3：如果指定 --download-only，则停止 ==========
        if args.download_only:
            logger.info("[模式] 仅下载模式已完成")
            logger.info(f"\n{'='*60}")
            logger.info(f"[完成] 待办清单文件: {todo_file}")
            if not_renewing_file:
                logger.info(f"       离岗不续签清单: {not_renewing_file}")
                logger.info(f"       后续可通过以下命令继续处理：")
                logger.info(f"       python main.py --process-only {todo_file} \\")
                logger.info(f"                      --not-renewing-file {not_renewing_file} \\")
                logger.info(f"                      --headless")
            else:
                logger.info(f"       后续可通过以下命令继续处理：")
                logger.info(f"       python main.py --process-only {todo_file} --headless")
            logger.info(f"{'='*60}\n")
            return
        
        # ========== 分支4：完整流程：下载 + 清单 + 下单 ==========
        logger.info("\n[模式] 完整流程模式（下载 -> 清单 -> 下单）")
        
        confirm = input("\n[确认] 将执行自动下单流程，是否继续？(y/n): ").strip().lower()
        if confirm != 'y':
            logger.info("[取消] 用户取消了下单流程")
            sys.exit(0)
        
        logger.info("[执行] 开始下单流程...")
        
        processor = RenewalOrderProcessor(headless=args.headless, username=username, password=password)
        result_file = processor.execute_full_flow(
            todo_file=todo_file,
            output_dir=str(output_dir),
            not_renewing_df=not_renewing_df,
            skip_delete=args.skip_delete,
            resume=args.resume
        )

        logger.info(f"\n{'='*60}")
        logger.info(f"[完成] 完整流程已完成")
        logger.info(f"       清单文件: {todo_file}")
        if not_renewing_file:
            logger.info(f"       离岗清单: {not_renewing_file}")
        logger.info(f"       结果文件: {result_file}")
        logger.info(f"{'='*60}\n")
        
    except KeyboardInterrupt:
        logger.warning("\n[取消] 用户中断程序")
        sys.exit(0)
    except Exception as e:
        logger.error(f"[失败] {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
