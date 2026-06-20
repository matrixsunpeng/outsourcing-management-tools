"""
主流程 - 查找需求返回职位编号
1. 查询飞书多维表中"是否发布"为是且"职位编号"为空的记录
2. 登录TAM网站
3. 导航到"查询招聘任务"页面，设置筛选条件并查询
4. 逐条记录在查询结果中匹配（第1-2页），找到职位编号
5. 将职位编号更新回多维表

用法:
  python main.py               # 默认 BU=185
  python main.py --bu 185      # 单个 BU
  python main.py --bu 185,186  # 多个 BU（中英文逗号均可）
"""

import os
import sys
from datetime import datetime
from dotenv import dotenv_values

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

from feishu_query import query_records_needing_position
from feishu_update import update_position_code
from tam_query import navigate_to_query_task, set_filters_and_search, find_position_for_record


def _extract_bu_code(sbu_name: str) -> str:
    """从事业部/SBU 名称提取 BU 代码，如 '亚信科技CTC' → '121'"""
    sbu_upper = sbu_name.upper().strip()
    # 已知映射
    if "CTC" in sbu_upper:
        return "121"
    if "CMB" in sbu_upper:
        return "185"
    if "CUC" in sbu_upper:
        return "186"
    # 尝试从名称开头提取数字（如 "(121)亚信科技CTC"）
    import re
    m = re.match(r'\(?(\d+)\)?', sbu_name.strip())
    if m:
        return m.group(1)
    return "185"  # 默认 CMB


def parse_bu_values(raw: str) -> list[str]:
    """解析逗号分隔的 BU 代码，支持中英文逗号，去空白去重"""
    if not raw:
        return ["185"]
    raw = raw.replace("，", ",")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    seen = set()
    result = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def create_browser_context(playwright):
    """启动浏览器"""
    browser = playwright.chromium.launch(headless=False, channel="chrome")
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    return browser, context, page


def login_tam(page, username, password):
    """登录 TAM 网站"""
    print("  正在访问 TAM 网站...")
    page.goto("https://tam.asiainfo.com/webapps/ai-hr-tam-web/", wait_until="domcontentloaded", timeout=30000)
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
    # 解析命令行参数
    import argparse
    parser = argparse.ArgumentParser(description="查找需求返回职位编号")
    parser.add_argument("--bu", default=os.getenv("BU_VALUES", "185"),
                        help="BU 代码，多个用逗号分隔（默认 185）")
    parser.add_argument("--username", default="", help="IMS 登录用户名")
    parser.add_argument("--password", default="", help="IMS 登录密码")
    args, unknown = parser.parse_known_args()

    bu_values = parse_bu_values(args.bu)

    # 加载配置
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

    bitable_token = config.get("BITABLE_TOKEN", "")
    table_id = config.get("TABLE_ID", "tblR7HsWVzDka9AS")

    print("=" * 60)
    print(f"查找需求返回职位编号 - 开始运行 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"默认 BU: {', '.join(bu_values)}（优先使用记录自身的 事业部/SBU）")
    print("=" * 60)

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

            # Step 3: 导航到查询招聘任务页面
            print("\n[Step 3] 导航到查询招聘任务页面")
            page = navigate_to_query_task(page)

            # Step 4: 逐条记录查找职位编号（每条用自身的 BU 重新筛选查询）
            found_count = 0
            not_found_count = 0
            last_bu = None

            for idx, record in enumerate(pending_records):
                code = str(record.get("合作申请单编号", "")).strip()
                sbu = str(record.get("事业部/SBU", "")).strip()

                # 用多维表记录的 事业部/SBU 文本直接查询（如 "亚信科技CTC"）
                record_bu = sbu if sbu else bu_values[0]

                print(f"\n[Step 5.{idx + 1}] 查找记录: {code}")
                print(f"    事业部/SBU: {sbu} → BU={record_bu}")
                print("-" * 40)

                # BU 变化时重新筛选查询
                if record_bu != last_bu:
                    print(f"    重新设置 BU={record_bu} 筛选条件...")
                    page = set_filters_and_search(page, [record_bu])
                    last_bu = record_bu

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
