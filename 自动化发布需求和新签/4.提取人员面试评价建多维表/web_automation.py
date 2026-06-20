"""IMS website automation using Playwright.

Login → Navigate → Query → Export → Download.
The IMS system uses a frameset — left tree menu + right content area.

Supports multiple BU codes: logs in once, then loops per BU,
returning a list of downloaded file paths.
"""

import os
import re
import time
from datetime import date, timedelta

from playwright.sync_api import sync_playwright, Page, Browser, Frame, BrowserContext

from config import Config


def _parse_bu_list(raw: str) -> list[str]:
    """Parse comma-separated BU string into numeric codes.

    "(185)亚信科技CMB,121" → ["185", "121"]
    """
    if not raw:
        return ["185"]
    raw = raw.replace("，", ",")
    codes = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        # Extract numeric code: e.g. "(185)亚信科技CMB" → "185", "121" → "121"
        m = re.search(r'(\d+)', part)
        if m:
            codes.append(m.group(1))
        else:
            codes.append(part)
    # Deduplicate preserving order
    seen = set()
    result = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


class IMSAutomator:
    def __init__(self):
        self.config = Config

    def run(self) -> list[str]:
        """Execute full workflow and return list of downloaded file paths (one per BU)."""
        download_dir = os.path.abspath(self.config.DOWNLOAD_DIR)
        os.makedirs(download_dir, exist_ok=True)

        bu_codes = _parse_bu_list(self.config.QUERY_BU)
        print(f"[IMS] BU 列表: {bu_codes}")

        file_paths = []

        with sync_playwright() as pw:
            browser: Browser = pw.chromium.launch(
                headless=False,
                downloads_path=download_dir,
            )
            context: BrowserContext = browser.new_context(accept_downloads=True)
            page: Page = context.new_page()
            page.set_default_timeout(30000)

            try:
                self._login(page)
                print("[IMS] 登录成功")

                os.makedirs(download_dir, exist_ok=True)
                page.screenshot(path=os.path.join(download_dir, "_debug_after_login.png"))
                print("[IMS] 已保存截图: _debug_after_login.png")

                self._navigate_to_table(page)
                time.sleep(3)
                page.screenshot(path=os.path.join(download_dir, "_debug_after_nav.png"))
                print("[IMS] 已导航至人员面试评价表")

                # ── Loop per BU ──
                for idx, bu_code in enumerate(bu_codes):
                    print(f"\n[IMS] === BU [{idx + 1}/{len(bu_codes)}]: {bu_code} ===")

                    # Re-find frame (may have detached after previous operation)
                    target = self._find_table_frame(page)
                    if not target:
                        raise Exception(f"未找到目标frame (BU={bu_code})")

                    self._set_query_conditions(target, bu_code)
                    print(f"[IMS] 查询条件已设置 (BU={bu_code})")

                    self._click_query(target)
                    print(f"[IMS] 查询完成 (BU={bu_code})")
                    time.sleep(3)

                    filepath = self._click_export(page, target, bu_code, idx)
                    print(f"[IMS] 导出完成: {filepath}")
                    file_paths.append(filepath)

                    # Brief pause between BUs
                    time.sleep(2)

                print(f"\n[IMS] 全部导出完成，共 {len(file_paths)} 个文件")
                return file_paths

            except Exception as e:
                print(f"[IMS] 自动化出错: {e}")
                import traceback
                traceback.print_exc()
                try:
                    page.screenshot(path=os.path.join(download_dir, "_debug_error.png"))
                    print("[IMS] 错误截图已保存: _debug_error.png")
                except Exception:
                    pass
                print("[IMS] 浏览器保持打开以便调试，按 Enter 关闭...")
                try:
                    input()
                except EOFError:
                    pass
                raise

            finally:
                for p in context.pages:
                    try:
                        p.close()
                    except Exception:
                        pass
                context.close()
                browser.close()

    def _wait_stable(self, page_or_frame, seconds: float = 2):
        try:
            if hasattr(page_or_frame, 'wait_for_load_state'):
                page_or_frame.wait_for_load_state("networkidle", timeout=8000)
            else:
                page_or_frame.page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        time.sleep(seconds)

    def _login(self, page: Page):
        page.goto(self.config.IMS_LOGIN_URL)
        self._wait_stable(page)

        text_inputs = page.locator('input[type="text"]').all()
        pwd_inputs = page.locator('input[type="password"]').all()

        if text_inputs:
            text_inputs[0].fill(self.config.IMS_USERNAME)
        if pwd_inputs:
            pwd_inputs[0].fill(self.config.IMS_PASSWORD)

        for sel in [
            'input[value*="登录"]',
            'button:has-text("登录")',
            'a:has-text("登录")',
            'input[type="submit"]',
            'button[type="submit"]',
        ]:
            btn = page.locator(sel)
            if btn.count() > 0:
                # JS 原生 click 绕过 Playwright 导航追踪，避免 SSO 重定向超时
                btn.first.evaluate("el => el.click()")
                break
        else:
            if pwd_inputs:
                pwd_inputs[0].press("Enter")

        # SSO 重定向需要较长等待
        page.wait_for_timeout(10000)
        self._wait_stable(page)

        if "登录" in page.title() or "login" in page.url.lower():
            print("[IMS] 可能仍在登录页 — 请手动完成登录（如验证码），完成后按 Enter 继续...")
            try:
                input()
            except EOFError:
                pass
            self._wait_stable(page)

    def _navigate_to_table(self, page: Page):
        """Navigate tree menu: 招聘过程管理 → 人员面试评价表."""
        self._wait_stable(page)
        time.sleep(2)

        # Find "招聘过程管理" in the tree — it's in the left nav frame
        # Try main page and all frames
        found = False
        for frame in [page] + page.frames:
            try:
                # The tree menu uses <a> or <span> elements with text
                el = frame.get_by_text("招聘过程管理", exact=True)
                if el.count() > 0:
                    el.first.dblclick()
                    print(f"[IMS] 双击 '招聘过程管理'")
                    found = True
                    time.sleep(2)
                    break
            except Exception:
                continue

        if not found:
            # Try partial match
            for frame in [page] + page.frames:
                try:
                    el = frame.locator('text="招聘过程管理"')
                    if el.count() > 0:
                        el.first.dblclick()
                        print(f"[IMS] 双击 '招聘过程管理' (fuzzy)")
                        found = True
                        time.sleep(2)
                        break
                except Exception:
                    continue

        # Click "人员面试评价表"
        time.sleep(1)
        found = False
        for frame in [page] + page.frames:
            try:
                el = frame.get_by_text("人员面试评价表", exact=True)
                if el.count() > 0:
                    el.first.click()
                    print(f"[IMS] 点击 '人员面试评价表'")
                    found = True
                    time.sleep(3)
                    break
            except Exception:
                continue

        if not found:
            for frame in [page] + page.frames:
                try:
                    el = frame.locator('text="人员面试评价表"')
                    if el.count() > 0:
                        el.first.click()
                        print(f"[IMS] 点击 '人员面试评价表' (fuzzy)")
                        found = True
                        time.sleep(3)
                        break
                except Exception:
                    continue

        self._wait_stable(page)
        time.sleep(2)

    def _find_table_frame(self, page: Page) -> Frame | Page | None:
        """Find the frame that contains the interview evaluation table.
        Identified by URL pattern: resume_evaluationList.action"""
        print(f"[IMS] 查找目标frame... (共 {len(page.frames)} 个frames)")

        # Look for frame with the evaluation list URL
        for frame in page.frames:
            try:
                url = frame.url or ""
                if "resume_evaluationList" in url or "evaluation" in url.lower():
                    print(f"[IMS] 找到目标frame: url={url[:100]}")
                    return frame
            except Exception:
                continue

        # Fallback: look for frame with "申请时间" text
        for frame in page.frames:
            try:
                if frame.locator('text="申请时间"').count() > 0:
                    print(f"[IMS] 通过'申请时间'找到目标frame")
                    return frame
            except Exception:
                continue

        # Check main page
        try:
            if page.locator('text="申请时间"').count() > 0:
                print("[IMS] 目标表单在主页面")
                return page
        except Exception:
            pass

        # Debug: print all frame URLs
        for i, f in enumerate(page.frames):
            try:
                print(f"[IMS] Frame[{i}]: name='{f.name}' url={f.url[:120]}")
            except Exception:
                print(f"[IMS] Frame[{i}]: (unavailable)")

        return None

    def _set_query_conditions(self, target: Frame | Page, bu_code: str = None):
        """Set query conditions: date range, status, BU.

        Args:
            target: The frame or page containing the form.
            bu_code: Numeric BU code like "185". If None, uses Config.QUERY_BU.
        """
        self._wait_stable(target)

        if bu_code is None:
            bu_code = self.config.QUERY_BU

        today = date.today()
        start_date = today - timedelta(days=self.config.QUERY_DAYS_BACK)
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = today.strftime("%Y-%m-%d")

        # Pass variables as arguments to avoid f-string escaping issues
        js = """
        ([startStr, endStr, buCode]) => {
            // Set date inputs
            let inputs = document.querySelectorAll('input[type="text"]');
            let visible = [];
            for (let el of inputs) {
                if (el.offsetParent !== null) visible.push(el);
            }
            if (visible.length >= 2) {
                visible[0].value = startStr;
                visible[0].dispatchEvent(new Event('input', {bubbles: true}));
                visible[0].dispatchEvent(new Event('change', {bubbles: true}));
                visible[1].value = endStr;
                visible[1].dispatchEvent(new Event('input', {bubbles: true}));
                visible[1].dispatchEvent(new Event('change', {bubbles: true}));
            }

            // Set status dropdown to "审批通过"
            let selects = document.querySelectorAll('select');
            for (let s of selects) {
                for (let o of s.options) {
                    if (o.text.trim() === '审批通过') {
                        s.value = o.value;
                        s.dispatchEvent(new Event('change', {bubbles: true}));
                        try { if (typeof $ !== 'undefined') $(s).trigger('change'); } catch(e) {}
                        break;
                    }
                }
            }

            // Set BU — match by numeric code in parentheses, e.g. "(185)" or "(121)"
            let buPattern = '(' + buCode + ')';
            let buFound = false;
            for (let s of selects) {
                for (let o of s.options) {
                    let t = o.text.trim();
                    if (t.includes(buPattern)) {
                        s.value = o.value;
                        s.dispatchEvent(new Event('change', {bubbles: true}));
                        try { if (typeof $ !== 'undefined') $(s).trigger('change'); } catch(e) {}
                        buFound = true;
                        break;
                    }
                }
                if (buFound) break;
            }
            // Fallback: match option text that starts with the code
            if (!buFound) {
                for (let s of selects) {
                    for (let o of s.options) {
                        if (o.text.trim().startsWith('(' + buCode + ')') ||
                            o.text.trim().includes(buCode)) {
                            s.value = o.value;
                            s.dispatchEvent(new Event('change', {bubbles: true}));
                            buFound = true;
                            break;
                        }
                    }
                    if (buFound) break;
                }
            }
            return 'dates=' + startStr + '~' + endStr + ' bu=' + buCode + ' bu_ok=' + buFound + ' status_set=1';
        }
        """
        result = target.evaluate(js, [start_str, end_str, bu_code])
        print(f"[IMS] 条件设置: {result}")
        if "bu_ok=false" in str(result).lower():
            print(f"[IMS] 警告: 未找到 BU={bu_code} 的下拉选项，尝试继续...")

    def _click_query(self, target: Frame | Page):
        """Click the query button."""
        js = """
        () => {
            let btns = document.querySelectorAll('input[type="button"], input[type="submit"], button, a');
            for (let b of btns) {
                let t = (b.value || b.textContent || '').trim();
                if (t === '查询' || t === '查 询') {
                    b.click();
                    return 'ok_btn:' + t;
                }
            }
            for (let b of btns) {
                let t = (b.value || b.textContent || '');
                if (t.includes('查询') || t.includes('查')) {
                    b.click();
                    return 'ok_fuzzy:' + t.trim();
                }
            }
            // onclick fallback
            let el = document.querySelector('[onclick*="query"],[onclick*="Query"],[onclick*="doQuery"]');
            if (el) { el.click(); return 'ok_onclick'; }
            return 'not_found';
        }
        """
        fn = target.evaluate if hasattr(target, 'evaluate') else (lambda j: target.evaluate(j))
        result = fn(js)
        print(f"[IMS] 查询按钮: {result}")
        if "not_found" in str(result):
            raise Exception("未找到查询按钮")
        time.sleep(5)

    def _click_export(self, page: Page, target: Frame | Page,
                      bu_code: str = "", idx: int = 0) -> str | None:
        """Click export button in the target frame and download.

        Args:
            bu_code: BU code for unique filename.
            idx: Index for unique filename.
        """
        with page.expect_download(timeout=120000) as dl:
            js = """
            () => {
                let btns = document.querySelectorAll('input[type="button"], input[type="submit"], button, a');
                for (let b of btns) {
                    let t = (b.value || b.textContent || '').trim();
                    if (t === '导出' || t === '导 出') {
                        b.click();
                        return 'ok_btn:' + t;
                    }
                }
                for (let b of btns) {
                    let t = (b.value || b.textContent || '');
                    if (t.includes('导出') || t.includes('导')) {
                        b.click();
                        return 'ok_fuzzy:' + t.trim();
                    }
                }
                let el = document.querySelector('[onclick*="export"],[onclick*="Export"],[onclick*="down"]');
                if (el) { el.click(); return 'ok_onclick'; }
                return 'not_found';
            }
            """
            fn = target.evaluate if hasattr(target, 'evaluate') else (lambda j: target.evaluate(j))
            result = fn(js)
            print(f"[IMS] 导出按钮: {result}")
            if "not_found" in str(result):
                raise Exception("未找到导出按钮")

        download = dl.value
        suggested = download.suggested_filename
        # Add BU suffix to filename to avoid overwrites
        base, ext = os.path.splitext(suggested)
        if bu_code:
            unique_name = f"{base}_BU{bu_code}{ext}"
        else:
            unique_name = suggested
        download_dir = os.path.abspath(self.config.DOWNLOAD_DIR)
        filepath = os.path.join(download_dir, unique_name)
        download.save_as(filepath)
        try:
            download.delete()
        except Exception:
            pass
        time.sleep(2)
        return filepath
