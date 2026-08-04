from fastapi import APIRouter
from pydantic import BaseModel
from typing import List

from ..core.store import load_cards, save_cards, import_cards_text
from ..core.database import get_conn, put_conn

router = APIRouter(prefix="/api/cards", tags=["cards"])


class ImportBody(BaseModel):
    text: str


class BatchIdBody(BaseModel):
    ids: List[int]


@router.get("")
def list_cards():
    cards = load_cards()
    safe = []
    for c in cards:
        number = c.get("number", "")
        claimed = c.get("claimed_by", "")
        safe.append({
            "id": c.get("id"),
            "number_masked": f"**** {number[-4:]}" if len(number) >= 4 else "****",
            "expiry": c.get("expiry", ""),
            "used": c.get("used", False),
            "claimed": bool(claimed),
            "created_at": c.get("created_at"),
        })
    return {"cards": safe}


@router.post("/import")
def import_cards_api(body: ImportBody):
    return import_cards_text(body.text)


@router.delete("/{card_id}")
def delete_card(card_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cards WHERE id = %s", (card_id,))
            ok = cur.rowcount > 0
        conn.commit()
        return {"ok": ok}
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


@router.post("/mark-used")
def mark_used(body: BatchIdBody):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE cards SET used = TRUE WHERE id = ANY(%s) AND used = FALSE", (body.ids,))
            count = cur.rowcount
        conn.commit()
        return {"ok": True, "count": count}
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


@router.post("/mark-unused")
def mark_unused(body: BatchIdBody):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE cards SET used = FALSE WHERE id = ANY(%s) AND used = TRUE", (body.ids,))
            count = cur.rowcount
        conn.commit()
        return {"ok": True, "count": count}
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


@router.delete("")
def clear_cards():
    save_cards([])
    return {"ok": True}
