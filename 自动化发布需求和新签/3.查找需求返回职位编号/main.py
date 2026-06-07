"""
主流程 - 查找需求返回职位编号
1. 查询飞书多维表中"是否发布"为是且"职位编号"为空的记录
2. 登录TAM网站
3. 导航到"查询招聘任务"页面，设置筛选条件并查询
4. 逐条记录在查询结果中匹配（第1-2页），找到职位编号
5. 将职位编号更新回多维表

用法:
  python main.py
"""

import os
import sys
from datetime import datetime
from dotenv import dotenv_values

sys.stdout.reconfigure(line_buffering=True)

from playwright.sync_api import sync_playwright

from feishu_query import query_records_needing_position
from feishu_update import update_position_code
from tam_query import navigate_to_query_task, set_filters_and_search, find_position_for_record


def create_browser_context(playwright):
    """启动浏览器"""
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    return browser, context, page


def login_tam(page, username, password):
    """登录 TAM 网站"""
    print("  正在访问 TAM 网站...")
    page.goto("https://tam.asiainfo.com/webapps/ai-hr-tam-web/", wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(3000)

    current_url = page.url
    print(f"  当前页面: {current_url}")

    username_input = None
    password_input = None

    for sel in [
        'input[name="username"]', 'input[name="userId"]', 'input[name="loginName"]',
        'input[id="username"]', 'input[id="userId"]',
        'input[type="text"]', 'input[placeholder*="用户名"]', 'input[placeholder*="账号"]'
    ]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                username_input = el
                break
        except Exception:
            continue

    for sel in [
        'input[name="password"]', 'input[name="passwd"]', 'input[id="password"]',
        'input[type="password"]', 'input[placeholder*="密码"]'
    ]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                password_input = el
                break
        except Exception:
            continue

    if username_input and password_input:
        print("  正在填写登录信息...")
        username_input.fill(username)
        password_input.fill(password)
        page.wait_for_timeout(500)

        clicked = False
        for sel in [
            'input[type="submit"]', 'button[type="submit"]',
            'input[name="submit"]', 'button:has-text("登录")', 'input[value="登录"]',
            'input[value="Login"]', 'button:has-text("Login")',
            '.login-btn', '#loginBtn'
        ]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            print("  [WARN] 未找到登录按钮，请手动点击登录")
    else:
        print("  [INFO] 未检测到登录表单，可能已登录")

    print("  等待登录完成...")
    page.wait_for_timeout(5000)
    page.wait_for_load_state("networkidle", timeout=30000)

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    print("  登录完成")
    return page


def main():
    print("=" * 60)
    print(f"查找需求返回职位编号 - 开始运行 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 加载配置
    config_path = os.path.join(os.path.dirname(__file__), "config.env")
    config = dotenv_values(config_path)

    username = config.get("IMS_USERNAME", "")
    password = config.get("IMS_PASSWORD", "")
    bitable_token = config.get("BITABLE_TOKEN", "")
    table_id = config.get("TABLE_ID", "tblR7HsWVzDka9AS")

    if not username or not password:
        print("[ERROR] 请先在 config.env 中填写 IMS_USERNAME 和 IMS_PASSWORD")
        sys.exit(1)
    if not bitable_token:
        print("[ERROR] 请先在 config.env 中填写 BITABLE_TOKEN")
        sys.exit(1)

    # Step 1: 查询多维表中待查找职位编号的记录
    print("\n[Step 1] 查询飞书多维表中待查找职位编号的记录")
    pending_records = query_records_needing_position(bitable_token, table_id)

    if not pending_records:
        print("\n没有需要查找职位编号的记录，流程结束")
        return

    print(f"\n共找到 {len(pending_records)} 条待查找记录")
    for i, rec in enumerate(pending_records):
        code = rec.get("合作申请单编号", "")
        supplier = rec.get("供应商", "")
        position = rec.get("岗位", "")
        print(f"  {i + 1}. 编号:{code}  供应商:{supplier}  岗位:{position}")

    # Step 2: 启动浏览器并登录TAM
    print("\n[Step 2] 登录TAM网站")
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)

    with sync_playwright() as p:
        browser, context, page = create_browser_context(p)

        try:
            page = login_tam(page, username, password)

            # Step 3: 导航到查询招聘任务页面并设置筛选条件
            print("\n[Step 3] 导航到查询招聘任务页面")
            page = navigate_to_query_task(page)

            print("\n[Step 4] 设置筛选条件并查询")
            page = set_filters_and_search(page)

            # Step 5: 逐条记录查找职位编号
            found_count = 0
            not_found_count = 0

            for idx, record in enumerate(pending_records):
                code = str(record.get("合作申请单编号", "")).strip()
                print(f"\n[Step 5.{idx + 1}] 查找记录: {code}")
                print("-" * 40)

                try:
                    position_codes = find_position_for_record(page, record)

                    if position_codes:
                        record_id = record.get("_record_id", "")
                        if record_id:
                            update_position_code(bitable_token, table_id, record_id, position_codes)
                        else:
                            print(f"    [WARN] 记录缺少 _record_id，无法更新")
                        found_count += 1
                        print(f"    记录 {code} → 职位编号: {position_codes}")
                    else:
                        not_found_count += 1
                        print(f"    记录 {code} 未找到匹配的职位编号")

                except Exception as e:
                    not_found_count += 1
                    print(f"    [ERROR] 处理异常: {e}")
                    import traceback
                    traceback.print_exc()

                page.wait_for_timeout(1000)

            # 完成
            print("\n" + "=" * 60)
            print("执行完成！")
            print(f"  - 待查找记录: {len(pending_records)} 条")
            print(f"  - 找到职位编号: {found_count} 条")
            print(f"  - 未找到: {not_found_count} 条")
            print("=" * 60)

        except Exception as e:
            print(f"\n[ERROR] 执行异常: {e}")
            import traceback
            traceback.print_exc()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
