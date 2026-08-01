"""独立进程运行邮箱接码。"""

import asyncio
import json
import sys
from pathlib import Path

try: asyncio.get_event_loop().close()
except: pass
asyncio.set_event_loop(None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    try: asyncio.get_event_loop().close()
    except: pass
    try: asyncio.set_event_loop(None)
    except: pass

    data = json.loads(sys.stdin.read())
    logs = []

    def _log(msg):
        logs.append(msg)
        print(msg, file=sys.stderr)

    try:
        from core.mailcom import find_claude_magic_link
        result = find_claude_magic_link(
            email=data["email"],
            password=data["password"],
            proxy=data.get("proxy", ""),
            since_ms=data.get("since_ms", 0),
            log_fn=_log,
        )
        json.dump({"link": result, "logs": logs}, sys.stdout, ensure_ascii=False)
    except Exception as exc:
        json.dump({"link": None, "error": str(exc), "logs": logs}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
