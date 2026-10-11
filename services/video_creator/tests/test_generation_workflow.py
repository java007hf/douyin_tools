import unittest

from services.video_creator.workflow.generation import load_full_h3_template


class GenerationWorkflowQualityTests(unittest.TestCase):
    def test_h3_768p_quality_profile_binds_native_pixel_area_and_full_steps(self):
        graph=load_full_h3_template("i2v",{"resolution":"768p","aspect":"16:9","duration":"5","steps":"24","seed":"7","prompt":"test"})
        self.assertIsNotNone(graph)
        resolution=next(node for node in graph.values() if node.get("class_type")=="ResolutionSelector")
        self.assertEqual(resolution["inputs"]["megapixels"],1.0)
        self.assertEqual(resolution["inputs"]["aspect_ratio"],"16:9 (Widescreen)")
        turbo=next(node for node in graph.values() if node.get("class_type")=="PrimitiveBoolean")
        self.assertFalse(turbo["inputs"]["value"])
        self.assertTrue(any(node.get("class_type")=="PrimitiveInt" and node.get("inputs",{}).get("value")==24 for node in graph.values()))

    def test_h3_768p_rejects_more_than_five_seconds_on_12gb_profile(self):
        with self.assertRaisesRegex(ValueError,"最多支持 5 秒"):
            load_full_h3_template("i2v",{"resolution":"768p","duration":"6"})


if __name__=="__main__": unittest.main()
