"""单账号浏览器 Worker — 打开浏览器并注入 session cookie。"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.request import ProxyHandler, build_opener
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from adspower_client import AdsPowerClient, AdsPowerError

logger = logging.getLogger(__name__)


def _clear_asyncio_loop():
    import asyncio
    try:
        asyncio._set_running_loop(None)
    except (AttributeError, RuntimeError, TypeError):
        pass
    try:
        asyncio.set_event_loop(None)
    except Exception:
        pass


# ── 本地 Chrome 路径检测 ──

_CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium-browser",
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
]


def _find_chrome(configured_path: str = "") -> str:
    if configured_path and Path(configured_path).exists():
        return configured_path
    for p in _CHROME_PATHS:
        if Path(p).exists():
            return p
    return ""


# ── 并发安全的端口分配 ──

_EPHEMERAL_PORT_RANGE_START = 19300
_EPHEMERAL_PORT_RANGE_TRIES = 200
_EPHEMERAL_PORT_LOCK = threading.Lock()
_EPHEMERAL_RESERVED_PORTS: dict[int, float] = {}
_EPHEMERAL_PORT_RESERVE_TTL = 60.0
_EPHEMERAL_CDP_WAIT_SECONDS = 30.0
_EPHEMERAL_LAUNCH_ATTEMPTS = 2
_EPHEMERAL_BASE_DIRNAME = "ephemeral-chrome"
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

_ADSPOWER_API_LOCK = threading.Lock()


def _prune_reserved_ports(now: float):
    expired = [p for p, ts in _EPHEMERAL_RESERVED_PORTS.items() if now - ts > _EPHEMERAL_PORT_RESERVE_TTL]
    for p in expired:
        _EPHEMERAL_RESERVED_PORTS.pop(p, None)


def _find_free_port() -> int:
    with _EPHEMERAL_PORT_LOCK:
        now = time.time()
        _prune_reserved_ports(now)
        for offset in range(max(1, _EPHEMERAL_PORT_RANGE_TRIES)):
            port = _EPHEMERAL_PORT_RANGE_START + offset
            if port > 65535:
                break
            if port in _EPHEMERAL_RESERVED_PORTS:
                continue
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.bind(("127.0.0.1", port))
                _EPHEMERAL_RESERVED_PORTS[port] = now
                return port
            except OSError:
                continue
        for _ in range(10):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                fallback = int(sock.getsockname()[1])
            if fallback not in _EPHEMERAL_RESERVED_PORTS:
                _EPHEMERAL_RESERVED_PORTS[fallback] = now
                return fallback
        raise RuntimeError("无法分配本地 TCP 端口")


def _is_cdp_available(cdp_url: str, timeout: float = 1.0) -> bool:
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(f"{cdp_url}/json/version", timeout=timeout) as resp:
            return 200 <= int(resp.status) < 300
    except Exception:
        return False


def _devtools_active_port(profile_dir: Path) -> int:
    try:
        first_line = (profile_dir / "DevToolsActivePort").read_text(encoding="utf-8").splitlines()[0]
        return int(first_line.strip())
    except (OSError, IndexError, ValueError):
        return 0


def _terminate_process_group(process: subprocess.Popen):
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8, check=False,
            )
        except Exception:
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=5)
        except Exception:
            pass
        return

    try:
        pgid = os.getpgid(process.pid)
    except OSError:
        pgid = None

    def _signal_group(sig):
        if pgid is None:
            return False
        try:
            os.killpg(pgid, sig)
            return True
        except OSError:
            return False

    if not _signal_group(signal.SIGTERM):
        try:
            process.terminate()
        except OSError:
            pass
    try:
        process.wait(timeout=5)
        _signal_group(signal.SIGKILL)
        return
    except subprocess.TimeoutExpired:
        pass
    if not _signal_group(signal.SIGKILL):
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass


def _stop_ephemeral_chrome(process: Optional[subprocess.Popen], profile_dir: Any):
    if process is not None:
        try:
            if process.poll() is None:
                _terminate_process_group(process)
        except Exception:
            pass
    if not profile_dir:
        return
    path = profile_dir if isinstance(profile_dir, Path) else Path(str(profile_dir))
    if not path.exists():
        return
    for attempt in range(5):
        try:
            shutil.rmtree(path)
            return
        except OSError:
            if attempt >= 4:
                shutil.rmtree(path, ignore_errors=True)
                return
            time.sleep(0.6)


def purge_orphan_profiles(max_age_seconds: int = 3600) -> int:
    base_dir = DATA_DIR / _EPHEMERAL_BASE_DIRNAME
    if not base_dir.exists():
        return 0
    cutoff = time.time() - max(60, max_age_seconds)
    deleted = 0
    for entry in base_dir.iterdir():
        try:
            if not entry.is_dir():
                continue
            if entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                if not entry.exists():
                    deleted += 1
        except Exception:
            pass
    return deleted


# ── Worker 主类 ──

class SubscribeWorker:
    def __init__(
        self,
        account: Dict[str, Any],
        config: Dict[str, Any],
        log_callback: Optional[Callable[[str, str], None]] = None,
    ):
        self.account = account
        self.config = config
        self.account_id = account.get("id", "unknown")
        self.session_key = account.get("session_key", "")
        self._log_cb = log_callback
        self._ads_profile_id = ""
        self._ads_client: Optional[AdsPowerClient] = None
        self._chrome_process: Optional[subprocess.Popen] = None
        self._chrome_profile_dir: Optional[Path] = None
        self._keep_browser = False
        self._used_card_number = ""
        self._cdp_url = ""
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    def _log(self, level: str, msg: str):
        full = f"[{self.account.get('email', '')}] {msg}"
        getattr(logger, level, logger.info)(full)
        if self._log_cb:
            self._log_cb(self.account_id, f"[{level.upper()}] {msg}")

    def run(self, auto_fill_card: bool = False) -> Dict[str, Any]:
        _clear_asyncio_loop()

        if not self.session_key:
            return {"success": False, "error": "session_key 为空"}

        cfg = self.config
        browser_provider = cfg.get("browser_provider", "adspower")

        try:
            if browser_provider == "local_chrome":
                cdp_url = self._start_local_chrome(cfg)
            else:
                cdp_url = self._start_adspower(cfg)

            self._open_and_login(cdp_url)
            self._keep_browser = True

            if not auto_fill_card:
                self._log("info", "浏览器已打开并登录，等待操作")
                return {"success": False, "error": "需要手动操作"}

            self._log("info", "浏览器已打开并登录，开始自动填卡...")
            return self._do_card_flow()

        except Exception as exc:
            self._log("error", f"失败: {exc}")
            return {"success": False, "error": str(exc)[:500]}

    def _do_card_flow(self) -> Dict[str, Any]:
        from .store import get_next_card_locked

        card = get_next_card_locked()
        if not card:
            self._log("error", "无可用卡片，请先导入卡号")
            return {"success": False, "error": "无可用卡片"}

        self._log("info", f"已选取卡片: **** {card['number'][-4:]}")

        from address_generator import generate_address
        proxy = self.config.get("proxy", "")
        address = generate_address(proxy=proxy)
        self._log("info", f"随机地址: {address['country']} {address['city']}, {address['state']} {address['postal_code']}")

        plan = self.config.get("plan", "max")
        page = self._page

        try:
            self._step_navigate_upgrade(page, plan)
            self._step_fill_card(page, card, address)
            self._step_submit_subscribe(page)
            self._used_card_number = card["number"]
            self._log("info", "订阅流程完成，请确认完成后卡号将标记为已用")
            return {"success": True, "error": ""}
        except Exception as exc:
            self._log("error", f"填卡失败: {exc}")
            return {"success": False, "error": str(exc)[:500]}

    def run_card_flow(self) -> Dict[str, Any]:
        _clear_asyncio_loop()

        self._close_playwright()

        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        browser = self._pw.chromium.connect_over_cdp(self._cdp_url)
        self._browser = browser
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        self._context = context
        page = context.pages[0] if context.pages else context.new_page()
        self._page = page

        result = self._do_card_flow()
        return {"ok": result.get("success", False), "error": result.get("error", "")}

    def _open_and_login(self, cdp_url: str):
        from playwright.sync_api import sync_playwright

        _clear_asyncio_loop()
        self._cdp_url = cdp_url
        self._pw = sync_playwright().start()
        browser = self._pw.chromium.connect_over_cdp(cdp_url)
        self._browser = browser
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        self._context = context
        page = context.pages[0] if context.pages else context.new_page()
        self._page = page

        self._step_login(context, page)

    # ── 浏览器启动 ──

    def _start_adspower(self, cfg) -> str:
        with _ADSPOWER_API_LOCK:
            return self._start_adspower_inner(cfg)

    def _adspower_api_call(self, fn, *args, retries=3, **kwargs):
        for attempt in range(retries):
            try:
                return fn(*args, **kwargs)
            except AdsPowerError as exc:
                if "too many request" in str(exc).lower() and attempt < retries - 1:
                    wait = 1.5 * (attempt + 1)
                    self._log("info", f"AdsPower 限速，等待 {wait}s 后重试...")
                    time.sleep(wait)
                    continue
                raise

    def _start_adspower_inner(self, cfg) -> str:
        self._ads_client = AdsPowerClient(
            cfg.get("adspower_api_base", "http://localhost:50325"),
            api_key=cfg.get("adspower_api_key", ""),
        )
        if not self._ads_client.health():
            raise RuntimeError("AdsPower 未启动")

        self._adspower_cleanup_my_profile()
        time.sleep(1)

        proxy = self._resolve_proxy(cfg)

        try:
            self._ads_profile_id = self._adspower_api_call(
                self._ads_client.create_profile,
                name=f"claude_{self.account_id}",
                group_id=cfg.get("adspower_group_id", "0"),
                proxy=proxy,
            )
        except AdsPowerError as exc:
            if "limit" in str(exc).lower() or "exceeds" in str(exc).lower():
                self._log("warning", "profile 数量超限，清理所有 claude_ 残留...")
                self._adspower_cleanup_all_stale()
                time.sleep(1.5)
                self._ads_profile_id = self._adspower_api_call(
                    self._ads_client.create_profile,
                    name=f"claude_{self.account_id}",
                    group_id=cfg.get("adspower_group_id", "0"),
                    proxy=proxy,
                )
            else:
                raise

        self._log("info", f"AdsPower profile: {self._ads_profile_id}")
        time.sleep(1)

        cdp_ws_url = self._adspower_api_call(self._ads_client.open_browser, self._ads_profile_id)
        self._log("info", "浏览器已启动 (AdsPower)")
        return cdp_ws_url

    def _adspower_cleanup_my_profile(self):
        try:
            profiles = self._adspower_api_call(self._ads_client.list_profiles)
            my_name = f"claude_{self.account_id}"
            stale = [
                str(p.get("user_id") or p.get("id") or "")
                for p in profiles
                if str(p.get("name") or "").lower() == my_name.lower()
            ]
            for pid in stale:
                if not pid:
                    continue
                try:
                    self._adspower_api_call(self._ads_client.close_browser, pid)
                except AdsPowerError:
                    pass
                time.sleep(1)
                try:
                    self._adspower_api_call(self._ads_client.delete_profile, pid)
                    self._log("info", f"已清理残留 profile: {pid}")
                except AdsPowerError:
                    pass
                time.sleep(1)
        except AdsPowerError as exc:
            self._log("warning", f"清理残留失败（不阻断）: {exc}")

    def _adspower_cleanup_all_stale(self):
        try:
            profiles = self._adspower_api_call(self._ads_client.list_profiles)
            stale = [
                str(p.get("user_id") or p.get("id") or "")
                for p in profiles
                if str(p.get("name") or "").lower().startswith("claude_")
            ]
            self._log("info", f"发现 {len(stale)} 个 claude_ 残留 profile")
            for pid in stale:
                if not pid:
                    continue
                try:
                    self._adspower_api_call(self._ads_client.close_browser, pid)
                except AdsPowerError:
                    pass
                time.sleep(1)
                try:
                    self._adspower_api_call(self._ads_client.delete_profile, pid)
                    self._log("info", f"超限清理 profile: {pid}")
                except AdsPowerError:
                    pass
                time.sleep(1)
        except AdsPowerError as exc:
            self._log("warning", f"超限清理失败: {exc}")

    def _resolve_proxy(self, cfg) -> str:
        proxy = cfg.get("proxy", "").strip()
        if cfg.get("vless_enabled"):
            share_link = cfg.get("vless_share_link", "").strip()
            xray_path = cfg.get("vless_xray_path", "").strip()
            if share_link and xray_path:
                from .vless_relay import ensure_vless_http_relay
                vless_url = ensure_vless_http_relay(share_link, xray_path)
                if vless_url:
                    self._log("info", f"VLESS 代理已启动: {vless_url}")
                    return vless_url
                else:
                    self._log("warning", "VLESS 启动失败，回退到普通代理")
        return proxy

    def _start_local_chrome(self, cfg) -> str:
        chrome_path = _find_chrome(cfg.get("chrome_path", ""))
        if not chrome_path:
            raise RuntimeError("未找到本地 Chrome，请在配置中指定 chrome_path")

        proxy = self._resolve_proxy(cfg)

        profile_dir = DATA_DIR / "chrome-profiles" / f"claude_{self.account_id}"
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._chrome_profile_dir = profile_dir

        for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie", "lockfile"):
            try:
                (profile_dir / lock_name).unlink(missing_ok=True)
            except OSError:
                pass

        port = _find_free_port()
        cdp_url = f"http://127.0.0.1:{port}"

        launch_args: List[str] = [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={str(profile_dir)}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--disable-features=SignInProfileCreation",
        ]
        if proxy:
            launch_args.append(f"--proxy-server={proxy}")

        popen_kwargs: Dict[str, Any] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        self._chrome_process = subprocess.Popen(launch_args, **popen_kwargs)

        deadline = time.monotonic() + _EPHEMERAL_CDP_WAIT_SECONDS
        while time.monotonic() < deadline:
            exit_code = self._chrome_process.poll()
            if exit_code is not None:
                self._chrome_process = None
                raise RuntimeError(f"Chrome 启动后立即退出 (exit={exit_code})")

            if _is_cdp_available(cdp_url, timeout=0.5):
                self._log("info", f"浏览器已启动 (本地 Chrome pid={self._chrome_process.pid} port={port})")
                return cdp_url

            active_port = _devtools_active_port(profile_dir)
            if active_port and active_port != port:
                candidate = f"http://127.0.0.1:{active_port}"
                if _is_cdp_available(candidate, timeout=0.5):
                    self._log("warning", f"Chrome 实际端口 {active_port} != 请求 {port}")
                    return candidate

            time.sleep(0.25)

        self._chrome_process = None
        raise RuntimeError(f"Chrome CDP 未就绪 (等待 {int(_EPHEMERAL_CDP_WAIT_SECONDS)}s)")

    # ── 清理 ──

    def _cleanup(self):
        self._close_playwright()

        if self._ads_client and self._ads_profile_id:
            try:
                self._ads_client.close_browser(self._ads_profile_id)
            except AdsPowerError:
                pass
            try:
                self._ads_client.delete_profile(self._ads_profile_id)
            except AdsPowerError:
                pass
            self._ads_profile_id = ""
            self._log("info", "AdsPower 已清理")

        if self._chrome_process is not None:
            try:
                if self._chrome_process.poll() is None:
                    _terminate_process_group(self._chrome_process)
            except Exception:
                pass
            self._chrome_process = None
            self._chrome_profile_dir = None
            self._log("info", "本地 Chrome 已关闭（profile 保留复用）")

    def get_session_key_from_browser(self) -> str:
        if not self._context:
            return ""
        try:
            cookies = self._context.cookies(["https://claude.ai"])
            for c in cookies:
                if c.get("name") == "sessionKey":
                    return c.get("value", "")
        except Exception:
            pass
        return ""

    def _close_playwright(self):
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    # ── 登录 ──

    def _step_login(self, context, page):
        self._log("info", "注入 cookie 登录...")
        context.add_cookies([{
            "name": "sessionKey",
            "value": self.session_key,
            "domain": ".claude.ai",
            "path": "/",
            "httpOnly": True,
            "secure": True,
            "sameSite": "Lax",
        }])
        page.goto("https://claude.ai/new", wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(2000)
        url = page.url
        if "login" in url.lower() or "sign" in url.lower():
            raise RuntimeError("sk_expired")
        try:
            has_email_input = page.evaluate("""() => {
                const el = document.querySelector('input[type="email"], input[name="email"], input[autocomplete="email"]');
                return el && el.offsetParent !== null;
            }""")
            if has_email_input:
                raise RuntimeError("sk_expired")
        except RuntimeError:
            raise
        except Exception:
            pass
        self._log("info", "登录成功")

    # ── 信用卡自动填卡流程 ──

    def _js_click(self, page, selector_js: str, label: str):
        clicked = page.evaluate(f"""() => {{
            const el = {selector_js};
            if (el) {{ el.scrollIntoView({{block: 'center'}}); el.click(); return true; }}
            return false;
        }}""")
        if not clicked:
            raise RuntimeError(f"未找到: {label}")
        self._log("info", f"[填卡] 已点击: {label}")

    def _dismiss_overlays(self, page):
        page.evaluate("""() => {
            document.querySelectorAll('[data-base-ui-inert], [aria-hidden="true"][role="presentation"]').forEach(el => {
                if (el.style) el.style.pointerEvents = 'none';
            });
            document.querySelectorAll('[data-base-ui-portal]').forEach(el => el.remove());
        }""")

    def _step_navigate_upgrade(self, page, plan: str):
        import random
        self._log("info", f"[填卡] 导航到升级页面，计划: {plan}")

        upgrade_url = f"https://claude.ai/upgrade/{plan}"
        page.goto(upgrade_url, wait_until="domcontentloaded", timeout=30000)
        self._log("info", f"[填卡] 已导航到 {upgrade_url}")
        page.wait_for_timeout(random.randint(3000, 5000))

        # 检测页面错误提示
        error_text = page.evaluate("""() => {
            const body = document.body.innerText || '';
            if (body.includes('出了点问题') || body.includes('something went wrong') || body.includes('无法使用'))
                return body.substring(0, 200);
            return '';
        }""")
        if error_text:
            raise RuntimeError(f"页面异常: {error_text[:100]}")

        plan_option = "20x" if plan == "max" else "Pro"
        import time as _time
        deadline = _time.time() + 20
        clicked = ""
        while _time.time() < deadline:
            clicked = page.evaluate(f"""() => {{
                const btns = document.querySelectorAll('button[type="button"]');
                for (const btn of btns) {{
                    const text = btn.innerText || btn.textContent || '';
                    if (text.includes('{plan_option}') && btn.getAttribute('aria-pressed') !== 'true') {{
                        btn.scrollIntoView({{block: 'center'}});
                        btn.click();
                        return text.replace(/\\s+/g, ' ').trim().substring(0, 60);
                    }}
                }}
                return '';
            }}""")
            if clicked:
                break
            page.wait_for_timeout(1000)

        if clicked:
            self._log("info", f"[填卡] 已选择套餐: {clicked}")
        else:
            all_btns = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('button[type="button"]'))
                    .map(b => (b.innerText || b.textContent || '').replace(/\\s+/g, ' ').trim().substring(0, 80))
                    .filter(t => t.length > 0);
            }""")
            self._log("error", f"[填卡] 页面所有按钮: {all_btns}")
            raise RuntimeError(f"未找到 '{plan_option}' 套餐按钮，无法继续")

        page.wait_for_timeout(random.randint(3000, 5000))

    def _find_stripe_frame(self, page, keyword: str, timeout: int = 20000, exclude: str = ""):
        import time as _time
        deadline = _time.time() + timeout / 1000
        while _time.time() < deadline:
            for frame in page.frames:
                url = frame.url or ""
                if keyword in url and (not exclude or exclude not in url):
                    return frame
            page.wait_for_timeout(500)
        raise RuntimeError(f"未找到 Stripe iframe (keyword={keyword})")

    def _step_fill_card(self, page, card: Dict[str, Any], address: Dict[str, str]):
        import random
        self._log("info", "[填卡] 开始填写支付信息...")
        page.wait_for_timeout(random.randint(2000, 3000))

        number = card.get("number", "")
        expiry = card.get("expiry", "")
        cvv = card.get("cvv", "")

        # 有效期转 MMYY
        exp_digits = expiry.replace("/", "").replace("-", "").strip()
        if len(exp_digits) == 6:
            exp_digits = exp_digits[:2] + exp_digits[4:]

        def _fill_field(frame, field_id, value, label, use_type=False):
            try:
                el = frame.locator(field_id).first
                el.wait_for(state="visible", timeout=8000)
                el.click()
                page.wait_for_timeout(random.randint(150, 300))
                if use_type:
                    el.press_sequentially(value, delay=random.randint(30, 60))
                else:
                    el.fill(value)
                el.press("Escape")
                self._log("info", f"[填卡] {label} -> {value}")
                page.wait_for_timeout(random.randint(300, 600))
            except Exception as exc:
                self._log("warning", f"[填卡] {label} 填写失败: {exc}")

        # ── 1. 账单地址（address iframe 先出现） ──
        self._log("info", "[填卡] 填写账单地址...")
        addr_frame = self._find_stripe_frame(page, "elements-inner-address", exclude="autocomplete")

        _fill_field(addr_frame, "#billingAddress-nameInput", address["name"], "Full name")

        target_country = address.get("country", "US")
        country_select = addr_frame.locator("#billingAddress-countryInput").first
        if country_select.count() > 0:
            try:
                country_select.click()
                page.wait_for_timeout(random.randint(200, 400))
                country_select.select_option(target_country)
                self._log("info", f"[填卡] Country -> {target_country}")
                page.wait_for_timeout(random.randint(2000, 3000))
                addr_frame = self._find_stripe_frame(page, "elements-inner-address", exclude="autocomplete")
            except Exception as exc:
                self._log("warning", f"[填卡] Country 设置失败: {exc}")

        _fill_field(addr_frame, "#billingAddress-addressLine1Input", address["line1"], "Address", use_type=True)
        _fill_field(addr_frame, "#billingAddress-localityInput", address["city"], "City")

        if address.get("state"):
            state_el = addr_frame.locator("#billingAddress-administrativeAreaInput").first
            if state_el.count() > 0:
                try:
                    state_el.click()
                    page.wait_for_timeout(random.randint(200, 400))
                    try:
                        state_el.select_option(address["state"])
                    except Exception:
                        state_el.fill(address["state"])
                    self._log("info", f"[填卡] State -> {address['state']}")
                    page.wait_for_timeout(random.randint(300, 600))
                except Exception as exc:
                    self._log("warning", f"[填卡] State 填写失败: {exc}")

        _fill_field(addr_frame, "#billingAddress-postalCodeInput", address["postal_code"], "ZIP")
        self._log("info", "[填卡] 账单地址填写完成")

        # ── 2. 卡号信息（payment iframe） ──
        self._log("info", "[填卡] 填写卡号...")
        page.wait_for_timeout(random.randint(1000, 2000))
        pay_frame = self._find_stripe_frame(page, "elements-inner-payment")

        # 选择 Card tab（如果有多种支付方式）
        for tab_text in ["Card", "card"]:
            tab = pay_frame.locator(f"text={tab_text}").first
            if tab.count() > 0:
                try:
                    tab.click()
                    self._log("info", f"[填卡] 已选择 Card 支付方式")
                    page.wait_for_timeout(random.randint(2000, 3000))
                except Exception:
                    pass
                break

        CARD_NUMBER_SELS = [
            '#cardNumber', 'input[name="cardnumber"]', 'input[name="cardNumber"]',
            'input[name="number"]', 'input[autocomplete="cc-number"]',
            'input[data-elements-stable-field-name="cardNumber"]',
            'input[aria-label*="Card number"]', 'input[placeholder*="1234"]',
        ]
        CARD_EXPIRY_SELS = [
            '#cardExpiry', 'input[name="cardExpiry"]', 'input[name="exp-date"]',
            'input[autocomplete="cc-exp"]',
            'input[data-elements-stable-field-name="cardExpiry"]',
            'input[aria-label*="Expiration"]', 'input[placeholder*="MM"]',
        ]
        CARD_CVC_SELS = [
            '#cardCvc', 'input[name="cardCvc"]', 'input[name="cvc"]',
            'input[autocomplete="cc-csc"]',
            'input[data-elements-stable-field-name="cardCvc"]',
            'input[aria-label*="CVC"]', 'input[placeholder*="CVC"]',
        ]

        def _find_input(frame, selectors, label, timeout=15000):
            import time as _time
            deadline = _time.time() + timeout / 1000
            while _time.time() < deadline:
                for sel in selectors:
                    el = frame.locator(sel).first
                    if el.count() > 0 and el.is_visible():
                        self._log("info", f"[填卡] 找到 {label}: {sel}")
                        return el
                page.wait_for_timeout(500)
            raise RuntimeError(f"未找到 {label} 输入框")

        card_input = _find_input(pay_frame, CARD_NUMBER_SELS, "卡号")
        page.wait_for_timeout(random.randint(300, 600))
        card_input.click()
        page.wait_for_timeout(random.randint(200, 400))
        card_input.press_sequentially(number, delay=random.randint(50, 90))
        self._log("info", f"[填卡] 卡号已输入: **** {number[-4:]}")
        page.wait_for_timeout(random.randint(400, 800))

        exp_input = _find_input(pay_frame, CARD_EXPIRY_SELS, "有效期")
        exp_input.click()
        page.wait_for_timeout(random.randint(200, 400))
        exp_input.press_sequentially(exp_digits, delay=random.randint(50, 90))
        self._log("info", f"[填卡] 有效期已输入: {expiry}")
        page.wait_for_timeout(random.randint(400, 800))

        cvc_input = _find_input(pay_frame, CARD_CVC_SELS, "CVC")
        cvc_input.click()
        page.wait_for_timeout(random.randint(200, 400))
        cvc_input.press_sequentially(cvv, delay=random.randint(50, 90))
        self._log("info", "[填卡] CVV 已输入")
        page.wait_for_timeout(random.randint(800, 1500))

        self._log("info", "[填卡] 支付信息填写完成")

    def _step_submit_subscribe(self, page):
        import random
        self._log("info", "[填卡] 准备提交订阅...")
        page.wait_for_timeout(random.randint(1000, 2000))

        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(random.randint(500, 800))

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
            self._log("info", "[填卡] 协议已勾选")
        page.wait_for_timeout(random.randint(500, 1000))

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
            self._log("info", "[填卡] 已点击 Subscribe!")
            page.wait_for_timeout(random.randint(5000, 8000))
        else:
            self._log("warning", "[填卡] 未找到 Subscribe 按钮")
