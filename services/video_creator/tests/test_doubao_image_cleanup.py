import tempfile
import unittest
from pathlib import Path
from PIL import Image,ImageDraw
from services.video_creator.tools.ai.doubao_image_cleanup import prepare_publication_image


class DoubaoCleanupTests(unittest.TestCase):
    def test_crop_preserves_original_and_removes_only_bottom_band(self):
        root=Path(__file__).resolve().parents[3]/'cache'
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            path=Path(tmp)/'illustration-01.png'
            image=Image.new('RGB',(400,800),'blue')
            ImageDraw.Draw(image).rectangle((0,760,399,799),fill='red');image.save(path)
            original_bytes=path.read_bytes()
            result=prepare_publication_image(path)
            self.assertEqual((path.parent/result['original_file']).read_bytes(),original_bytes)
            with Image.open(path) as cropped:
                self.assertEqual(cropped.size,(400,760))
                self.assertEqual(cropped.getpixel((399,759)),(0,0,255))
            self.assertTrue(result['ai_generated'])
            with self.assertRaises(ValueError):prepare_publication_image(path)
