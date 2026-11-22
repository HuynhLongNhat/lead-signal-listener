"""SearXNG -> Trafilatura -> evidence-first pain/opportunity detection.

No outbound requests happen unless run() is invoked. All external calls are bounded.
Leads from Lead Signal Listener are read locally, not silently re-scraped.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

USER_AGENT = 'HADES-Market-Intelligence/0.1 (public research; user-operated)'
MAX_HTML_BYTES = 2_000_000
MAX_RESULT_TEXT = 16000

# Intentionally narrow. These are signals for review, NOT proof of purchasing intent.
PAIN_RULES = {
    'customer_acquisition': ['khó tìm khách', 'không có khách', 'ít khách', 'không ra đơn', 'mất khách', 'không có đơn', 'khó chốt đơn', 'struggling to get customers', 'no customers'],
    'customer_support': ['bỏ sót tin nhắn', 'quá tải tin nhắn', 'trả lời khách chậm', 'không trả lời kịp', 'khó chăm sóc khách', 'missed messages', 'slow response'],
    'operations': ['quản lý bằng excel', 'khó quản lý đơn', 'tốn thời gian nhập liệu', 'sai sót đơn hàng', 'không quản lý nổi', 'manual data entry', 'too much manual work'],
    'website': ['website chậm', 'web chậm', 'website bị lỗi', 'không đặt hàng được', 'website không hoạt động', 'site is slow', 'website broken'],
    'marketing': ['quảng cáo không hiệu quả', 'chạy quảng cáo không ra đơn', 'chi phí quảng cáo cao', 'không biết chạy quảng cáo', 'ads not converting'],
}
INTENT_TERMS = ['cần thuê', 'đang tìm dịch vụ', 'có ai giới thiệu', 'xin báo giá', 'tìm đơn vị', 'looking to hire', 'looking for an agency']
NEGATIVE_TERMS = ['mình nhận làm', 'chúng tôi cung cấp', 'ưu đãi lớn', 'liên hệ để mua', 'our agency offers']


def canonical_url(url: str) -> str:
    """Discard trackers/fragments; only accept normal HTTPS/HTTP URLs."""
    p = urllib.parse.urlsplit(str(url).strip())
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('URL không hợp lệ hoặc không phải HTTP(S)')
    host = p.hostname.lower()
    if host in ('localhost',) or host.endswith('.local') or host.endswith('.internal'):
        raise ValueError('Không truy cập host nội bộ')
    query = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
    query = [(k, v) for k, v in query if not k.lower().startswith(('utm_', 'fbclid', 'gclid'))]
    netloc = host + ((':' + str(p.port)) if p.port else '')
    return urllib.parse.urlunsplit((p.scheme, netloc, p.path or '/', urllib.parse.urlencode(query), ''))


def check_public_host(url: str) -> None:
    """Basic SSRF check. Not a substitute for a network-level egress policy."""
    host = urllib.parse.urlsplit(canonical_url(url)).hostname
    try:
        answers = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f'Không phân giải được máy chủ: {host}') from exc
    if not answers or any(not ipaddress.ip_address(a[4][0]).is_global for a in answers):
        raise ValueError('Chặn địa chỉ mạng riêng / nội bộ')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Disallow redirects so a public site cannot redirect to a private IP."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Không theo chuyển hướng HTTP')


def http_get(url: str, *, timeout: int = 12, check_host: bool = True) -> bytes:
    if check_host:
        check_public_host(url)
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json,text/html;q=0.9'})
    with urllib.request.build_opener(NoRedirect).open(req, timeout=timeout) as response:
        content_type = response.headers.get('Content-Type', '').lower()
        if 'application/octet-stream' in content_type:
            raise ValueError('Từ chối nội dung nhị phân')
        raw = response.read(MAX_HTML_BYTES + 1)
    if len(raw) > MAX_HTML_BYTES:
        raise ValueError('Nội dung vượt quá giới hạn dung lượng')
    return raw


@dataclass
class Evidence:
    url: str
    source: str
    title: str
    excerpt: str
    query: str
    published_at: str = ''
    first_seen: int = 0


def normalize_text(text: str) -> str:
    return re.sub(r'\s+', ' ', text or '').strip()


def detect(text: str) -> list[dict]:
    """Deterministic, explainable signal detector; never calls an LLM."""
    hay = normalize_text(text).casefold()
    if not hay:
        return []
    intent = [p for p in INTENT_TERMS if p in hay]
    negative = [p for p in NEGATIVE_TERMS if p in hay]
    results = []
    for category, phrases in PAIN_RULES.items():
        found = [p for p in phrases if p in hay]
        if not found:
            continue
        # Confidence describes keyword evidence strength, not likelihood of buying.
        score = max(0, min(100, 30 + min(25, 10 * len(found)) + (20 if intent else 0) - (35 if negative else 0)))
        results.append({'category': category, 'matched': found, 'intent_terms': intent,
                        'negative_terms': negative, 'signal_score': score})
    return results


class MarketStore:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS evidence (
                url TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT, excerpt TEXT,
                query TEXT, published_at TEXT, first_seen INTEGER, last_seen INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS analyses (
                url TEXT NOT NULL, category TEXT NOT NULL, result TEXT NOT NULL,
                analyzed_at INTEGER NOT NULL, PRIMARY KEY(url,category)
            );
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_at INTEGER NOT NULL,
                mode TEXT NOT NULL, query TEXT NOT NULL, found INTEGER NOT NULL,
                inserted INTEGER NOT NULL, failures TEXT NOT NULL
            );
        ''')
        self.db.commit()

    def put(self, item: Evidence) -> bool:
        now = int(time.time())
        cur = self.db.execute('''INSERT OR IGNORE INTO evidence
          (url,source,title,excerpt,query,published_at,first_seen,last_seen)
          VALUES(?,?,?,?,?,?,?,?)''',
          (item.url, item.source, item.title, item.excerpt, item.query,
           item.published_at, item.first_seen or now, now))
        if cur.rowcount == 0:
            self.db.execute('UPDATE evidence SET last_seen=? WHERE url=?', (now, item.url))
        self.db.commit()
        return bool(cur.rowcount)

    def analyze(self, item: Evidence) -> list[dict]:
        results = detect(item.title + '. ' + item.excerpt)
        now = int(time.time())
        for result in results:
            self.db.execute('INSERT OR REPLACE INTO analyses VALUES(?,?,?,?)',
                            (item.url, result['category'], json.dumps(result, ensure_ascii=False), now))
        self.db.commit()
        return results

    def report(self, *, min_score=30, limit=200) -> dict:
        rows = self.db.execute('''SELECT e.url,e.source,e.title,e.excerpt,e.query,e.published_at,
                    a.category,a.result FROM analyses a JOIN evidence e ON e.url=a.url
                    ORDER BY a.analyzed_at DESC LIMIT ?''', (max(1, min(limit, 2000)),)).fetchall()
        groups = defaultdict(list)
        for row in rows:
            result = json.loads(row['result'])
            if result['signal_score'] < min_score:
                continue
            groups[row['category']].append({'url': row['url'], 'source': row['source'],
                    'title': row['title'], 'excerpt': row['excerpt'][:400], 'query': row['query'],
                    'matched': result['matched'], 'intent_terms': result['intent_terms'],
                    'signal_score': result['signal_score'], 'published_at': row['published_at']})
        categories = []
        for category, evidence in sorted(groups.items(), key=lambda x: (-len(x[1]), x[0])):
            categories.append({'pain_category': category, 'evidence_count': len(evidence),
                'opportunity_hypothesis': f'Có thể nghiên cứu giải pháp cho nhóm vấn đề {category}. Cần xác minh nhu cầu mua.',
                'evidence': evidence})
        return {'status': 'hypotheses_not_verified_buyers', 'total_evidence': sum(len(x['evidence']) for x in categories),
                'opportunities': categories, 'warning': 'Điểm tín hiệu không phải xác suất mua; cần xác minh thủ công.'}

    def log_run(self, mode, query, found, inserted, failures):
        self.db.execute('INSERT INTO runs(run_at,mode,query,found,inserted,failures) VALUES(?,?,?,?,?,?)',
                        (int(time.time()), mode, query, found, inserted, json.dumps(failures, ensure_ascii=False)))
        self.db.commit()


def search_searxng(base_url: str, query: str, *, limit: int = 10,
                   fetch: Callable = http_get) -> list[dict]:
    """SearXNG must be explicitly configured with JSON format enabled."""
    if not base_url:
        raise ValueError('Thiếu SEARXNG_URL; cần chạy SearXNG và bật format=json')
    p = urllib.parse.urlsplit(base_url)
    # Local SearXNG is an intentional exception to public-host policy.
    if p.scheme not in ('http', 'https') or p.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('SEARXNG_URL chỉ được trỏ tới SearXNG cục bộ')
    url = base_url.rstrip('/') + '/search?' + urllib.parse.urlencode({'q': query, 'format': 'json', 'language': 'vi'})
    raw = fetch(url, check_host=False)
    try:
        data = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError('SearXNG không trả JSON; hãy bật JSON trong settings.yml') from exc
    if not isinstance(data.get('results'), list):
        raise ValueError('SearXNG trả về dữ liệu không hợp lệ')
    return data['results'][:max(1, min(50, limit))]


def extract_article(url: str, *, fetch: Callable = http_get) -> str:
    """Use Trafilatura for main article content; never invent text on failure."""
    try:
        import trafilatura
    except ImportError as exc:
        raise RuntimeError('Cần cài trafilatura: pip install trafilatura') from exc
    html = fetch(url).decode('utf-8', errors='replace')
    return normalize_text(trafilatura.extract(html, include_comments=False, include_tables=False) or '')[:MAX_RESULT_TEXT]


def normalize_result(record: dict, query: str, *, fetch: Callable = http_get,
                     enrich: bool = True) -> Evidence:
    url = canonical_url(record.get('url', ''))
    title = normalize_text(str(record.get('title') or ''))[:300]
    snippet = normalize_text(str(record.get('content') or ''))[:MAX_RESULT_TEXT]
    if enrich:
        try:
            article = extract_article(url, fetch=fetch)
            if article:
                snippet = article
        except (ValueError, RuntimeError, OSError, urllib.error.URLError):
            # Keep a traceable snippet when a website blocks extraction.
            pass
    return Evidence(url=url, source='searxng', title=title, excerpt=snippet, query=query,
                    published_at=str(record.get('publishedDate') or ''))


def import_listener_signals(store: MarketStore, listener_db: str | Path,
                            *, limit: int = 500, min_score: int = 10) -> dict:
    """Read existing Lead Signal Listener records (read-only SQLite URI)."""
    path = Path(listener_db).resolve()
    if not path.is_file():
        raise FileNotFoundError(f'Không thấy cơ sở dữ liệu Lead Signal Listener: {path}')
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('''SELECT source,title,text,url,query,first_seen FROM signals
          WHERE score >= ? AND url IS NOT NULL AND url != ''
          ORDER BY score DESC LIMIT ?''', (min_score, max(1, min(limit, 2000)))).fetchall()
    conn.close()
    inserted, analyzed, failures = 0, 0, []
    for r in rows:
        try:
            item = Evidence(url=canonical_url(r['url']), source=r['source'],
                  title=r['title'] or '', excerpt=(r['text'] or '')[:MAX_RESULT_TEXT],
                  query=r['query'] or '', first_seen=r['first_seen'] or 0)
            inserted += store.put(item)
            analyzed += len(store.analyze(item))
        except (ValueError, TypeError) as exc:
            failures.append(str(exc))
    store.log_run('listener', str(path), len(rows), inserted, failures[:30])
    return {'found': len(rows), 'new_evidence': inserted, 'pain_matches': analyzed,
            'errors': failures[:30]}


def run_web(store: MarketStore, *, searxng_url: str, queries: list[str],
            limit_per_query: int = 10, enrich: bool = True,
            fetch: Callable = http_get) -> dict:
    if not queries or len(queries) > 12 or any(not isinstance(q, str) or len(q.strip()) < 3 or len(q) > 160 for q in queries):
        raise ValueError('Cần 1–12 truy vấn có độ dài 3–160 ký tự')
    total, inserted, signals, errors = 0, 0, 0, []
    for q in queries:
        try:
            results = search_searxng(searxng_url, q, limit=limit_per_query, fetch=fetch)
        except (ValueError, OSError, urllib.error.URLError) as exc:
            errors.append({'query': q, 'error': str(exc)})
            continue
        for result in results:
            total += 1
            try:
                item = normalize_result(result, q, fetch=fetch, enrich=enrich)
                inserted += store.put(item)
                signals += len(store.analyze(item))
            except (ValueError, TypeError, OSError) as exc:
                errors.append({'query': q, 'error': str(exc)})
    store.log_run('web', ','.join(queries), total, inserted, errors[:30])
    return {'found': total, 'new_evidence': inserted, 'pain_matches': signals,
            'errors': errors[:30], 'report': store.report()}
