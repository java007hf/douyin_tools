import tempfile
import unittest
from unittest.mock import Mock
from pathlib import Path
from services.douyin.publishing.douyin_music import music_candidates, music_queries, require_music_payload, select_music, is_music_search_url, guard_music_request


class DouyinMusicTests(unittest.TestCase):
    def test_uses_selectable_track_not_original_sound_child(self):
        value={'music':[{'mid':'7654899660881168385','id_str':'7654899660881168385',
            'title':'Calm Piano','author':'Spa Relaxing Music','duration':60,
            'original_sound':{'id_str':'7654899802035865601','title':'Calm Piano'}}]}
        result=music_candidates(value)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['music_id'],'7654899660881168385')
        self.assertEqual(result[0]['author'],'Spa Relaxing Music')

    def test_catalog_rejects_unusable_and_incomplete_results(self):
        values=[{'music_id':'7654899660881168385','music_name':'Calm Piano','duration':60,'can_use':False},
                {'mid':'not-a-real-id','title':'Fake','duration':60},
                {'mid':'7654899660881168385','title':'No duration'}]
        self.assertEqual(music_candidates(values),[])

    def test_search_matches_observed_platform_host_only(self):
        self.assertTrue(is_music_search_url('https://tsearch.amemv.com/openapi/aweme/v1/music/search/?keyword=calm'))
        self.assertFalse(is_music_search_url('https://tsearch.amemv.com.example.org/openapi/aweme/v1/music/search/'))
        self.assertFalse(is_music_search_url('https://creator.douyin.com/unrelated'))

    def test_search_uses_bounded_model_keywords(self):
        self.assertEqual(music_queries({'keywords':['calm piano','calm piano','','soft ambient','piano','extra']}),
                         ['calm piano','soft ambient','piano'])
        for value in (None,{}, {'keywords':[]}, {'keywords':'piano'}):
            with self.assertRaises(ValueError):music_queries(value)

    def test_wire_music_must_match_selected_catalog_id(self):
        selected={'status':'selected','music_id':'7654899660881168385'}
        value={'item':{'common':{'music_id':'7654899660881168385','music_end_time':60000}}}
        self.assertEqual(require_music_payload(value,selected),{'music_id':'7654899660881168385','start_time_ms':0,'end_time_ms':60000})
        for identifier in (None,False,0,'0','7654899802035865601',{},7654899660881168385.0):
            with self.assertRaises(ValueError):
                require_music_payload({'item':{'common':{'music_id':identifier}}},selected)
        with self.assertRaises(ValueError):require_music_payload(value,{'status':'suggested','music_id':selected['music_id']})
        with self.assertRaises(ValueError):require_music_payload({'music_id':selected['music_id']},selected)

    def test_missing_music_is_aborted_before_any_network_forward(self):
        route=Mock()
        route.request.url='https://creator.douyin.com/web/api/media/aweme/create_v2/'
        route.request.method='POST'
        route.request.post_data_json={'item':{'common':{'music_id':'0'}}}
        mark=Mock();state={}
        guard_music_request(route,{'status':'selected','music_id':'7654899660881168385'},state,mark)
        route.abort.assert_called_once()
        route.continue_.assert_not_called()
        mark.assert_not_called()
        self.assertIn('blocked',state)

    def test_matching_music_is_marked_before_forwarding(self):
        route=Mock();events=[]
        route.request.url='https://creator.douyin.com/web/api/media/aweme/create_v2/'
        route.request.method='POST'
        route.request.post_data_json={'item':{'common':{'music_id':'7654899660881168385','music_end_time':60000}}}
        route.continue_.side_effect=lambda:events.append('forward')
        state={}
        guard_music_request(route,{'status':'selected','music_id':'7654899660881168385'},state,lambda:events.append('mark'))
        self.assertEqual(events,['mark','forward'])
        route.abort.assert_not_called()
        self.assertEqual(state['submitted']['music_id'],'7654899660881168385')

    def test_zero_or_invalid_music_interval_is_not_audible_binding(self):
        selected={'status':'selected','music_id':'7654899660881168385'}
        for end in (None,0,-1,False,float('inf')):
            with self.assertRaises(ValueError):
                require_music_payload({'item':{'common':{'music_id':selected['music_id'],'music_end_time':end}}},selected)

    def test_missing_music_plan_stops_before_browser_actions(self):
        with tempfile.TemporaryDirectory(dir='cache') as folder:
            with self.assertRaises(ValueError):select_music(None,{},Path(folder))


if __name__=='__main__':unittest.main()
