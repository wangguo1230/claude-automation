"""AdsPower 指纹浏览器 Local API 客户端。

参考 gpt_auto_cdk 项目的 fingerprint_browser.py，简化为仅保留登录场景所需的功能：
创建 profile、启动浏览器拿 CDP 端点、关闭浏览器、删除 profile。

Local API 默认端口 http://localhost:50325。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "http://localhost:50325"
_API_TIMEOUT = 30.0
_START_RETRY_MAX = 12
_START_RETRY_INTERVAL = 5.0
_RETRYABLE_KEYWORDS = ("updating", "waiting for download", "downloading")


class AdsPowerError(RuntimeError):
    pass


class AdsPowerClient:
    def __init__(self, api_base: str = DEFAULT_API_BASE, api_key: str = "") -> None:
        self.api_base = (api_base or DEFAULT_API_BASE).strip().rstrip("/") or DEFAULT_API_BASE
        self.api_key = (api_key or "").strip()

    def _request(self, method: str, path: str, payload: Any = None) -> Dict[str, Any]:
        url = f"{self.api_base}{path}"
        headers: Dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        if method == "GET":
            if payload:
                qs = "&".join(f"{k}={v}" for k, v in payload.items() if v is not None)
                if qs:
                    url = f"{url}?{qs}"
            req = Request(url, headers=headers, method="GET")
        else:
            body = json.dumps(payload or {}).encode("utf-8")
            headers["Content-Type"] = "application/json"
            req = Request(url, data=body, headers=headers, method="POST")

        try:
            with urlopen(req, timeout=_API_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except URLError as exc:
            raise AdsPowerError(
                f"连接 AdsPower API 失败（{self.api_base}）：{getattr(exc, 'reason', exc)}；"
                "请确认 AdsPower 客户端已启动且 Local API 端口正确"
            ) from exc
        except OSError as exc:
            raise AdsPowerError(f"调用 AdsPower API 异常：{str(exc)[:200]}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AdsPowerError(f"AdsPower API 返回非 JSON：{raw[:200]}") from exc

        if data.get("code") != 0:
            raise AdsPowerError(f"AdsPower API {path} 失败：{str(data.get('msg') or data)[:200]}")
        return dict(data.get("data") or {})

    def health(self) -> bool:
        try:
            self._request("GET", "/status")
            return True
        except AdsPowerError:
            return False

    def list_profiles(self, page: int = 1, page_size: int = 100) -> list[Dict[str, Any]]:
        data = self._request("GET", "/api/v1/user/list", {"page": page, "page_size": page_size})
        return [item for item in (data.get("list") or []) if isinstance(item, dict)]

    def create_profile(self, *, name: str = "claude_login", group_id: str = "0", proxy: str = "") -> str:
        fingerprint_config: Dict[str, Any] = {
            "automatic_timezone": "1",
            "language": ["en-US", "en"],
            "flash": "block",
            "webrtc": "proxy",
            "browser_kernel_config": {"version": "ua_auto", "type": "chrome"},
            "random_ua": {
                "ua_browser": ["chrome"],
                "ua_system_version": ["Windows 10", "Windows 11", "Mac OS X 13"],
            },
        }
        payload: Dict[str, Any] = {
            "name": name,
            "group_id": group_id or "0",
            "fingerprint_config": fingerprint_config,
        }
        proxy_cfg = _parse_proxy(proxy)
        if proxy_cfg:
            payload["user_proxy_config"] = proxy_cfg
        else:
            payload["user_proxy_config"] = {"proxy_soft": "no_proxy", "proxy_type": "noproxy"}

        data = self._request("POST", "/api/v1/user/create", payload)
        profile_id = str(data.get("id") or "").strip()
        if not profile_id:
            raise AdsPowerError("AdsPower 创建 profile 成功但未返回 id")
        return profile_id

    def open_browser(self, profile_id: str) -> str:
        """启动浏览器，返回 CDP WebSocket URL。遇到内核更新自动重试。"""
        last_err = ""
        for attempt in range(1, _START_RETRY_MAX + 1):
            try:
                data = self._request("GET", "/api/v1/browser/start", {
                    "user_id": profile_id, "open_tabs": "1", "ip_tab": "0",
                })
            except AdsPowerError as exc:
                msg = str(exc).lower()
                if any(kw in msg for kw in _RETRYABLE_KEYWORDS):
                    last_err = str(exc)
                    logger.info("AdsPower 内核更新中，等待重试 (%d/%d)", attempt, _START_RETRY_MAX)
                    time.sleep(_START_RETRY_INTERVAL)
                    continue
                raise
            ws_info = data.get("ws") or {}
            puppeteer_ws = str(ws_info.get("puppeteer") or "").strip()
            if not puppeteer_ws:
                raise AdsPowerError("AdsPower 启动浏览器成功但未返回 CDP(puppeteer) 端点")
            return puppeteer_ws
        raise AdsPowerError(f"AdsPower 启动浏览器重试 {_START_RETRY_MAX} 次仍失败：{last_err[:300]}")

    def close_browser(self, profile_id: str) -> None:
        self._request("GET", "/api/v1/browser/stop", {"user_id": profile_id})

    def delete_profile(self, profile_id: str) -> None:
        self._request("POST", "/api/v1/user/delete", {"user_ids": [profile_id]})


def _parse_proxy(proxy: str) -> Optional[Dict[str, Any]]:
    text = (proxy or "").strip()
    if not text:
        return None
    if "://" not in text:
        text = "http://" + text
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    host = parts.hostname or ""
    port = parts.port
    if not host or not port:
        return None
    scheme = (parts.scheme or "http").lower()
    proxy_type = {"http": "http", "https": "https", "socks5": "socks5"}.get(scheme, "http")
    cfg: Dict[str, Any] = {
        "proxy_soft": "other",
        "proxy_type": proxy_type,
        "proxy_host": host,
        "proxy_port": str(port),
    }
    if parts.username:
        cfg["proxy_user"] = parts.username
    if parts.password:
        cfg["proxy_password"] = parts.password
    return cfg
