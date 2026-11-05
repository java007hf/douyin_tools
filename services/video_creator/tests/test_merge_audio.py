import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from services.video_creator.tools.video.merge import merge_videos


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class MergeAudioTests(unittest.TestCase):
    def test_mixed_audio_rates_preserve_duration_and_seekability(self):
        import cv2
        cache=Path(__file__).resolve().parents[3]/'cache'
        cache.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache) as folder:
            root=Path(folder);inputs=[]
            for index,(rate,channels) in enumerate([(32000,1),(44100,2)]):
                path=root/f'{index}.mp4'
                subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=red:s=160x90:r=24:d=0.5','-f','lavfi','-i',f'sine=frequency=440:sample_rate={rate}:duration=0.5','-c:v','libx264','-c:a','aac','-ac',str(channels),'-t','0.5',str(path)],check=True,capture_output=True,timeout=30)
                inputs.append(path)
            output=merge_videos(inputs,root/'final.mp4')
            probe=subprocess.run(['ffprobe','-v','error','-show_streams','-of','json',str(output)],check=True,capture_output=True,text=True,timeout=10)
            streams=json.loads(probe.stdout)['streams']
            audio=next(x for x in streams if x['codec_type']=='audio');video=next(x for x in streams if x['codec_type']=='video')
            self.assertEqual(audio['sample_rate'],'48000');self.assertEqual(audio['channels'],2)
            self.assertAlmostEqual(float(video['duration']),1.0,delta=.05)
            self.assertLess(abs(float(audio['duration'])-float(video['duration'])),.1)
            capture=cv2.VideoCapture(str(output))
            try:
                for index in (0,12,23):
                    capture.set(cv2.CAP_PROP_POS_FRAMES,index)
                    self.assertTrue(capture.read()[0],index)
            finally:capture.release()
