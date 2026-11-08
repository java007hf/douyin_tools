"""Isolated Qwen3-TTS worker for reusable reference voices."""
from pathlib import Path
import sys


MODEL = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"


def main():
    import soundfile
    import torch
    from qwen_tts import Qwen3TTSModel

    audio, transcript, script, output = map(Path, sys.argv[1:])
    torch.set_num_threads(min(6, torch.get_num_threads()))
    use_cuda = torch.cuda.is_available() and torch.cuda.mem_get_info()[0] >= 4 * 1024**3
    device = "cuda:0" if use_cuda else "cpu"
    print(f"Qwen3-TTS inference on {device}", flush=True)
    dtype = torch.bfloat16 if use_cuda and torch.cuda.is_bf16_supported() else torch.float32
    model = Qwen3TTSModel.from_pretrained(MODEL, device_map=device, dtype=dtype)
    waves, rate = model.generate_voice_clone(
        text=script.read_text(encoding="utf-8"),
        language="Auto",
        ref_audio=str(audio),
        ref_text=transcript.read_text(encoding="utf-8"),
        max_new_tokens=320,
        do_sample=False,
        subtalker_dosample=False,
    )
    soundfile.write(output, waves[0], rate)


if __name__ == "__main__":
    main()
