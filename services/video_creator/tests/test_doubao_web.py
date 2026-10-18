import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.video_creator.tools.ai.doubao_web import build_web_request, DoubaoWebImageProvider
from services.video_creator.tools.ai.providers import ProviderError


class DoubaoWebTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(Path(__file__).with_name('fixtures').joinpath('doubao_web_request.json').read_text(encoding='utf-8'))

    def test_actual_nested_parameter_schema_and_new_message_ids(self):
        before = copy.deepcopy(self.config)
        url, headers, body = build_web_request(self.config, '一只小狗', model='mock_doubao_seedream_4_5', style='skill_image_styles_watercolor', aspect='1:1')
        ability = json.loads(body['chat_ability']['ability_param'])
        self.assertEqual(body['chat_ability']['ability_type'], 3)
        self.assertEqual(ability['ability_type'], 1)
        self.assertEqual(ability['ability_param']['model'], 'Seedream 4.5')
        self.assertEqual(ability['ability_param']['style'], 'skill_image_styles_watercolor')
        self.assertEqual(ability['ability_param']['ratio'], '1:1')
        self.assertIn('水彩画', body['messages'][0]['content_block'][0]['content']['text_block']['text'])
        self.assertNotEqual(body['option']['unique_key'], before['web_request']['body']['option']['unique_key'])
        self.assertEqual(self.config, before)

    def test_admin_cookie_takes_precedence_and_absence_is_error(self):
        self.config['headers']['Cookie'] = 'sessionid=refreshed-fixture'
        self.assertEqual(build_web_request(self.config, 'dog')[1]['Cookie'], 'sessionid=refreshed-fixture')
        self.config['headers'] = {}
        self.config['web_request']['headers'] = {}
        with self.assertRaises(ProviderError):
            build_web_request(self.config, 'dog')

    def test_unsafe_endpoint_rejected_before_sending_cookie(self):
        self.config['web_request']['url'] = 'https://other.example/chat/completion'
        with self.assertRaises(ProviderError):
            build_web_request(self.config, 'dog')

    def provider(self):
        root = Path(__file__).resolve().parents[3] / 'cache' / 'tests'
        root.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(temp.cleanup)
        path = Path(temp.name)/'config.json'
        path.write_text(json.dumps(self.config), encoding='utf-8')
        return DoubaoWebImageProvider(path)

    def response(self, lines):
        response = MagicMock(status_code=200)
        response.__enter__.return_value = response
        response.iter_lines.return_value = lines
        return response

    def test_actual_patch_events_ignore_avatar_and_require_reply_end(self):
        patch_value = {'message_id':'fixture-message', 'patch_op':[{'patch_object':1,'patch_type':1,'patch_value':{'content_block':[{
            'content':{'creation_block':{'creations':[{'type':1,'image':{'status':2,'image_ori_raw':{'url':'https://cdn.test/generated.png'}}}]}}}
        ]}}]}
        lines = ['event: SSE_ACK', 'data: '+json.dumps({'ack_client_meta':{'image':{'image_ori':{'url':'https://cdn.test/avatar.png'}}}}), '',
                 'event: STREAM_CHUNK', 'data: '+json.dumps(patch_value), '',
                 'event: SSE_REPLY_END', 'data: {"end_type":3}', '']
        trace = {}
        with patch('services.video_creator.tools.ai.doubao_web.requests.post', return_value=self.response(lines)) as post:
            self.assertEqual(self.provider().generate('dog', diagnostics=trace), ['https://cdn.test/generated.png'])
        self.assertEqual(post.call_count, 1)
        self.assertTrue(trace['reply_end'])
        sent = json.loads(post.call_args.kwargs['data'])
        self.assertEqual(sent['messages'][0]['content_block'][0]['content']['text_block']['text'].split('，')[0], '生成图片：dog')

    def test_auth_failure_never_retries_or_falls_back(self):
        with patch('services.video_creator.tools.ai.doubao_web.requests.post', return_value=self.response(['{"code":710012001,"message":"login invalid"}'])) as post:
            with self.assertRaises(ProviderError) as caught:
                self.provider().generate('dog')
        self.assertIn('710012001', str(caught.exception))
        self.assertEqual(post.call_count, 1)

    def test_two_references_preserve_attachment_schema_and_locate_text_message(self):
        config=json.loads(Path(__file__).with_name('fixtures').joinpath('doubao_web_reference_request.json').read_text(encoding='utf-8'))
        before=copy.deepcopy(config)
        refs=[{'uri':'tos-cn-i-a9rns2rl98/one.png','name':'one.png','width':100,'height':200,'format':'png'},
              {'uri':'tos-cn-i-a9rns2rl98/two.png','name':'two.png','width':300,'height':400,'format':'png'}]
        _,_,body=build_web_request(config,'two dogs',references=refs,aspect='1:1',style='skill_image_styles_watercolor')
        attachment=body['messages'][0]['content_block'][0]['content']['attachment_block']['attachments']
        self.assertEqual([x['image']['uri'] for x in attachment],[x['uri'] for x in refs])
        self.assertEqual(attachment[1]['image']['image_ori']['width'],300)
        self.assertIn('two dogs',body['messages'][1]['content_block'][0]['content']['text_block']['text'])
        self.assertIn('水彩画',body['messages'][1]['content_block'][0]['content']['text_block']['text'])
        self.assertNotEqual(body['messages'][1]['local_message_id'],before['web_reference_request']['body']['messages'][1]['local_message_id'])
        self.assertEqual(config,before)

    def test_upload_failure_prevents_generation_post(self):
        self.config=json.loads(Path(__file__).with_name('fixtures').joinpath('doubao_web_reference_request.json').read_text(encoding='utf-8'))
        with patch('services.video_creator.tools.ai.doubao_upload_bridge.upload_references',side_effect=ProviderError('upload failed')),patch('services.video_creator.tools.ai.doubao_web.requests.post') as post:
            with self.assertRaisesRegex(ProviderError,'upload failed'):
                self.provider().generate('dog',reference_images=[Path('fixture.png')])
            post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
