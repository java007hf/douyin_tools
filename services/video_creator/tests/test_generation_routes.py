import unittest
from services.video_creator.tools.ai.generation_routes import image_generation_fields

class GenerationRoutesTests(unittest.TestCase):
    def test_ai_video_image_route_preserves_mock_provider_config_id_and_model(self):
        fields=image_generation_fields({'default_image_provider_id':'configured-mock-id','default_image_model':'mock_doubao_seedream_5_0_flash','api_key':'agent-secret'}, {'prompt':'independent prop'})
        self.assertEqual(fields['provider_id'],'configured-mock-id')
        self.assertEqual(fields['model'],'mock_doubao_seedream_5_0_flash')
        self.assertEqual(fields['prompt'],'independent prop')
        self.assertNotIn('api_key',fields)

    def test_missing_ai_video_route_does_not_use_regular_prompt_helper(self):
        fields=image_generation_fields({}, {},'brief')
        self.assertEqual(fields['provider_id'],'local')
        self.assertEqual(fields['prompt'],'brief')

    def test_automatic_model_uses_selected_provider_default(self):
        fields=image_generation_fields({'default_image_provider_id':'mock-id'}, {'prompt':'prop'},provider={'model':'mock_doubao_seedream_5_0_flash'})
        self.assertEqual(fields['model'],'mock_doubao_seedream_5_0_flash')
