"""Exercise daily fallback without consuming a real provider's free allowance."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from contextlib import nullcontext

from PIL import Image

from services.video_creator.tools.ai.image_priority import PriorityImageTool, daily_quota_exhausted
from services.video_creator.tools.ai.providers import ProviderError


class ImagePriorityTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[3] / 'cache'
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='image-priority-', dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.day = '2026-11-04'
        self.tool = PriorityImageTool(self.root, day=lambda: self.day)
        self.tool.providers.save({'provider': 'mock_doubao', 'model': 'mock_doubao_seedream_5_0_flash'})
        (self.root / 'mock_doubao.json').write_text(json.dumps({'web_request': {'headers': {'Cookie': 'private-session-cookie'}}}))

    @staticmethod
    def output(prompt, target, *args, **kwargs):
        Image.new('RGB', (256, 256), '#cddbbb').save(target)

    def test_only_explicit_daily_quota_is_classified(self):
        for message in ('今日免费生图次数已用完，请明日再来', 'Daily image quota exhausted', '每日生图额度不足'):
            self.assertTrue(daily_quota_exhausted(message), message)
        for message in ('HTTP 429', '当前服务访问频繁 710022002', '请检查登录状态、额度或请求模板',
                        'Daily rate limit reached', 'HTTP 401 今日额度用完', '网络超时，请勿重复提交'):
            self.assertFalse(daily_quota_exhausted(message), message)

    def test_cloud_is_first_and_local_is_not_called_on_success(self):
        with patch.object(self.tool, 'doubao', side_effect=self.output) as cloud, patch.object(self.tool, 'local') as local:
            trace = self.tool.generate('test prompt', self.root / 'one.png')
        cloud.assert_called_once(); local.assert_not_called()
        self.assertEqual(trace['provider'], 'mock_doubao')
        self.assertEqual(trace['status'], 'done')

    def test_portrait_ratio_survives_cloud_and_quota_fallback(self):
        with patch.object(self.tool,'doubao',side_effect=self.output) as cloud:
            self.tool.generate('portrait',self.root/'portrait.png',aspect='9:16')
        self.assertEqual(cloud.call_args.kwargs['aspect'],'9:16')
        with patch.object(self.tool,'doubao',side_effect=ProviderError('今日生图次数已用完')), \
             patch.object(self.tool,'local',side_effect=self.output) as local:
            self.tool.generate('portrait fallback',self.root/'portrait-fallback.png',aspect='9:16')
        self.assertEqual(local.call_args.kwargs['aspect'],'9:16')

    def test_portrait_local_graph_uses_vertical_one_megapixel_latents(self):
        client=MagicMock()
        client.object_info.return_value={'UNETLoader':{'input':{'required':{'unet_name':[['flux1-krea-dev_fp8_scaled.safetensors']]}}}}
        client.queue.return_value='portrait-prompt'
        client.wait.side_effect=RuntimeError('stop before real inference')
        with patch('services.video_creator.tools.ai.image_priority.ComfyUIClient',return_value=client), \
             patch('services.core.understanding_queue.shared_slot',return_value=nullcontext()), \
             patch('services.douyin.video_understanding.release_understanding_model'):
            with self.assertRaises(RuntimeError):
                self.tool.local('portrait',self.root/'portrait-local.png',lambda **values:None,aspect='9:16')
        latent=client.validate_graph.call_args.args[0]['6']['inputs']
        self.assertGreater(latent['height'],latent['width'])
        self.assertGreaterEqual(latent['width']*latent['height'],1000000)
        self.assertAlmostEqual(latent['width']/latent['height'],9/16,delta=.02)

    def test_quota_switch_persists_and_next_day_retries_cloud(self):
        with patch.object(self.tool, 'doubao', side_effect=ProviderError('今日生图次数已用完')) as cloud, \
             patch.object(self.tool, 'local', side_effect=self.output) as local:
            first = self.tool.generate('first', self.root / 'first.png')
            second = self.tool.generate('second', self.root / 'second.png')
        self.assertEqual(cloud.call_count, 1); self.assertEqual(local.call_count, 2)
        self.assertEqual(first['provider'], 'local'); self.assertEqual(second['provider'], 'local')
        restarted = PriorityImageTool(self.root, day=lambda: self.day)
        with patch.object(restarted, 'doubao') as cloud, patch.object(restarted, 'local', side_effect=self.output):
            restarted.generate('restart', self.root / 'third.png')
            cloud.assert_not_called()
        self.day = '2026-11-05'
        with patch.object(restarted, 'doubao', side_effect=self.output) as cloud, patch.object(restarted, 'local') as local:
            restarted.generate('new day', self.root / 'fourth.png')
            cloud.assert_called_once(); local.assert_not_called()

    def test_response_crossing_midnight_does_not_exhaust_new_day(self):
        def failure(*args, **kwargs):
            self.day = '2026-11-05'
            raise ProviderError('今日生图额度用完')
        with patch.object(self.tool, 'doubao', side_effect=failure), patch.object(self.tool, 'local', side_effect=self.output):
            self.tool.generate('late request', self.root / 'late.png')
        account = self.tool.route_config()[2]
        self.assertTrue(self.tool.quota.exhausted(account, '2026-11-04'))
        self.assertFalse(self.tool.quota.exhausted(account, '2026-11-05'))

    def test_auth_rate_limit_and_ambiguous_timeout_never_switch_or_retry(self):
        for message in ('登录已失效', '710022002 当前服务访问频率过高', '网络超时，请求可能已提交'):
            with self.subTest(message=message), patch.object(self.tool, 'doubao', side_effect=ProviderError(message)) as cloud, patch.object(self.tool, 'local') as local:
                with self.assertRaises(ProviderError): self.tool.generate('test', self.root / 'bad.png')
                cloud.assert_called_once(); local.assert_not_called()
                self.assertFalse(self.tool.quota.exhausted(self.tool.route_config()[2], self.day))

    def test_missing_provider_does_not_silently_use_local(self):
        self.tool.providers.save({'provider': 'mock_doubao', 'enabled': False})
        with patch.object(self.tool, 'local') as local, self.assertRaisesRegex(ProviderError, '启用豆包'):
            self.tool.generate('test', self.root / 'bad.png')
        local.assert_not_called()

    def test_local_failure_is_terminal_and_credentials_are_redacted(self):
        with patch.object(self.tool, 'doubao', side_effect=ProviderError('今日生图额度已用完')), \
             patch.object(self.tool, 'local', side_effect=RuntimeError('private-session-cookie local unavailable')):
            with self.assertRaises(ProviderError): self.tool.generate('test', self.root / 'failed.png')
        text = (self.root / 'failed-trace.json').read_text(encoding='utf-8')
        self.assertNotIn('private-session-cookie', text)
        self.assertEqual(json.loads(text)['status'], 'error')

    def test_account_session_change_has_its_own_day_marker(self):
        old = self.tool.route_config()[2]
        self.tool.quota.mark(old, self.day)
        (self.root / 'mock_doubao.json').write_text(json.dumps({'headers': {'Cookie': 'different-account-cookie'}}))
        new = self.tool.route_config()[2]
        self.assertNotEqual(old, new)
        self.assertFalse(self.tool.quota.exhausted(new, self.day))

    def test_late_old_day_response_cannot_overwrite_new_day_marker(self):
        self.tool.quota.mark('account', '2026-11-05')
        self.tool.quota.mark('account', '2026-11-04')
        self.assertTrue(self.tool.quota.exhausted('account', '2026-11-05'))

    def test_local_error_cancels_child_preserves_root_error_and_releases_models(self):
        client = MagicMock()
        client.object_info.return_value = {'UNETLoader': {'input': {'required': {'unet_name': [['flux1-krea-dev_fp8_scaled.safetensors']]}}}}
        client.queue.return_value = 'child-prompt-id'
        client.wait.side_effect = RuntimeError('root model execution failed')
        client.release_models.side_effect = RuntimeError('release also failed')
        with patch('services.video_creator.tools.ai.image_priority.ComfyUIClient', return_value=client), \
             patch('services.core.understanding_queue.shared_slot', return_value=nullcontext()), \
             patch('services.douyin.video_understanding.release_understanding_model'):
            with self.assertRaisesRegex(RuntimeError, 'root model execution failed'):
                self.tool.local('test', self.root / 'local.png', lambda **values: None)
        client.cancel.assert_called_once_with('child-prompt-id')
        client.release_models.assert_called_once()
        graph = client.validate_graph.call_args.args[0]
        self.assertEqual(graph['6']['class_type'], 'EmptySD3LatentImage')


if __name__ == '__main__':
    unittest.main()
