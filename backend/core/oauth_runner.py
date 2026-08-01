"""独立进程运行 OAuth 流程。"""

import asyncio
import json
import os
import sys
from pathlib import Path

try:
    asyncio.get_event_loop().close()
except Exception:
    pass
asyncio.set_event_loop(None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    try:
        asyncio.get_event_loop().close()
    except Exception:
        pass
    try:
        asyncio.set_event_loop(None)
    except Exception:
        pass

    data = json.loads(sys.stdin.read())
    logs = []

    def _log(msg):
        logs.append(msg)
        print(msg, file=sys.stderr)

    try:
        from core.claude_oauth import full_oauth_flow
        result = full_oauth_flow(
            session_key=data.get("session_key", ""),
            config=data.get("config", {}),
            email=data.get("email", ""),
            password=data.get("password", ""),
            log_fn=_log,
        )
        result["logs"] = logs
        json.dump(result, sys.stdout, ensure_ascii=False)
    except Exception as exc:
        json.dump({"ok": False, "step": "unknown", "error": str(exc)[:500], "logs": logs}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
