"""内置 VLESS 代理：把 vless:// 分享链接拉起为本地 HTTP 代理入口。

通过本机 xray 二进制把 vless:// 链接转为 http://127.0.0.1:PORT，
供 Chrome --proxy-server 直接使用。
"""

from __future__ import annotations

import atexit
import base64
import json
import logging
import os
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse

logger = logging.getLogger(__name__)

_READY_TIMEOUT_S = 6.0

_RELAYS: dict[tuple[str, str], "_VlessRelay"] = {}
_LOCK = threading.Lock()
_LAST_START_ERROR: str = ""


def parse_vless_link(share_link: str) -> Optional[dict[str, Any]]:
    raw = str(share_link or "").strip()
    if not raw.lower().startswith("vless://"):
        return None
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    uuid = unquote(parsed.username or "")
    host = parsed.hostname or ""
    port = int(parsed.port or 0)
    if not uuid or not host or port <= 0:
        return None
    q = {k: (v[0] if v else "") for k, v in parse_qs(parsed.query).items()}
    return {
        "uuid": uuid,
        "host": host,
        "port": port,
        "encryption": q.get("encryption", "none") or "none",
        "flow": q.get("flow", ""),
        "network": (q.get("type", "tcp") or "tcp").lower(),
        "security": (q.get("security", "none") or "none").lower(),
        "sni": q.get("sni", "") or q.get("peer", ""),
        "fp": q.get("fp", ""),
        "pbk": q.get("pbk", ""),
        "sid": q.get("sid", ""),
        "spx": q.get("spx", "") or "/",
        "alpn": q.get("alpn", ""),
        "host_header": q.get("host", ""),
        "path": q.get("path", "") or "/",
        "service_name": q.get("serviceName", ""),
        "header_type": (q.get("headerType", "none") or "none").lower(),
    }


def build_xray_config(node: dict[str, Any], http_port: int) -> dict[str, Any]:
    user: dict[str, Any] = {"id": node["uuid"], "encryption": node.get("encryption", "none") or "none"}
    if node.get("flow"):
        user["flow"] = node["flow"]

    network = node.get("network", "tcp") or "tcp"
    security = node.get("security", "none") or "none"
    stream: dict[str, Any] = {"network": network, "security": security}

    if security == "reality":
        stream["realitySettings"] = {
            "serverName": node.get("sni", ""),
            "fingerprint": node.get("fp", "") or "chrome",
            "publicKey": node.get("pbk", ""),
            "shortId": node.get("sid", ""),
            "spiderX": node.get("spx", "") or "/",
        }
    elif security == "tls":
        tls: dict[str, Any] = {
            "serverName": node.get("sni", ""),
            "allowInsecure": False,
        }
        if node.get("fp"):
            tls["fingerprint"] = node["fp"]
        if node.get("alpn"):
            tls["alpn"] = [a for a in node["alpn"].split(",") if a]
        stream["tlsSettings"] = tls

    if network == "ws":
        ws: dict[str, Any] = {"path": node.get("path", "/") or "/"}
        if node.get("host_header"):
            ws["headers"] = {"Host": node["host_header"]}
        stream["wsSettings"] = ws
    elif network == "grpc":
        stream["grpcSettings"] = {"serviceName": node.get("service_name", "") or ""}
    elif network in ("h2", "http"):
        h2: dict[str, Any] = {"path": node.get("path", "/") or "/"}
        if node.get("host_header"):
            h2["host"] = [h for h in node["host_header"].split(",") if h]
        stream["httpSettings"] = h2

    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "http-in",
                "listen": "127.0.0.1",
                "port": int(http_port),
                "protocol": "http",
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
            }
        ],
        "outbounds": [
            {
                "tag": "proxy",
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {"address": node["host"], "port": int(node["port"]), "users": [user]}
                    ]
                },
                "streamSettings": stream,
            }
        ],
    }


def validate_node(node: dict[str, Any]) -> str:
    if (node.get("security") or "") == "reality":
        pbk = str(node.get("pbk", "") or "")
        try:
            raw = base64.urlsafe_b64decode(pbk + "=" * (-len(pbk) % 4))
        except Exception:
            raw = b""
        if len(raw) != 32:
            return f"reality 公钥(pbk)非法：应为 43 字符/32 字节，当前 {len(pbk)} 字符/{len(raw)} 字节"
        if not str(node.get("sni", "") or "").strip():
            return "reality 缺少 sni，请确认分享链接含 sni= 参数"
    return ""


def _free_local_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


def ensure_vless_http_relay(share_link: str, xray_path: str) -> str:
    link = str(share_link or "").strip()
    xpath = str(xray_path or "").strip()
    if not link or not xpath:
        return ""
    key = (xpath, link)
    with _LOCK:
        relay = _RELAYS.get(key)
        if relay is None or not relay.is_alive():
            relay = _VlessRelay(link, xpath)
            relay.start()
            if relay.is_alive():
                _RELAYS[key] = relay
            else:
                return ""
        return relay.local_url()


class _VlessRelay:
    def __init__(self, share_link: str, xray_path: str) -> None:
        self.share_link = share_link
        self.xray_path = xray_path
        self._proc: Optional[subprocess.Popen] = None
        self._port: Optional[int] = None
        self._config_path: str = ""
        self._stderr_path: str = ""
        self.start_error: str = ""

    def is_alive(self) -> bool:
        return bool(self._proc and self._proc.poll() is None and self._port)

    def local_url(self) -> str:
        return f"http://127.0.0.1:{self._port}" if self._port else ""

    def _fail(self, reason: str) -> None:
        global _LAST_START_ERROR
        _LAST_START_ERROR = reason
        self.start_error = reason
        logger.warning("内置 vless 启动失败：%s", reason)
        self.stop()

    def _read_stderr_tail(self) -> str:
        if not self._stderr_path:
            return ""
        try:
            with open(self._stderr_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            return ""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for ln in reversed(lines):
            low = ln.lower()
            if "failed to start" in low or "failed to build" in low or "> infra/conf" in low:
                return ln[-360:]
        useful = [
            ln for ln in lines
            if not ln.startswith("Xray ") and "anti-censorship" not in ln
            and "[Info]" not in ln and "Reading config" not in ln
        ]
        return " | ".join((useful or lines)[-3:])[:360]

    def start(self) -> None:
        global _LAST_START_ERROR
        _LAST_START_ERROR = ""
        node = parse_vless_link(self.share_link)
        if not node:
            self._fail("vless 分享链接解析不出有效节点")
            return
        node_error = validate_node(node)
        if node_error:
            self._fail(node_error)
            return
        if not os.path.exists(self.xray_path):
            self._fail(f"xray 路径不存在：{self.xray_path}")
            return
        port = _free_local_port()
        config = build_xray_config(node, port)
        try:
            fd, cfg_path = tempfile.mkstemp(prefix="vless-", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config, f)
            self._config_path = cfg_path
            err_fd, self._stderr_path = tempfile.mkstemp(prefix="vless-err-", suffix=".log")
            os.close(err_fd)
        except OSError as exc:
            self._fail(f"写临时配置出错 {str(exc)[:160]}")
            return
        try:
            stderr_fh = open(self._stderr_path, "wb")
        except OSError:
            stderr_fh = None
        try:
            self._proc = subprocess.Popen(
                [self.xray_path, "run", "-c", self._config_path],
                stdout=(stderr_fh or subprocess.DEVNULL),
                stderr=subprocess.STDOUT,
            )
        except OSError as exc:
            self._fail(f"拉起 xray 出错：{str(exc)[:160]}")
            if stderr_fh:
                stderr_fh.close()
            return
        if stderr_fh:
            stderr_fh.close()
        deadline = time.monotonic() + _READY_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                tail = self._read_stderr_tail()
                self._fail(f"xray 进程提前退出：{tail}" if tail else "xray 进程提前退出")
                return
            if self._port_connectable(port):
                self._port = port
                logger.info("内置 vless 已启动 http://127.0.0.1:%s", port)
                return
            time.sleep(0.2)
        self._fail(f"本地入口 {_READY_TIMEOUT_S}s 内未就绪")

    @staticmethod
    def _port_connectable(port: int) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False
        finally:
            s.close()

    def _cleanup_config(self) -> None:
        for attr in ("_config_path", "_stderr_path"):
            path = getattr(self, attr, "")
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
                setattr(self, attr, "")

    def stop(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except OSError:
                pass
        self._port = None
        self._cleanup_config()


def _proxy_get_text(local_url: str, target: str, timeout_s: float) -> tuple[int, str]:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": local_url, "https": local_url})
    )
    req = urllib.request.Request(target, headers={"User-Agent": "Mozilla/5.0"})
    resp = opener.open(req, timeout=timeout_s)
    try:
        return int(getattr(resp, "status", 0) or 0), resp.read(4096).decode("utf-8", "replace")
    finally:
        resp.close()


def probe_vless(share_link: str, xray_path: str, timeout_s: float = 12.0) -> dict[str, Any]:
    node = parse_vless_link(share_link)
    if not node:
        return {"ok": False, "message": "vless 分享链接解析失败：请确认是 vless:// 开头且含 uuid@host:port"}
    if not os.path.exists(str(xray_path or "").strip()):
        return {"ok": False, "message": f"xray 路径不存在：{xray_path}"}
    url = ensure_vless_http_relay(share_link, xray_path)
    if not url:
        detail = (_LAST_START_ERROR or "").strip()
        return {
            "ok": False,
            "message": f"内置 xray 启动失败：{detail}" if detail else "内置 xray 启动失败",
        }
    result: dict[str, Any] = {
        "ok": True,
        "local_url": url,
        "node": {"host": node["host"], "port": node["port"], "network": node["network"], "security": node["security"]},
    }
    try:
        _, body = _proxy_get_text(url, "https://ipinfo.io/json", timeout_s)
        info = json.loads(body)
        result["exit_ip"] = str(info.get("ip", "") or "")
        result["exit_country"] = str(info.get("country", "") or "")
        result["exit_org"] = str(info.get("org", "") or "")
    except Exception as exc:
        result["exit_ip"] = ""
        result["exit_error"] = str(exc)[:120]
    try:
        _proxy_get_text(url, "https://claude.ai/", timeout_s)
        result["claude_reachable"] = True
    except urllib.error.HTTPError:
        result["claude_reachable"] = True
    except Exception:
        result["claude_reachable"] = False
    exit_desc = f"{result.get('exit_ip', '') or '?'} {result.get('exit_country', '')}".strip()
    if result.get("claude_reachable"):
        result["message"] = f"连通正常 - 出口 {exit_desc}，claude.ai 可达"
    else:
        result["message"] = f"xray 已起、出口 {exit_desc}，但 claude.ai 不可达，可重试或换节点"
    return result


def get_relay_status(share_link: str, xray_path: str) -> dict[str, Any]:
    link = str(share_link or "").strip()
    xpath = str(xray_path or "").strip()
    if not link or not xpath:
        return {"running": False, "local_url": "", "message": "未配置"}
    key = (xpath, link)
    with _LOCK:
        relay = _RELAYS.get(key)
    if relay is None:
        return {"running": False, "local_url": "", "message": "未启动"}
    alive = relay.is_alive()
    return {
        "running": alive,
        "local_url": relay.local_url() if alive else "",
        "message": "运行中" if alive else (relay.start_error or "已停止"),
    }


@atexit.register
def _shutdown_all_vless_relays() -> None:
    with _LOCK:
        relays = list(_RELAYS.values())
        _RELAYS.clear()
    for relay in relays:
        relay.stop()
