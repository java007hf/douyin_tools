import base64
import unittest
from unittest.mock import Mock
from services.video_creator.tools.ai.doubao_upload_bridge import upload_file

class UploadBridgeTests(unittest.TestCase):
    def payload(self):
        return {'url':'https://tos-d-ct-lf.snssdk.com/upload/v1/tos-cn-i-a9rns2rl98/fixture.png',
                'headers':{'Authorization':'fixture-auth','Content-CRC32':'fixture-crc','Cookie':'never-forward',
                           'Host':'other.test','Content-Length':'999','X-Storage-U':'fixture-storage'},
                'data':base64.b64encode(b'actual bytes').decode()}

    def test_binary_and_upload_authorization_forwarded_cookie_and_length_not_forwarded(self):
        session=Mock();session.post.return_value=Mock(status_code=200,content=b'{}',text='{}',headers={})
        self.assertEqual(upload_file(self.payload(),session)['status'],200)
        call=session.post.call_args
        self.assertEqual(call.kwargs['data'],b'actual bytes')
        self.assertEqual(call.kwargs['headers'],{'Authorization':'fixture-auth','Content-CRC32':'fixture-crc','X-Storage-U':'fixture-storage'})
        self.assertFalse(call.kwargs['allow_redirects'])
        self.assertEqual(session.post.call_count,1)

    def test_unknown_host_path_and_userinfo_rejected_before_network(self):
        for url in ['http://127.0.0.1/upload/v1/tos-cn-i-a9rns2rl98/a',
                    'https://other.test/upload/v1/tos-cn-i-a9rns2rl98/a',
                    'https://tos-d-ct-lf.snssdk.com/other',
                    'https://user@tos-d-ct-lf.snssdk.com/upload/v1/tos-cn-i-a9rns2rl98/a']:
            session=Mock();payload=self.payload();payload['url']=url
            with self.assertRaises(ValueError):upload_file(payload,session)
            session.post.assert_not_called()

    def test_no_redirect_or_retry(self):
        session=Mock();session.post.return_value=Mock(status_code=302)
        with self.assertRaises(ValueError):upload_file(self.payload(),session)
        self.assertEqual(session.post.call_count,1)

    def test_new_storage_host_requires_explicit_apply_registration(self):
        payload=self.payload();payload['url']=payload['url'].replace('tos-d-ct-lf','tos-new-fixture')
        session=Mock();session.post.return_value=Mock(status_code=200,content=b'{}',text='{}',headers={})
        with self.assertRaises(ValueError):upload_file(payload,session)
        self.assertEqual(upload_file(payload,session,{'tos-new-fixture.snssdk.com'})['status'],200)

if __name__=='__main__':unittest.main()
