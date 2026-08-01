"""PostgreSQL 持久化存储。"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .database import get_conn, put_conn

DEFAULT_CONFIG: Dict[str, Any] = {
    "browser_provider": "adspower",
    "adspower_api_base": "http://localhost:50325",
    "adspower_group_id": "0",
    "chrome_path": "",
    "chrome_headless": False,
    "proxy": "",
    "plan": "max",
    "billing_period": "annual",
    "iban_country": "DE",
    "iban": "",
    "auto_subscribe": True,
    "max_concurrent": 3,
    "vless_enabled": False,
    "vless_share_link": "",
    "vless_xray_path": "",
    "sepa_extension_path": "",
    "payment_method": "sepa",
}

_ACCOUNT_COLUMNS = [
    "id", "email", "password", "session_key", "status",
    "last_error", "last_run_at", "created_at", "used", "disabled",
]


def _row_to_account(row, columns=_ACCOUNT_COLUMNS) -> Dict[str, Any]:
    d = dict(zip(columns, row))
    if d.get("last_run_at"):
        d["last_run_at"] = d["last_run_at"].isoformat()
    if d.get("created_at"):
        d["created_at"] = d["created_at"].isoformat()
    return d


# ── Accounts ──

def load_accounts() -> List[Dict[str, Any]]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT " + ", ".join(_ACCOUNT_COLUMNS) + " FROM accounts ORDER BY created_at")
            return [_row_to_account(r) for r in cur.fetchall()]
    finally:
        put_conn(conn)


def save_accounts(accounts: List[Dict[str, Any]]):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM accounts")
            for a in accounts:
                cur.execute(
                    """INSERT INTO accounts (id, email, password, session_key, status, last_error, last_run_at, created_at, used, disabled)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (id) DO UPDATE SET
                           email=EXCLUDED.email, password=EXCLUDED.password, session_key=EXCLUDED.session_key,
                           status=EXCLUDED.status, last_error=EXCLUDED.last_error, last_run_at=EXCLUDED.last_run_at,
                           created_at=EXCLUDED.created_at, used=EXCLUDED.used, disabled=EXCLUDED.disabled""",
                    (a.get("id", ""), a.get("email", ""), a.get("password", ""),
                     a.get("session_key", ""), a.get("status", "idle"), a.get("last_error", ""),
                     a.get("last_run_at"), a.get("created_at"),
                     bool(a.get("used", False)), bool(a.get("disabled", False))),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def get_account(account_id: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT " + ", ".join(_ACCOUNT_COLUMNS) + " FROM accounts WHERE id = %s", (account_id,))
            row = cur.fetchone()
            return _row_to_account(row) if row else None
    finally:
        put_conn(conn)


def update_account(account_id: str, fields: Dict[str, Any]):
    if not fields:
        return
    allowed = {"email", "password", "session_key", "status", "last_error", "last_run_at", "created_at", "used", "disabled"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [account_id]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE accounts SET {set_clause} WHERE id = %s", values)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def import_accounts(text: str) -> Dict[str, Any]:
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    conn = get_conn()
    try:
        added = 0
        skipped = 0
        with conn.cursor() as cur:
            cur.execute("SELECT session_key FROM accounts WHERE session_key IS NOT NULL AND session_key != ''")
            existing_keys = {r[0] for r in cur.fetchall()}

            for line in lines:
                parts = line.split("----")
                email = ""
                password = ""
                sk_part = ""

                if len(parts) >= 3:
                    email = parts[0].strip()
                    password = parts[1].strip()
                    sk_part = parts[2].strip()
                elif len(parts) == 2:
                    email = parts[0].strip()
                    sk_part = parts[1].strip()
                elif len(parts) == 1:
                    sk_part = parts[0].strip()
                else:
                    skipped += 1
                    continue

                sk_part = sk_part.strip('"').strip("'")
                session_key = sk_part
                if "=" in sk_part and not sk_part.startswith("sk-"):
                    session_key = sk_part.split("=", 1)[1].strip()
                session_key = session_key.strip('"').strip("'")

                if not session_key or session_key in existing_keys:
                    skipped += 1
                    continue

                aid = str(uuid.uuid4())[:8]
                now = datetime.now(timezone.utc).isoformat()
                cur.execute(
                    """INSERT INTO accounts (id, email, password, session_key, status, last_error, last_run_at, created_at, used, disabled)
                       VALUES (%s, %s, %s, %s, 'idle', '', NULL, %s, FALSE, FALSE)
                       ON CONFLICT DO NOTHING""",
                    (aid, email, password, session_key, now),
                )
                if cur.rowcount > 0:
                    existing_keys.add(session_key)
                    added += 1
                else:
                    skipped += 1

            cur.execute("SELECT COUNT(*) FROM accounts")
            total = cur.fetchone()[0]

        conn.commit()
        return {"added": added, "skipped": skipped, "total": total}
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def delete_account(account_id: str) -> bool:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM accounts WHERE id = %s", (account_id,))
            deleted = cur.rowcount > 0
        conn.commit()
        return deleted
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def clear_accounts():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM accounts")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


# ── Config ──

def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT key, value FROM config")
            for key, value in cur.fetchall():
                if key in DEFAULT_CONFIG:
                    try:
                        cfg[key] = json.loads(value)
                    except (json.JSONDecodeError, TypeError):
                        cfg[key] = value
    finally:
        put_conn(conn)
    return cfg


def save_config(config: Dict[str, Any]) -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    for k in DEFAULT_CONFIG:
        if k in config:
            cfg[k] = config[k]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for k, v in cfg.items():
                cur.execute(
                    "INSERT INTO config (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    (k, json.dumps(v, ensure_ascii=False)),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)
    return cfg


# ── Cards ──

_CARD_COLUMNS = ["id", "number", "cvv", "expiry", "used", "created_at"]

_CARD_FIELD_PATTERNS = {
    "number": re.compile(r"(?:卡号|card|number)\s*[:：]\s*(\S+)", re.IGNORECASE),
    "cvv": re.compile(r"(?:cvv|cvc|安全码)\s*[:：]?\s*(\d{3,4})", re.IGNORECASE),
    "expiry": re.compile(r"(?:有效期|expiry|exp|expire)\s*[:：]\s*(\S+)", re.IGNORECASE),
}


def _row_to_card(row) -> Dict[str, Any]:
    d = dict(zip(_CARD_COLUMNS, row))
    if d.get("created_at"):
        d["created_at"] = d["created_at"].isoformat()
    return d


def load_cards() -> List[Dict[str, Any]]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT " + ", ".join(_CARD_COLUMNS) + " FROM cards ORDER BY id")
            return [_row_to_card(r) for r in cur.fetchall()]
    finally:
        put_conn(conn)


def save_cards(cards: List[Dict[str, Any]]):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cards")
            for c in cards:
                cur.execute(
                    """INSERT INTO cards (number, cvv, expiry, used, created_at)
                       VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    (c.get("number", ""), c.get("cvv", ""), c.get("expiry", ""),
                     bool(c.get("used", False)), c.get("created_at")),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def import_cards_text(text: str) -> Dict[str, Any]:
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    conn = get_conn()
    try:
        added = 0
        skipped = 0
        with conn.cursor() as cur:
            cur.execute("SELECT number FROM cards")
            existing = {r[0] for r in cur.fetchall()}

            for line in lines:
                number = ""
                cvv = ""
                expiry = ""

                if ";" in line or "；" in line:
                    parts = re.split(r"[;；]", line)
                    for part in parts:
                        part = part.strip()
                        for field, pattern in _CARD_FIELD_PATTERNS.items():
                            m = pattern.search(part)
                            if m:
                                if field == "number":
                                    number = re.sub(r"\s+", "", m.group(1))
                                elif field == "cvv":
                                    cvv = m.group(1)
                                elif field == "expiry":
                                    expiry = m.group(1)

                if not number and "|" in line:
                    parts = line.split("|")
                    if len(parts) >= 3:
                        number = re.sub(r"\s+", "", parts[0].strip())
                        expiry = parts[1].strip()
                        cvv = parts[2].strip()

                if not number or not number.isdigit() or len(number) < 13:
                    skipped += 1
                    continue
                if number in existing:
                    skipped += 1
                    continue

                now = datetime.now(timezone.utc).isoformat()
                cur.execute(
                    """INSERT INTO cards (number, cvv, expiry, used, created_at)
                       VALUES (%s, %s, %s, FALSE, %s) ON CONFLICT (number) DO NOTHING""",
                    (number, cvv, expiry, now),
                )
                if cur.rowcount > 0:
                    existing.add(number)
                    added += 1
                else:
                    skipped += 1

            cur.execute("SELECT COUNT(*) FROM cards")
            total = cur.fetchone()[0]

        conn.commit()
        return {"added": added, "skipped": skipped, "total": total}
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def get_next_card() -> Optional[Dict[str, Any]]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT " + ", ".join(_CARD_COLUMNS) + " FROM cards WHERE used = FALSE ORDER BY id LIMIT 1")
            row = cur.fetchone()
            return _row_to_card(row) if row else None
    finally:
        put_conn(conn)


def mark_card_used(number: str):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE cards SET used = TRUE WHERE number = %s", (number,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)
