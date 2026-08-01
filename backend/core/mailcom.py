"""mail.com 邮箱接码（Python 版，参考 codex_register/src/mail/mailcom.ts）。

流程：
1. Playwright 登录 mail.com
2. 截获 maillist API 的 Bearer token
3. 用 Bearer 调 maillist API 拉收件箱
4. 调 mailbody API 取邮件正文
5. 正则提取 magic link 或验证码
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

MAILLIST_BASE = "https://maillist.mail.com/Mailbox/Mail"
MAILBODY_BASE = "https://mailcom.mailbody-ui.de/Mail"
POLL_ATTEMPTS = 20
POLL_INTERVAL = 6
MAGIC_LINK_RE = re.compile(r'https?://claude\.ai/magic-link#[^\s"\'()<>]+', re.IGNORECASE)


def _html_to_text(html: str) -> str:
    import re as _re
    text = _re.sub(r'<(script|style)\b[^>]*>[\s\S]*?</\1>', ' ', html, flags=_re.IGNORECASE)
    text = _re.sub(r'<[^>]+>', ' ', text)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return _re.sub(r'\s+', ' ', text).strip()


class MailcomSession:
    """mail.com 邮箱会话：Playwright 登录 + Bearer 截获。"""

    def __init__(self):
        self.pw = None
        self.browser = None
        self.context = None
        self.page = None
        self.bearer: str = ""

    def login(self, email: str, password: str, proxy: str = ""):
        from playwright.sync_api import sync_playwright

        self.pw = sync_playwright().start()

        launch_opts = {
            "channel": "chrome",
            "headless": True,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if proxy:
            try:
                from urllib.parse import urlparse
                p = urlparse(proxy if "://" in proxy else f"http://{proxy}")
                launch_opts["proxy"] = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
                if p.username:
                    launch_opts["proxy"]["username"] = p.username
                if p.password:
                    launch_opts["proxy"]["password"] = p.password
            except Exception:
                launch_opts["proxy"] = {"server": proxy}

        self.browser = self.pw.chromium.launch(**launch_opts)
        self.context = self.browser.new_context(
            viewport={"width": 1139, "height": 974},
            locale="en-US",
        )
        self.page = self.context.new_page()

        # 截获 Bearer
        def on_request(request):
            if self.bearer:
                return
            if "maillist.mail.com/Mailbox/Mail" in request.url:
                auth = request.headers.get("authorization", "")
                if auth.lower().startswith("bearer "):
                    self.bearer = auth
                    logger.info("[mailcom] 截获 Bearer: %s...", auth[:32])

        self.page.on("request", on_request)
        self.page.set_default_timeout(20000)

        logger.info("[mailcom] 登录 %s ...", email)
        self.page.goto("https://www.mail.com/", wait_until="commit", timeout=90000)
        self.page.wait_for_timeout(4000)

        # 关闭 consent 弹窗
        for name in ["Continue to Mail", "Accept All", "Accept", "Agree"]:
            try:
                btn = self.page.get_by_role("button", name=name)
                if btn.count() > 0:
                    btn.first.click(timeout=4000)
                    self.page.wait_for_timeout(1500)
                    break
            except Exception:
                pass

        # 登录表单
        if "navigator-lxa" not in self.page.url:
            try:
                self.page.click("#login-button", timeout=10000)
                self.page.wait_for_timeout(1000)
            except Exception:
                pass
            self.page.fill("#login-email", email, timeout=15000)
            self.page.fill("#login-password", password)
            submitted = False
            for sel in ["#header-login-box span", "#header-login-box button"]:
                try:
                    self.page.click(sel, timeout=5000)
                    submitted = True
                    break
                except Exception:
                    pass
            if not submitted:
                try:
                    self.page.press("#login-password", "Enter")
                except Exception:
                    pass

        try:
            self.page.wait_for_url("**navigator-lxa.mail.com**", timeout=45000, wait_until="commit")
        except Exception:
            pass

        # 等待 Bearer 截获
        for i in range(30):
            if self.bearer:
                break
            self.page.wait_for_timeout(1000)

        if not self.bearer:
            self.close()
            raise RuntimeError(f"mail.com 登录失败，未截获 Bearer: {email}")

        logger.info("[mailcom] 登录成功: %s", email)

    def fetch_inbox(self, folder: str = "INBOX", amount: int = 20) -> List[Dict[str, Any]]:
        """拉收件箱列表。"""
        list_body = json.dumps({
            "aditionContext": {"brand": "mailcom", "category": "mail", "section": "3c/folder",
                               "tagid": "inline_united_srq", "layoutclass": "b"},
            "deviceContext": {"app": {"name": "browser"}, "deviceclass": "b"},
            "adBlocker": True,
            "mailboxContext": {"currentPage": 1, "visibleMessages": 9},
        })

        resp = self.context.request.post(
            MAILLIST_BASE,
            params={"folderTypeOrId": folder, "offset": "0", "amount": str(amount), "orderBy": "INTERNALDATE DESC"},
            headers={
                "authorization": self.bearer,
                "origin": "https://webmailer.mail.com",
                "referer": "https://webmailer.mail.com/",
                "x-ui-app": "mailcom.webmailer.mail-list/6.0.0",
                "accept": "application/vnd.1and1.mms.unified-maillist-v1+json; charset=utf-8",
                "content-type": "application/vnd.1and1.mms.inboxadrequest-v1+json; charset=utf-8",
            },
            data=list_body,
        )
        if resp.status == 401:
            raise RuntimeError("Bearer 已过期")
        if not resp.ok:
            raise RuntimeError(f"maillist HTTP {resp.status}")

        data = resp.json()
        result = []
        for el in data.get("mailListElements", []):
            raw = el.get("rawData", el)
            mh = raw.get("mailHeader", {})
            at = raw.get("attribute", {})
            result.append({
                "id": at.get("mailIdentifier", ""),
                "from": mh.get("from", ""),
                "subject": mh.get("subject", ""),
                "timestamp": mh.get("date", at.get("internalDate", 0)),
            })
        return result

    def fetch_body(self, mail_id: str) -> str:
        """取邮件正文 HTML。"""
        token = self.bearer.split(" ", 1)[-1] if " " in self.bearer else self.bearer
        resp = self.context.request.post(
            f"{MAILBODY_BASE}/{mail_id}/Body/html",
            params={"target_origin": "https://webmailer.mail.com"},
            headers={
                "origin": "https://webmailer.mail.com",
                "referer": "https://webmailer.mail.com/",
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*",
            },
            form={"access_token": token},
        )
        if not resp.ok:
            return ""
        return resp.text()

    def close(self):
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        try:
            if self.pw:
                self.pw.stop()
        except Exception:
            pass


def find_claude_magic_link(
    email: str,
    password: str,
    proxy: str = "",
    attempts: int = POLL_ATTEMPTS,
    interval: int = POLL_INTERVAL,
    since_ms: int = 0,
    log_fn=None,
) -> Optional[str]:
    """轮询 mail.com 收件箱，提取 Claude magic link。"""
    _log = log_fn or (lambda m: logger.info(m))

    session = MailcomSession()
    try:
        _log(f"[mailcom] 登录 {email} ...")
        session.login(email, password, proxy=proxy)
        _log(f"[mailcom] 登录成功，Bearer 已截获")

        for i in range(attempts):
            _log(f"[mailcom] 轮询 {i + 1}/{attempts} ...")
            try:
                mails = session.fetch_inbox()
                _log(f"[mailcom] 收件箱共 {len(mails)} 封邮件")

                # 过滤 Anthropic/Claude 邮件
                candidates = [
                    m for m in mails
                    if re.search(r'anthropic|claude', f"{m['from']} {m['subject']}", re.IGNORECASE)
                    and (not since_ms or m.get("timestamp", 0) >= since_ms - 120000)
                ]
                if candidates:
                    _log(f"[mailcom] 找到 {len(candidates)} 封 Claude 相关邮件")
                    for c in candidates[:3]:
                        _log(f"[mailcom]   from={c['from']} subject={c['subject'][:60]}")

                for m in candidates[:3]:
                    body = session.fetch_body(m["id"])
                    _log(f"[mailcom] 正文长度: {len(body)}")
                    match = MAGIC_LINK_RE.search(body)
                    if match:
                        link = match.group(0)
                        _log(f"[mailcom] 找到 magic link (subject: {m['subject']})")
                        return link
                    # 如果正文不为空但没匹配到，打印一段内容帮助调试
                    if body and not match:
                        text = _html_to_text(body)[:200]
                        _log(f"[mailcom] 正文无 magic link: {text[:100]}...")
            except Exception as exc:
                _log(f"[mailcom] 轮询异常: {exc}")

            if i < attempts - 1:
                time.sleep(interval)

        _log(f"[mailcom] {attempts} 轮未找到 magic link")
        return None
    except Exception as exc:
        _log(f"[mailcom] 致命错误: {exc}")
        raise
    finally:
        session.close()
