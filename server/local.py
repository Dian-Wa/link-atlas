"""Windows local helper: loopback only, no user database, private stop token."""
import json
import os
from pathlib import Path
import secrets
import sys

import uvicorn

HERE = Path(__file__).resolve()
ROOT = next(p for p in (HERE.parents[1], HERE.parents[2]) if (p/'backend/crawler.py').exists())
sys.path.insert(0, str(ROOT))
from service import create_service


if __name__ == '__main__':
    token = secrets.token_urlsafe(32)
    origins = ['https://dian-wa.github.io', 'http://127.0.0.1:5180', 'http://localhost:5180']
    app = create_service(origins=origins, local_only=True, shutdown_token=token, shutdown_callback=lambda: setattr(server, 'should_exit', True))
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8787, access_log=False, proxy_headers=False))
    control = ROOT/'cache/local-fetch/control.json'
    control.parent.mkdir(parents=True, exist_ok=True)
    control.write_text(json.dumps({'pid': os.getpid(), 'token': token}), encoding='utf-8')
    server.run()
