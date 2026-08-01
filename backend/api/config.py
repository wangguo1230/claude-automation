from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from ..core.store import load_config, save_config

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from iban_generator import generate_iban

router = APIRouter(prefix="/api/config", tags=["config"])


class ConfigUpdate(BaseModel):
    browser_provider: Optional[str] = None
    adspower_api_base: Optional[str] = None
    adspower_group_id: Optional[str] = None
    chrome_path: Optional[str] = None
    chrome_headless: Optional[bool] = None
    proxy: Optional[str] = None
    plan: Optional[str] = None
    billing_period: Optional[str] = None
    iban_country: Optional[str] = None
    iban: Optional[str] = None
    auto_subscribe: Optional[bool] = None
    max_concurrent: Optional[int] = None
    vless_enabled: Optional[bool] = None
    vless_share_link: Optional[str] = None
    vless_xray_path: Optional[str] = None
    sepa_extension_path: Optional[str] = None
    payment_method: Optional[str] = None


@router.get("")
def get_config():
    return load_config()


@router.put("")
def update_config(body: ConfigUpdate):
    current = load_config()
    try:
        updates = body.model_dump(exclude_none=True)
    except AttributeError:
        updates = {k: v for k, v in body.dict().items() if v is not None}
    current.update(updates)
    saved = save_config(current)
    return saved


@router.get("/generate-iban")
def gen_iban(country: str = "DE"):
    return {"iban": generate_iban(country)}


class VlessTestRequest(BaseModel):
    share_link: str
    xray_path: str


@router.post("/vless/test")
def test_vless(body: VlessTestRequest):
    from ..core.vless_relay import probe_vless
    return probe_vless(body.share_link, body.xray_path)


@router.get("/vless/status")
def vless_status():
    from ..core.vless_relay import get_relay_status
    cfg = load_config()
    return get_relay_status(cfg.get("vless_share_link", ""), cfg.get("vless_xray_path", ""))
