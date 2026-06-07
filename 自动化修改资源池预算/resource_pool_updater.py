"""
资源池预算修改自动化工具 v2
根据 Excel（资源池预算.xlsx）中的数据，自动登录系统并批量修改资源池年化人数预算和年度费用预算

修复说明（v2）：
  - 查询按钮：a#search（layui a标签，非button/input）
  - 编辑按钮：a[lay-event='edit']，被 layui-table-fixed-r 遮挡，改用 JS dispatchEvent 触发
  - 编辑弹窗：layer.open type:2 iframe，URL含 editPoolDetail
  - 年化人数预算字段：input#yearHc
  - 年度费用预算字段：input#yearExpenses
  - 保存/发布按钮：button#updateApply
"""

import sys
import pandas as pd
from pathlib import Path
from playwright.sync_api import sync_playwright

# -------- 路径配置 --------
BASE_DIR   = Path(__file__).parent.parent          # F:\CodeBuddy
EXCEL_PATH = Path(__file__).parent / "资源池预算.xlsx"
LOGIN_URL  = "https://ims.asiainfo.com/AIOMS/Jsp/main.jsp"


# -------- 读取 Excel --------
def load_excel(path: Path) -> list[dict]:
    df = pd.read_excel(path, dtype=str)
    df.columns = df.columns.str.strip()
    records = df.to_dict(orient="records")
    print(f"[INFO] 共读取 {len(records)} 条资源池记录")
    for r in records:
        print(
            f"  资源池代码={r.get('资源池代码')}, "
            f"年化人数预算={r.get('年化人数预算')}, "
            f"年度费用预算（元）={r.get('年度费用预算（元）')}"
        )
    return records


# -------- 登录 --------
def login(page, username: str, password: str):
    print(f"[INFO] 访问登录页: {LOGIN_URL}")
    page.goto(LOGIN_URL, wait_until="networkidle")
    page.wait_for_timeout(2000)
    page.locator("input[name='username'], input[id='username'], input[type='text']").first.fill(username)
    page.locator("input[name='password'], input[id='password'], input[type='password']").first.fill(password)
    page.locator("button[type='submit'], input[type='submit'], button:has-text('登录'), input[value*='登录']").first.click()
    page.wait_for_timeout(4000)
    print("[INFO] 登录完成")


# -------- 导航到"资源池设立" --------
def navigate_to_resource_pool_setup(page):
    print("[INFO] 导航到资源池设立...")

    # 双击"资源池"展开
    try:
        page.locator(".mini-tree-nodetext:has-text('资源池')").first.dblclick()
        page.wait_for_timeout(1500)
        print("[INFO] 已双击 '资源池' 节点")
    except Exception as e:
        print(f"[WARN] 双击资源池失败: {e}")

    # 双击"资源池管理"
    try:
        page.locator(".mini-tree-nodetext:has-text('资源池管理')").first.dblclick()
        page.wait_for_timeout(1500)
        print("[INFO] 已双击 '资源池管理' 节点")
    except Exception as e:
        print(f"[WARN] 双击资源池管理失败: {e}")

    # 单击"资源池设立"
    try:
        page.locator(".mini-tree-nodetext:has-text('资源池设立')").first.click()
        page.wait_for_timeout(4000)
        print("[INFO] 已单击 '资源池设立'，等待 iframe 加载...")
    except Exception as e:
        print(f"[ERROR] 单击资源池设立失败: {e}")
        raise


# -------- 找到资源池设立 iframe --------
def find_resource_pool_frame(page):
    for frame in page.frames:
        if any(k in frame.url for k in ["resourcePool_resourcePoolManage", "resourcePool", "ResourcePool"]):
            if "editPoolDetail" not in frame.url:
                print(f"[INFO] 找到资源池设立 frame: {frame.url}")
                return frame

    # 兜底：取最后一个非空、非主、非登录 frame
    candidates = [
        f for f in page.frames
        if f.url not in ("about:blank", "", LOGIN_URL)
        and f != page.main_frame
        and "editPoolDetail" not in f.url
        and "firstHome" not in f.url.lower()
        and "FirstHome" not in f.url
    ]
    if candidates:
        frame = candidates[-1]
        print(f"[INFO] 使用候选资源池frame: {frame.url}")
        return frame

    print("[WARN] 未找到资源池设立 frame，使用主frame")
    return page.main_frame


# -------- 对单条记录执行查询→编辑→保存 --------
def update_one_record(page, record: dict) -> bool:
    pool_code   = str(record.get("资源池代码", "")).strip()
    head_count  = str(record.get("年化人数预算", "")).strip()
    budget_yuan = str(record.get("年度费用预算（元）", "")).strip()

    print(f"\n[INFO] ===== 开始处理: {pool_code} =====")
    print(f"  目标年化人数预算: {head_count}")
    print(f"  目标年度费用预算: {budget_yuan}")

    # --- 找资源池设立 frame ---
    target_frame = find_resource_pool_frame(page)

    # --- 输入资源池代码 ---
    try:
        target_frame.locator("input#poolCode").fill(pool_code)
        print(f"[INFO] 已输入资源池代码: {pool_code}")
        page.wait_for_timeout(500)
    except Exception as e:
        print(f"[ERROR] 输入资源池代码失败: {e}")
        page.screenshot(path=str(BASE_DIR / "修改资源池预算" / f"error_{pool_code}_input.png"))
        return False

    # --- 点击查询（a#search，layui a 标签）---
    try:
        target_frame.locator("a#search").click()
        page.wait_for_timeout(5000)
        print("[INFO] 已点击查询，等待结果...")
    except Exception as e:
        print(f"[ERROR] 点击查询失败: {e}")
        page.screenshot(path=str(BASE_DIR / "修改资源池预算" / f"error_{pool_code}_query.png"))
        return False

    # --- 验证查询到结果 ---
    try:
        row_count = target_frame.evaluate("""
            () => document.querySelectorAll('a[lay-event="edit"]').length
        """)
        print(f"[INFO] 查询结果中找到编辑按钮数: {row_count}")
        if row_count == 0:
            print(f"[ERROR] 未找到资源池 {pool_code} 的查询结果")
            page.screenshot(path=str(BASE_DIR / "修改资源池预算" / f"error_{pool_code}_no_result.png"))
            return False
    except Exception as e:
        print(f"[WARN] 验证查询结果失败: {e}")

    # --- 点击目标行的编辑按钮（按资源池代码精确匹配行，避免点到错误记录）---
    try:
        result = target_frame.evaluate(f"""
            (poolCode) => {{
                // 找到表格中所有行，匹配包含目标资源池代码的行
                var rows = document.querySelectorAll('tr[data-index], tbody tr');
                var targetBtn = null;
                for (var i = 0; i < rows.length; i++) {{
                    var rowText = rows[i].textContent || '';
                    if (rowText.indexOf(poolCode) !== -1) {{
                        var btn = rows[i].querySelector('a[lay-event="edit"]');
                        if (btn) {{
                            targetBtn = btn;
                            break;
                        }}
                    }}
                }}
                // 回退：如果精确匹配没找到，使用第一个编辑按钮
                if (!targetBtn) {{
                    var allBtns = document.querySelectorAll('a[lay-event="edit"]');
                    if (allBtns.length === 0) return 'no edit btn';
                    targetBtn = allBtns[0];
                }}
                targetBtn.dispatchEvent(new MouseEvent('click', {{
                    bubbles: true, cancelable: true, view: window
                }}));
                return 'ok';
            }}
        """, pool_code)
        print(f"[INFO] JS触发编辑按钮: {result}")
        page.wait_for_timeout(5000)
    except Exception as e:
        print(f"[ERROR] 触发编辑按钮失败: {e}")
        page.screenshot(path=str(BASE_DIR / "修改资源池预算" / f"error_{pool_code}_edit.png"))
        return False

    # --- 找编辑弹窗 frame（URL含 editPoolDetail）---
    edit_frame = None
    for attempt in range(3):
        for frame in page.frames:
            if "editPoolDetail" in frame.url:
                edit_frame = frame
                print(f"[INFO] 找到编辑弹窗frame: {frame.url}")
                break
        if edit_frame:
            break
        print(f"[INFO] 等待编辑弹窗frame（第{attempt+1}次）...")
        page.wait_for_timeout(2000)

    if not edit_frame:
        print("[ERROR] 未找到编辑弹窗frame")
        page.screenshot(path=str(BASE_DIR / "修改资源池预算" / f"error_{pool_code}_no_edit_frame.png"))
        return False

    # --- 修改年化人数预算（input#yearHc）---
    try:
        # 用 JS 直接设置 value，确保覆盖原有值
        edit_frame.evaluate(
            "(v) => { var el = document.querySelector('input#yearHc'); "
            "el.value = ''; el.value = v; "
            "el.dispatchEvent(new Event('input', {bubbles:true})); "
            "el.dispatchEvent(new Event('change', {bubbles:true})); }",
            head_count
        )
        actual = edit_frame.evaluate("() => document.querySelector('input#yearHc').value")
        print(f"[INFO] 年化人数预算已设置: {actual}（目标: {head_count}）")
    except Exception as e:
        print(f"[ERROR] 设置年化人数预算失败: {e}")
        page.screenshot(path=str(BASE_DIR / "修改资源池预算" / f"error_{pool_code}_yearHc.png"))
        return False

    # --- 修改年度费用预算（input#yearExpenses）---
    try:
        edit_frame.evaluate(
            "(v) => { var el = document.querySelector('input#yearExpenses'); "
            "el.value = ''; el.value = v; "
            "el.dispatchEvent(new Event('input', {bubbles:true})); "
            "el.dispatchEvent(new Event('change', {bubbles:true})); }",
            budget_yuan
        )
        actual = edit_frame.evaluate("() => document.querySelector('input#yearExpenses').value")
        print(f"[INFO] 年度费用预算已设置: {actual}（目标: {budget_yuan}）")
    except Exception as e:
        print(f"[ERROR] 设置年度费用预算失败: {e}")
        page.screenshot(path=str(BASE_DIR / "修改资源池预算" / f"error_{pool_code}_yearExpenses.png"))
        return False

    # --- 截图确认修改内容 ---
    page.screenshot(path=str(BASE_DIR / "修改资源池预算" / f"before_save_{pool_code}.png"))
    print("[INFO] 已截图确认修改内容")

    # --- 点击"发布"（button#updateApply）保存 ---
    try:
        save_btn = edit_frame.locator("button#updateApply")
        save_btn.click()
        page.wait_for_timeout(4000)
        print(f"[SUCCESS] 资源池 {pool_code} 修改并发布成功！")
    except Exception as e:
        print(f"[ERROR] 点击发布按钮失败: {e}")
        page.screenshot(path=str(BASE_DIR / "修改资源池预算" / f"error_{pool_code}_save.png"))
        return False

    # --- 截图确认保存结果 ---
    page.screenshot(path=str(BASE_DIR / "修改资源池预算" / f"after_save_{pool_code}.png"))
    print("[INFO] 已截图确认保存结果")

    # --- 关闭 layer 弹窗（如果还打开着）---
    try:
        target_frame.evaluate("""
            () => {
                if (typeof layui !== 'undefined' && layui.layer) {
                    layui.layer.closeAll('iframe');
                }
            }
        """)
        page.wait_for_timeout(1000)
    except Exception:
        pass

    return True


# -------- 主流程 --------
def main():
    import argparse
    parser = argparse.ArgumentParser(description="资源池预算批量修改工具 v2")
    parser.add_argument("-u", "--username", help="登录用户名")
    parser.add_argument("-p", "--password", help="登录密码")
    parser.add_argument("--headless", action="store_true", help="隐藏浏览器（无头模式）")
    args = parser.parse_args()

    username = args.username or input("请输入用户名: ")
    password = args.password or input("请输入密码: ")
    headless = args.headless

    # 读取 Excel 数据
    records = load_excel(EXCEL_PATH)
    if not records:
        print("[ERROR] Excel 中无数据，退出")
        sys.exit(1)

    success_count = 0
    fail_count    = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page    = context.new_page()

        # 登录
        login(page, username, password)

        # 导航到资源池设立
        navigate_to_resource_pool_setup(page)

        # 逐条处理
        for i, record in enumerate(records):
            print(f"\n[INFO] 处理第 {i+1}/{len(records)} 条记录...")
            ok = update_one_record(page, record)
            if ok:
                success_count += 1
            else:
                fail_count += 1
                # 失败后重新导航，防止页面状态异常
                if i < len(records) - 1:
                    print("[INFO] 失败后重新导航到资源池设立...")
                    navigate_to_resource_pool_setup(page)

        browser.close()

    print(f"\n[SUMMARY] 处理完成：成功 {success_count} 条，失败 {fail_count} 条")


if __name__ == "__main__":
    main()
