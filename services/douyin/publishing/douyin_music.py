"""Select real creator-center music; never infer binding from an LLM suggestion."""
import json
import math
import re
from pathlib import Path
from urllib.parse import urlsplit


def is_music_search_url(url):
    parts = urlsplit(url)
    return (parts.scheme == 'https' and parts.hostname in ('creator.douyin.com', 'tsearch.amemv.com')
            and parts.path == '/openapi/aweme/v1/music/search/')


def music_candidates(value):
    found = []
    if isinstance(value, dict):
        # Search results contain an original_sound child with another ID. The
        # parent mid is the selectable track, not that child's source identity.
        identifier = value.get('mid') or value.get('music_id')
        title = value.get('title') or value.get('music_name')
        if identifier and isinstance(title, str) and title.strip():
            identifier = str(identifier)
            duration = value.get('duration')
            if (re.fullmatch(r'\d{5,25}', identifier) and type(duration) in (int, float)
                    and duration >= 5 and value.get('can_use') is not False):
                found.append({'music_id': identifier, 'title': title.strip(),
                              'author': value.get('author') if isinstance(value.get('author'), str) else '',
                              'duration_seconds': duration})
            return found
        for child in value.values():
            found.extend(music_candidates(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(music_candidates(child))
    return list({item['music_id']: item for item in found}.values())


def music_queries(plan):
    words = plan.get('keywords') if isinstance(plan, dict) else None
    if not isinstance(words, list):
        raise ValueError('缺少配乐搜索词，请先生成抖音配乐方案')
    queries = list(dict.fromkeys(w.strip() for w in words if isinstance(w, str) and 0 < len(w.strip()) <= 80))[:3]
    if not queries:
        raise ValueError('缺少有效的配乐搜索词，未提交发布')
    return queries


def require_music_payload(payload, selected):
    item = payload.get('item') if isinstance(payload, dict) else None
    common = item.get('common') if isinstance(item, dict) else None
    identifier = common.get('music_id') if isinstance(common, dict) else None
    if (not selected or selected.get('status') != 'selected' or
            type(identifier) not in (str, int) or str(identifier) != selected.get('music_id') or
            not re.fullmatch(r'\d{5,25}', str(identifier))):
        raise ValueError('发布请求未绑定所选音乐，已拦截提交')
    result = {'music_id': str(identifier)}
    end = common.get('music_end_time')
    start = common.get('music_start_time', 0)
    if (type(end) not in (int, float) or type(start) not in (int, float)
            or not math.isfinite(end) or not math.isfinite(start) or not 0 <= start < end):
        raise ValueError('配乐播放区间无效，已拦截提交')
    result.update(start_time_ms=start, end_time_ms=end)
    return result


def guard_music_request(route, selected, state, on_forward):
    request = route.request
    parts = urlsplit(request.url)
    if (request.method == 'POST' and parts.hostname == 'creator.douyin.com'
            and re.search(r'/aweme/.*(?:create|publish)', parts.path)):
        try:
            state['submitted'] = require_music_payload(request.post_data_json, selected)
        except Exception:
            state['blocked'] = '发布请求未绑定所选音乐，已拦截提交'
            route.abort()
            return
        on_forward()  # Mark uncertain outcomes before the request can leave the browser.
    route.continue_()


def select_music(page, content, directory, progress=None):
    queries = music_queries(content.get('music'))
    progress = progress or (lambda message: None)
    directory = Path(directory)
    trace = {'status': 'searching', 'required': True, 'queries': queries, 'attempts': []}
    def save():
        (directory / 'music.json').write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    try:
        page.get_by_text('选择音乐', exact=True).last.click()
        search = page.get_by_placeholder('搜索音乐', exact=True)
        search.wait_for(state='visible')
        for query in queries:
            progress('正在匹配抖音曲库配乐：' + query)
            def searched(response):
                return is_music_search_url(response.url)
            try:
                with page.expect_response(searched, timeout=25000) as response:
                    search.fill(query)
                    search.press('Enter')
                value = response.value.json()
            except Exception as exc:
                trace['attempts'].append({'query': query, 'status': 'search_failed', 'exception': type(exc).__name__})
                save()
                continue
            if not isinstance(value, dict) or value.get('status_code') != 0:
                trace['attempts'].append({'query': query, 'status': 'platform_rejected'})
                save()
                continue
            candidates = music_candidates(value)
            preferred = (content.get('preflight') or {}).get('music') or {}
            if preferred.get('music_id'):
                candidates = [c for c in candidates if c['music_id'] == preferred['music_id']]
            trace['attempts'].append({'query': query, 'candidates': candidates[:10]})
            save()
            for candidate in candidates[:3]:
                row = page.locator('[class*="card-wrapper-"]').filter(
                    has=page.get_by_text(candidate['title'], exact=True))
                if candidate['author']:
                    row = row.filter(has_text=candidate['author'])
                try:
                    row.first.wait_for(state='visible', timeout=8000)
                    if row.count() != 1:
                        continue  # Ambiguous title/artist rows must not bind an arbitrary ID.
                    row.hover()
                    use = row.get_by_text('使用', exact=True)
                    use.wait_for(state='visible', timeout=3000)
                    if not use.is_enabled() or use.get_attribute('aria-disabled') == 'true':
                        continue
                except Exception:
                    continue
                use.click()
                search.wait_for(state='hidden', timeout=10000)
                page.get_by_text('修改音乐', exact=True).wait_for(state='visible', timeout=10000)
                visible_title = page.get_by_text(candidate['title'], exact=True)
                if not any(visible_title.nth(i).is_visible() for i in range(visible_title.count())):
                    raise ValueError('音乐选择后未显示真实曲名，未提交发布')
                selected = {**candidate, 'status': 'selected', 'source': 'douyin_creator_catalog', 'query': query}
                trace.update(status='selected', selected=selected)
                save()
                progress('已选择抖音配乐：' + candidate['title'])
                return selected
        raise ValueError('未能匹配并绑定可用的抖音配乐，未提交发布')
    except Exception:
        trace['status'] = 'error'
        save()
        raise
