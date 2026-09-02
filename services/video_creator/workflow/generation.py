"""API-format ComfyUI workflows for the generation tab.

Image generation supports the installed Flux and Qwen Image checkpoints. Video generation is routed
to the matching user workflow template through the same API boundary; the
template can be supplied via COMFYUI_*_WORKFLOW environment variables.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def load_external(name: str) -> dict | None:
    value = os.getenv(name)
    if not value:
        return None
    path = Path(value)
    if not path.is_file():
        raise ValueError(f"Workflow file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("prompt", data)


def flux_image(prompt: str, negative: str, width: int, height: int, count: int, seed: int, reference: str | None = None, denoise: float = 0.7, model: str = "flux1-krea-dev_fp8_scaled.safetensors") -> dict:
    graph = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": model, "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl_fp8_e4m3fn_scaled.safetensors", "type": "flux"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "4": {"class_type": "CLIPTextEncodeFlux", "inputs": {"clip": ["2", 0], "clip_l": prompt, "t5xxl": prompt, "guidance": 3.5}},
        "5": {"class_type": "CLIPTextEncodeFlux", "inputs": {"clip": ["2", 0], "clip_l": negative, "t5xxl": negative, "guidance": 3.5}},
        "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": width, "height": height, "batch_size": count}},
        "7": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0], "seed": seed, "steps": 20, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "douyin_creator/image", "images": ["8", 0]}},
    }
    if reference:
        graph["10"] = {"class_type": "LoadImage", "inputs": {"image": reference}}
        graph["11"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["10", 0], "vae": ["3", 0]}}
        graph["7"]["inputs"]["latent_image"] = ["11", 0]
        graph["7"]["inputs"]["denoise"] = max(0.05, min(1.0, denoise))
    return graph


def qwen_image(prompt: str, width: int, height: int, count: int, seed: int) -> dict:
    """Build the native Qwen-Image text-to-image graph."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_fp8_e4m3fn.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": ""}},
        "6": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": count}},
        "7": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.1}},
        "8": {"class_type": "KSampler", "inputs": {"model": ["7", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0], "seed": seed, "steps": 20, "cfg": 4.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"filename_prefix": "douyin_creator/qwen_image", "images": ["9", 0]}},
    }


def video_workflow(kind: str, payload: dict) -> dict:
    env = {"t2v": "COMFYUI_T2V_WORKFLOW", "i2v": "COMFYUI_I2V_WORKFLOW", "r2v": "COMFYUI_R2V_WORKFLOW"}[kind]
    workflow = load_external(env)
    if workflow is not None:
        return workflow
    resolution = str(payload.get("resolution") or "360p").lower()
    if payload.get("width") or payload.get("height"):
        width = max(32, int(payload.get("width") or 768))
        height = max(32, int(payload.get("height") or 768))
    elif resolution in {"1080p", "1080"}:
        width, height = 1920, 1088
    elif resolution in {"720p", "720", "768p", "768"}:
        # H3's 768P workflow uses the model's native 1344x768 canvas.
        width, height = 1344, 768
    else:
        width, height = 768, 448
    aspect = str(payload.get("aspect") or "")
    if ":" in aspect:
        ratio_w, ratio_h = (float(x) for x in aspect.split(":", 1))
        if ratio_w > 0 and ratio_h > 0:
            if ratio_w >= ratio_h:
                height = max(32, int(round(width * ratio_h / ratio_w / 32) * 32))
            else:
                height = width
                width = max(32, int(round(height * ratio_w / ratio_h / 32) * 32))
    length = max(5, int(payload.get("frames") or int(payload.get("duration") or 5) * 24))
    prompt = str(payload.get("prompt") or "")
    video_model = str(payload.get("model") or "")
    if video_model not in {"minimax_h3_fl2va_pruned_int8_convrot.safetensors", "minimax_h3_ref2va_pruned_int8_convrot.safetensors"}:
        video_model = "minimax_h3_ref2va_pruned_int8_convrot.safetensors" if kind == "r2v" else "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
    graph = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": video_model, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
        "5": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"clip": ["2", 0], "vae": ["3", 0], "audio_vae": ["4", 0], "prompt": prompt, "width": width, "height": height, "length": length, "ref_image_size": "match"}},
        "6": {"class_type": "RandomNoise", "inputs": {"noise_seed": int(payload.get("seed") or 0)}},
        "7": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["1", 0], "shift_video": 12.0, "shift_audio": 3.0}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "9": {"class_type": "BasicScheduler", "inputs": {"model": ["7", 0], "scheduler": "simple", "steps": 4, "denoise": 1.0}},
        "10": {"class_type": "BasicGuider", "inputs": {"model": ["7", 0], "conditioning": ["5", 0]}},
        "11": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["6", 0], "guider": ["10", 0], "sampler": ["8", 0], "sigmas": ["9", 0], "latent_image": ["5", 1]}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["11", 0], "vae": ["4", 0]}},
        "14": {"class_type": "CreateVideo", "inputs": {"images": ["12", 0], "fps": 24.0, "audio": ["13", 0]}},
        "15": {"class_type": "SaveVideo", "inputs": {"video": ["14", 0], "filename_prefix": "douyin_creator/h3", "format": "auto", "codec": "auto"}},
    }
    if kind == "i2v":
        graph["16"] = {"class_type": "LoadImage", "inputs": {"image": "reference.png"}}
        graph["5"]["inputs"]["ref_images"] = {"ref_image_1": ["16", 0]}
    elif kind == "r2v":
        graph["16"] = {"class_type": "LoadVideo", "inputs": {"file": "reference.mp4"}}
        graph["17"] = {"class_type": "GetVideoComponents", "inputs": {"video": ["16", 0]}}
        graph["5"]["inputs"]["ref_videos"] = {"ref_video_1": ["17", 0]}
        graph["5"]["inputs"]["ref_video_audios"] = {"ref_video_audio_1": ["17", 1]}
    return graph


def bind_media(workflow: dict, image: str | None = None, video: str | None = None) -> dict:
    """Bind uploaded media to conventional LoadImage/LoadVideo API nodes."""
    import copy
    graph = copy.deepcopy(workflow)
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if node.get("class_type") == "LoadImage" and image:
            inputs["image"] = image
        if node.get("class_type") == "LoadVideo" and video:
            inputs["file"] = video
    return graph
