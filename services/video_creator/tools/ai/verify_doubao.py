"""Staged acceptance: original test.py must produce an image before service testing.

This is a diagnostic entry point, not a production dependency on cache/test.py.
No generation POST is retried. Captured credentials and request bodies are not logged.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import logging
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import cv2
import requests

from services.core.storage import ROOT, service_store


def business_errors(raw: str) -> list[dict]:
    """Check API status independently of test.py's HTTP-only success flag."""
    events = []
    try:
        events.append(json.loads(raw))
    except ValueError:
        for line in raw.splitlines():
            if line.startswith('data:'):
                try:
                    events.append(json.loads(line[5:].strip()))
                except ValueError:
                    pass
    failures = []

    def visit(node):
        if isinstance(node, dict):
            code = node.get('status_code', node.get('code'))
            if code not in (None, 0, '0', 200, '200'):
                # Numeric codes can be retained without copying provider error text.
                safe = str(code)
                if len(safe) > 80 or not all(c.isalnum() or c in '_.-' for c in safe):
                    safe = 'unknown'
                failures.append({'code':safe})
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    for event in events:
        visit(event)
    return failures


def download_and_verify(urls, directory):
    artifacts = []
    for index, url in enumerate(dict.fromkeys(urls), 1):
        if not isinstance(url, str) or urlsplit(url).scheme not in ('http', 'https'):
            raise RuntimeError('输出图片地址无效')
        with requests.get(url, timeout=(15, 120)) as response:
            response.raise_for_status()
            data = response.content
        target = directory / f'image_{index}.png'
        target.write_bytes(data)
        image = cv2.imread(str(target))
        if image is None or not image.size:
            raise RuntimeError('下载文件无法解码为图片')
        artifacts.append({'file':target.name, 'bytes':len(data), 'width':int(image.shape[1]),
                          'height':int(image.shape[0]), 'sha256':hashlib.sha256(data).hexdigest()})
    return artifacts


def run_original(module, prompt, directory, handler=None):
    directory.mkdir(parents=True, exist_ok=True)
    handler = handler or module.SimpleDoubaoHandler()
    # Run once through the original implementation; never call its batch main().
    result = handler.process_message(prompt)
    parsed = module.parseResponse(result)
    failures = business_errors(result.get('raw_response') or '')
    urls = parsed.get('image_urls') or []
    summary = {'http_status':result.get('status_code'), 'script_status':parsed.get('status'),
               'business_errors':failures, 'image_count':len(urls), 'status':'error'}
    if failures:
        summary['reason'] = '豆包业务错误；HTTP 200 不代表出图成功'
    elif result.get('status') != 'success':
        summary['reason'] = '原始脚本请求失败'
    elif not urls:
        summary['reason'] = '原始脚本未提取到图片，不能进入工程验证'
    else:
        try:
            summary['artifacts'] = download_and_verify(urls, directory)
            summary['status'] = 'done'
        except Exception:
            summary['reason'] = '原始脚本返回图片地址，但下载或解码失败'
    (directory/'result.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


def compare_templates(module, config):
    baseline = module.SimpleDoubaoHandler()
    return {'base_url':baseline.base_url == config.get('base_url'),
            'endpoint':baseline.endpoint == config.get('endpoint'),
            'headers':baseline.base_headers == config.get('headers'),
            'query':baseline.base_query_params == config.get('query'),
            'body':baseline.base_request_data == config.get('body')}


def run_service(prompt, service_url, directory, timeout=600):
    directory.mkdir(parents=True, exist_ok=True)
    boundary = '----DoubaoVerification' + uuid.uuid4().hex
    fields = {'prompt':prompt, 'model':'mock_doubao_seedream', 'provider_id':'mock_doubao', 'count':'1'}
    body = ''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n' for key,value in fields.items())
    body += f'--{boundary}--\r\n'
    with requests.post(service_url+'/api/generate-image', data=body.encode(),
                       headers={'Content-Type':f'multipart/form-data; boundary={boundary}'}, timeout=(15, 60)) as response:
        response.raise_for_status()
        job_id = response.json()['jobId']
    print(json.dumps({'phase':'service_submitted', 'job_id':job_id}), flush=True)
    (directory/'monitor.json').write_text(json.dumps({'job_id':job_id, 'status':'submitted'}), encoding='utf-8')
    started = time.monotonic()
    last = None
    while True:
        with requests.get(service_url+'/api/generation-jobs/'+job_id, timeout=(15, 30)) as response:
            response.raise_for_status()
            task = response.json()
        state = task.get('status')
        (directory/'monitor.json').write_text(json.dumps({'job_id':job_id, 'status':state}), encoding='utf-8')
        if state != last:
            print(json.dumps({'phase':'service_monitor', 'job_id':job_id, 'status':state}), flush=True)
            last = state
        if state == 'done':
            urls = [item['href'] for item in task.get('outputs', []) if item.get('type') == 'image']
            urls = [service_url+url if url.startswith('/') else url for url in urls]
            if not urls:
                return {'status':'error', 'job_id':job_id, 'reason':'工程标记完成但没有图片'}
            return {'status':'done', 'job_id':job_id, 'artifacts':download_and_verify(urls, directory)}
        if state in ('error', 'cancelled'):
            return {'status':state, 'job_id':job_id, 'reason':'工程生成失败；请检查任务完整错误和 provider_response'}
        if time.monotonic()-started >= timeout:
            # Keep the submitted ID for follow-up; do not mark an active task successful.
            raise RuntimeError(f'工程任务仍未终止，需要继续监控：{job_id}')
        time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description='先原始 test.py，出图成功后才进行工程验收')
    parser.add_argument('--script', type=Path, default=ROOT/'cache'/'test.py')
    parser.add_argument('--prompt', default='生成一只可爱的小狗的图片')
    parser.add_argument('--service-url', default='http://127.0.0.1:8003/tabs/video-creator')
    parser.add_argument('--baseline-only', action='store_true')
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    report_dir = service_store('video_creator')/'generation_jobs'/('test_py_verify_'+uuid.uuid4().hex)
    report_dir.mkdir(parents=True)
    report = {'prompt':args.prompt, 'script_sha256':hashlib.sha256(args.script.read_bytes()).hexdigest(),
              'service':{'status':'skipped'}, 'parameter_extension':{'status':'skipped', 'reason':'先验证默认请求，再使用真实已确认参数做单项扩展'}}
    try:
        spec = importlib.util.spec_from_file_location('original_doubao_baseline', args.script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        print(json.dumps({'phase':'original_test_py', 'requests':1}), flush=True)
        report['baseline'] = run_original(module, args.prompt, report_dir/'baseline')
        if report['baseline']['status'] == 'done' and not args.baseline_only:
            config = json.loads((service_store('video_creator')/'mock_doubao.json').read_text(encoding='utf-8'))
            report['template_comparison'] = compare_templates(module, config)
            if all(report['template_comparison'].values()):
                report['service'] = run_service(args.prompt, args.service_url.rstrip('/'), report_dir/'service')
            else:
                report['service']['reason'] = '模板未对齐，停止提交工程任务'
    except Exception as exc:
        report['verification_error'] = type(exc).__name__
    (report_dir/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'report':str(report_dir/'report.json'), 'baseline':report.get('baseline',{}),
                      'service':report['service']}, ensure_ascii=False), flush=True)
    return 0 if report.get('baseline',{}).get('status') == 'done' and (args.baseline_only or report['service'].get('status')=='done') else 1


if __name__ == '__main__':
    raise SystemExit(main())
