import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

from services.douyin.service import WEB_HTML, WebJobStore, extract_media_from_payload, download_work_media
from services.douyin.video_understanding import (
    UnderstandingProvider, validate_config, transcript_chunks, understand_work, validate_summary,
)


TEST_CONFIG = {"base_url": "http://127.0.0.1:11434/v1", "model": "test-vision", "api_format": "ollama", "transcription_model": "small", "context_window": 32768}


class UnderstandingTests(unittest.TestCase):
    def test_author_system_prompt_is_used_by_both_api_formats(self):
        from services.douyin.understanding_prompts import AUTHOR_SYSTEM_PROMPT
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            'message': {'content': '{"ok":true}'},
            'choices': [{'message': {'content': '{"ok":true}'}}]}).encode()
        for api_format in ('ollama', 'openai'):
            with self.subTest(api_format=api_format), patch('services.douyin.video_understanding.request.urlopen', return_value=response) as request:
                provider = UnderstandingProvider({**TEST_CONFIG, 'api_format': api_format})
                provider.complete('成稿', system_prompt=AUTHOR_SYSTEM_PROMPT)
                payload = json.loads(request.call_args.args[0].data)
                self.assertEqual(payload['messages'][0]['content'], AUTHOR_SYSTEM_PROMPT)
                provider.complete('提取证据')
                payload = json.loads(request.call_args.args[0].data)
                self.assertIn('视频内容分析员', payload['messages'][0]['content'])

    def test_editorial_style_change_invalidates_finished_analysis_cache(self):
        from services.douyin.mention_mcp import analysis_cache_fingerprint
        current = analysis_cache_fingerprint(TEST_CONFIG)
        with patch('services.douyin.mention_mcp.SUMMARY_STYLE_VERSION', 'old-analysis-voice'):
            self.assertNotEqual(current, analysis_cache_fingerprint(TEST_CONFIG))
        self.assertNotEqual(current, analysis_cache_fingerprint({**TEST_CONFIG, 'model': 'other'}))

    def test_bare_mentions_and_simple_summaries_do_not_invoke_model(self):
        from services.douyin.mention_agent import classify_intent
        provider = MagicMock()
        for text in ('@露露', '@Benyl 总结一下', '总结视频', '测试'):
            self.assertEqual(classify_intent(provider, text)['intent'], 'summary')
        provider.complete.assert_not_called()

    def test_specific_question_has_small_explicit_intent_budget(self):
        from services.douyin.mention_agent import classify_intent
        provider = MagicMock()
        provider.complete.return_value = {'intent': 'question', 'question': '这是什么飞机？'}
        result = classify_intent(provider, '@露露这是什么飞机？')
        self.assertEqual(result['intent'], 'question')
        self.assertEqual(provider.complete.call_args.kwargs, {'max_tokens': 256, 'context_limit': 4096})

    def test_inference_errors_are_classified_without_retrying_configuration_errors(self):
        from services.douyin.inference_health import inference_failure_kind
        for text, kind in [('std::bad_alloc', 'memory'), ('failed to allocate CUDA_Host buffer', 'memory'),
                           ('CUDA error: unknown error', 'gpu'), ('wsarecv: connection was forcibly closed', 'runner')]:
            self.assertEqual(inference_failure_kind(RuntimeError(text)), kind)
        self.assertEqual(inference_failure_kind('视频理解模型 HTTP 401: unauthorized'), '')

    def test_prefetch_restores_retry_media_before_opening_browser(self):
        from services.douyin.mention_agent import MentionAgent
        source = self.root / ('a' * 32)
        target = self.root / ('b' * 32)
        (source / 'media').mkdir(parents=True)
        (source / 'media/video.mp4').write_bytes(b'recovered video')
        for name, value in [('analysis_checkpoint.json', {}), ('task.json', {'status': 'error'}),
                            ('prepared_media.json', {'url': 'source', 'files': ['media/video.mp4']})]:
            (source / name).write_text(json.dumps(value), encoding='utf-8')
        agent = MentionAgent(lambda: TEST_CONFIG, self.root / 'config.json', self.root / 'profile')
        row = {'source_url': 'source', 'retry_history': [{'task_directory': source.name}]}
        with patch('services.douyin.service.download_work_media') as download, \
             patch('services.douyin.service.seed_browser_profile') as seed:
            agent.prepare(row, target, lambda message: None)
        download.assert_not_called()
        seed.assert_not_called()
        self.assertEqual((target / 'media/video.mp4').read_bytes(), b'recovered video')
        self.assertTrue((target / 'prepared_media.json').exists())
        (source / 'analysis_checkpoint.json').unlink()
        with patch('services.douyin.service.download_work_media') as download:
            target = self.root / ('c' * 32)
            agent.prepare(row, target, lambda message: None)
        download.assert_not_called()
        self.assertEqual((target / 'media/video.mp4').read_bytes(), b'recovered video')

    def test_download_streams_to_disk_without_browser_response_buffer(self):
        from services.douyin.service import download_url
        context = MagicMock()
        context.cookies.return_value = []
        with patch('services.douyin.service.requests.Session') as factory:
            session = factory.return_value.__enter__.return_value
            response = session.get.return_value.__enter__.return_value
            response.ok = True
            response.headers = {'content-length': '6'}
            response.iter_content.return_value = [b'abc', b'def']
            destination = self.root / 'video.mp4'
            download_url(context, 'https://example.com/video', destination, 'https://www.douyin.com/video/123')
        self.assertEqual(destination.read_bytes(), b'abcdef')
        self.assertTrue(session.get.call_args.kwargs['stream'])
        context.request.get.assert_not_called()

    def test_stream_failure_removes_partial_file(self):
        from services.douyin.service import download_url
        def broken_stream(**kwargs):
            yield b'partial'
            raise ConnectionError('connection lost')
        context = MagicMock()
        context.cookies.return_value = []
        with patch('services.douyin.service.requests.Session') as factory:
            response = factory.return_value.__enter__.return_value.get.return_value.__enter__.return_value
            response.ok = True
            response.headers = {}
            response.iter_content.side_effect = broken_stream
            destination = self.root / 'video.mp4'
            with self.assertRaisesRegex(ConnectionError, 'connection lost'):
                download_url(context, 'https://example.com/video', destination, 'referer')
        self.assertFalse(destination.exists())

    def test_stream_total_deadline_and_content_length_are_checked(self):
        from services.douyin.service import download_url
        context = MagicMock()
        context.cookies.return_value = []
        with patch('services.douyin.service.requests.Session') as factory:
            response = factory.return_value.__enter__.return_value.get.return_value.__enter__.return_value
            response.ok = True
            response.headers = {'content-length': '10'}
            response.iter_content.return_value = [b'abc']
            destination = self.root / 'video.mp4'
            with self.assertRaisesRegex(RuntimeError, '不完整'):
                download_url(context, 'https://example.com/video', destination, 'referer')
            with patch('services.douyin.service.time.monotonic', side_effect=[0, 11]):
                with self.assertRaises(TimeoutError):
                    download_url(context, 'https://example.com/video', destination, 'referer', total_timeout=10)
        self.assertFalse(destination.exists())

    def test_failed_summary_resumes_completed_evidence_and_chunks(self):
        media = self.root / 'media/video.mp4'
        media.parent.mkdir()
        media.write_bytes(b'video')
        frame = self.root / 'frame.jpg'
        frame.write_bytes(b'frame')
        first, second = MagicMock(), MagicMock()
        note = {'summary': '已有口播归纳'}
        first.complete.side_effect = [{'observations': []}, note, RuntimeError('runner failed')]
        second.complete.side_effect = [note, self.summary()]
        with patch('services.douyin.video_understanding.inspect_video', return_value=(10, [{'file': frame, 'seconds': 0}])), \
             patch('services.douyin.video_understanding.transcribe', return_value=([{'start': 0, 'end': 9, 'text': '完整口播'}], '')) as asr, \
             patch('services.douyin.video_understanding.transcript_chunks', return_value=['first', 'second']), \
             patch('services.douyin.video_understanding.UnderstandingProvider', side_effect=[first, second]):
            with self.assertRaisesRegex(RuntimeError, 'runner failed'):
                understand_work('https://www.douyin.com/video/123', self.root, lambda *a: [media], TEST_CONFIG, lambda *a: None)
            result = understand_work('https://www.douyin.com/video/123', self.root, lambda *a: [media], TEST_CONFIG, lambda *a: None)
        asr.assert_called_once()
        self.assertEqual(second.complete.call_count, 2)
        self.assertTrue(second.complete.call_args_list[0].args[0].endswith('second'))
        self.assertEqual(result['summary'], self.summary()['summary'])
        trace = json.loads((self.root / 'task.json').read_text(encoding='utf-8'))
        self.assertEqual([n['name'] for n in trace['nodes'] if n.get('reused')], ['transcribe', 'visual_understanding'])
        self.assertEqual(next(n for n in trace['nodes'] if n['name'] == 'summarize')['reused_chunks'], 1)

    def test_checkpoint_rejects_changed_media_or_model(self):
        from services.douyin.video_understanding import analysis_checkpoint_key
        media = self.root / 'video.mp4'
        media.write_bytes(b'original')
        key = analysis_checkpoint_key('url', TEST_CONFIG, [media])
        self.assertNotEqual(key, analysis_checkpoint_key('url', {**TEST_CONFIG, 'model': 'other'}, [media]))
        media.write_bytes(b'changed')
        self.assertNotEqual(key, analysis_checkpoint_key('url', TEST_CONFIG, [media]))

    def test_ollama_reloads_a_stopped_runner_once(self):
        import io
        from urllib.error import HTTPError
        failure = HTTPError('http://localhost/api/chat', 500, 'error', {}, io.BytesIO(b'{"error":"model runner has unexpectedly stopped"}'))
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"message":{"content":"{\\"ok\\":true}"}}'
        with patch('services.douyin.video_understanding.request.urlopen', side_effect=[failure, response]) as call, \
             patch('services.douyin.video_understanding.time.sleep'), \
             self.assertLogs('services.douyin.video_understanding', level='WARNING'):
            self.assertEqual(UnderstandingProvider(TEST_CONFIG).complete('prompt'), {'ok': True})
        self.assertEqual(call.call_count, 2)

    def test_model_socket_failure_keeps_provider_context_for_queue_recovery(self):
        from services.douyin.inference_health import inference_failure_kind
        with patch('services.douyin.video_understanding.request.urlopen', side_effect=ConnectionResetError('connection reset')):
            with self.assertRaisesRegex(RuntimeError, '视频理解模型连接失败') as raised:
                UnderstandingProvider(TEST_CONFIG).complete('prompt')
        self.assertEqual(inference_failure_kind(raised.exception), 'transport')

    def test_understanding_prefers_moderate_renditions(self):
        from services.douyin.service import MediaItem, understanding_media_rank
        sizes = [1080, 720, 240, 480, 0]
        items = [MediaItem('video', f'https://example.com/{size}', 'mp4',
                           width=size * 16 // 9, height=size) for size in sizes]
        ordered = sorted(items, key=understanding_media_rank)
        self.assertEqual([item.height for item in ordered], [480, 720, 1080, 240, 0])

    def test_candidate_dimensions_use_rendition_not_original_size(self):
        from services.douyin.service import extract_media_from_aweme
        media = extract_media_from_aweme({'video': {'width': 1920, 'height': 1080,
            'bit_rate': [{'play_addr': {'width': 854, 'height': 480,
                         'url_list': ['https://example.com/480.mp4']}}]}})
        self.assertEqual((media[0].width, media[0].height), (854, 480))

    def test_understanding_prefers_muxed_mp4_over_smaller_dash_variant(self):
        from services.douyin.service import extract_media_from_aweme, understanding_media_rank
        payload = {'video': {'bit_rate': [
            {'gear_name': '540_2_1', 'format': 'dash', 'bit_rate': 100,
             'play_addr': {'width': 1024, 'height': 576, 'url_list': ['https://example.com/video-only']}},
            {'gear_name': '540_2_1', 'format': 'mp4', 'bit_rate': 140,
             'play_addr': {'width': 1024, 'height': 576, 'url_list': ['https://example.com/with-audio']}}]}}
        media = sorted(extract_media_from_aweme(payload), key=understanding_media_rank)
        self.assertEqual(media[0].url, 'https://example.com/with-audio')

    def test_local_asr_requires_complete_local_files(self):
        from services.douyin.video_understanding import local_asr_model
        with self.assertRaisesRegex(RuntimeError, '不会联网'):
            local_asr_model(self.root, 'large-v3-turbo')
        model = self.root / 'large-v3-turbo'
        model.mkdir()
        for name in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.json'):
            (model / name).write_text('{}', encoding='utf-8')
        self.assertEqual(local_asr_model(self.root, 'large-v3-turbo'), model.resolve())

    def test_transcription_releases_ollama_before_loading_asr(self):
        self.release_patcher.stop()
        import types
        from services.douyin.video_understanding import transcribe
        order = []
        model = MagicMock()
        model.transcribe.return_value = ([], None)
        factory = MagicMock(side_effect=lambda *a, **k: (order.append('asr'), model)[1])
        probe = MagicMock(returncode=0, stdout='{"streams":[{"index":0}]}')
        def unload(req, **kwargs):
            self.assertEqual(json.loads(req.data)['keep_alive'], 0)
            self.assertEqual(req.full_url, 'http://127.0.0.1:11434/api/generate')
            order.append('unload')
            return MagicMock()
        with patch.dict('sys.modules', {'faster_whisper': types.SimpleNamespace(WhisperModel=factory)}), \
             patch('services.douyin.video_understanding.subprocess.run', return_value=probe), \
             patch('services.douyin.video_understanding.local_asr_model', return_value=self.root / 'small'), \
             patch('services.douyin.video_understanding.request.urlopen', side_effect=unload):
            transcribe(self.root / 'video.mp4', self.root, TEST_CONFIG, lambda *a: None)
        self.assertEqual(order, ['unload', 'asr'])
        factory.assert_called_once_with(str(self.root / 'small'), device='cpu', compute_type='int8', local_files_only=True)

    def test_long_video_samples_at_most_twenty_frames_across_full_duration(self):
        from services.douyin.video_understanding import inspect_video, cv2
        capture = MagicMock()
        capture.get.side_effect = lambda key: {cv2.CAP_PROP_FPS: 24,
                                               cv2.CAP_PROP_FRAME_COUNT: 24 * 3600}[key]
        frame = MagicMock()
        frame.shape = (720, 1280, 3)
        capture.read.return_value = (True, frame)
        with patch('services.douyin.video_understanding.cv2.VideoCapture', return_value=capture), \
             patch('services.douyin.video_understanding.cv2.resize', return_value=frame), \
             patch('services.douyin.video_understanding.cv2.imwrite', return_value=True):
            duration, frames = inspect_video(self.root / 'video.mp4', self.root)
        self.assertEqual(duration, 3600)
        self.assertEqual(len(frames), 20)
        self.assertEqual(frames[0]['seconds'], 0)
        self.assertGreater(frames[-1]['seconds'], 3599)
        capture.release.assert_called_once()

    def test_target_page_does_not_download_unrelated_response_video(self):
        playwright = MagicMock()
        context = playwright.__enter__.return_value.chromium.launch_persistent_context.return_value
        page = context.new_page.return_value
        page.url = 'https://www.douyin.com/video/123'
        page.title.return_value = '作品页'
        callbacks = {}
        page.on.side_effect = lambda name, callback: callbacks.update({name: callback})
        response = MagicMock()
        response.url = 'https://www.douyin.com/aweme/v1/web/aweme/detail/'
        response.headers = {'content-type': 'application/json'}
        response.status = 200
        response.json.return_value = {'aweme_detail': {'aweme_id': '999', 'video': {
            'play_addr': {'url_list': ['https://example.com/wrong.mp4']}}}}
        page.goto.side_effect = lambda *args, **kwargs: callbacks['response'](response)
        with patch('services.douyin.service.sync_playwright', return_value=playwright), \
             patch('services.douyin.service.close_popups'), \
             patch('services.douyin.service.choose_default_media', side_effect=lambda context, media, *args, **kwargs: media), \
             patch('services.douyin.service.download_url') as download:
            with self.assertRaisesRegex(RuntimeError, 'No downloadable media'):
                download_work_media(page.url, output_dir=self.root / 'media', headless=True,
                                    user_data_dir=self.root / 'profile', wait_seconds=0)
            download.assert_not_called()

    def test_nested_response_cannot_erase_target_media(self):
        playwright = MagicMock()
        context = playwright.__enter__.return_value.chromium.launch_persistent_context.return_value
        page = context.new_page.return_value
        page.url = 'https://www.douyin.com/video/123'
        handlers = {}
        page.on.side_effect = lambda name, callback: handlers.update({name: callback})
        target = MagicMock()
        unrelated = MagicMock()
        for response in (target, unrelated):
            response.url = 'https://www.douyin.com/aweme/v1/web/aweme/detail/'
            response.headers = {'content-type': 'application/json'}
            response.status = 200
        target.json.return_value = {'aweme_detail': {'aweme_id': '123', 'video': {
            'play_addr': {'url_list': ['https://example.com/target.mp4']}}}}

        def read_unrelated():
            handlers['response'](target)
            return {'aweme_detail': {'aweme_id': '999'}}

        unrelated.json.side_effect = read_unrelated
        page.goto.side_effect = lambda *a, **k: handlers['response'](unrelated)
        with patch('services.douyin.service.sync_playwright', return_value=playwright), \
             patch('services.douyin.service.close_popups'), \
             patch('services.douyin.service.downloaded_file_has_video', return_value=True), \
             patch('services.douyin.service.mp4_handler_types', return_value={'vide', 'soun'}), \
             patch('services.douyin.service.download_url', side_effect=lambda c, u, p, r, **kw: p.write_bytes(b'video')) as download:
            files = download_work_media(page.url, output_dir=self.root / 'media', headless=True,
                user_data_dir=self.root / 'profile', wait_seconds=0, understanding_media=True)
        self.assertEqual(len(files), 1)
        self.assertEqual(download.call_args.args[1], 'https://example.com/target.mp4')

    def test_media_extraction_rejects_recommendations_and_missing_work_id(self):
        wrong = {'aweme_id': '999', 'video': {'play_addr': {'url_list': ['https://example.com/wrong.mp4']}}}
        target = {'aweme_id': '123', 'video': {'play_addr': {'url_list': ['https://example.com/target.mp4']}}}
        self.assertEqual(extract_media_from_payload({'aweme_list': [wrong]}, '123'), [])
        self.assertEqual(extract_media_from_payload({'video': target['video']}, '123'), [])
        self.assertEqual([item.url for item in extract_media_from_payload({'aweme_list': [wrong, target]}, '123')],
                         ['https://example.com/target.mp4'])

    def test_downloader_waits_for_delayed_target_detail_response(self):
        playwright = MagicMock()
        context = playwright.__enter__.return_value.chromium.launch_persistent_context.return_value
        page = context.new_page.return_value
        page.url = 'https://www.douyin.com/video/123'
        handlers = {}
        page.on.side_effect = lambda name, callback: handlers.update({name: callback})
        response = MagicMock()
        response.url = 'https://www.douyin.com/aweme/v1/web/aweme/detail/'
        response.headers = {'content-type': 'application/json'}
        response.status = 200
        response.json.return_value = {'status_code': 0, 'aweme_detail': {'aweme_id': '123',
                                      'video': {'play_addr': {'url_list': ['https://example.com/target.mp4']}}}}
        page.wait_for_timeout.side_effect = lambda delay: handlers['response'](response) if delay == 500 else None
        with patch('services.douyin.service.sync_playwright', return_value=playwright), \
             patch('services.douyin.service.close_popups'), \
             patch('services.douyin.service.choose_default_media', side_effect=lambda context, media, *args, **kwargs: media), \
             patch('services.douyin.service.downloaded_file_has_video', return_value=True), \
             patch('services.douyin.service.download_url', side_effect=lambda context, url, path, referer, **kwargs: path.write_bytes(b'video')):
            files = download_work_media(page.url, output_dir=self.root / 'media', headless=True,
                                        user_data_dir=self.root / 'profile', wait_seconds=0)
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].exists())
        page.goto.assert_called_once()
        identity = json.loads((self.root / 'media/media_identity.json').read_text(encoding='utf-8'))
        self.assertEqual(identity['work_id'], '123')

    def setUp(self):
        self.root = Path("cache/understanding_tests") / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.release_patcher = patch('services.douyin.video_understanding.release_understanding_model')
        self.release_patcher.start()
        self.addCleanup(self.release_patcher.stop)

    def test_understanding_skips_video_only_rendition_for_original_audio(self):
        playwright = MagicMock()
        context = playwright.__enter__.return_value.chromium.launch_persistent_context.return_value
        page = context.new_page.return_value
        page.url = 'https://www.douyin.com/video/123'
        handlers = {}
        page.on.side_effect = lambda name, callback: handlers.update({name: callback})
        response = MagicMock(status=200)
        response.url = 'https://www.douyin.com/aweme/v1/web/aweme/detail/'
        response.headers = {'content-type': 'application/json'}
        response.json.return_value = {'aweme_detail': {'aweme_id': '123', 'video': {
            'play_addr': {'url_list': ['https://example.com/silent.mp4']},
            'download_addr': {'url_list': ['https://example.com/with-audio.mp4']}}}}
        page.goto.side_effect = lambda *a, **k: handlers['response'](response)
        with patch('services.douyin.service.sync_playwright', return_value=playwright), \
             patch('services.douyin.service.close_popups'), \
             patch('services.douyin.service.choose_default_media', side_effect=lambda c, m, *a, **k: m), \
             patch('services.douyin.service.downloaded_file_has_video', return_value=True), \
             patch('services.douyin.service.mp4_handler_types', side_effect=[{'vide'}, {'vide', 'soun'}]), \
             patch('services.douyin.service.download_url', side_effect=lambda c, u, p, r, **kwargs: p.write_bytes(b'video')) as download:
            files = download_work_media(page.url, output_dir=self.root / 'media', headless=True,
                user_data_dir=self.root / 'profile', wait_seconds=0, understanding_media=True)
        self.assertEqual(download.call_count, 2)
        self.assertEqual(files[0].name, '123_video_02.mp4')
        self.assertFalse((self.root / 'media/123_silent_fallback.mp4').exists())

    def tearDown(self):
        shutil.rmtree(self.root)

    def summary(self):
        return {"title": "预算", "format": "口播", "topic": "经济", "tags": ["消费"],
                "summary": "作者讲述预算管理。", "comment_reply": "主要讲如何比较价格、安排家庭预算。", "key_points": ["比较价格"],
                "timeline": [{"seconds": 2, "content": "比较价格"}], "limitations": ["抽帧采样"]}

    def test_word_timestamps_are_coalesced_without_losing_speech(self):
        segments = [{'start': i * .5, 'end': (i + 1) * .5, 'text': f'词{i}'} for i in range(200)]
        chunks = transcript_chunks(segments)
        lines = '\n'.join(chunks).splitlines()
        self.assertEqual(len(lines), 4)
        self.assertIn('[0.0-30.0秒]', lines[0])
        self.assertIn('[90.0-100.0秒]', lines[-1])
        for segment in segments:
            self.assertIn(segment['text'], '\n'.join(chunks))
        self.assertEqual(segments[0]['text'], '词0')

    def test_transcript_chunks_keep_every_segment(self):
        segments = [{"start": i, "end": i + 1, "text": str(i) + "x" * 40} for i in range(20)]
        chunks = transcript_chunks(segments, 120)
        self.assertGreater(len(chunks), 1)
        for item in segments:
            self.assertIn(item["text"], "\n".join(chunks))

    def test_image_note_without_audio_preserves_all_images_and_history(self):
        from PIL import Image
        from services.douyin.understanding_history import UnderstandingHistory
        root = self.root / 'downloads/understanding/note'
        media = root / 'media'
        media.mkdir(parents=True)
        images = [media / f'{i}.png' for i in range(5)]
        for image in images:
            Image.new('RGB', (32, 32)).save(image)
        summary = {**self.summary(), 'format': '图文', 'timeline': []}
        with patch.object(UnderstandingProvider, 'complete', side_effect=[{'observations': []}, {'observations': []}, summary]) as complete, \
             patch('services.douyin.video_understanding.transcribe') as transcribe:
            result = understand_work('https://www.douyin.com/video/123', root, lambda *args: images, TEST_CONFIG, lambda *args: None)
        transcribe.assert_not_called()
        self.assertEqual(result['source_type'], 'image_note')
        self.assertEqual(len(result['image_files']), 5)
        self.assertEqual(result['duration_seconds'], 0)
        self.assertNotIn('video_file', result)
        self.assertIn('不得将图片序号当作时间', complete.call_args_list[0].args[0])
        store = UnderstandingHistory(self.root / 'history.sqlite3', self.root / 'downloads')
        saved = store.save(root, result)
        self.assertNotIn('video', saved)
        self.assertEqual(len(saved['images']), 5)
        self.assertTrue((root / 'report.md').exists())

    def test_missing_configuration_never_falls_back(self):
        for config in (None, {}, {"model": "test"}, {**TEST_CONFIG, "model": ""}, {**TEST_CONFIG, "api_format": ""}):
            with self.assertRaises(ValueError):
                validate_config(config)

    def test_context_window_validation(self):
        self.assertEqual(validate_config({**TEST_CONFIG, "context_window": "65536"})["context_window"], 65536)
        for value in (0, 300000, "bad", "32768.5"):
            with self.assertRaises(ValueError):
                validate_config({**TEST_CONFIG, "context_window": value})

    def test_turbo_asr_is_configurable_and_unknown_model_is_rejected(self):
        self.assertEqual(validate_config({**TEST_CONFIG, "transcription_model": "large-v3-turbo"})["transcription_model"], "large-v3-turbo")
        with self.assertRaises(ValueError):
            validate_config({**TEST_CONFIG, "transcription_model": "unregistered-model"})

    def test_invalid_timeline_is_rejected(self):
        summary = self.summary()
        summary["timeline"][0]["seconds"] = 20
        with self.assertRaises(ValueError):
            validate_summary(summary, 10)

    def test_workflow_preserves_transcript_and_named_artifacts(self):
        video = self.root / "media/input.mp4"
        video.parent.mkdir()
        video.touch()
        frame = self.root / "frame.jpg"
        frame.touch()
        transcript = [{"start": 0, "end": 3, "text": "今天讨论家庭预算"}]
        with patch("services.douyin.video_understanding.inspect_video", return_value=(4, [{"file": frame, "seconds": 0}])), \
             patch("services.douyin.video_understanding.transcribe", return_value=(transcript, "")), \
             patch.object(UnderstandingProvider, "complete", side_effect=[{"observations": []}, {"summary": "预算"}, self.summary()]) as complete:
            result = understand_work("https://www.douyin.com/video/123", self.root, lambda *args: [video], TEST_CONFIG, lambda *args: None)
        self.assertEqual(result["transcript"], transcript)
        self.assertEqual(result["summary_basis"], "audio_primary")
        self.assertEqual(result['comment_reply'], self.summary()['comment_reply'])
        self.assertEqual(complete.call_count, 3)
        self.assertEqual([call.kwargs['context_limit'] for call in complete.call_args_list], [16384, 8192, 16384])
        from services.douyin.understanding_prompts import AUTHOR_SYSTEM_PROMPT, SUMMARY_STYLE_VERSION
        self.assertNotIn('system_prompt', complete.call_args_list[0].kwargs)
        self.assertNotIn('system_prompt', complete.call_args_list[1].kwargs)
        self.assertEqual(complete.call_args.kwargs['system_prompt'], AUTHOR_SYSTEM_PROMPT)
        self.assertEqual(result['summary_style_version'], SUMMARY_STYLE_VERSION)
        self.assertIn('不得混入summary正文', complete.call_args.args[0])
        self.assertIn('comment_reply字段', complete.call_args.args[0])
        self.assertIn("音频与画面或字幕冲突时以音频为准", complete.call_args.args[0])
        trace = json.loads((self.root / "task.json").read_text(encoding="utf-8"))
        self.assertEqual(trace["status"], "done")
        self.assertTrue(all(x["status"] == "success" for x in trace["nodes"]))
        self.assertEqual(trace["artifacts"]["summary"], "summary.json")
        self.assertEqual(trace["artifacts"]["report"], "report.md")
        self.assertIn("完整音频转写", (self.root / "report.md").read_text(encoding="utf-8"))
        self.assertNotIn("api_key", (self.root / "task.json").read_text())

    def test_history_survives_restart_and_report_escapes_model_html(self):
        from services.douyin.understanding_history import UnderstandingHistory, render_report
        download_root = self.root / "downloads"
        root = download_root / "understanding" / "test-id"
        root.mkdir(parents=True)
        (root / "video.mp4").touch()
        result = {**self.summary(), "title": "<script>alert(1)</script>", "source_url": "https://www.douyin.com/video/123",
                  "duration_seconds": 4, "frame_count": 0, "model": "test", "video_file": "video.mp4", "transcript": []}
        trace = {"status": "done", "nodes": [{"name": "download", "status": "success", "started_at": 1, "ended_at": 2}],
                 "artifacts": {"video": "video.mp4", "frames": []}}
        (root / "task.json").write_text(json.dumps(trace), encoding="utf-8")
        (root / "summary.json").write_text(json.dumps(result), encoding="utf-8")
        store = UnderstandingHistory(self.root / "history.sqlite3", download_root)
        store.backfill()
        store.backfill()
        restored = UnderstandingHistory(self.root / "history.sqlite3", download_root)
        self.assertEqual(restored.list()["total"], 1)
        self.assertEqual(restored.list(offset=1)["items"], [])
        saved = restored.get("test-id")
        self.assertEqual(saved["video"]["href"], "/downloads/understanding/test-id/video.mp4")
        self.assertTrue(saved["report"]["href"].endswith("report.md"))
        self.assertIsNone(restored.get("missing"))
        with restored.connect() as db:
            row = db.execute("SELECT source_url,report_markdown,video_cache_file FROM understanding_history").fetchone()
        self.assertEqual(row[0], result["source_url"])
        self.assertIn("视频理解报告", row[1])
        self.assertEqual(row[2], "understanding/test-id/video.mp4")
        rendered = render_report(root, saved, trace, "/downloads/")
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        mention_root = download_root / 'mentions' / 'mention-id'
        mention_root.mkdir(parents=True)
        (mention_root / 'video.mp4').touch()
        (mention_root / 'task.json').write_text(json.dumps(trace), encoding='utf-8')
        mention = {'id': 'account:work:comment', 'author': '<Jessica>', 'status': 'done',
                   'analysis': result, 'reply': '回复正文', 'error': ''}
        restored.save_mention(mention_root, mention)
        restored.save_mention(mention_root, {**mention, 'status': 'draft'})
        mention_saved = restored.get('mention-id')
        self.assertEqual(mention_saved['artifact_directory'], 'mentions/mention-id')
        self.assertEqual(mention_saved['video']['href'], '/downloads/mentions/mention-id/video.mp4')
        self.assertEqual(mention_saved['reply_status'], 'draft')
        listed = next(x for x in restored.list()['items'] if x['id'] == 'mention-id')
        self.assertEqual(listed['record_source'], 'mention')
        self.assertEqual(listed['reply_username'], '<Jessica>')
        self.assertIn('&lt;Jessica&gt;', render_report(mention_root, mention_saved, trace, '/downloads/'))
        restored.delete('mention-id')
        restored.save_mention(mention_root, mention)
        self.assertIsNone(restored.get('mention-id'))
        self.assertTrue(restored.delete("test-id"))
        self.assertFalse(restored.delete("test-id"))
        restored = UnderstandingHistory(self.root / "history.sqlite3", download_root)
        restored.backfill()
        self.assertEqual(restored.list()["total"], 0)
        self.assertIsNone(restored.get("test-id"))

    def test_pending_mention_history_updates_without_report(self):
        from services.douyin.understanding_history import UnderstandingHistory
        downloads = self.root / 'downloads'
        store = UnderstandingHistory(self.root / 'history.sqlite3', downloads)
        root = downloads / 'mentions' / 'queued-id'
        row = {'id': 'account:work:comment', 'author': '测试用户', 'status': 'pending',
               'source_url': 'https://www.douyin.com/video/123', 'created_at': 10}
        store.save_mention(root, row)
        self.assertFalse(store.get('queued-id')['analysis_ready'])
        self.assertEqual(store.list()['items'][0]['queue_position'], 1)
        store.save_mention(root, {**row, 'status': 'running', 'progress': '正在转写'})
        self.assertEqual(store.list()['total'], 1)
        self.assertEqual(store.list()['items'][0]['progress'], '正在转写')
        store.save_mention(root, {**row, 'status': 'error', 'error': '下载失败'})
        self.assertEqual(store.get('queued-id')['reply_error'], '下载失败')
        store.delete('queued-id')
        store.save_mention(root, row)
        self.assertEqual(store.list()['total'], 0)

    def test_download_failure_is_saved(self):
        def download(*args):
            raise RuntimeError("验证码未完成")
        with self.assertRaisesRegex(RuntimeError, "验证码"):
            understand_work("url", self.root, download, TEST_CONFIG, lambda *args: None)
        trace = json.loads((self.root / "task.json").read_text(encoding="utf-8"))
        self.assertEqual(trace["status"], "error")
        self.assertEqual(trace["nodes"][0]["status"], "failed")

    def test_restart_marks_running_jobs_interrupted_and_keeps_results(self):
        store = WebJobStore(self.root)
        running = store.create("running")
        done = store.create("done")
        store.update(done, status="done", result={"summary": "saved"})
        restored = WebJobStore(self.root)
        self.assertEqual(restored.get(running)["status"], "error")
        self.assertEqual(restored.get(done)["result"], {"summary": "saved"})

    def test_job_write_retries_temporary_windows_file_lock(self):
        store = WebJobStore(self.root)
        original = Path.replace
        attempts = []
        def replace(path, target):
            attempts.append(path)
            if len(attempts) < 3:
                raise PermissionError("temporary file lock")
            return original(path, target)
        with patch.object(Path, "replace", replace), patch("services.douyin.service.time.sleep"):
            identifier = store.create("retry")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(json.loads((self.root / (identifier + ".json")).read_text(encoding="utf-8"))["message"], "retry")

    def test_multimodal_payload_uses_actual_image_bytes(self):
        image = self.root / "frame.jpg"
        image.write_bytes(b"jpeg-fixture")
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"choices":[{"message":{"content":"{\\"description\\":\\"frame\\"}"}}]}'
        with patch("services.douyin.video_understanding.request.urlopen", return_value=Response()) as call:
            result = UnderstandingProvider({**TEST_CONFIG, "base_url": "https://example.com/v1", "api_format": "openai"}).complete("describe", [image])
        payload = json.loads(call.call_args.args[0].data)
        self.assertEqual(result["description"], "frame")
        self.assertTrue(payload["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    def test_ollama_explicit_context_and_native_image_payload(self):
        image = self.root / "frame.jpg"
        image.write_bytes(b"jpeg-fixture")
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"message":{"content":"{\\"description\\":\\"frame\\"}"}}'
        with patch("services.douyin.video_understanding.request.urlopen", return_value=Response()) as call:
            UnderstandingProvider(TEST_CONFIG).complete("describe", [image])
        req = call.call_args.args[0]
        payload = json.loads(req.data)
        self.assertTrue(req.full_url.endswith("/api/chat"))
        self.assertEqual(payload["options"]["num_ctx"], 32768)
        self.assertFalse(payload["think"])
        self.assertEqual(len(payload["messages"][1]["images"]), 1)


if __name__ == "__main__":
    unittest.main()
