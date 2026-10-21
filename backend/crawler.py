import asyncio
import email.utils
import ipaddress
import json
import re
import socket
import time
import zlib
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .store import canonical_url

PAGE_LIMIT = 2 * 1024 * 1024
README_LIMIT = 256 * 1024


class UnsafeURL(ValueError):
    pass


class RateLimited(Exception):
    def __init__(self, delay):
        self.delay = delay
        super().__init__(f'远端限流，约 {int(delay)} 秒后重试')


def validate_public_url(url):
    p = urlsplit(canonical_url(url))
    host = p.hostname
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        if host.lower() == 'localhost' or host.lower().endswith(('.localhost', '.local')):
            raise UnsafeURL('禁止访问本机或内网')
        try:
            addresses = list({row[4][0] for row in socket.getaddrinfo(host, p.port or (443 if p.scheme == 'https' else 80), type=socket.SOCK_STREAM)})
        except socket.gaierror as e:
            raise httpx.ConnectError('无法解析域名') from e
    if not addresses or any(not ipaddress.ip_address(x).is_global for x in addresses):
        raise UnsafeURL('仅允许公网地址；禁止访问本机、内网和保留地址')
    return addresses


class PublicTransport(httpx.AsyncHTTPTransport):
    """Pin the validated IP while retaining TLS SNI and the original Host header."""
    async def handle_async_request(self, request):
        addresses = await asyncio.to_thread(validate_public_url, str(request.url))
        host = request.url.host
        request.headers['Host'] = request.url.netloc.decode('ascii')
        request.extensions['sni_hostname'] = host
        request.url = request.url.copy_with(host=addresses[0])
        return await super().handle_async_request(request)


def classify(data, rules=None):
    if rules is None:
        rules = [
            {'category_id': 2, 'keywords': '机器学习,人工智能,大模型,llm,openai,huggingface,模型,ai'},
            {'category_id': 4, 'keywords': '设计,figma,design,icon'},
            {'category_id': 3, 'keywords': '教程,课程,学习,文档,docs,tutorial'},
            {'category_id': 1, 'keywords': 'github,gitlab,代码,开发,工具,typescript,javascript,rust'}]
    text = ' '.join(str(data.get(k, '')) for k in ('url','title','description','repo')).lower()
    for rule in rules:
        for word in re.split(r'[,，]', rule['keywords']):
            word = word.strip().lower()
            if not word:
                continue
            matched = bool(re.search(r'(?<![a-z0-9])' + re.escape(word) + r'(?![a-z0-9])', text)) if word.isascii() and word.isalnum() else word in text
            if matched:
                return {'category_id': rule['category_id'], 'classification_reason': f'匹配本地分类规则：{word}'}
    return {'classification_reason': '没有匹配规则，已放入待整理'}


def retry_after(headers):
    value = headers.get('retry-after', '')
    try:
        return max(1, float(value))
    except ValueError:
        try:
            return max(1, (email.utils.parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError):
            try:
                reset = headers.get('x-ratelimit-reset')
                return max(1, float(reset) - time.time()) if reset else 60
            except ValueError:
                return 60


class Crawler:
    def __init__(self, transport=None, validator=validate_public_url, page_limit_mib=2):
        self.transport = transport
        self.validator = validator
        if type(page_limit_mib) is not int or not 1 <= page_limit_mib <= 10:
            raise ValueError('网页读取上限必须为 1–10 MiB 的整数')
        self.page_limit_mib = page_limit_mib

    async def read(self, url, limit=PAGE_LIMIT, accept='text/html', allow_json=False):
        # One overall deadline includes DNS, redirects and response streaming.
        async with asyncio.timeout(15):
            transport = self.transport or PublicTransport(retries=0)
            async with httpx.AsyncClient(transport=transport, timeout=15, trust_env=False, follow_redirects=False,
                                         headers={'User-Agent': 'LocalLinkAtlas/1.0', 'Accept': accept, 'Accept-Encoding': 'identity'}) as client:
                for redirects in range(4):
                    await asyncio.to_thread(self.validator, url)
                    async with client.stream('GET', url) as response:
                        if response.status_code in (301,302,303,307,308):
                            if redirects == 3:
                                raise ValueError('重定向超过 3 次')
                            url = canonical_url(urljoin(url, response.headers.get('location', '')))
                            continue
                        if response.status_code == 429 or response.status_code == 403 and (response.headers.get('x-ratelimit-remaining') == '0' or 'retry-after' in response.headers):
                            raise RateLimited(retry_after(response.headers))
                        response.raise_for_status()
                        content_type = response.headers.get('content-type', '').split(';')[0].lower()
                        disposition = response.headers.get('content-disposition', '').lower()
                        raw_readme = accept == 'application/vnd.github.raw+json' and content_type == 'application/vnd.github.raw+json'
                        if 'attachment' in disposition or not (content_type.startswith('text/') or raw_readme or allow_json and content_type == 'application/json'):
                            return b'', False, 'binary'
                        encoding = response.headers.get('content-encoding', 'identity').lower()
                        if encoding not in ('identity', '', 'gzip', 'deflate'):
                            return b'', False, 'unsupported'
                        decoder = zlib.decompressobj(16+zlib.MAX_WBITS if encoding == 'gzip' else zlib.MAX_WBITS) if encoding in ('gzip', 'deflate') else None
                        chunks = bytearray()
                        # MockTransport responses may already be consumed; production uses raw compressed chunks.
                        source = response.aiter_bytes(chunk_size=16384) if response.is_stream_consumed else response.aiter_raw(chunk_size=16384)
                        if response.is_stream_consumed:
                            decoder = None
                        async for chunk in source:
                            remaining = limit-len(chunks)
                            decoded = decoder.decompress(chunk, remaining) if decoder else chunk[:remaining]
                            chunks.extend(decoded)
                            if len(chunks) >= limit:
                                return bytes(chunks), True, content_type
                        return bytes(chunks), False, content_type
        raise ValueError('无效重定向')

    async def fetch(self, url):
        p = urlsplit(url)
        parts = [x for x in p.path.split('/') if x]
        if p.hostname in ('github.com', 'www.github.com') and len(parts) == 2 and re.fullmatch(r'[\w.-]+', parts[0]) and re.fullmatch(r'[\w.-]+', parts[1]):
            return await self.github(parts[0], parts[1].removesuffix('.git'))
        if re.search(r'\.(zip|tar|gz|7z|rar|exe|msi|pdf|mp4|mp3|iso|bin)(?:$|\?)', url, re.I):
            return {}, 'partial', '下载链接只保留地址，未下载文件'
        page_limit_mib = self.page_limit_mib
        body, truncated, content_type = await self.read(url, limit=page_limit_mib * 1024 * 1024)
        if content_type in ('binary', 'unsupported'):
            return {}, 'partial', '仅保留链接：非网页内容或不支持的编码'
        soup = BeautifulSoup(body, 'html.parser')
        title = soup.find('meta', property='og:title')
        title = title.get('content', '') if title else soup.title.get_text(' ', strip=True) if soup.title else ''
        description = soup.find('meta', attrs={'name': re.compile('^description$', re.I)}) or soup.find('meta', property='og:description')
        result = {k: v for k, v in {'title': title[:1000], 'description': (description.get('content', '') if description else '')[:2000]}.items() if v}
        message = f'网页达到 {page_limit_mib} MiB 读取上限，已截断' if truncated else '已提取网页信息' if result else '页面缺少静态元信息，可手动填写'
        return result, 'partial' if truncated or not result else 'success', message

    async def github(self, owner, name):
        root = f'https://api.github.com/repos/{owner}/{name}'
        body, truncated, content_type = await self.read(root, accept='application/vnd.github+json', allow_json=True)
        if truncated or content_type in ('binary', 'unsupported'):
            raise ValueError('仓库元信息过大或格式不支持')
        repo = json.loads(body)
        if repo.get('private'):
            raise ValueError('仅收录公共仓库')
        license_data = repo.get('license') or {}
        license_name = license_data.get('spdx_id')
        if not license_name or license_name == 'NOASSERTION':
            license_name = '许可证待核实'
        metadata = {'language': repo.get('language') or '未标注', 'topics': repo.get('topics', []), 'license': license_name,
                    'stars': repo.get('stargazers_count', 0), 'updated_at': repo.get('pushed_at'), 'readme': ''}
        status, message = 'success', '已收录项目索引；未下载源码'
        try:
            text, truncated, readme_type = await self.read(root+'/readme', README_LIMIT, 'application/vnd.github.raw+json')
            if readme_type in ('binary', 'unsupported'):
                status, message = 'partial', '仓库信息已保存，README 格式无法读取'
            else:
                metadata['readme'] = text.decode('utf-8', errors='replace')[:2000]
                metadata['readme_truncated'] = truncated or len(text.decode('utf-8', errors='replace')) > 2000
                if metadata['readme_truncated']:
                    status, message = 'partial', 'README 已截断，仅保存 2000 字摘要；未下载源码'
        except (httpx.HTTPError, TimeoutError, ValueError) as e:
            status, message = 'partial', f'仓库信息已保存，README 未获取：{str(e)[:200]}'
        return {'title': repo.get('full_name', f'{owner}/{name}'), 'description': (repo.get('description') or '')[:2000],
                'kind': 'repository', 'repo': metadata, 'tags': repo.get('topics', [])[:20]}, status, message


async def worker(store, stop):
    crawler = Crawler()
    while not stop.is_set():
        task = await asyncio.to_thread(store.claim_task)
        if not task:
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                pass
            continue
        try:
            crawler.page_limit_mib = (await asyncio.to_thread(store.settings))['page_limit_mib']
            result, status, message = await crawler.fetch(task['url'])
            resource = await asyncio.to_thread(store.get, task['resource_id'])
            categories = await asyncio.to_thread(store.categories)
            allowed = {c['id'] for c in categories if c['library_id'] == resource['library_id']}
            rules = [r for r in await asyncio.to_thread(store.rules) if r['category_id'] in allowed]
            result.update(classify({**result, 'url': task['url']}, rules))
            await asyncio.to_thread(store.apply_fetch, task['resource_id'], result, status, message)
            await asyncio.to_thread(store.finish_task, task['id'], status, message)
        except RateLimited as e:
            await asyncio.to_thread(store.finish_task, task['id'], 'queued', str(e), e.delay)
        except (httpx.TransportError, TimeoutError) as e:
            delay = 2 ** (task['attempts']+1) if task['attempts'] < 2 else None
            await asyncio.to_thread(store.finish_task, task['id'], 'failed', '网络请求失败：'+str(e)[:400], delay)
        except Exception as e:
            await asyncio.to_thread(store.finish_task, task['id'], 'failed', str(e)[:500])
