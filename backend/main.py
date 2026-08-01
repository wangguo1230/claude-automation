from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.accounts import router as accounts_router
from .api.config import router as config_router
from .api.tasks import router as tasks_router
from .api.oauth import router as oauth_router
from .api.cards import router as cards_router
from .core.database import init_db


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(title="Claude 账号管理", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts_router)
app.include_router(config_router)
app.include_router(tasks_router)
app.include_router(oauth_router)
app.include_router(cards_router)


@app.get("/api/health")
def health():
    return {"ok": True}
