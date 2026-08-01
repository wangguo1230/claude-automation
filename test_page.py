"""测试脚本：登录 claude.ai 并截图 checkout 页面结构。"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from adspower_client import AdsPowerClient

SESSION_KEY = "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"
PROXY = "socks5://127.0.0.1:10808"


def main():
    client = AdsPowerClient("http://localhost:50325")
    if not client.health():
        print("AdsPower 未启动")
        return

    pid = ""
    try:
        pid = client.create_profile(name="test_page", proxy=PROXY)
        print(f"profile: {pid}")
        time.sleep(0.6)
        cdp = client.open_browser(pid)
        print(f"CDP: {cdp}")

        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(cdp)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            ctx.add_cookies([{
                "name": "sessionKey", "value": SESSION_KEY,
                "domain": ".claude.ai", "path": "/",
                "httpOnly": True, "secure": True, "sameSite": "Lax",
            }])

            page.goto("https://claude.ai/new", wait_until="domcontentloaded", timeout=90000)
            time.sleep(3)
            print(f"登录后 URL: {page.url}")

            # 点菜单 → Upgrade
            menu = page.locator('[data-testid="user-menu-button"]')
            menu.wait_for(state="visible", timeout=30000)
            menu.click()
            time.sleep(0.5)

            upgrade = page.get_by_text("Upgrade plan", exact=False)
            upgrade.wait_for(state="visible", timeout=15000)
            upgrade.click()
            time.sleep(2)

            # 点 Get Max plan
            btn = page.get_by_text("Get Max plan", exact=False).first
            btn.wait_for(state="visible", timeout=30000)
            btn.click()
            time.sleep(5)

            # 关 cookie 弹窗
            page.evaluate("""() => {
                for (const b of document.querySelectorAll('button')) {
                    if (b.textContent.includes('Reject All')) { b.click(); return; }
                }
            }""")
            time.sleep(1)

            # 截图整个页面
            page.screenshot(path="data/test_full_page.png", full_page=True)
            print("截图已保存: data/test_full_page.png")

            # 列出所有 frames
            print("\n所有 frames:")
            for f in page.frames:
                if f.url and f.url != "about:blank":
                    print(f"  {f.url[:150]}")

            # 扫描页面上所有 input
            inputs = page.evaluate("""() => {
                const result = [];
                document.querySelectorAll('input, select, textarea').forEach(el => {
                    result.push({
                        tag: el.tagName, id: el.id, name: el.name,
                        type: el.type, placeholder: el.placeholder,
                        visible: el.offsetParent !== null
                    });
                });
                return result;
            }""")
            print("\n主页面 input 元素:")
            for inp in inputs:
                print(f"  <{inp['tag']} id='{inp['id']}' name='{inp['name']}' type='{inp['type']}' placeholder='{inp['placeholder']}' visible={inp['visible']}>")

            # 扫描 Stripe iframe 内的 input
            for f in page.frames:
                url = f.url or ""
                if "stripe.com" in url:
                    try:
                        f_inputs = f.evaluate("""() => {
                            const result = [];
                            document.querySelectorAll('input, select, textarea').forEach(el => {
                                result.push({
                                    tag: el.tagName, id: el.id, name: el.name,
                                    type: el.type, placeholder: el.placeholder
                                });
                            });
                            return result;
                        }""")
                        if f_inputs:
                            print(f"\nStripe iframe ({url[:80]}) 内的 input:")
                            for inp in f_inputs:
                                print(f"  <{inp['tag']} id='{inp['id']}' name='{inp['name']}' type='{inp['type']}' placeholder='{inp['placeholder']}'>")
                    except Exception:
                        pass

            print("\n浏览器保持打开，按 Ctrl+C 退出")
            while True:
                time.sleep(1)

    except KeyboardInterrupt:
        print("退出")
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if pid:
            try:
                client.close_browser(pid)
                client.delete_profile(pid)
            except Exception:
                pass


if __name__ == "__main__":
    main()
