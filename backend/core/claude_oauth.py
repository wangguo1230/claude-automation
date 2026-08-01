"""Claude Code 授权码获取。

优先路径（快速，参考 sub2api）：
  sessionKey 有效 → HTTP API 直接获取 org UUID → POST authorize → 拿到 code

回退路径（sessionKey 无效时）：
  浏览器打开 OAuth → 邮箱接码 magic link → 完成登录 → 拿到 code
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlencode, urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from adspower_client import AdsPowerClient, AdsPowerError

logger = logging.getLogger(__name__)

CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_BASE = "https://claude.ai/oauth/authorize"
AUTHORIZE_API_BASE = "https://claude.ai/v1/oauth"
ORGS_API = "https://claude.ai/api/organizations"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
REDIRECT_URI = "https://platform.claude.com/oauth/code/callback"
SCOPE = "user:inference user:insights org:create_api_key"
SCOPE_CLAUDE_CODE = "user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload"
MAILCOM_RUNNER = str(Path(__file__).resolve().parent / "mailcom_runner.py")


def _find_magic_link_subprocess(email: str, password: str, proxy: str, since_ms: int, _log) -> Optional[str]:
    """用独立子进程跑邮箱接码（避免两个 Playwright 实例冲突）。"""
    import subprocess
    _log("[mailcom] 启动邮箱接码子进程...")
    input_data = json.dumps({"email": email, "password": password, "proxy": proxy, "since_ms": since_ms})
    try:
        proc = subprocess.run(
            [sys.executable, MAILCOM_RUNNER],
            input=input_data, capture_output=True, text=True,
            timeout=180,
        )
        if proc.returncode != 0:
            _log(f"[mailcom] 子进程退出码 {proc.returncode}")
            _log(f"[mailcom] stderr: {proc.stderr[:500]}")
            _log(f"[mailcom] stdout: {proc.stdout[:500]}")
            return None
        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError:
            _log(f"[mailcom] 输出解析失败: {proc.stdout[:300]}")
            _log(f"[mailcom] stderr: {proc.stderr[:300]}")
            return None
        for log_line in result.get("logs", []):
            _log(log_line)
        if result.get("error"):
            _log(f"[mailcom] 子进程错误: {result['error']}")
        link = result.get("link")
        if link:
            _log(f"[mailcom] 获取到 magic link")
        else:
            _log(f"[mailcom] 未获取到 magic link")
        return link
    except subprocess.TimeoutExpired:
        _log("[mailcom] 子进程超时 (180s)")
        return None
    except Exception as exc:
        _log(f"[mailcom] 子进程异常: {exc}")
        return None


def _generate_code_verifier() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")


def _generate_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _generate_state() -> str:
    return base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode("ascii")


def _build_proxy_dict(proxy: str) -> Optional[Dict]:
    if not proxy:
        return None
    return {"https": proxy, "http": proxy}


def _api_get_org_uuid(session_key: str, proxy: str, _log) -> Optional[str]:
    """用 sessionKey 调 /api/organizations 拿到 org UUID。"""
    import requests

    _log("[OAuth-API] 获取 organization UUID...")
    headers = {
        "Cookie": f"sessionKey={session_key}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }
    proxies = _build_proxy_dict(proxy)

    try:
        resp = requests.get(ORGS_API, headers=headers, proxies=proxies, timeout=30)
        if resp.status_code != 200:
            _log(f"[OAuth-API] 获取 org 失败: HTTP {resp.status_code} {resp.text[:200]}")
            return None
        data = resp.json()
    except Exception as exc:
        _log(f"[OAuth-API] 获取 org 异常: {exc}")
        return None

    if not isinstance(data, list) or len(data) == 0:
        _log(f"[OAuth-API] 无 organization 数据")
        return None

    for org in data:
        if org.get("raven_type") == "team":
            _log(f"[OAuth-API] 选择 team org: {org.get('name', '')} uuid={org['uuid']}")
            return org["uuid"]

    _log(f"[OAuth-API] 使用第一个 org: {data[0].get('name', '')} uuid={data[0]['uuid']}")
    return data[0]["uuid"]


def _api_get_auth_code(session_key: str, org_uuid: str, code_challenge: str, state: str, proxy: str, _log, scope: str = "") -> Optional[str]:
    """用 sessionKey 直接 POST authorize API 拿到授权码。"""
    import requests

    auth_url = f"{AUTHORIZE_API_BASE}/{org_uuid}/authorize"
    body = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "organization_uuid": org_uuid,
        "redirect_uri": REDIRECT_URI,
        "scope": scope or SCOPE,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    headers = {
        "Cookie": f"sessionKey={session_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://claude.ai",
        "Referer": "https://claude.ai/new",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }
    proxies = _build_proxy_dict(proxy)

    _log(f"[OAuth-API] POST {auth_url}")
    try:
        resp = requests.post(auth_url, json=body, headers=headers, proxies=proxies, timeout=30)
        if resp.status_code != 200:
            _log(f"[OAuth-API] authorize 失败: HTTP {resp.status_code} {resp.text[:200]}")
            return None
        data = resp.json()
    except Exception as exc:
        _log(f"[OAuth-API] authorize 异常: {exc}")
        return None

    redirect_uri = data.get("redirect_uri", "")
    if not redirect_uri:
        _log(f"[OAuth-API] 响应中无 redirect_uri: {json.dumps(data)[:200]}")
        return None

    parsed = urlparse(redirect_uri)
    params = parse_qs(parsed.query)
    auth_code = params.get("code", [""])[0]

    if not auth_code:
        _log(f"[OAuth-API] redirect_uri 中无 code: {redirect_uri[:100]}")
        return None

    _log(f"[OAuth-API] 授权成功！拿到 code")
    return redirect_uri


def _try_api_flow(session_key: str, proxy: str, _log) -> Optional[Dict[str, Any]]:
    """尝试纯 API 方式获取授权码（不需要浏览器和邮箱）。"""
    if not session_key:
        return None

    _log("[OAuth] 尝试 API 直接获取授权码（无需浏览器）...")

    org_uuid = _api_get_org_uuid(session_key, proxy, _log)
    if not org_uuid:
        _log("[OAuth] API 方式失败：无法获取 org UUID（sessionKey 可能无效）")
        return None

    code_verifier = _generate_code_verifier()
    code_challenge = _generate_code_challenge(code_verifier)
    state = _generate_state()

    redirect_url = _api_get_auth_code(session_key, org_uuid, code_challenge, state, proxy, _log)
    if not redirect_url:
        _log("[OAuth] API 方式失败：无法获取授权码")
        return None

    return {
        "ok": True,
        "redirect_url": redirect_url,
        "new_session_key": session_key,
        "code_verifier": code_verifier,
    }


def full_oauth_flow(
    session_key: str,
    config: Dict[str, Any],
    email: str = "",
    password: str = "",
    log_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    """完整 OAuth 流程。优先 API 直接获取，失败则回退浏览器+邮箱。"""
    _log = log_fn or (lambda m: logger.info(m))
    proxy = config.get("proxy", "")

    # ===== 优先路径：API 直接获取（参考 sub2api） =====
    api_result = _try_api_flow(session_key, proxy, _log)
    if api_result:
        return api_result

    # ===== 回退路径：浏览器 + 邮箱接码 =====
    _log("[OAuth] API 方式不可用，回退到浏览器+邮箱方式...")

    if not email or not password:
        return {"ok": False, "step": "input", "error": "sessionKey 无效且未提供邮箱密码，无法完成授权"}

    from playwright.sync_api import sync_playwright

    browser_provider = config.get("browser_provider", "adspower")
    ads_client = None
    ads_profile_id = ""
    chrome_process = None
    profile_dir = None

    code_verifier = _generate_code_verifier()
    code_challenge = _generate_code_challenge(code_verifier)
    state = _generate_state()

    auth_url = AUTHORIZE_BASE + "?" + urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    })

    try:
        _log("[OAuth] 启动浏览器...")
        if browser_provider == "local_chrome":
            from .worker import _find_chrome, _find_free_port, _is_cdp_available, _stop_ephemeral_chrome, DATA_DIR, _EPHEMERAL_BASE_DIRNAME
            import subprocess, tempfile
            chrome_path = _find_chrome(config.get("chrome_path", ""))
            if not chrome_path:
                return {"ok": False, "step": "browser", "error": "未找到本地 Chrome"}
            base_dir = DATA_DIR / _EPHEMERAL_BASE_DIRNAME
            base_dir.mkdir(parents=True, exist_ok=True)
            profile_dir = Path(tempfile.mkdtemp(prefix="oauth_", dir=str(base_dir)))
            port = _find_free_port()
            args = [chrome_path, f"--remote-debugging-port={port}", f"--user-data-dir={str(profile_dir)}",
                    "--no-first-run", "--no-default-browser-check"]
            if proxy:
                args.append(f"--proxy-server={proxy}")
            popen_kw = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if os.name == "nt":
                popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kw["start_new_session"] = True
            chrome_process = subprocess.Popen(args, **popen_kw)
            cdp_url = f"http://127.0.0.1:{port}"
            for _ in range(60):
                if _is_cdp_available(cdp_url, timeout=0.5):
                    break
                time.sleep(0.5)
            else:
                return {"ok": False, "step": "browser", "error": "Chrome CDP 未就绪"}
        else:
            ads_client = AdsPowerClient(
                config.get("adspower_api_base", "http://localhost:50325"),
                api_key=config.get("adspower_api_key", ""),
            )
            if not ads_client.health():
                return {"ok": False, "step": "browser", "error": "AdsPower 未启动"}
            try:
                for p in ads_client.list_profiles():
                    if str(p.get("name", "")).startswith("oauth_"):
                        pid = str(p.get("user_id") or p.get("id") or "")
                        if pid:
                            try: ads_client.close_browser(pid)
                            except: pass
                            time.sleep(0.3)
                            try: ads_client.delete_profile(pid)
                            except: pass
                            time.sleep(0.3)
            except: pass
            ads_profile_id = ads_client.create_profile(
                name="oauth_temp", group_id=config.get("adspower_group_id", "0"), proxy=proxy,
            )
            time.sleep(0.6)
            cdp_url = ads_client.open_browser(ads_profile_id)

        pw = sync_playwright().start()
        redirect_result = {"url": ""}

        try:
            browser = pw.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()

            def on_response(response):
                url = response.url
                if REDIRECT_URI in url and "code=" in url:
                    redirect_result["url"] = url
                    _log(f"[OAuth] 截获授权回调 URL")

            page.on("response", on_response)

            def on_request(request):
                url = request.url
                if REDIRECT_URI in url and "code=" in url:
                    redirect_result["url"] = url

            page.on("request", on_request)

            _log(f"[OAuth] 打开授权页...")
            page.goto(auth_url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(5000)

            for _ in range(10):
                if "just a moment" in page.title().lower():
                    _log("[OAuth] 等待 Cloudflare...")
                    page.wait_for_timeout(3000)
                else:
                    break

            _log(f"[OAuth] 当前页面: {page.url}")

            # 如果有 sessionKey，先注入试试
            if session_key:
                context.add_cookies([{
                    "name": "sessionKey", "value": session_key,
                    "domain": ".claude.ai", "path": "/",
                    "httpOnly": True, "secure": True, "sameSite": "Lax",
                }])
                page.goto(auth_url, wait_until="domcontentloaded", timeout=120000)
                page.wait_for_timeout(5000)

                if redirect_result["url"]:
                    _log("[OAuth] sessionKey 有效，直接拿到授权码")
                    return {"ok": True, "redirect_url": redirect_result["url"], "new_session_key": session_key}

            # 需要登录 → 输入邮箱
            _log("[OAuth] 输入邮箱登录...")
            before_ts = int(time.time() * 1000)

            try:
                email_input = page.locator('input[type="email"], input[name="email"], input[autocomplete="email"]')
                email_input.wait_for(state="visible", timeout=30000)
                email_input.fill(email)
                page.wait_for_timeout(500)

                clicked = False
                for text in ["Continue with email", "Continue", "Send login code", "Log in"]:
                    btn = page.get_by_text(text, exact=False)
                    if btn.count() > 0:
                        btn.first.click()
                        clicked = True
                        _log(f"[OAuth] 点击了 '{text}'")
                        break

                if not clicked:
                    page.locator('button[type="submit"]').first.click()
                    _log("[OAuth] 点击了 submit 按钮")

                page.wait_for_timeout(3000)
            except Exception as exc:
                return {"ok": False, "step": "login_form", "error": f"登录表单操作失败: {exc}"}

            _log("[OAuth] 已提交邮箱，等待验证邮件...")

            magic_link = _find_magic_link_subprocess(
                email=email, password=password, proxy=proxy,
                since_ms=before_ts, _log=_log,
            )
            if not magic_link:
                return {"ok": False, "step": "magic_link", "error": "未收到验证邮件（轮询超时）"}

            _log("[OAuth] 打开 magic link...")
            page.goto(magic_link, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)

            try:
                for text in ["Authorize", "Allow", "Confirm", "Approve", "Continue"]:
                    btn = page.get_by_text(text, exact=False)
                    if btn.count() > 0:
                        btn.first.click()
                        _log(f"[OAuth] 点击了 '{text}'")
                        page.wait_for_timeout(3000)
                        break
            except Exception:
                pass

            for i in range(30):
                if redirect_result["url"]:
                    break
                if REDIRECT_URI in page.url and "code=" in page.url:
                    redirect_result["url"] = page.url
                    break
                page.wait_for_timeout(1000)

            new_sk = session_key
            try:
                for c in context.cookies(["https://claude.ai"]):
                    if c.get("name") == "sessionKey":
                        new_sk = c.get("value", session_key)
            except Exception:
                pass

            if redirect_result["url"]:
                _log(f"[OAuth] 授权成功！")
                return {"ok": True, "redirect_url": redirect_result["url"], "new_session_key": new_sk}

            return {"ok": False, "step": "redirect", "error": f"未截获授权回调。当前页面: {page.url}"}

        finally:
            try:
                pw.stop()
            except Exception:
                pass

    except Exception as exc:
        return {"ok": False, "step": "unknown", "error": str(exc)[:500]}
    finally:
        if ads_client and ads_profile_id:
            try: ads_client.close_browser(ads_profile_id)
            except: pass
            try: ads_client.delete_profile(ads_profile_id)
            except: pass
        if chrome_process:
            from .worker import _stop_ephemeral_chrome
            _stop_ephemeral_chrome(chrome_process, profile_dir)


# ══════════════════════════════════════════════════════════
# sub2api JSON 导出
# ══════════════════════════════════════════════════════════

def _exchange_code_for_tokens(code: str, code_verifier: str, proxy: str, _log) -> Optional[Dict]:
    import requests

    body = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "axios/1.13.6",
    }
    proxies = _build_proxy_dict(proxy)

    _log("[Token] 交换 access_token...")
    try:
        resp = requests.post(TOKEN_URL, json=body, headers=headers, proxies=proxies, timeout=30)
        if resp.status_code != 200:
            _log(f"[Token] 失败: HTTP {resp.status_code} {resp.text[:200]}")
            return None
        return resp.json()
    except Exception as exc:
        _log(f"[Token] 异常: {exc}")
        return None


def generate_sub2api_entry(
    session_key: str,
    email: str,
    proxy: str,
    name: str = "",
    _log=None,
) -> Optional[Dict]:
    _log = _log or (lambda m: None)

    org_uuid = _api_get_org_uuid(session_key, proxy, _log)
    if not org_uuid:
        return None

    code_verifier = _generate_code_verifier()
    code_challenge = _generate_code_challenge(code_verifier)
    state = _generate_state()

    redirect_url = _api_get_auth_code(
        session_key, org_uuid, code_challenge, state, proxy, _log,
        scope=SCOPE_CLAUDE_CODE,
    )
    if not redirect_url:
        return None

    parsed = urlparse(redirect_url)
    params = parse_qs(parsed.query)
    auth_code = params.get("code", [""])[0]
    if not auth_code:
        _log("[sub2api] redirect_url 中无 code")
        return None

    token_data = _exchange_code_for_tokens(auth_code, code_verifier, proxy, _log)
    if not token_data:
        return None

    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 28800)
    scope = token_data.get("scope", "")
    token_type = token_data.get("token_type", "Bearer")

    account_uuid = ""
    email_address = email
    resp_org_uuid = org_uuid
    if token_data.get("account"):
        account_uuid = token_data["account"].get("uuid", "")
        email_address = token_data["account"].get("email_address", email)
    if token_data.get("organization"):
        resp_org_uuid = token_data["organization"].get("uuid", org_uuid)

    expires_at = int(time.time()) + expires_in

    _log(f"[sub2api] 成功: {email_address}")
    return {
        "name": name or email_address,
        "platform": "anthropic",
        "type": "oauth",
        "credentials": {
            "access_token": access_token,
            "account_uuid": account_uuid,
            "email_address": email_address,
            "expires_at": expires_at,
            "expires_in": expires_in,
            "org_uuid": resp_org_uuid,
            "refresh_token": refresh_token,
            "scope": scope,
            "token_type": token_type,
        },
        "extra": {
            "account_uuid": account_uuid,
            "email_address": email_address,
            "org_uuid": resp_org_uuid,
        },
        "concurrency": 100,
        "priority": 1,
        "rate_multiplier": 1,
        "auto_pause_on_expired": True,
    }
