"""Reversible bottom-band crop for Doubao publication illustration outputs."""
from pathlib import Path
import shutil
from PIL import Image


def prepare_publication_image(path):
    """Exclude the bottom 5% before typography; preserve the untouched output.

    This is a provider-specific crop, not OCR or a claim to recognize arbitrary
    watermarks. The final publication renderer restores the platform canvas.
    """
    path=Path(path)
    original=path.with_name(path.stem+'-provider-original'+path.suffix)
    if original.exists():
        raise ValueError('豆包原图备份已存在，不能重复裁切同一输出')
    with Image.open(path) as image:
        image.load();width,height=image.size
        removed=max(1,round(height*.05))
        cropped=image.crop((0,0,width,height-removed))
        shutil.copyfile(path,original)
        cropped.save(path,'PNG')
    return {'method':'provider_bottom_band_crop','removed_bottom_fraction':.05,
            'original_file':original.name,'original_size':[width,height],
            'output_size':[width,height-removed],'ai_generated':True,
            'scope':'doubao_publication_illustration','watermark_detection':'not_performed'}
