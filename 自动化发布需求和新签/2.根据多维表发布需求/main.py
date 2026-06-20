"""
主流程 - 根据多维表发布需求
1. 查询飞书多维表中"是否发布"为否的记录
2. 登录TAM网站
3. 逐条记录填写表单并发布
4. 发布成功后更新多维表的"发布时间"和"是否发布"字段

用法:
  python main.py        # 逐条交互确认
  python main.py -y     # 自动确认发布（跳过交互）
"""

import os
import sys
from datetime import datetime
from dotenv import dotenv_values

# 禁用输出缓冲
sys.stdout.reconfigure(line_buffering=True)


def secure_input(prompt="密码: "):
    """密码输入 — Windows 显示 * 回显，其他平台用 getpass"""
    if sys.platform == "win32":
        import msvcrt
        print(prompt, end="", flush=True)
        password = ""
        while True:
            ch = msvcrt.getch()
            if ch in (b"\r", b"\n"):
                print()
                break
            elif ch == b"\x08":
                if password:
                    password = password[:-1]
                    print("\b \b", end="", flush=True)
            elif ch == b"\x03":
                raise KeyboardInterrupt()
            else:
                password += ch.decode("utf-8", errors="ignore")
                print("*", end="", flush=True)
        return password
    else:
        import getpass
        return getpass.getpass(prompt)


from playwright.sync_api import sync_playwright

from tam_login import create_browser_context, login_tam, navigate_to_new_recruitment_task
from tam_publish import fill_and_publish, _click_continue_create
from feishu_query import query_unpublished_records, get_bitable_config
from feishu_update import update_record_published


def main():
    # 解析命令行参数
    import argparse
    parser = argparse.ArgumentParser(description="根据多维表发布需求")
    parser.add_argument("-y", "--yes", action="store_true", help="自动确认发布（跳过交互）")
    parser.add_argument("--username", default="", help="IMS 登录用户名")
    parser.add_argument("--password", default="", help="IMS 登录密码")
    args, unknown = parser.parse_known_args()

    auto_yes = args.yes

    # 加载配置（用于多维表 token 和凭证回退）
    config_path = os.path.join(os.path.dirname(__file__), "config.env")
    config = dotenv_values(config_path)

    username = args.username or config.get("IMS_USERNAME", "")
    password = args.password or config.get("IMS_PASSWORD", "")

    if not username:
        username = input("IMS 用户名: ").strip()
    if not password:
        password = secure_input("IMS 密码: ").strip()

    if not username or not password:
        print("[ERROR] 用户名和密码不能为空")
        sys.exit(1)

    print("=" * 60)
    print(f"根据多维表发布需求 - 开始运行 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if auto_yes:
        print("模式: 自动确认发布")
    print("=" * 60)

    # Step 1: 查询多维表未发布记录
    print("\n[Step 1] 查询飞书多维表未发布记录")
    unpublished_records = query_unpublished_records(config_path)

    if not unpublished_records:
        print("\n没有未发布的记录，流程结束")
        return

    print(f"\n共找到 {len(unpublished_records)} 条未发布记录")

    # 显示待发布记录
    for i, rec in enumerate(unpublished_records):
        code = rec.get("合作申请单编号", "")
        position = rec.get("岗位", "")
        location = rec.get("工作地点", "")
        print(f"  {i + 1}. 编号:{code}  岗位:{position}  地点:{location}")

    # Step 2: 启动浏览器并登录TAM
    print("\n[Step 2] 登录TAM网站")
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)

    with sync_playwright() as p:
        browser, context, page = create_browser_context(p, data_dir)

        try:
            page = login_tam(page, username, password)

            # Step 3: 导航到新建招聘任务页面
            print("\n[Step 3] 导航到新建招聘任务页面")
            page = navigate_to_new_recruitment_task(page)

            # 获取多维表配置
            bitable_token, table_id = get_bitable_config(config_path)

            # Step 4: 逐条记录发布
            success_count = 0
            fail_count = 0

            for idx, record in enumerate(unpublished_records):
                code = str(record.get("合作申请单编号", "")).strip()
                print(f"\n[Step 4.{idx + 1}] 处理记录: {code}")
                print("-" * 40)

                try:
                    # 第一条记录：导航到新建招聘任务页面
                    # 后续记录：发布成功后通过"继续创建"按钮进入下一条
                    if idx == 0:
                        page = navigate_to_new_recruitment_task(page)
                    else:
                        # 点击上一条发布成功弹窗中的"继续创建"
                        _click_continue_create(page)
                        page.wait_for_timeout(2000)

                    # 填写表单并发布
                    published = fill_and_publish(page, record, auto_yes=auto_yes)

                    if published:
                        # 直接使用记录中的 _record_id 更新多维表
                        record_id = record.get("_record_id", "")
                        if record_id:
                            update_record_published(bitable_token, table_id, record_id)
                        else:
                            print(f"  [WARN] 记录缺少 _record_id，无法更新多维表: {code}")

                        success_count += 1
                        print(f"  记录 {code} 发布成功")
                    else:
                        fail_count += 1
                        print(f"  记录 {code} 发布跳过")

                except Exception as e:
                    fail_count += 1
                    print(f"  [ERROR] 记录 {code} 处理异常: {e}")
                    import traceback
                    traceback.print_exc()

                # 每条记录之间等待一下
                page.wait_for_timeout(2000)

            # 完成
            print("\n" + "=" * 60)
            print(f"执行完成！")
            print(f"  - 未发布记录: {len(unpublished_records)} 条")
            print(f"  - 发布成功: {success_count} 条")
            print(f"  - 发布跳过/失败: {fail_count} 条")
            print("=" * 60)

        except Exception as e:
            print(f"\n[ERROR] 执行异常: {e}")
            import traceback
            traceback.print_exc()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
