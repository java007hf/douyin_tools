import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from services.video_creator.tools.ai.doubao_web_video import build_video_request, build_confirmation_request, captured_request, extract_videos, DoubaoWebVideoProvider, MODELS
from services.video_creator.tools.ai.providers import ProviderError
from services.video_creator.tools.ai.mock_doubao_config import MockDoubaoConfigStore

class VideoWebTests(unittest.TestCase):
    def setUp(self):
        self.config=json.loads(Path(__file__).with_name('fixtures').joinpath('doubao_web_video_request.json').read_text(encoding='utf-8'))

    def provider(self):
        root=Path(__file__).resolve().parents[3]/'cache/tests';root.mkdir(parents=True,exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir=root);self.addCleanup(temp.cleanup)
        path=Path(temp.name)/'config.json';path.write_text(json.dumps(self.config),encoding='utf-8')
        return DoubaoWebVideoProvider(path)

    def test_actual_ability_17_model_map_and_model_specific_duration(self):
        before=copy.deepcopy(self.config)
        for name,raw in MODELS.items():
            _,headers,body=build_video_request(self.config,'dog',model=name,aspect='16:9',duration='10')
            self.assertEqual(body['chat_ability']['ability_type'],17)
            ability=json.loads(body['chat_ability']['ability_param'])
            self.assertEqual(ability['model'],raw)
            self.assertEqual(ability['duration'],10)
            self.assertEqual(ability['ratio'],'16:9')
            self.assertEqual(headers['Cookie'],'sessionid=fixture')
            self.assertNotEqual(body['messages'][0]['local_message_id'],before['web_video_request']['submit']['body']['messages'][0]['local_message_id'])
        self.assertEqual(self.config,before)
        with self.assertRaises(ProviderError):build_video_request(self.config,'dog',model='mock_doubao_seedance_2_0_mini',duration='30')
        build_video_request(self.config,'dog',model='mock_doubao_seedance_2_5',duration='30')

    def test_security_checks_both_captured_endpoints(self):
        self.config['web_video_request']['poll']['url']='https://other.test/im/chain/single'
        with self.assertRaises(ProviderError):captured_request(self.config,'poll','/im/chain/single')
        self.config['headers']={}
        with self.assertRaises(ProviderError):build_video_request(self.config,'dog',model=next(iter(MODELS)))

    def test_web_video_only_configuration_saves_without_legacy_android_body(self):
        root=Path(__file__).resolve().parents[3]/'cache/tests';root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            store=MockDoubaoConfigStore(Path(directory)/'config.json')
            self.assertTrue(store.save({'request_config':self.config})['configured'])
            self.assertEqual(store.credentials()['web_video_request'],self.config['web_video_request'])
            self.assertTrue(store.save({'cookie':'sessionid=updated'})['cookie_configured'])

    def test_extract_only_completed_generated_videos_not_reference_or_cover(self):
        value={'avatar':{'url':'https://cdn.test/avatar.mp4'},'content':json.dumps({'creations':[
            {'type':2,'video':{'status':1,'download_url':'https://cdn.test/pending.mp4'}},
            {'type':2,'video':{'status':3,'download_url':'https://cdn.test/output.mp4','cover':{'url':'https://cdn.test/cover.png'}}},
            {'type':1,'image':{'url':'https://cdn.test/image.png'}}]})}
        self.assertEqual(extract_videos(value),['https://cdn.test/output.mp4'])

    def responses(self,poll):
        submit=MagicMock(status_code=200);submit.__enter__.return_value=submit
        submit.iter_lines.return_value=['event: SSE_ACK','data: '+json.dumps({'ack_client_meta':{'conversation_id':'new-conversation'}}),'event: SSE_REPLY_END','data: {}']
        query=MagicMock(status_code=200);query.json.return_value=poll
        return submit,query

    def test_submit_once_then_poll_new_conversation(self):
        trace={}
        responses=self.responses({'content':json.dumps({'creations':[{'type':2,'video':{'status':3,'download_url':'https://cdn.test/video.mp4'}}]})})
        with patch('services.video_creator.tools.ai.doubao_web_video.requests.post',side_effect=responses) as post:
            self.assertEqual(self.provider().generate('dog',model=next(iter(MODELS)),diagnostics=trace),['https://cdn.test/video.mp4'])
        self.assertEqual(post.call_count,2)
        query=json.loads(post.call_args.kwargs['data'])
        self.assertEqual(query['uplink_body']['pull_singe_chain_uplink_body']['conversation_id'],'new-conversation')
        self.assertTrue(trace['reply_end'])

    def test_confirmation_stops_instead_of_indefinite_wait_or_resubmit(self):
        trace={}
        with patch('services.video_creator.tools.ai.doubao_web_video.requests.post',side_effect=self.responses({'text':'请先确认参数，确认后再生成'})) as post:
            with self.assertRaisesRegex(ProviderError,'确认'):
                self.provider().generate('dog',model=next(iter(MODELS)),diagnostics=trace)
        self.assertEqual(post.call_count,2)
        self.assertTrue(trace['awaiting_confirmation'])

    def test_login_error_never_retries_submission(self):
        response=MagicMock(status_code=200);response.__enter__.return_value=response
        response.iter_lines.return_value=['data: {"code":710012001,"message":"login invalid"}']
        with patch('services.video_creator.tools.ai.doubao_web_video.requests.post',return_value=response) as post:
            with self.assertRaises(ProviderError):self.provider().generate('dog',model=next(iter(MODELS)))
        self.assertEqual(post.call_count,1)

    def test_i2v_binds_uploaded_reference_and_updates_all_message_ids(self):
        reference={'name':'reference.png','uri':'tos-cn-i-a9rns2rl98/new.png','width':512,'height':768,'format':'png'}
        before=copy.deepcopy(self.config)
        _,_,body=build_video_request(self.config,'moving dog',model=next(iter(MODELS)),duration='4',aspect='9:16',reference=reference)
        attachment=body['messages'][0]['content_block'][0]['content']['attachment_block']['attachments'][0]
        self.assertEqual(attachment['image']['uri'],reference['uri'])
        self.assertEqual(attachment['image']['image_ori']['width'],512)
        self.assertIn('moving dog',body['messages'][1]['content_block'][0]['content']['text_block']['text'])
        for message,old in zip(body['messages'],before['web_video_request']['i2v_submit']['body']['messages']):self.assertNotEqual(message['local_message_id'],old['local_message_id'])
        self.assertEqual(self.config,before)

    def confirmation_message(self):
        return {'user_type':2,'section_id':'new-section','index_in_conv':'6','content_block':[{'content':{'text_block':{'text':'请先确认：Seedance 2.0 Mini，10 秒，1:1。确认后生成。'}}}]}

    def test_confirmation_uses_same_conversation_and_real_message_cursor(self):
        _,_,body=build_confirmation_request(self.config,'new-conversation',self.confirmation_message(),model=next(iter(MODELS)),duration=10,aspect='1:1')
        self.assertEqual(body['client_meta']['conversation_id'],'new-conversation')
        self.assertEqual(body['client_meta']['last_message_index'],6)
        self.assertEqual(body['client_meta']['last_section_id'],'new-section')
        self.assertFalse(body['option']['need_create_conversation'])
        with self.assertRaisesRegex(ProviderError,'不匹配'):build_confirmation_request(self.config,'new-conversation',self.confirmation_message(),model=next(iter(MODELS)),duration=4,aspect='1:1')

    def test_auto_confirms_at_most_once_and_ignores_old_confirmation_after_new_reply(self):
        submit,_=self.responses({})
        query=MagicMock(status_code=200);query.json.return_value={'downlink_body':{'pull_singe_chain_downlink_body':{'messages':[self.confirmation_message()]}}}
        result=MagicMock(status_code=200);result.json.return_value={'creations':[{'type':2,'video':{'status':3,'download_url':'https://cdn.test/done.mp4'}}]}
        trace={}
        with patch('services.video_creator.tools.ai.doubao_web_video.requests.post',side_effect=[submit,query,submit,query,result]) as post,patch('services.video_creator.tools.ai.doubao_web_video.time.sleep'):
            self.assertEqual(self.provider().generate('dog',model=next(iter(MODELS)),duration=10,aspect='1:1',diagnostics=trace),['https://cdn.test/done.mp4'])
        self.assertTrue(trace['confirmation_sent'])
        self.assertEqual(sum('/chat/completion' in call.args[0] for call in post.call_args_list),2)

if __name__=='__main__':unittest.main()
