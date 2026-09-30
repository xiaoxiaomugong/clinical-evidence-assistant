#!/usr/bin/env python3
"""Start the local-only public API without reading .env or inherited secrets."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "src"):
    sys.path.insert(0, str(directory))

from scripts.local_runtime import install_loopback_only_guard, prepare_offline_environment


def main() -> int:
    parser = argparse.ArgumentParser(description="Local offline evidence Web API")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--check", action="store_true", help="Run an offline API smoke check and exit")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    prepare_offline_environment(os.environ, ROOT)
    install_loopback_only_guard()
    try:
        import uvicorn
        from evidence_assistant.web import create_app

        app = create_app()
        if args.check:
            from fastapi.testclient import TestClient

            with TestClient(app) as client:
                assert client.get("/health/ready").status_code == 200
                result = client.post("/api/v1/queries", json={
                    "question": "降压药应早上服用还是睡前服用？", "audience": "public",
                })
                assert result.status_code == 200 and result.json()["status"] == "answered"
                assert result.json()["sources"]
            print("PASS: local API, real evidence answer and sources; external network disabled")
            return 0
        print(f"Local offline API: http://127.0.0.1:{args.port}", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1,
                    access_log=False, log_level="warning")
        return 0
    except Exception:
        print("本地服务未能启动或自检失败。请确认已安装 .[web] 依赖、语料文件完整且端口可用。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
