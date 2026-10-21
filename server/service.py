"""Stateless metadata fetcher. Never initializes Store, accounts, or a database."""
import asyncio
import math
import os
import secrets
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pathlib import Path

from backend.crawler import Crawler, RateLimited, UnsafeURL
from backend.store import canonical_url


class LocalNetworkCORS(CORSMiddleware):
    """Support the PNA preflight on both old and new Starlette releases."""
    def preflight_response(self, request_headers):
        private = request_headers.get('access-control-request-private-network')
        filtered = Headers({k: v for k, v in request_headers.items() if k != 'access-control-request-private-network'})
        response = super().preflight_response(filtered)
        if private == 'true' and response.status_code == 200 and self.is_allowed_origin(request_headers.get('origin', '')):
            response.headers['Access-Control-Allow-Private-Network'] = 'true'
        return response


def create_service(origins=None, crawler_factory=Crawler, local_only=False, shutdown_token=None, shutdown_callback=None):
    if origins is None:
        origins = [x.strip() for x in os.environ.get('ATLAS_ALLOWED_ORIGINS', 'http://127.0.0.1:5180').split(',') if x.strip()]
        external = os.environ.get('RENDER_EXTERNAL_URL', '').rstrip('/')
        if external and external not in origins:
            origins.append(external)
    for origin in origins:
        parsed = urlsplit(origin)
        if not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password or (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost'))):
            raise ValueError('Allowed origins must be exact HTTPS origins (localhost HTTP allowed for testing)')
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    slots = asyncio.Semaphore(3)
    limits = defaultdict(deque)

    @app.middleware('http')
    async def guard(request: Request, call_next):
        if request.method == 'POST':
            origin = request.headers.get('origin')
            own_origin = f'{request.url.scheme}://{request.url.netloc}'
            if origin not in origins and origin != own_origin:
                return JSONResponse({'detail': '此网站未获准使用抓取服务'}, status_code=403)
            size, chunks = 0, []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 4096:
                    return JSONResponse({'detail': '请求超过 4 KiB'}, status_code=413)
                chunks.append(chunk)
            request._body = b''.join(chunks)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' https: http://127.0.0.1:8787; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    app.add_middleware(LocalNetworkCORS, allow_origins=origins, allow_methods=['POST', 'GET'], allow_headers=['content-type'], expose_headers=['Retry-After'])
    if local_only:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]'])

    @app.get('/fetch-api/health')
    async def health():
        return {'status': 'ok', 'app': 'link-atlas-fetch', 'mode': 'local' if local_only else 'service', 'storage': 'none', 'source_storage': False, 'concurrency': 3}

    @app.post('/fetch-api/fetch')
    async def fetch(request: Request):
        ip = request.client.host if request.client else 'unknown'
        now = time.monotonic()
        for key in list(limits):
            if not limits[key] or now-limits[key][-1] > 60:
                del limits[key]
        if ip not in limits and len(limits) >= 1024:
            return JSONResponse({'detail': '服务繁忙，请稍后重试', 'retry_after': 60}, status_code=429, headers={'Retry-After': '60'})
        requests = limits[ip]
        while requests and requests[0] <= now-60:
            requests.popleft()
        if len(requests) >= 30:
            return JSONResponse({'detail': '每个客户端每分钟最多 30 次抓取', 'retry_after': 60}, status_code=429, headers={'Retry-After': '60'})
        requests.append(now)
        try:
            data = await request.json()
            if not isinstance(data, dict) or set(data)-{'url', 'page_limit_mib'}:
                raise ValueError('仅接受链接和读取上限')
            url = canonical_url(data['url'])
            limit = data.get('page_limit_mib', 2)
            crawler = crawler_factory(page_limit_mib=limit)
        except (ValueError, KeyError, TypeError, AttributeError):
            return JSONResponse({'detail': '链接或读取上限无效', 'retryable': False}, status_code=400)
        if slots.locked():
            return JSONResponse({'detail': '抓取服务繁忙，请稍后重试', 'retry_after': 5}, status_code=429, headers={'Retry-After': '5'})
        async with slots:
            try:
                async with asyncio.timeout(45):
                    result, status, message = await crawler.fetch(url)
                return {'data': result, 'status': status, 'message': message}
            except RateLimited as error:
                delay = max(1, min(86400, math.ceil(error.delay)))
                return JSONResponse({'detail': str(error), 'retry_after': delay}, status_code=429, headers={'Retry-After': str(delay)})
            except UnsafeURL as error:
                return JSONResponse({'detail': str(error), 'retryable': False}, status_code=400)
            except (httpx.TransportError, TimeoutError):
                return JSONResponse({'detail': '远端网络连接失败或超时', 'retryable': True}, status_code=502)
            except (httpx.HTTPError, ValueError) as error:
                return JSONResponse({'detail': str(error)[:300], 'retryable': False}, status_code=422)

    if local_only and shutdown_token and shutdown_callback:
        @app.post('/fetch-api/control/stop')
        async def stop(request: Request):
            if not secrets.compare_digest(request.headers.get('x-atlas-control', ''), shutdown_token):
                return JSONResponse({'detail': '无效的本机控制令牌'}, status_code=403)
            shutdown_callback()
            return {'stopping': True}

    dist = Path(__file__).resolve().parents[1]/'dist'
    if dist.exists() and not local_only:
        app.mount('/', StaticFiles(directory=dist, html=True), name='frontend')
    return app


app = create_service()
