"""并发任务管理器 — 多实例安全。"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .store import (
    load_accounts, load_config, save_accounts, update_account,
    claim_account, release_account, release_instance_accounts,
    append_task_log, get_task_logs, clear_task_logs,
    mark_card_used,
)
from .worker import SubscribeWorker


class TaskManager:
    def __init__(self):
        self.instance_id = str(uuid.uuid4())[:8]
        self._executor: Optional[ThreadPoolExecutor] = None
        self._futures: Dict[str, Any] = {}
        self._running = False
        self._lock = threading.Lock()
        self._workers: Dict[str, SubscribeWorker] = {}

    def on_startup(self):
        release_instance_accounts(self.instance_id)

    @property
    def is_running(self) -> bool:
        return self._running

    def _log(self, account_id: str, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        append_task_log(account_id, self.instance_id, f"{ts} {message}")

    def get_logs(self, account_id: str, since_id: int = 0) -> List[Dict[str, Any]]:
        return get_task_logs(account_id, since_id)

    def get_all_status(self) -> List[Dict[str, Any]]:
        accounts = load_accounts()
        result = []
        for acc in accounts:
            if acc.get("disabled"):
                continue
            aid = acc.get("id", "")
            worker = self._workers.get(aid)
            logs = get_task_logs(aid, 0)
            result.append({
                "id": aid,
                "email": acc.get("email", ""),
                "status": acc.get("status", "idle"),
                "last_error": acc.get("last_error", ""),
                "last_run_at": acc.get("last_run_at"),
                "instance_id": acc.get("instance_id", ""),
                "log_count": len(logs),
                "last_log": logs[-1]["message"] if logs else "",
                "has_browser": worker is not None and worker._page is not None,
            })
        return result

    def start(self, account_ids: Optional[List[str]] = None):
        return self._start_internal(account_ids, auto_fill_card=False)

    def start_auto(self, account_ids: Optional[List[str]] = None):
        return self._start_internal(account_ids, auto_fill_card=True)

    def _start_internal(self, account_ids: Optional[List[str]], auto_fill_card: bool):
        config = load_config()
        max_concurrent = max(1, int(config.get("max_concurrent", 3)))

        accounts = load_accounts()
        if account_ids:
            targets = [
                a for a in accounts
                if a.get("id") in account_ids
                and a.get("id") not in self._futures
                and not a.get("disabled")
                and (not a.get("instance_id") or a.get("instance_id") == self.instance_id)
            ]
        else:
            targets = [
                a for a in accounts
                if a.get("status") in ("idle", "failed")
                and a.get("id") not in self._futures
                and not a.get("disabled")
                and not a.get("instance_id")
            ]

        if not targets:
            return {"started": 0, "error": "没有可运行的账号"}

        if not self._executor or self._executor._shutdown:
            self._executor = ThreadPoolExecutor(max_workers=max_concurrent)

        self._running = True
        started = 0
        for acc in targets:
            aid = acc["id"]
            if not claim_account(aid, self.instance_id):
                self._log(aid, "[WARNING] 账号被其他实例占用，跳过")
                continue
            clear_task_logs(aid)
            update_account(aid, {"status": "running", "last_error": ""})
            future = self._executor.submit(self._run_one, acc, config, auto_fill_card)
            self._futures[aid] = future
            started += 1

        return {"started": started}

    def _run_one(self, account: Dict[str, Any], config: Dict[str, Any], auto_fill_card: bool = False):
        aid = account["id"]
        try:
            worker = SubscribeWorker(account, config, log_callback=self._log)
            worker._instance_id = self.instance_id
            self._workers[aid] = worker
            result = worker.run(auto_fill_card=auto_fill_card)

            now = datetime.now(timezone.utc).isoformat()
            if result.get("success"):
                status = "waiting" if worker._keep_browser else "success"
                fields = {"status": status, "last_error": "", "last_run_at": now}
                if worker._used_card_number:
                    fields["used_card_number"] = worker._used_card_number
                update_account(aid, fields)
            else:
                error_msg = result.get("error", "")
                if error_msg == "sk_expired":
                    update_account(aid, {"status": "failed", "last_error": "sessionKey 已失效", "last_run_at": now})
                    self._log(aid, "[ERROR] sessionKey 已失效，跳过")
                    try:
                        worker._cleanup()
                    except Exception:
                        pass
                    self._workers.pop(aid, None)
                    release_account(aid)
                else:
                    status = "waiting" if worker._keep_browser else "failed"
                    update_account(aid, {"status": status, "last_error": error_msg, "last_run_at": now})
                    if not worker._keep_browser:
                        release_account(aid)
        except Exception as exc:
            err = str(exc)[:500]
            now = datetime.now(timezone.utc).isoformat()
            if "sk_expired" in err:
                update_account(aid, {"status": "failed", "last_error": "sessionKey 已失效", "last_run_at": now})
                self._log(aid, "[ERROR] sessionKey 已失效，跳过")
            else:
                update_account(aid, {"status": "failed", "last_error": err, "last_run_at": now})
            worker = self._workers.pop(aid, None)
            if worker:
                try:
                    worker._cleanup()
                except Exception:
                    pass
            release_account(aid)

        with self._lock:
            self._futures.pop(aid, None)
            if not self._futures:
                self._running = False

    def run_card_flow(self, account_id: str) -> Dict[str, Any]:
        worker = self._workers.get(account_id)
        if not worker:
            return {"ok": False, "error": "未找到该账号的浏览器实例（可能在其他实例运行）"}
        if not worker._page:
            return {"ok": False, "error": "浏览器页面已关闭，请重新打开"}
        from concurrent.futures import ThreadPoolExecutor, Future
        with ThreadPoolExecutor(max_workers=1) as pool:
            future: Future = pool.submit(worker.run_card_flow)
            result = future.result(timeout=120)
        if worker._used_card_number:
            update_account(account_id, {"used_card_number": worker._used_card_number})
        return result

    def open_browser(self, account_id: str) -> Dict[str, Any]:
        worker = self._workers.get(account_id)
        if not worker:
            return {"ok": False, "error": "未找到该账号的浏览器实例（可能在其他实例运行）"}
        if not worker._page:
            return {"ok": False, "error": "浏览器页面已关闭"}
        try:
            worker._page.bring_to_front()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": f"聚焦浏览器失败: {exc}"}

    def confirm_and_close(self, account_id: str) -> Dict[str, Any]:
        worker = self._workers.get(account_id)

        from .store import get_account
        acc = get_account(account_id)
        used_card = (acc or {}).get("used_card_number", "")

        if used_card:
            mark_card_used(used_card)
            self._log(account_id, f"[INFO] 卡号已标记为已用: **** {used_card[-4:]}")

        new_sk = ""
        if worker:
            try:
                new_sk = worker.get_session_key_from_browser()
            except Exception as exc:
                self._log(account_id, f"[WARNING] 获取 cookie 失败: {exc}")

            try:
                worker._cleanup()
            except Exception:
                pass
            self._workers.pop(account_id, None)

        now = datetime.now(timezone.utc).isoformat()
        fields = {"status": "success", "last_error": "", "last_run_at": now, "used_card_number": "", "instance_id": ""}
        if new_sk:
            fields["session_key"] = new_sk
            self._log(account_id, f"[INFO] 已更新 sessionKey: ...{new_sk[-20:]}")

        update_account(account_id, fields)
        self._log(account_id, "[INFO] 任务标记为成功")

        return {"ok": True, "new_session_key": bool(new_sk)}

    def stop_all(self):
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

        accounts = load_accounts()
        for acc in accounts:
            if acc.get("status") == "running" and acc.get("instance_id") == self.instance_id:
                update_account(acc["id"], {"status": "idle", "last_error": "手动停止", "instance_id": ""})

        for worker in self._workers.values():
            try:
                worker._cleanup()
            except Exception:
                pass
        self._workers.clear()
        self._futures.clear()
        self._running = False
        return {"stopped": True}


task_manager = TaskManager()
