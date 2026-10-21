import importlib.util
from pathlib import Path
import asyncio

import httpx
from fastapi.testclient import TestClient

spec=importlib.util.spec_from_file_location('browser_fetch_service',Path(__file__).parents[1]/'server/service.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ORIGIN='http://127.0.0.1:5180'


class FakeCrawler:
    def __init__(self,page_limit_mib=2):
        if type(page_limit_mib) is not int or not 1<=page_limit_mib<=10:raise ValueError('limit')
    async def fetch(self,url):
        if 'limited' in url:raise module.RateLimited(45)
        if 'timeout' in url:raise httpx.ConnectTimeout('test')
        return {'title':'测试标题 <script>alert(1)</script>'},'success','完成'


def client(factory=FakeCrawler):
    return TestClient(module.create_service(origins=[ORIGIN],crawler_factory=factory),base_url='http://127.0.0.1:8787')


def test_stateless_success_and_cors(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    with client() as c:
        assert c.get('/fetch-api/health').json()['storage']=='none'
        r=c.post('/fetch-api/fetch',headers={'Origin':ORIGIN},json={'url':'https://example.com','page_limit_mib':3})
        assert r.status_code==200 and '<script>' in r.json()['data']['title']
        assert r.headers['access-control-allow-origin']==ORIGIN
        assert not list(tmp_path.rglob('*.sqlite3'))
        assert c.get('/api/resources').status_code==404


def test_foreign_origin_body_limits_and_input():
    with client() as c:
        assert c.post('/fetch-api/fetch',headers={'Origin':'https://evil.example'},json={'url':'https://example.com'}).status_code==403
        assert c.post('/fetch-api/fetch',json={'url':'https://example.com'}).status_code==403
        assert c.post('/fetch-api/fetch',headers={'Origin':ORIGIN},content='x'*4097).status_code==413
        for data in [{'url':'file:///x'},{'url':'https://example.com','page_limit_mib':99},{'url':'https://example.com','notes':'private'},[]]:
            assert c.post('/fetch-api/fetch',headers={'Origin':ORIGIN},json=data).status_code==400


def test_retry_and_rate_limit():
    with client() as c:
        r=c.post('/fetch-api/fetch',headers={'Origin':ORIGIN},json={'url':'https://limited.example'})
        assert r.status_code==429 and r.headers['retry-after']=='45'
        r=c.post('/fetch-api/fetch',headers={'Origin':ORIGIN},json={'url':'https://timeout.example'})
        assert r.status_code==502 and r.json()['retryable']
        for _ in range(28):c.post('/fetch-api/fetch',headers={'Origin':ORIGIN},json={'url':'https://example.com'})
        assert c.post('/fetch-api/fetch',headers={'Origin':ORIGIN},json={'url':'https://example.com'}).status_code==429


def test_private_ip_and_redirect_blocked():
    from backend.crawler import Crawler
    async def handler(request):return httpx.Response(302,headers={'location':'http://127.0.0.1/private'})
    factory=lambda **kw:Crawler(transport=httpx.MockTransport(handler),**kw)
    with client(factory) as c:
        for url in ['http://127.0.0.1/','http://10.0.0.1/','http://169.254.169.254/']:
            r=c.post('/fetch-api/fetch',headers={'Origin':ORIGIN},json={'url':url})
            assert r.status_code==400 and not r.json()['retryable']
        r=c.post('/fetch-api/fetch',headers={'Origin':ORIGIN},json={'url':'https://1.1.1.1/'})
        assert r.status_code==400


def test_concurrency_is_bounded():
    class Slow(FakeCrawler):
        active=0
        maximum=0
        async def fetch(self,url):
            Slow.active+=1;Slow.maximum=max(Slow.maximum,Slow.active)
            await asyncio.sleep(.05)
            Slow.active-=1
            return {},'partial','done'
    async def check():
        transport=httpx.ASGITransport(app=module.create_service(origins=[ORIGIN],crawler_factory=Slow))
        async with httpx.AsyncClient(transport=transport,base_url='http://127.0.0.1:8787') as c:
            responses=await asyncio.gather(*(c.post('/fetch-api/fetch',headers={'Origin':ORIGIN},json={'url':'https://example.com'}) for _ in range(8)))
        assert sum(r.status_code==200 for r in responses)==3
        assert Slow.maximum==3
    asyncio.run(check())


def test_no_wildcard_origin():
    import pytest
    for origin in ['*','http://example.com','https://example.com/path','https://user:pass@example.com']:
        with pytest.raises(ValueError):module.create_service(origins=[origin])
