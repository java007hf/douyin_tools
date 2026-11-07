import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock,patch
from PIL import Image
from services.douyin.publishing.preview_review import review_preview,capture_preview


class PreviewReviewTests(unittest.TestCase):
    def test_visible_native_preview_and_all_cards_are_required(self):
        root=Path(__file__).resolve().parents[3]/'cache'
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            folder=Path(tmp);paths=[folder/f'{i}.png' for i in range(4)]
            for p in paths:Image.new('RGB',(108,192)).save(p)
            provider=Mock(config={'model':'configured-vision','api_key':'test-secret'})
            with patch('services.douyin.publishing.preview_review.shared_slot',return_value=nullcontext()):
                for result in ({'passed':True,'preview_visible':False,'issues':[]},
                               {'passed':True,'preview_visible':True,'issues':[{'page':2,'problem':'正文被遮挡'}]},
                               {'passed':'true','preview_visible':True,'issues':[]}):
                    provider.complete.return_value=result
                    with self.assertRaises(ValueError):
                        review_preview(paths[0],paths[1:],folder,task_id='test',progress=lambda m:None,provider=provider)
                    self.assertEqual(json.loads((folder/'visual-review.json').read_text(encoding='utf-8'))['status'],'failed')
                provider.complete.return_value={'passed':True,'preview_visible':True,'issues':[],'summary':'可见文字完整'}
                result=review_preview(paths[0],paths[1:],folder,task_id='test',progress=lambda m:None,provider=provider)
                self.assertEqual(result['status'],'passed')
                self.assertEqual(provider.complete.call_args.kwargs['images'],paths)
                self.assertNotIn('test-secret',(folder/'visual-review.json').read_text(encoding='utf-8'))

    def test_missing_native_preview_never_uses_entire_page_as_success(self):
        page=Mock();page.get_by_text.return_value.first.wait_for.side_effect=RuntimeError('missing')
        with self.assertRaises(RuntimeError):capture_preview(page,Path('cache'))
        page.screenshot.assert_not_called()
