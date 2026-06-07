"""
TAM网站登录模块 - 使用 Playwright 自动登录 https://tam.asiainfo.com
"""

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
import os


def create_browser_context(playwright: sync_playwright, data_dir: str) -> tuple[Browser, BrowserContext, Page]:
    """
    启动浏览器并配置下载路径
    返回 (browser, context, page)
    """
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    return browser, context, page


def login_tam(page: Page, username: str, password: str) -> Page:
    """
    登录 TAM 网站
    返回登录后的 page 对象
    """
    print("  正在访问 TAM 网站...")
    page.goto("https://tam.asiainfo.com/webapps/ai-hr-tam-web/", wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(3000)

    # 检查是否已经在登录页面或已经登录
    current_url = page.url
    print(f"  当前页面: {current_url}")

    # 尝试查找登录表单
    username_input = None
    password_input = None

    # 尝试多种选择器查找用户名输入框
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

    # 尝试多种选择器查找密码输入框
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

        # 点击登录按钮
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
        print("  [INFO] 未检测到登录表单，可能已登录或需要手动处理")

    print("  等待登录完成...")
    page.wait_for_timeout(5000)
    page.wait_for_load_state("networkidle", timeout=30000)

    # 登录后可能有弹窗遮挡（ant-modal-wrap），尝试关闭
    _dismiss_modals(page)

    print("  登录完成")
    return page


def navigate_to_new_recruitment_task(page: Page) -> Page:
    """
    导航到 新建招聘任务 页面
    路径: 人才招聘 > 招聘任务 > 新建招聘任务
    """
    print("  正在导航到新建招聘任务页面...")

    # 先尝试关闭可能的弹窗
    _dismiss_modals(page)

    # 点击左侧功能栏 "人才招聘"
    try:
        recruit_menu = page.locator('text=人才招聘').first
        if recruit_menu.is_visible(timeout=5000):
            recruit_menu.click()
            page.wait_for_timeout(1000)
            print("  已点击 '人才招聘'")
        else:
            print("  [WARN] 未找到 '人才招聘' 菜单")
    except Exception as e:
        print(f"  [WARN] 点击 '人才招聘' 失败: {e}")

    # 点击 "招聘任务"
    try:
        task_menu = page.locator('text=招聘任务').first
        if task_menu.is_visible(timeout=5000):
            task_menu.click()
            page.wait_for_timeout(1000)
            print("  已点击 '招聘任务'")
        else:
            print("  [WARN] 未找到 '招聘任务' 菜单")
    except Exception as e:
        print(f"  [WARN] 点击 '招聘任务' 失败: {e}")

    # 点击 "新建招聘任务"（尝试多种方式）
    _click_new_recruitment_task(page)

    page.wait_for_load_state("networkidle", timeout=15000)
    print("  导航完成")
    return page


def _click_new_recruitment_task(page: Page):
    """尝试多种方式点击"新建招聘任务" """
    selectors = [
        'text=新建招聘任务',
        'a:has-text("新建招聘任务")',
        'span:has-text("新建招聘任务")',
        'li:has-text("新建招聘任务")',
        '.ant-menu-item:has-text("新建招聘任务")',
        'button:has-text("新建招聘任务")',
        '[title="新建招聘任务"]',
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=3000):
                el.click()
                page.wait_for_timeout(3000)
                print("  已点击 '新建招聘任务'")
                return
        except Exception:
            continue

    # 最后尝试用 JS 查找并点击
    try:
        page.evaluate("""() => {
            var all = document.querySelectorAll('a, span, li, button, div');
            for (var el of all) {
                if (el.textContent.trim() === '新建招聘任务') {
                    el.click();
                    return true;
                }
            }
            return false;
        }""")
        page.wait_for_timeout(3000)
        print("  已通过JS点击 '新建招聘任务'")
    except Exception:
        print("  [WARN] 未找到 '新建招聘任务' 菜单")


def _dismiss_modals(page: Page):
    """尝试关闭页面上的各种弹窗/对话框"""
    try:
        # 按 Escape 关闭弹窗
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

        # 尝试点击 ant-modal 的关闭按钮
        for sel in [
            '.ant-modal-close', '.ant-modal-close-x',
            '.ant-modal-wrap .ant-btn:has-text("关闭")',
            '.ant-modal-wrap .ant-btn:has-text("取消")',
            '.ant-modal-wrap .ant-btn:has-text("知道了")',
        ]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    el.click()
                    page.wait_for_timeout(500)
            except Exception:
                continue
    except Exception:
        pass
