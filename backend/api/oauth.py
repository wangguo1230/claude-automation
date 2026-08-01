import json
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from ..core.store import load_accounts, load_config, update_account

router = APIRouter(prefix="/api/oauth", tags=["oauth"])

RUNNER_SCRIPT = str(Path(__file__).resolve().parent.parent / "core" / "oauth_runner.py")


class OAuthBody(BaseModel):
    account_id: str


@router.post("/authorize")
async def authorize(body: OAuthBody):
    accounts = load_accounts()
    account = None
    for a in accounts:
        if a.get("id") == body.account_id:
            account = a
            break

    if not account:
        return {"ok": False, "error": "账号不存在"}

    session_key = account.get("session_key", "").strip()
    email = account.get("email", "")
    password = account.get("password", "")

    if not session_key and not email:
        return {"ok": False, "error": "该账号没有 sessionKey 也没有邮箱"}

    config = load_config()

    input_data = json.dumps({
        "session_key": session_key,
        "config": config,
        "email": email,
        "password": password,
    }, ensure_ascii=False)

    import asyncio
    loop = asyncio.get_event_loop()

    def _run():
        proc = subprocess.run(
            [sys.executable, RUNNER_SCRIPT],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        if proc.returncode != 0:
            return {"ok": False, "error": f"进程退出 {proc.returncode}: {proc.stderr[:500]}"}
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {"ok": False, "error": f"输出解析失败: {proc.stdout[:300]} stderr: {proc.stderr[:200]}"}

    result = await loop.run_in_executor(None, _run)

    if result.get("ok"):
        fields = {}
        if result.get("redirect_url"):
            fields["oauth_redirect_url"] = result["redirect_url"]
        new_sk = result.get("new_session_key", "")
        if new_sk and new_sk != session_key:
            fields["session_key"] = new_sk
        if fields:
            update_account(body.account_id, fields)

    # 把日志带回前端方便排查
    resp = {k: v for k, v in result.items() if k != "logs"}
    if not result.get("ok") and result.get("logs"):
        resp["detail_logs"] = result["logs"]
    return resp
