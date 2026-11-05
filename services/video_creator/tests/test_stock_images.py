import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from PIL import Image

from services.video_creator.tools.ai.stock_images import StockFirstImageTool


class StockImageTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[3] / 'cache'
        self.temp = tempfile.TemporaryDirectory(prefix='stock-test-', dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ai = MagicMock()
        def generate(prompt, target, progress, **kwargs):
            Image.new('RGB', (1280, 720), '#ead9bb').save(target)
            trace = {'provider':'mock_doubao','status':'done','model':'fixture'}
            progress(trace)
            return trace
        self.ai.generate.side_effect = generate
        self.tool = StockFirstImageTool(self.root, ai=self.ai)

    def config(self, provider='stock_pixabay'):
        self.tool.providers.save({'provider':provider,'api_key':'test-private-api-key','enabled':True})
        return self.tool.providers.get_by_provider(provider)

    def photo(self, **values):
        return {**{'id':1,'type':'photo','tags':'park sunlight walking','largeImageURL':'https://cdn.pixabay.com/photo/1.jpg',
                   'pageURL':'https://pixabay.com/photos/park-1/','user':'Photographer','imageWidth':1800,'imageHeight':1200},**values}

    def response(self, data):
        result=MagicMock();result.__enter__.return_value=result;result.status_code=200;result.json.return_value=data
        return result

    def test_missing_key_uses_ai_and_explains_why(self):
        result=self.tool.generate('prompt',self.root/'one.png',search_terms=['park sunlight'])
        self.assertEqual(result['provider'],'mock_doubao')
        self.assertIn('图库未配置',result['stock_fallback_reason'])
        self.ai.generate.assert_called_once()

    def test_photo_source_precedes_ai_and_retains_credit(self):
        self.config()
        with patch('services.video_creator.tools.ai.stock_images.requests.get',return_value=self.response({'hits':[self.photo()]})), \
             patch('services.video_creator.tools.ai.stock_images.save_image',side_effect=lambda url,target:Image.new('RGB',(1280,720)).save(target)):
            result=self.tool.generate('prompt',self.root/'one.png',search_terms=['park sunlight'])
        self.ai.generate.assert_not_called()
        self.assertFalse(result['ai_generated'])
        self.assertEqual(result['author'],'Photographer')
        self.assertIn('Pixabay',result['license'])
        self.assertIn('Photo by',result['attribution'])
        raw=(self.root/'one-trace.json').read_text(encoding='utf-8')
        self.assertNotIn('test-private-api-key',raw)

    def test_search_cache_reuses_response_for_24_hours(self):
        config=self.config()
        with patch('services.video_creator.tools.ai.stock_images.requests.get',return_value=self.response({'hits':[self.photo()]})) as request:
            self.tool.search('stock_pixabay',config,'park sunlight','16:9')
            self.tool.search('stock_pixabay',config,'park sunlight','16:9')
        self.assertEqual(request.call_count,1)
        self.assertNotIn('test-private-api-key',self.tool.cache.read_bytes().decode('utf-8',errors='ignore'))

    def test_rejects_ai_metadata_vector_and_untrusted_download_host(self):
        config=self.config()
        data={'hits':[self.photo(type='vector'),self.photo(is_ai_generated=True),self.photo(tags='AI generated park'),
                      self.photo(largeImageURL='https://evil.example/a.jpg')]}
        with patch('services.video_creator.tools.ai.stock_images.requests.get',return_value=self.response(data)):
            self.assertEqual(self.tool.search('stock_pixabay',config,'park','16:9'),[])

    def test_no_matching_photo_uses_ai_and_no_duplicate_in_one_package(self):
        self.config()
        with patch.object(self.tool,'search',return_value=[{'id':'1','provider':'stock_pixabay','url':'https://cdn.pixabay.com/a.jpg',
             'page_url':'https://pixabay.com/photos/a/','author':'A','description':'park sunlight',
             'license':'Pixabay Content License','license_url':'https://pixabay.com/service/license-summary/'}]), \
             patch('services.video_creator.tools.ai.stock_images.save_image',side_effect=lambda url,target:Image.new('RGB',(1280,720)).save(target)):
            first=self.tool.generate('prompt',self.root/'one.png',search_terms=['park'])
            second=self.tool.generate('prompt',self.root/'two.png',search_terms=['park'])
        self.assertEqual(first['provider'],'stock_pixabay')
        self.assertEqual(second['provider'],'mock_doubao')

    def test_failed_api_never_leaks_request_key(self):
        self.config()
        with patch('services.video_creator.tools.ai.stock_images.requests.get',side_effect=requests.ConnectionError('https://pixabay.com/api?key=test-private-api-key')):
            result=self.tool.generate('prompt',self.root/'one.png',search_terms=['park'])
        self.assertNotIn('test-private-api-key',json.dumps(result))
        self.assertTrue(result['ai_generated'])

    def test_nine_sixteen_search_requests_portrait_photos(self):
        config=self.config()
        with patch('services.video_creator.tools.ai.stock_images.requests.get',return_value=self.response({'hits':[]})) as request:
            self.tool.search('stock_pixabay',config,'apartment','9:16')
        self.assertEqual(request.call_args.kwargs['params']['orientation'],'vertical')

    def test_pexels_endpoint_uses_header_and_captures_photographer(self):
        config=self.config('stock_pexels')
        data={'photos':[{'id':2,'alt':'sunlight park','photographer':'Jane','url':'https://www.pexels.com/photo/2/',
                         'src':{'large2x':'https://images.pexels.com/photos/2.jpg'},'width':2000,'height':3000}]}
        with patch('services.video_creator.tools.ai.stock_images.requests.get',return_value=self.response(data)) as request:
            result=self.tool.search('stock_pexels',config,'park','3:4')
        self.assertEqual(result[0]['author'],'Jane')
        self.assertEqual(request.call_args.kwargs['headers']['Authorization'],'test-private-api-key')
        self.assertNotIn('key',request.call_args.kwargs['params'])

    def test_pixabay_only_never_calls_ai_when_no_photo_matches(self):
        self.config()
        tool=StockFirstImageTool(self.root,ai=self.ai,stock_only=True,sources=('stock_pixabay',))
        traces=[]
        with patch.object(tool,'search',return_value=[]),self.assertRaisesRegex(RuntimeError,'本次限定图库'):
            tool.generate('prompt',self.root/'only.png',traces.append,search_terms=['park sunlight'])
        self.ai.generate.assert_not_called()
        self.assertEqual(traces[-1]['status'],'error')

    def test_over_specific_physical_search_can_broaden_without_ai(self):
        self.config()
        queries=[]
        def search(provider,config,query,aspect):
            queries.append(query)
            return []
        with patch.object(self.tool,'search',side_effect=search):
            self.tool.generate('prompt',self.root/'broaden.png',search_terms=['bright cafe window natural light'])
        self.assertIn('cafe window',queries)


if __name__=='__main__':unittest.main()
