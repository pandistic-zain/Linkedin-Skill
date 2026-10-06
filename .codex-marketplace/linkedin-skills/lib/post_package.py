"""Validated post packages and bounded public-web reads. No publishing here."""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def public_url(url: str) -> str:
    parts = urlsplit(url)
    if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
            or parts.port not in (None, 443) or any(c.isspace() for c in url)):
        raise ValueError('expected a public HTTPS URL without credentials')
    if parts.hostname.lower() == 'localhost' or parts.hostname.endswith(('.local', '.internal')):
        raise ValueError('private destination is not allowed')
    return parts.hostname


class PublicConnection(http.client.HTTPSConnection):
    def connect(self):
        # Pin the validated address, but verify TLS against the original hostname.
        addresses = socket.getaddrinfo(self.host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('private or mixed DNS destination is not allowed')
        raw = socket.create_connection(addresses[0][4][:2], timeout=self.timeout)
        try:
            self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def fetch(url: str, *, maximum: int = 2_000_000) -> tuple[bytes, str, str]:
    for _ in range(5):
        host = public_url(url)
        parts = urlsplit(url)
        connection = PublicConnection(host, timeout=20)
        try:
            connection.request('GET', parts.path + ('?' + parts.query if parts.query else '') or '/',
                               headers={'User-Agent': 'LinkedInSkills/SourceReview', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise ValueError('redirect without destination')
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError(f'source returned HTTP {response.status}')
            data = response.read(maximum + 1)
            if len(data) > maximum:
                raise ValueError('source exceeds size limit')
            return data, response.getheader('Content-Type', '').split(';')[0].lower(), url
        finally:
            connection.close()
    raise ValueError('too many redirects')


class Page(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.parts: list[str] = []
        self.images: list[str] = []
        self.links: list[str] = []
        self.dates: list[str] = []
        self.hidden = 0
        self.feed(html)
        for script in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I):
            try:
                def dates(value):
                    if isinstance(value, dict):
                        for key, child in value.items():
                            if key == 'datePublished' and isinstance(child, str):
                                self.dates.append(child)
                            else:
                                dates(child)
                    elif isinstance(value, list):
                        for child in value:
                            dates(child)
                dates(json.loads(script))
            except (ValueError, RecursionError):
                continue  # Invalid publisher metadata is not evidence of a date.

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('script', 'style', 'noscript'):
            self.hidden += 1
        if tag == 'meta':
            key = a.get('property', a.get('name', ''))
            if key in ('article:published_time', 'date', 'datePublished'):
                self.dates.append(a.get('content', ''))
            if key == 'og:image':
                self.images.append(a.get('content', ''))
        if tag == 'time' and a.get('datetime'):
            self.dates.append(a['datetime'])
        if tag == 'img' and a.get('src'):
            self.images.append(a['src'])
        if tag == 'a' and a.get('href'):
            self.links.append(a['href'])

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    @property
    def text(self):
        return ' '.join(' '.join(self.parts).split())


def read_page(url: str) -> tuple[Page, str]:
    data, mime, final = fetch(url)
    if mime not in ('text/html', 'application/xhtml+xml', 'text/plain'):
        raise ValueError('source must be a readable HTML/text page')
    return Page(data.decode('utf-8', errors='replace')), final


def text_field(obj: dict, key: str, maximum: int = 2000) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'missing or invalid {key}')
    return value.strip()


def json_object(raw: str) -> dict:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('expected a JSON object, without prose or fences')
    return value


def body_problem(body: str) -> str | None:
    if not isinstance(body, str) or not 300 <= len(body) <= 3000:
        return 'post must contain 300-3000 characters'
    if re.search(r'(?im)^\s*(?:P\.?S\.?\s*[:.]|FORMULA:|MOTIF:|WHY:|```|#\s)', body):
        return 'post contains a P.S., metadata, or Markdown wrapper'
    if re.search(r"(?i)(good (?:enough )?length|my final draft|final output|here(?: is|'s) the (?:post|draft)|\b\d+ chars?\b|character count)", body):
        return 'post contains drafting commentary'
    return None


def validate_visual(v: dict) -> dict:
    if not isinstance(v, dict) or v.get('kind') not in ('comparison', 'checklist', 'process', 'sourced'):
        raise ValueError('visual must be comparison, checklist, process or sourced')
    text_field(v, 'alt', 1000)
    if v['kind'] == 'comparison':
        for key, limit in [('title', 100), ('leftTitle', 45), ('rightTitle', 45), ('takeaway', 140)]:
            text_field(v, key, limit)
        for key in ('left', 'right'):
            rows = v.get(key)
            if not isinstance(rows, list) or not 2 <= len(rows) <= 4 or any(
                    not isinstance(x, str) or not x.strip() or len(x) > 90 for x in rows):
                raise ValueError('comparison needs 2-4 concise points per side')
    elif v['kind'] in ('checklist', 'process'):
        for key, limit in [('title', 100), ('takeaway', 140)]:
            text_field(v, key, limit)
        rows = v.get('items')
        if not isinstance(rows, list) or not 3 <= len(rows) <= 5 or any(
                not isinstance(x, str) or not x.strip() or len(x) > 140 for x in rows):
            raise ValueError('visual needs 3-5 concise items')
    else:
        for key in ('url', 'sourceUrl', 'licenseUrl'):
            public_url(text_field(v, key))
        for key in ('credit', 'licenseQuote'):
            text_field(v, key)
        if v.get('license') not in ('CC0', 'CC BY 4.0'):
            raise ValueError('sourced image needs verified CC0 or CC BY 4.0 terms; otherwise make an original')
    return v


def inspect_image(data: bytes) -> dict:
    from PIL import Image
    if len(data) > 8_000_000:
        raise ValueError('image exceeds 8 MB')
    with Image.open(BytesIO(data)) as im:
        if im.format not in ('PNG', 'JPEG', 'WEBP') or min(im.size) < 400 or max(im.size) > 8000:
            raise ValueError('image must be a readable PNG/JPEG/WebP, 400-8000 pixels')
        if im.width * im.height > 25_000_000:
            raise ValueError('image pixel limit exceeded')
        info = {'width': im.width, 'height': im.height, 'mime': Image.MIME[im.format]}
        im.verify()
    return {**info, 'sha256': digest(data)}


def revision(package: dict) -> str:
    fields = {k: package.get(k) for k in ('body', 'sources', 'visual', 'media', 'postGroupId', 'audit')}
    return digest(json.dumps(fields, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode())


def publish_problem(package: dict) -> str | None:
    problem = body_problem(package.get('body', ''))
    if problem:
        return problem
    if package.get('revision') != revision(package):
        return 'package changed after review'
    audit = package.get('audit', {})
    if (audit.get('verdict') != 'pass' or audit.get('blockers') != []
            or audit.get('imageInspected') is not True):
        return 'package audit has not passed'
    media = package.get('media', {})
    if not media.get('url') or not media.get('sha256') or not package.get('postGroupId'):
        return 'prepared media is missing'
    if not package.get('sources'):
        return 'verified sources are missing'
    for source in package['sources']:
        if source['url'] not in package['body']:
            return 'source attribution is missing from the post'
        age = (datetime.now(timezone.utc).date() - datetime.strptime(source['publishedAt'], '%Y-%m-%d').date()).days
        if not 0 <= age <= 30:
            return 'source needs fresh review before publishing'
    return None
