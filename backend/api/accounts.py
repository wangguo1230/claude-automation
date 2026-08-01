from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional

from ..core.store import clear_accounts, delete_account, import_accounts, load_accounts, save_accounts

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class ImportBody(BaseModel):
    text: str


class BatchBody(BaseModel):
    ids: List[str]


@router.get("")
def list_accounts():
    accounts = load_accounts()
    safe = []
    for a in accounts:
        safe.append({
            "id": a.get("id"),
            "email": a.get("email", ""),
            "status": a.get("status", "idle"),
            "used": a.get("used", False),
            "disabled": a.get("disabled", False),
            "last_error": a.get("last_error", ""),
            "last_run_at": a.get("last_run_at"),
            "created_at": a.get("created_at"),
        })
    return {"accounts": safe}


@router.post("/import")
def import_accounts_api(body: ImportBody):
    result = import_accounts(body.text)
    return result


@router.delete("/{account_id}")
def delete_account_api(account_id: str):
    ok = delete_account(account_id)
    return {"ok": ok}


@router.delete("")
def clear_accounts_api():
    clear_accounts()
    return {"ok": True}


@router.post("/batch-delete")
def batch_delete_api(body: BatchBody):
    accounts = load_accounts()
    id_set = set(body.ids)
    before = len(accounts)
    accounts = [a for a in accounts if a.get("id") not in id_set]
    save_accounts(accounts)
    return {"deleted": before - len(accounts)}


@router.post("/mark-used")
def mark_used_api(body: BatchBody):
    accounts = load_accounts()
    id_set = set(body.ids)
    count = 0
    for a in accounts:
        if a.get("id") in id_set:
            a["used"] = True
            count += 1
    save_accounts(accounts)
    return {"ok": True, "count": count}


@router.post("/mark-disabled")
def mark_disabled_api(body: BatchBody):
    accounts = load_accounts()
    id_set = set(body.ids)
    count = 0
    for a in accounts:
        if a.get("id") in id_set:
            a["disabled"] = True
            count += 1
    save_accounts(accounts)
    return {"ok": True, "count": count}


@router.post("/mark-enabled")
def mark_enabled_api(body: BatchBody):
    accounts = load_accounts()
    id_set = set(body.ids)
    count = 0
    for a in accounts:
        if a.get("id") in id_set:
            a["disabled"] = False
            count += 1
    save_accounts(accounts)
    return {"ok": True, "count": count}


@router.post("/mark-unused")
def mark_unused_api(body: BatchBody):
    accounts = load_accounts()
    id_set = set(body.ids)
    count = 0
    for a in accounts:
        if a.get("id") in id_set:
            a["used"] = False
            count += 1
    save_accounts(accounts)
    return {"ok": True, "count": count}


@router.post("/export-raw")
def export_raw_api(body: BatchBody):
    accounts = load_accounts()
    id_set = set(body.ids)
    lines = []
    for a in accounts:
        if a.get("id") in id_set:
            email = a.get("email", "")
            password = a.get("password", "")
            sk = a.get("session_key", "")
            if email and password and sk:
                lines.append(f"{email}----{password}----{sk}")
            elif email and sk:
                lines.append(f"{email}----{sk}")
            elif sk:
                lines.append(sk)
    return {"lines": lines, "count": len(lines)}


@router.post("/export-sk")
def export_sk_api(body: BatchBody):
    accounts = load_accounts()
    id_set = set(body.ids)
    keys = []
    for a in accounts:
        if a.get("id") in id_set:
            sk = a.get("session_key", "")
            if sk:
                keys.append(sk)
    return {"keys": keys, "count": len(keys)}


@router.post("/export-sub2api")
async def export_sub2api_api(body: BatchBody):
    from ..core.claude_oauth import generate_sub2api_entry
    from ..core.store import load_config
    import asyncio

    accounts = load_accounts()
    config = load_config()
    proxy = config.get("proxy", "")
    id_set = set(body.ids)
    targets = [a for a in accounts if a.get("id") in id_set and a.get("session_key")]

    if not targets:
        return {"ok": False, "error": "没有可导出的账号（需要有 sessionKey）"}

    loop = asyncio.get_event_loop()
    results = []
    errors = []

    def _process_one(acc):
        logs = []
        entry = generate_sub2api_entry(
            session_key=acc.get("session_key", ""),
            email=acc.get("email", ""),
            proxy=proxy,
            name=acc.get("email", ""),
            _log=lambda m: logs.append(m),
        )
        return acc.get("email", ""), entry, logs

    for acc in targets:
        email, entry, logs = await loop.run_in_executor(None, _process_one, acc)
        if entry:
            results.append(entry)
        else:
            errors.append({"email": email, "logs": logs})

    import time as _t
    from datetime import datetime, timezone
    export_data = {
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "proxies": [],
        "accounts": results,
    }

    return {"ok": True, "data": export_data, "success": len(results), "failed": len(errors), "errors": errors}
