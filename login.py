"""通过 AdsPower 指纹浏览器 + sessionKey cookie 登录 claude.ai。

流程：
1. 连接 AdsPower Local API，创建 profile 并启动浏览器
2. 通过 CDP 连接 Playwright
3. 注入 sessionKey cookie 到 claude.ai
4. 导航到 claude.ai 验证登录状态
5. 保持浏览器打开供后续操作
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict

from adspower_client import AdsPowerClient, AdsPowerError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).parent / "config.json"


def load_config() -> Dict[str, Any]:
    if not CONFIG_FILE.exists():
        logger.error("配置文件不存在: %s", CONFIG_FILE)
        sys.exit(1)
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def login_with_adspower():
    cfg = load_config()
    session_key = cfg.get("session_key", "").strip()
    if not session_key:
        logger.error("config.json 中 session_key 为空")
        sys.exit(1)

    api_base = cfg.get("adspower_api_base", "http://localhost:50325")
    api_key = cfg.get("adspower_api_key", "")
    group_id = cfg.get("adspower_group_id", "0")
    proxy = cfg.get("proxy", "")
    target_url = cfg.get("target_url", "https://claude.ai")

    client = AdsPowerClient(api_base, api_key=api_key)

    if not client.health():
        logger.error("AdsPower 未启动或无法连接（%s）", api_base)
        sys.exit(1)
    logger.info("AdsPower 连接正常")

    profile_id = ""
    try:
        profile_id = client.create_profile(name="claude_login", group_id=group_id, proxy=proxy)
        logger.info("创建 profile 成功: %s", profile_id)

        time.sleep(0.6)
        cdp_ws_url = client.open_browser(profile_id)
        logger.info("浏览器已启动, CDP: %s", cdp_ws_url)

        _do_login(cdp_ws_url, session_key, target_url)

        logger.info("登录流程完成，浏览器保持打开")
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


def _do_login(cdp_ws_url: str, session_key: str, target_url: str):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp_ws_url)
        logger.info("Playwright 已连接 CDP")

        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()

        context.add_cookies([{
            "name": "sessionKey",
            "value": session_key,
            "domain": ".claude.ai",
            "path": "/",
            "httpOnly": True,
            "secure": True,
            "sameSite": "Lax",
        }])
        logger.info("sessionKey cookie 已注入")

        page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
        logger.info("已导航到 %s", target_url)

        time.sleep(3)

        title = page.title()
        url = page.url
        logger.info("页面标题: %s", title)
        logger.info("当前 URL: %s", url)

        if "login" in url.lower() or "sign" in url.lower():
            logger.warning("看起来未登录成功，页面跳转到了登录页: %s", url)
        else:
            logger.info("登录成功！")

        # 不关闭 browser —— 保持 AdsPower 窗口打开供手动操作
        # browser.close() 会关闭 CDP 连接但 AdsPower 窗口保持


def _cleanup(client: AdsPowerClient, profile_id: str):
    try:
        client.close_browser(profile_id)
        logger.info("浏览器已关闭")
    except AdsPowerError as exc:
        logger.debug("关闭浏览器异常（已忽略）: %s", exc)
    try:
        client.delete_profile(profile_id)
        logger.info("profile 已删除: %s", profile_id)
    except AdsPowerError as exc:
        logger.debug("删除 profile 异常（已忽略）: %s", exc)


if __name__ == "__main__":
    login_with_adspower()
