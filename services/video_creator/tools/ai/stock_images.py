"""Licensed-photo search before AI fallback; credentials remain server-side."""
import hashlib
import json
import re
import sqlite3
import time
from contextlib import closing
from urllib.parse import urlsplit

import requests

from services.core.storage import service_store
from .config_store import ProviderConfigStore
from .image_priority import PriorityImageTool, save_image

SOURCES = {
    'stock_pixabay': {'name': 'Pixabay', 'endpoint': 'https://pixabay.com/api/', 'domain': 'pixabay.com',
                      'license': 'Pixabay Content License', 'license_url': 'https://pixabay.com/service/license-summary/'},
    'stock_pexels': {'name': 'Pexels', 'endpoint': 'https://api.pexels.com/v1/search', 'domain': 'pexels.com',
                     'license': 'Pexels License', 'license_url': 'https://www.pexels.com/license/'},
}


def trusted_url(url, domain):
    parts = urlsplit(str(url))
    return parts.scheme == 'https' and (parts.hostname == domain or (parts.hostname or '').endswith('.' + domain)) and not parts.username


def matches_subject(description,subject):
    patterns={'finance':r'\b(financ\w*|stocks?|forex|trading|nasdaq|securities|investment|börse)\b',
              'semiconductor':r'\b(semiconductor\w*|silicon|microchip\w*|chipset|microprocessor\w*|circuit\w*|electronics?|memory module)\b'}
    return subject not in patterns or bool(re.search(patterns[subject],str(description).lower()))


class StockFirstImageTool:
    def __init__(self, directory=None, *, ai=None, stock_only=False, sources=None, background_only=False):
        self.directory = directory or service_store('video_creator')
        self.directory.mkdir(parents=True, exist_ok=True)
        self.providers = ProviderConfigStore(self.directory / 'provider_configs.json')
        self.ai = ai or PriorityImageTool(self.directory)
        self.stock_only = stock_only
        self.background_only = background_only
        self.sources = tuple(sources or SOURCES)
        if any(source not in SOURCES for source in self.sources):raise ValueError('不支持的图库来源')
        self.seen = set()
        self.cache = self.directory / 'stock_search_cache.sqlite3'
        with closing(sqlite3.connect(self.cache, timeout=30)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS searches (key TEXT PRIMARY KEY, created_at REAL NOT NULL, photos TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS photo_usage (provider TEXT NOT NULL, photo_id TEXT NOT NULL, used_at REAL NOT NULL, PRIMARY KEY(provider,photo_id))')
            db.execute('CREATE TABLE IF NOT EXISTS usage_migrations (name TEXT PRIMARY KEY)')
            seeded = db.execute("SELECT 1 FROM usage_migrations WHERE name='publication-traces-v1'").fetchone()
        if not seeded:
            # Include existing publications, so upgrading does not select the old cover again.
            records=[]
            for path in (service_store('douyin')/'web_downloads'/'publications').glob('*/*/*/illustration-*-trace.json'):
                try:
                    trace=json.loads(path.read_text(encoding='utf-8'))
                    if trace.get('provider') in SOURCES and trace.get('id'):
                        records.append((trace['provider'],str(trace['id']),float(trace.get('downloaded_at') or path.stat().st_mtime)))
                except (OSError,ValueError,TypeError):
                    continue
            with closing(sqlite3.connect(self.cache, timeout=30)) as db, db:
                db.executemany('INSERT OR IGNORE INTO photo_usage VALUES (?,?,?)',records)
                db.execute("INSERT OR IGNORE INTO usage_migrations VALUES ('publication-traces-v1')")

    def claim_photo(self, provider, identifier):
        with closing(sqlite3.connect(self.cache, timeout=30)) as db, db:
            db.execute('DELETE FROM photo_usage WHERE used_at<?',(time.time()-90*86400,))
            return db.execute('INSERT OR IGNORE INTO photo_usage VALUES (?,?,?)',
                              (provider,str(identifier),time.time())).rowcount == 1

    def search(self, provider, config, query, aspect):
        token = config.get('api_key') or ''
        key = hashlib.sha256(json.dumps([provider, token, query, aspect]).encode()).hexdigest()
        with closing(sqlite3.connect(self.cache, timeout=30)) as db:
            row = db.execute('SELECT created_at,photos FROM searches WHERE key=?', (key,)).fetchone()
        if row and time.time() - row[0] < 86400:
            return json.loads(row[1])
        portrait = aspect in ('3:4', '9:16')
        if provider == 'stock_pixabay':
            params = {'key': token, 'q': query[:100], 'image_type': 'photo', 'safesearch': 'true',
                      'orientation': 'vertical' if portrait else 'horizontal', 'per_page': 12, 'min_width': 1000}
            headers = {}
        else:
            params = {'query': query, 'orientation': 'portrait' if portrait else 'landscape', 'per_page': 12, 'locale': 'en-US'}
            headers = {'Authorization': token}
        # Do not expose request URLs: Pixabay places the credential in its query string.
        with requests.get(SOURCES[provider]['endpoint'], params=params, headers=headers, timeout=(10, 25)) as response:
            if response.status_code != 200:
                raise RuntimeError(f'{SOURCES[provider]["name"]} 搜图失败 HTTP {response.status_code}')
            data = response.json()
        photos = []
        for item in data.get('hits' if provider == 'stock_pixabay' else 'photos', []):
            if provider == 'stock_pixabay':
                if item.get('type') != 'photo': continue
                photo = {'id': str(item.get('id', '')), 'url': item.get('largeImageURL'), 'page_url': item.get('pageURL'),
                         'author': item.get('user'), 'description': item.get('tags', ''), 'width': item.get('imageWidth', 0), 'height': item.get('imageHeight', 0)}
            else:
                photo = {'id': str(item.get('id', '')), 'url': item.get('src', {}).get('large2x') or item.get('src', {}).get('original'),
                         'page_url': item.get('url'), 'author': item.get('photographer'), 'description': item.get('alt', ''),
                         'width': item.get('width', 0), 'height': item.get('height', 0)}
            description = str(photo['description']).lower()
            if item.get('is_ai_generated') or item.get('ai_generated') or re.search(r'ai.generated|generative ai|3d render|digital illustration', description): continue
            if not photo['id'] or not photo['author'] or min(int(photo['width']), int(photo['height'])) < 700: continue
            if not trusted_url(photo['url'], SOURCES[provider]['domain']) or not trusted_url(photo['page_url'], SOURCES[provider]['domain']): continue
            photo.update(provider=provider, license=SOURCES[provider]['license'], license_url=SOURCES[provider]['license_url'])
            photos.append(photo)
        with closing(sqlite3.connect(self.cache, timeout=30)) as db, db:
            db.execute('INSERT OR REPLACE INTO searches VALUES (?,?,?)', (key, time.time(), json.dumps(photos)))
            db.execute('DELETE FROM searches WHERE created_at<?', (time.time()-7*86400,))
        return photos

    def generate(self, prompt, target, progress=lambda trace: None, *, aspect='16:9', search_terms=()):
        attempts = []
        for provider in self.sources:
            config = self.providers.get_by_provider(provider) or {}
            if not config.get('api_key') or config.get('enabled') is False:
                attempts.append({'provider': provider, 'outcome': 'not_configured'})
                continue
            queries = list(search_terms)[:3]
            # Pixabay combines words; short physical queries rescue overly specific LLM phrases.
            for term in list(queries):
                words = [w for w in re.findall(r'[a-z]+', term.lower()) if w not in {'the','with','and','natural','light','bright','warm','cozy','daylight','photo','photography','realistic','close'}]
                if len(words) >= 2:
                    broad = ' '.join(words[:2])
                    if broad not in queries:queries.append(broad)
            for query in queries[:5]:
                progress({'status': 'running', 'provider': provider, 'message': f'检索{SOURCES[provider]["name"]}照片：{query}', 'stock_search': list(attempts)})
                try:
                    photos = self.search(provider, config, query, aspect)
                    tokens = set(re.findall(r'[a-z]{3,}', query.lower())) - {'and','the','with','for'}
                    ranked = sorted(photos, key=lambda p: -len(tokens & set(re.findall(r'[a-z]{3,}', str(p['description']).lower()))))
                    for photo in ranked:
                        if not matches_subject(photo['description'],getattr(self,'required_subject',None)):continue
                        if self.background_only and re.search(r'\b(toilet|bathroom|washroom|lingerie|bikini|circus|referee)\b',str(photo['description']).lower()):continue
                        identity = (provider, photo['id'])
                        if identity in self.seen: continue
                        if tokens and not tokens.intersection(re.findall(r'[a-z]{3,}', str(photo['description']).lower())): continue
                        if not self.claim_photo(provider, photo['id']): continue
                        try:
                            save_image(photo['url'], target)
                        except Exception:
                            with closing(sqlite3.connect(self.cache, timeout=30)) as db, db:
                                db.execute('DELETE FROM photo_usage WHERE provider=? AND photo_id=?',(provider,str(photo['id'])))
                            raise
                        self.seen.add(identity)
                        trace = {**{k: photo[k] for k in ('id','provider','page_url','author','license','license_url','description')},
                                 'status': 'done', 'model': 'stock_photo', 'query': query, 'aspect': aspect, 'file': target.name,
                                 'message': '图库照片已保存', 'kind': 'stock_photo', 'ai_generated': False,
                                 'verification': 'provider_photo_category_and_metadata_filter', 'stock_search': attempts,
                                 'attribution': f'Photo by {photo["author"]} on {SOURCES[provider]["name"]}', 'downloaded_at': time.time()}
                        target.with_name(target.stem+'-trace.json').write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')
                        progress(dict(trace))
                        return trace
                    attempts.append({'provider': provider, 'query': query, 'outcome': 'no_suitable_photo'})
                except Exception as exc:
                    attempts.append({'provider': provider, 'query': query, 'outcome': 'search_or_download_failed',
                                     'error': str(exc) if type(exc) is RuntimeError else '图库请求或素材下载失败'})
        reason = '图库未配置或没有合适照片，使用AI补图'
        if self.stock_only:
            trace = {'status':'error','provider':self.sources[0],'message':'本次限定图库配图，未获取到合适照片；没有调用AI',
                     'stock_search':attempts,'ai_generated':False}
            target.with_name(target.stem+'-trace.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf-8')
            progress(trace)
            raise RuntimeError(trace['message'])
        def changed(trace):
            trace = {**trace, 'stock_search': list(attempts), 'stock_fallback_reason': reason, 'ai_generated': True}
            target.with_name(target.stem+'-trace.json').write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')
            progress(trace)
        result = self.ai.generate(prompt, target, changed, aspect=aspect)
        result.update(stock_search=attempts, stock_fallback_reason=reason, ai_generated=True)
        changed(result)
        return result
