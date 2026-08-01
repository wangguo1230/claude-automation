"""Claude SEPA 订阅自动化。

全流程：AdsPower 指纹浏览器登录 → 选择订阅计划 → 填写账单地址 → 填写 IBAN → 提交订阅。

用法：
    python subscribe.py                # 使用 config.json 配置
    python subscribe.py --auto         # 自动点击 Subscribe（覆盖配置）
    python subscribe.py --plan pro     # 指定计划
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict

from adspower_client import AdsPowerClient, AdsPowerError
from address_generator import generate_address
from iban_generator import generate_iban

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).parent / "config.json"

PLAN_SELECTORS = {
    "max": "text/Get Max plan",
    "pro": "text/Get Pro plan",
}


def load_config() -> Dict[str, Any]:
    if not CONFIG_FILE.exists():
        logger.error("配置文件不存在: %s", CONFIG_FILE)
        sys.exit(1)
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Claude SEPA 订阅自动化")
    parser.add_argument("--auto", action="store_true", help="自动点击 Subscribe")
    parser.add_argument("--plan", type=str, help="订阅计划: max / pro")
    parser.add_argument("--monthly", action="store_true", help="月付（默认年付）")
    args = parser.parse_args()

    cfg = load_config()
    session_key = cfg.get("session_key", "").strip()
    if not session_key:
        logger.error("config.json 中 session_key 为空")
        sys.exit(1)

    plan = args.plan or cfg.get("plan", "max")
    billing_period = "monthly" if args.monthly else cfg.get("billing_period", "annual")
    iban_country = cfg.get("iban_country", "DE")
    auto_subscribe = args.auto or cfg.get("auto_subscribe", True)

    client = AdsPowerClient(
        cfg.get("adspower_api_base", "http://localhost:50325"),
        api_key=cfg.get("adspower_api_key", ""),
    )

    if not client.health():
        logger.error("AdsPower 未启动或无法连接")
        sys.exit(1)
    logger.info("AdsPower 连接正常")

    address = generate_address()

    # IBAN 策略：配置里有就复用，没有才生成新的并写回配置
    iban = cfg.get("iban", "").strip()
    if iban:
        logger.info("复用 IBAN: %s", iban)
    else:
        iban = generate_iban(iban_country)
        cfg["iban"] = iban
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("生成新 IBAN 并保存: %s", iban)

    logger.info("地址: %s, %s, %s %s", address["name"], address["city"], address["state"], address["postal_code"])

    profile_id = ""
    try:
        profile_id = client.create_profile(
            name="claude_subscribe",
            group_id=cfg.get("adspower_group_id", "0"),
            proxy=cfg.get("proxy", ""),
        )
        logger.info("创建 profile: %s", profile_id)

        time.sleep(0.6)
        cdp_ws_url = client.open_browser(profile_id)
        logger.info("浏览器已启动, CDP: %s", cdp_ws_url)

        _run_automation(
            cdp_ws_url=cdp_ws_url,
            session_key=session_key,
            plan=plan,
            billing_period=billing_period,
            address=address,
            iban=iban,
            auto_subscribe=auto_subscribe,
        )

        logger.info("自动化流程完成，浏览器保持打开")
        logger.info("按 Ctrl+C 关闭浏览器并清理 profile")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("收到中断信号，开始清理...")

    except AdsPowerError as exc:
        logger.error("AdsPower 操作失败: %s", exc)
    except Exception as exc:
        logger.error("异常: %s", exc)
        import traceback
        traceback.print_exc()
    finally:
        if profile_id:
            _cleanup(client, profile_id)


def _run_automation(
    *,
    cdp_ws_url: str,
    session_key: str,
    plan: str,
    billing_period: str,
    address: Dict[str, str],
    iban: str,
    auto_subscribe: bool,
):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp_ws_url)
        logger.info("Playwright 已连接 CDP")

        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()

        # 1. 注入 cookie 并登录
        _step_login(context, page, session_key)

        # 2. 导航到升级页面并选择计划
        _step_select_plan(page, plan, billing_period)

        # 3. 填写 Stripe 账单地址（iframe）
        _step_fill_billing_address(page, address)

        # 4. 填写 IBAN（iframe）
        _step_fill_iban(page, iban)

        # 5. 勾选协议并提交
        _step_submit(page, auto_subscribe)


def _step_login(context, page, session_key: str):
    logger.info("[步骤1] 注入 cookie 并登录...")
    context.add_cookies([{
        "name": "sessionKey",
        "value": session_key,
        "domain": ".claude.ai",
        "path": "/",
        "httpOnly": True,
        "secure": True,
        "sameSite": "Lax",
    }])

    page.goto("https://claude.ai/new", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)

    url = page.url
    if "login" in url.lower() or "sign" in url.lower():
        logger.error("登录失败，页面跳转到: %s", url)
        raise RuntimeError("sessionKey 无效或已过期")

    logger.info("[步骤1] 登录成功, URL: %s", url)


def _step_select_plan(page, plan: str, billing_period: str):
    logger.info("[步骤2] 选择 %s 计划 (%s)...", plan, billing_period)

    # 点击用户菜单
    menu_btn = page.locator('[data-testid="user-menu-button"]')
    menu_btn.wait_for(state="visible", timeout=10000)
    menu_btn.click()
    page.wait_for_timeout(500)

    # 点击 Upgrade plan
    upgrade_item = page.get_by_text("Upgrade plan", exact=False)
    upgrade_item.wait_for(state="visible", timeout=5000)
    upgrade_item.click()
    page.wait_for_timeout(2000)

    # 选择计划
    plan_selector = PLAN_SELECTORS.get(plan, PLAN_SELECTORS["max"])
    plan_text = "Get Max plan" if plan == "max" else "Get Pro plan"
    plan_btn = page.get_by_text(plan_text, exact=False).first
    plan_btn.wait_for(state="visible", timeout=10000)
    plan_btn.click()
    logger.info("[步骤2] 已点击 %s 按钮", plan_text)

    page.wait_for_timeout(5000)

    # 选择计费周期（年付/月付）
    if billing_period == "annual":
        annual_tab = page.get_by_text("Save 50%", exact=False)
        if annual_tab.count() > 0:
            annual_tab.first.click()
            logger.info("[步骤2] 已选择年付")
            page.wait_for_timeout(1000)

    logger.info("[步骤2] 计划选择完成")


def _find_stripe_frame(page, keyword: str, timeout: int = 20000, exclude: str = ""):
    """在页面所有 iframe 中查找包含指定关键字的 Stripe iframe。"""
    import time as _time
    deadline = _time.time() + timeout / 1000
    while _time.time() < deadline:
        for frame in page.frames:
            url = frame.url or ""
            if keyword in url and (not exclude or exclude not in url):
                logger.info("  找到 Stripe iframe: %s", url[:120])
                return frame
        page.wait_for_timeout(500)
    all_urls = [f.url for f in page.frames if f.url and f.url != "about:blank"]
    logger.error("  未找到包含 '%s' 的 iframe，当前 frames: %s", keyword, all_urls)
    raise RuntimeError(f"未找到 Stripe iframe (keyword={keyword})")


def _step_fill_billing_address(page, address: Dict[str, str]):
    logger.info("[步骤3] 填写账单地址...")

    page.wait_for_timeout(3000)

    # 查找 Stripe address iframe（可能是 elements-inner-address 或其他 URL 模式）
    addr_frame = _find_stripe_frame(page, "address")

    # Full name
    name_input = addr_frame.locator("#billingAddress-nameInput")
    name_input.wait_for(state="visible", timeout=10000)
    name_input.click()
    name_input.fill(address["name"])
    logger.info("  Full name → %s", address["name"])
    page.wait_for_timeout(300)

    # Country → US（切换国家后 Stripe iframe 会 detach 并重新渲染）
    country_select = addr_frame.locator("#billingAddress-countryInput")
    country_select.click()
    page.wait_for_timeout(300)
    country_select.select_option("US")
    logger.info("  Country → US")

    # 等 iframe 重新渲染稳定
    page.wait_for_timeout(3000)
    addr_frame = _find_stripe_frame(page, "address")

    # 逐字段填写，每个字段前都重新获取 frame（Stripe 地址自动补全会导致 iframe 重载）
    def _fill_addr_field(field_id: str, value: str, label: str, use_type: bool = False):
        nonlocal addr_frame
        try:
            el = addr_frame.locator(field_id)
            el.wait_for(state="visible", timeout=8000)
            el.click()
            page.wait_for_timeout(200)
            if use_type:
                el.press_sequentially(value, delay=30)
            else:
                el.fill(value)
            # 按 Escape 关闭自动补全下拉
            el.press("Escape")
            logger.info("  %s → %s", label, value)
            page.wait_for_timeout(500)
        except Exception:
            # iframe 可能被刷新，重新获取后重试
            page.wait_for_timeout(1500)
            addr_frame = _find_stripe_frame(page, "address")
            el = addr_frame.locator(field_id)
            el.wait_for(state="visible", timeout=8000)
            el.click()
            page.wait_for_timeout(200)
            if use_type:
                el.press_sequentially(value, delay=30)
            else:
                el.fill(value)
            el.press("Escape")
            logger.info("  %s → %s (重试成功)", label, value)
            page.wait_for_timeout(500)

    _fill_addr_field("#billingAddress-addressLine1Input", address["line1"], "Address", use_type=True)

    _fill_addr_field("#billingAddress-localityInput", address["city"], "City")

    # State 是 select
    try:
        state_select = addr_frame.locator("#billingAddress-administrativeAreaInput")
        state_select.click()
        page.wait_for_timeout(300)
        state_select.select_option(address["state"])
        logger.info("  State → %s", address["state"])
        page.wait_for_timeout(300)
    except Exception:
        page.wait_for_timeout(1500)
        addr_frame = _find_stripe_frame(page, "address")
        state_select = addr_frame.locator("#billingAddress-administrativeAreaInput")
        state_select.click()
        page.wait_for_timeout(300)
        state_select.select_option(address["state"])
        logger.info("  State → %s (重试成功)", address["state"])
        page.wait_for_timeout(300)

    _fill_addr_field("#billingAddress-postalCodeInput", address["postal_code"], "ZIP")

    logger.info("[步骤3] 账单地址填写完成")


def _step_fill_iban(page, iban: str):
    logger.info("[步骤4] 填写 IBAN: %s", iban)

    page.wait_for_timeout(2000)

    # 调试：列出所有 iframe
    all_frames = [f.url for f in page.frames if f.url and f.url != "about:blank"]
    logger.info("  当前页面所有 frames:")
    for url in all_frames:
        logger.info("    - %s", url[:150])

    # 先尝试在主页面点击 SEPA/Bank transfer 支付方式标签（如果存在的话）
    for label_text in ["SEPA", "Bank", "bank transfer", "Bank transfer", "Direct debit"]:
        sepa_tab = page.get_by_text(label_text, exact=False)
        if sepa_tab.count() > 0:
            sepa_tab.first.click()
            logger.info("  已点击 '%s' 支付方式", label_text)
            page.wait_for_timeout(2000)
            break

    # 也在 payment iframe 内部查找支付方式切换
    try:
        pay_frame = _find_stripe_frame(page, "elements-inner-payment", exclude="google-pay", timeout=5000)
    except RuntimeError:
        # 没有 elements-inner-payment iframe，尝试更宽泛的匹配
        logger.info("  未找到 elements-inner-payment iframe，尝试其他 payment iframe...")
        pay_frame = None
        for frame in page.frames:
            url = frame.url or ""
            if "stripe.com" in url and "payment" in url and "google-pay" not in url:
                pay_frame = frame
                logger.info("  使用 payment frame: %s", url[:120])
                break

    if pay_frame is None:
        logger.error("  未找到任何 payment iframe")
        # 打印页面截图路径以便调试
        page.screenshot(path="/Users/mrwang/study/2026/cluade-automation/debug_step4.png")
        logger.info("  已保存调试截图到 debug_step4.png")
        raise RuntimeError("未找到 IBAN 支付 iframe")

    # 在 payment iframe 内查找 SEPA 选项
    sepa_option = pay_frame.locator("text=SEPA").first
    if sepa_option.count() > 0:
        sepa_option.click()
        logger.info("  在 iframe 内点击 SEPA 选项")
        page.wait_for_timeout(1000)

    # 尝试填写 IBAN
    iban_input = pay_frame.locator("#payment-ibanInput")
    if iban_input.count() == 0:
        # 尝试其他可能的 IBAN 选择器
        for sel in ["input[name*='iban']", "input[placeholder*='IBAN']", "[data-elements-stable-field-name='iban']"]:
            iban_input = pay_frame.locator(sel)
            if iban_input.count() > 0:
                logger.info("  通过备选选择器找到 IBAN: %s", sel)
                break

    if iban_input.count() == 0:
        logger.error("  IBAN 输入框不存在，该页面可能不支持 SEPA 支付")
        page.screenshot(path="/Users/mrwang/study/2026/cluade-automation/debug_no_iban.png")
        logger.info("  已保存截图到 debug_no_iban.png")
        raise RuntimeError("IBAN 输入框不可用，可能需要安装 SEPA Helper 扩展或切换账户区域")

    iban_input.wait_for(state="visible", timeout=10000)
    iban_input.click()
    page.wait_for_timeout(300)
    iban_input.fill(iban)
    page.wait_for_timeout(500)

    logger.info("[步骤4] IBAN 填写完成")


def _step_submit(page, auto_subscribe: bool):
    logger.info("[步骤5] 勾选协议...")

    page.wait_for_timeout(1000)

    # 先滚动到页面底部，确保协议区域可见
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(500)

    # 用 JS 直接点击 checkbox，避免 Playwright click 触发滚动
    clicked = page.evaluate("""() => {
        const cb = document.querySelector('aside input[type="checkbox"]');
        if (cb) { cb.scrollIntoView({block: 'center'}); cb.click(); return true; }
        const labels = document.querySelectorAll('aside label');
        for (const label of labels) {
            const input = label.querySelector('input');
            if (input) { input.scrollIntoView({block: 'center'}); input.click(); return true; }
        }
        return false;
    }""")
    if clicked:
        logger.info("  协议已勾选")
        page.wait_for_timeout(500)
    else:
        logger.warning("  未找到协议 checkbox")

    if auto_subscribe:
        logger.info("[步骤5] 点击 Subscribe...")
        page.wait_for_timeout(500)
        # 用 JS 点击避免滚动问题
        sub_clicked = page.evaluate("""() => {
            const btns = document.querySelectorAll('aside button');
            for (const btn of btns) {
                if (btn.textContent.trim().includes('Subscribe')) {
                    btn.scrollIntoView({block: 'center'});
                    btn.click();
                    return true;
                }
            }
            return false;
        }""")
        if sub_clicked:
            logger.info("[步骤5] 已点击 Subscribe！")
            page.wait_for_timeout(5000)
        else:
            logger.warning("[步骤5] 未找到 Subscribe 按钮")
    else:
        logger.info("[步骤5] auto_subscribe=false, 等待手动点击 Subscribe")
        logger.info("  请在浏览器中检查表单后手动点击 Subscribe 按钮")


def _wait_and_fill(frame_locator, selector: str, value: str, label: str):
    element = frame_locator.locator(selector)
    element.wait_for(state="visible", timeout=10000)
    element.click()
    element.fill(value)
    logger.info("  %s → %s", label, value)
    import time
    time.sleep(0.3)


def _cleanup(client: AdsPowerClient, profile_id: str):
    try:
        client.close_browser(profile_id)
        logger.info("浏览器已关闭")
    except AdsPowerError as exc:
        logger.debug("关闭浏览器异常: %s", exc)
    try:
        client.delete_profile(profile_id)
        logger.info("profile 已删除: %s", profile_id)
    except AdsPowerError as exc:
        logger.debug("删除 profile 异常: %s", exc)


if __name__ == "__main__":
    main()
