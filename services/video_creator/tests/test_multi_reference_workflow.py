import unittest

from services.video_creator.workflow.generation import bind_media, video_workflow


class MultiReferenceWorkflowTests(unittest.TestCase):
    def test_reference_pack_binds_up_to_nine_images(self):
        payload={"prompt":"test","resolution":"360p","aspect":"16:9","duration":"5","reference_count":4}
        graph=video_workflow("reference_pack_i2v",payload)
        uploaded=[f"douyin/reference_{index}.png" for index in range(1,5)]
        bound=bind_media(graph,images=uploaded)
        node=next(node["inputs"] for node in bound.values() if node.get("class_type")=="MiniMaxH3ReferenceToVideo")
        self.assertEqual(len([key for key in node if key.startswith("ref_images.ref_image_")]),4)
        self.assertEqual(bound["multi_ref_4"]["inputs"]["image"],uploaded[3])

    def test_reference_count_is_capped_at_nine(self):
        graph=video_workflow("reference_pack_i2v",{"prompt":"test","resolution":"360p","duration":"5","reference_count":20})
        self.assertEqual(len([node for node in graph.values() if node.get("class_type")=="LoadImage"]),9)


if __name__ == "__main__":
    unittest.main()
