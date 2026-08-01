"""PostgreSQL 连接池 + 建表 + JSON 数据迁移。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import psycopg2
import psycopg2.pool
import psycopg2.extras

logger = logging.getLogger(__name__)

DB_CONFIG = {
    "host": "192.168.1.126",
    "port": 5432,
    "dbname": "claude-automation",
    "user": "postgres",
    "password": "123456",
}

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL DEFAULT '',
    password TEXT NOT NULL DEFAULT '',
    session_key TEXT,
    status TEXT NOT NULL DEFAULT 'idle',
    last_error TEXT NOT NULL DEFAULT '',
    last_run_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    disabled BOOLEAN NOT NULL DEFAULT FALSE,
    instance_id TEXT NOT NULL DEFAULT '',
    used_card_number TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_session_key
    ON accounts (session_key) WHERE session_key IS NOT NULL AND session_key != '';

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cards (
    id SERIAL PRIMARY KEY,
    number TEXT UNIQUE NOT NULL,
    cvv TEXT NOT NULL DEFAULT '',
    expiry TEXT NOT NULL DEFAULT '',
    used BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS task_logs (
    id SERIAL PRIMARY KEY,
    account_id TEXT NOT NULL,
    instance_id TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_task_logs_account ON task_logs (account_id, id);
"""


def _ensure_database():
    db_cfg = dict(DB_CONFIG)
    dbname = db_cfg.pop("dbname")
    db_cfg["dbname"] = "postgres"
    try:
        conn = psycopg2.connect(**db_cfg)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
            if not cur.fetchone():
                cur.execute(f'CREATE DATABASE "{dbname}"')
                logger.info("已创建数据库: %s", dbname)
        conn.close()
    except Exception as exc:
        logger.warning("检查/创建数据库失败: %s", exc)


def init_db():
    global _pool
    if _pool is not None:
        return

    _ensure_database()
    _pool = psycopg2.pool.ThreadedConnectionPool(minconn=2, maxconn=20, **DB_CONFIG)
    logger.info("PostgreSQL 连接池已创建: %s@%s/%s", DB_CONFIG["user"], DB_CONFIG["host"], DB_CONFIG["dbname"])

    conn = _pool.getconn()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(_CREATE_TABLES_SQL)
        with conn.cursor() as cur:
            _alter_tables(cur)
        logger.info("数据库表已就绪")
        _migrate_json_data(conn)
    finally:
        _pool.putconn(conn)


def _alter_tables(cur):
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'accounts'")
    existing = {r[0] for r in cur.fetchall()}
    for col, default in [("instance_id", "''"), ("used_card_number", "''")]:
        if col not in existing:
            cur.execute(f"ALTER TABLE accounts ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}")
            logger.info("accounts 表新增列: %s", col)


def get_conn():
    if _pool is None:
        init_db()
    return _pool.getconn()


def put_conn(conn):
    if _pool is not None:
        _pool.putconn(conn)


def _migrate_json_data(conn):
    with conn.cursor() as cur:
        # accounts
        cur.execute("SELECT COUNT(*) FROM accounts")
        if cur.fetchone()[0] == 0:
            accounts_file = DATA_DIR / "accounts.json"
            if accounts_file.exists():
                try:
                    accounts = json.loads(accounts_file.read_text(encoding="utf-8"))
                    if isinstance(accounts, list) and accounts:
                        for a in accounts:
                            cur.execute(
                                """INSERT INTO accounts (id, email, password, session_key, status, last_error, last_run_at, created_at, used, disabled)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                   ON CONFLICT DO NOTHING""",
                                (a.get("id", ""), a.get("email", ""), a.get("password", ""),
                                 a.get("session_key", ""), a.get("status", "idle"), a.get("last_error", ""),
                                 a.get("last_run_at"), a.get("created_at"),
                                 bool(a.get("used", False)), bool(a.get("disabled", False))),
                            )
                        logger.info("已迁移 %d 条账号数据", len(accounts))
                except Exception as exc:
                    logger.warning("账号数据迁移失败: %s", exc)

        # config
        cur.execute("SELECT COUNT(*) FROM config")
        if cur.fetchone()[0] == 0:
            config_file = DATA_DIR / "config.json"
            if config_file.exists():
                try:
                    cfg = json.loads(config_file.read_text(encoding="utf-8"))
                    if isinstance(cfg, dict) and cfg:
                        for k, v in cfg.items():
                            cur.execute(
                                "INSERT INTO config (key, value) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                                (k, json.dumps(v, ensure_ascii=False)),
                            )
                        logger.info("已迁移 %d 条配置数据", len(cfg))
                except Exception as exc:
                    logger.warning("配置数据迁移失败: %s", exc)

        # cards
        cur.execute("SELECT COUNT(*) FROM cards")
        if cur.fetchone()[0] == 0:
            cards_file = DATA_DIR / "cards.json"
            if cards_file.exists():
                try:
                    cards = json.loads(cards_file.read_text(encoding="utf-8"))
                    if isinstance(cards, list) and cards:
                        for c in cards:
                            cur.execute(
                                """INSERT INTO cards (number, cvv, expiry, used, created_at)
                                   VALUES (%s, %s, %s, %s, %s)
                                   ON CONFLICT DO NOTHING""",
                                (c.get("number", ""), c.get("cvv", ""), c.get("expiry", ""),
                                 bool(c.get("used", False)), c.get("created_at")),
                            )
                        logger.info("已迁移 %d 条卡片数据", len(cards))
                except Exception as exc:
                    logger.warning("卡片数据迁移失败: %s", exc)
