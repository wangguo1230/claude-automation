from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional

from ..core.task_manager import task_manager

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class StartBody(BaseModel):
    account_ids: Optional[List[str]] = None


@router.post("/start")
def start_tasks(body: StartBody = StartBody()):
    return task_manager.start(body.account_ids)


@router.post("/start-auto")
def start_auto_tasks(body: StartBody = StartBody()):
    return task_manager.start_auto(body.account_ids)


@router.post("/stop")
def stop_tasks():
    return task_manager.stop_all()


@router.get("/status")
def get_status():
    return {
        "running": task_manager.is_running,
        "accounts": task_manager.get_all_status(),
    }


@router.get("/{account_id}/logs")
def get_logs(account_id: str, since: int = 0):
    logs = task_manager.get_logs(account_id, since)
    return {"logs": logs, "total": since + len(logs)}


@router.post("/{account_id}/confirm")
def confirm_task(account_id: str):
    return task_manager.confirm_and_close(account_id)


@router.post("/{account_id}/open-browser")
def open_browser(account_id: str):
    return task_manager.open_browser(account_id)


@router.post("/{account_id}/fill-card")
def fill_card(account_id: str):
    return task_manager.run_card_flow(account_id)
