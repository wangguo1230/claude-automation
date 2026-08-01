"""并发任务管理器。"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .store import load_accounts, load_config, save_accounts, update_account
from .worker import SubscribeWorker


class TaskManager:
    def __init__(self):
        self._executor: Optional[ThreadPoolExecutor] = None
        self._futures: Dict[str, Any] = {}
        self._logs: Dict[str, List[str]] = defaultdict(list)
        self._running = False
        self._lock = threading.Lock()
        self._workers: Dict[str, SubscribeWorker] = {}

    @property
    def is_running(self) -> bool:
        return self._running

    def get_logs(self, account_id: str, since: int = 0) -> List[str]:
        logs = self._logs.get(account_id, [])
        return logs[since:]

    def get_all_status(self) -> List[Dict[str, Any]]:
        accounts = load_accounts()
        result = []
        for acc in accounts:
            if acc.get("disabled"):
                continue
            aid = acc.get("id", "")
            logs = self._logs.get(aid, [])
            worker = self._workers.get(aid)
            result.append({
                "id": aid,
                "email": acc.get("email", ""),
                "status": acc.get("status", "idle"),
                "last_error": acc.get("last_error", ""),
                "last_run_at": acc.get("last_run_at"),
                "log_count": len(logs),
                "last_log": logs[-1] if logs else "",
                "has_browser": worker is not None and worker._page is not None,
            })
        return result

    def start(self, account_ids: Optional[List[str]] = None):
        config = load_config()
        max_concurrent = max(1, int(config.get("max_concurrent", 3)))

        accounts = load_accounts()
        if account_ids:
            targets = [a for a in accounts if a.get("id") in account_ids and a.get("id") not in self._futures and not a.get("disabled")]
        else:
            targets = [a for a in accounts if a.get("status") in ("idle", "failed") and a.get("id") not in self._futures and not a.get("disabled")]

        if not targets:
            return {"started": 0, "error": "没有可运行的账号"}

        if not self._executor or self._executor._shutdown:
            self._executor = ThreadPoolExecutor(max_workers=max_concurrent)

        self._running = True

        for acc in targets:
            aid = acc["id"]
            self._logs[aid] = []
            update_account(aid, {"status": "running", "last_error": ""})
            future = self._executor.submit(self._run_one, acc, config, False)
            self._futures[aid] = future

        return {"started": len(targets)}

    def start_auto(self, account_ids: Optional[List[str]] = None):
        config = load_config()
        max_concurrent = max(1, int(config.get("max_concurrent", 3)))

        accounts = load_accounts()
        if account_ids:
            targets = [a for a in accounts if a.get("id") in account_ids and a.get("id") not in self._futures and not a.get("disabled")]
        else:
            targets = [a for a in accounts if a.get("status") in ("idle", "failed") and a.get("id") not in self._futures and not a.get("disabled")]

        if not targets:
            return {"started": 0, "error": "没有可运行的账号"}

        if not self._executor or self._executor._shutdown:
            self._executor = ThreadPoolExecutor(max_workers=max_concurrent)

        self._running = True

        for acc in targets:
            aid = acc["id"]
            self._logs[aid] = []
            update_account(aid, {"status": "running", "last_error": ""})
            future = self._executor.submit(self._run_one, acc, config, True)
            self._futures[aid] = future

        return {"started": len(targets)}

    def _log_callback(self, account_id: str, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._logs[account_id].append(f"{ts} {message}")

    def _run_one(self, account: Dict[str, Any], config: Dict[str, Any], auto_fill_card: bool = False):
        aid = account["id"]
        try:
            worker = SubscribeWorker(account, config, log_callback=self._log_callback)
            self._workers[aid] = worker
            result = worker.run(auto_fill_card=auto_fill_card)

            now = datetime.now(timezone.utc).isoformat()
            if result.get("success"):
                status = "waiting" if worker._keep_browser else "success"
                update_account(aid, {"status": status, "last_error": "", "last_run_at": now})
            else:
                error_msg = result.get("error", "")
                if error_msg == "sk_expired":
                    update_account(aid, {"status": "failed", "last_error": "sessionKey 已失效", "last_run_at": now})
                    self._log_callback(aid, "[ERROR] sessionKey 已失效，跳过")
                    try:
                        worker._cleanup()
                    except Exception:
                        pass
                    self._workers.pop(aid, None)
                else:
                    status = "waiting" if worker._keep_browser else "failed"
                    update_account(aid, {"status": status, "last_error": error_msg, "last_run_at": now})
        except Exception as exc:
            err = str(exc)[:500]
            if "sk_expired" in err:
                now = datetime.now(timezone.utc).isoformat()
                update_account(aid, {"status": "failed", "last_error": "sessionKey 已失效", "last_run_at": now})
                self._log_callback(aid, "[ERROR] sessionKey 已失效，跳过")
                worker = self._workers.get(aid)
                if worker:
                    try:
                        worker._cleanup()
                    except Exception:
                        pass
                    self._workers.pop(aid, None)
            else:
                update_account(aid, {"status": "failed", "last_error": err})

        with self._lock:
            self._futures.pop(aid, None)
            if not self._futures:
                self._running = False

    def run_card_flow(self, account_id: str) -> Dict[str, Any]:
        worker = self._workers.get(account_id)
        if not worker:
            return {"ok": False, "error": "未找到该账号的浏览器实例，请先打开浏览器"}
        if not worker._page:
            return {"ok": False, "error": "浏览器页面已关闭，请重新打开"}
        from concurrent.futures import ThreadPoolExecutor, Future
        with ThreadPoolExecutor(max_workers=1) as pool:
            future: Future = pool.submit(worker.run_card_flow)
            return future.result(timeout=120)

    def open_browser(self, account_id: str) -> Dict[str, Any]:
        worker = self._workers.get(account_id)
        if not worker:
            return {"ok": False, "error": "未找到该账号的浏览器实例"}
        if not worker._page:
            return {"ok": False, "error": "浏览器页面已关闭"}
        try:
            worker._page.bring_to_front()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": f"聚焦浏览器失败: {exc}"}

    def confirm_and_close(self, account_id: str) -> Dict[str, Any]:
        """人工确认完成：标记卡号已用 → 获取最新 cookie → 更新 session_key → 关闭浏览器。"""
        worker = self._workers.get(account_id)

        new_sk = ""
        if worker:
            if worker._used_card_number:
                from .store import mark_card_used
                mark_card_used(worker._used_card_number)
                self._log_callback(account_id, f"[INFO] 卡号已标记为已用: **** {worker._used_card_number[-4:]}")
                worker._used_card_number = ""

            try:
                new_sk = worker.get_session_key_from_browser()
            except Exception as exc:
                self._log_callback(account_id, f"[WARNING] 获取 cookie 失败: {exc}")

            try:
                worker._cleanup()
            except Exception:
                pass
            self._workers.pop(account_id, None)

        now = datetime.now(timezone.utc).isoformat()
        fields = {"status": "success", "last_error": "", "last_run_at": now}
        if new_sk:
            fields["session_key"] = new_sk
            self._log_callback(account_id, f"[INFO] 已更新 sessionKey: ...{new_sk[-20:]}")

        update_account(account_id, fields)
        self._log_callback(account_id, "[INFO] 任务标记为成功")

        return {"ok": True, "new_session_key": bool(new_sk)}

    def stop_all(self):
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

        accounts = load_accounts()
        for acc in accounts:
            if acc.get("status") == "running":
                acc["status"] = "idle"
                acc["last_error"] = "手动停止"
        save_accounts(accounts)

        self._futures.clear()
        self._running = False
        return {"stopped": True}


task_manager = TaskManager()
