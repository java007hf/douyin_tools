"""Lossless-first video concatenation tool used by workflows."""
from __future__ import annotations
import subprocess
import shutil
from pathlib import Path


def _ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    fallback = Path(r"C:\ProgramData\chocolatey\bin\ffmpeg.exe")
    if fallback.is_file():
        return str(fallback)
    raise FileNotFoundError("ffmpeg is required to merge video clips; install it and add it to PATH")


def merge_videos(inputs: list[Path], output: Path) -> Path:
    """Normalize stream clocks and audio before concatenating Provider outputs."""
    import json
    import tempfile
    if not inputs:
        raise ValueError("没有可合成的视频片段")
    if len(inputs) == 1:
        output.write_bytes(inputs[0].read_bytes())
        return output
    ffmpeg = _ffmpeg()
    ffprobe = shutil.which('ffprobe') or str(Path(ffmpeg).with_name('ffprobe.exe'))
    metadata=[]
    for path in inputs:
        probe=subprocess.run([ffprobe,'-v','error','-show_streams','-of','json',str(path)],capture_output=True,text=True,timeout=60,check=True)
        streams=json.loads(probe.stdout)['streams']
        video=next(item for item in streams if item['codec_type']=='video')
        duration=float(video['duration'])
        metadata.append((video,duration,any(item['codec_type']=='audio' for item in streams)))
    width=int(metadata[0][0]['width']);height=int(metadata[0][0]['height'])
    # Mono 32 kHz Foley and stereo 44.1 kHz native speech cannot be stream-copied
    # into one track: ffmpeg may exit successfully with a stretched audio clock.
    with tempfile.TemporaryDirectory(prefix='merge_',dir=output.parent) as scratch:
        normalized=[]
        for index,(path,(_,duration,has_audio)) in enumerate(zip(inputs,metadata)):
            target=Path(scratch)/f'{index:03d}.mp4'
            command=[ffmpeg,'-y','-i',str(path)]
            if not has_audio: command+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
            command+=['-map','0:v:0','-map','0:a:0' if has_audio else '1:a:0',
                      '-vf',f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,setpts=PTS-STARTPTS',
                      '-af','aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS,apad',
                      '-t',str(duration),'-r','24','-video_track_timescale','12288',
                      '-c:v','libx264','-preset','fast','-crf','18','-c:a','aac','-ar','48000','-ac','2',str(target)]
            result=subprocess.run(command,capture_output=True,text=True,timeout=600)
            if result.returncode: raise RuntimeError('片段标准化失败：'+result.stderr[-1000:])
            normalized.append(target)
        manifest=Path(scratch)/'concat.txt'
        manifest.write_text(''.join("file '"+str(path.resolve()).replace("'","'\\''")+"'\n" for path in normalized),encoding='utf-8')
        result=subprocess.run([ffmpeg,'-y','-f','concat','-safe','0','-i',str(manifest),'-c','copy','-movflags','+faststart',str(output)],capture_output=True,text=True,timeout=300)
        if result.returncode or not output.is_file(): raise RuntimeError('视频合成失败：'+result.stderr[-1000:])
    return output
