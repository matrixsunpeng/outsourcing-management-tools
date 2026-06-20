"""
IMS 网站登录模块 - 使用 Playwright 自动登录 https://ims.asiainfo.com
"""

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
import os

IMS_URL = "https://ims.asiainfo.com/AIOMS/Jsp/main.jsp"


def create_browser_context(playwright: sync_playwright, data_dir: str) -> tuple[Browser, BrowserContext, Page]:
    """启动浏览器，返回 (browser, context, page)"""
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(
        viewport={"width": 1366, "height": 768},
        accept_downloads=True,
    )
    page = context.new_page()
    page.set_default_timeout(30000)
    return browser, context, page


def login_ims(page: Page, username: str, password: str) -> Page:
    """
    登录 IMS 网站（通过 SSO 认证）
    返回登录后的 page 对象
    """
    print("  正在访问 IMS 网站...")
    page.goto(IMS_URL, wait_until="load", timeout=15000)

    # IMS 会重定向到 sso.asiainfo.com 进行认证
    if "sso.asiainfo.com" in page.url:
        print("  检测到 SSO 登录页面，正在填写凭证...")
        page.fill("input[name='username']", username)
        page.fill("input[name='password']", password)

        # 勾选 SSO 同意协议复选框（如果存在）
        try:
            cb = page.locator("input#agreement")
            if cb.is_visible(timeout=1000) and not cb.is_checked():
                cb.check()
        except Exception:
            pass

        # 点击登录
        page.click("input[name='submit']")
        page.wait_for_timeout(8000)

    # 检查是否登录成功
    current_url = page.url.lower()
    if "login" in current_url or "sso" in current_url:
        raise RuntimeError("IMS 登录失败，请检查用户名和密码")

    # 登录后关闭可能的弹窗
    _dismiss_modals(page)

    print("  IMS 登录完成")
    return page


def _dismiss_modals(page: Page):
    """尝试关闭页面上的各种弹窗/对话框"""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass
