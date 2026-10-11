"""API-format ComfyUI workflows for the generation tab.

Image generation supports the installed Flux and Qwen Image checkpoints. Video generation is routed
to the matching user workflow template through the same API boundary; the
template can be supplied via COMFYUI_*_WORKFLOW environment variables.
"""
from __future__ import annotations

import json
import os
import copy
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


def load_full_h3_template(kind: str, payload: dict) -> dict | None:
    """Load an API-format H3 graph exported by ComfyUI and bind its inputs."""
    resolution = str(payload.get("resolution") or "360p").lower()
    length = max(5, int(payload.get("frames") or int(float(payload.get("duration") or 5) * 24)))
    length += (5 - length % 17) % 17
    if resolution in {"720p", "720", "768p", "768"} and length > 124:
        raise ValueError("当前本地 H3 在 12GB 显存下，720p 最多支持 5 秒（124 帧）；请降低清晰度或时长")
    if resolution in {"1080p", "1080"} and length > 73:
        raise ValueError("当前本地 H3 在 12GB 显存下，1080p 最多支持 3 秒（73 帧）；请降低清晰度或时长")
    template_kind = "r2v" if kind == "reference_pack_i2v" else kind
    env_name = {"t2v": "COMFYUI_T2V_API_WORKFLOW", "i2v": "COMFYUI_I2V_API_WORKFLOW", "r2v": "COMFYUI_R2V_API_WORKFLOW"}.get(template_kind)
    configured = os.getenv(env_name) if env_name else None
    default = Path(__file__).resolve().parents[1] / "workflows" / "h3_t2v_api.json" if template_kind in {"t2v", "i2v"} else Path(os.getenv("COMFYUI_WORKFLOW_DIR", r"C:\workspace\ComfyUI\user\default\workflows")) / "video_minimax_h3_r2v.json"
    path = Path(configured) if configured else default
    if not path or not path.is_file():
        return None
    source = json.loads(path.read_text(encoding="utf-8"))
    graph = canvas_to_api(source) if "nodes" in source else source.get("prompt", source)
    graph = copy.deepcopy(graph)
    aspect_names = {"1:1": "1:1 (Square)", "2:3": "2:3 (Portrait Photo)", "3:2": "3:2 (Photo)", "3:4": "3:4 (Portrait Standard)", "4:3": "4:3 (Standard)", "9:16": "9:16 (Portrait Widescreen)", "16:9": "16:9 (Widescreen)", "21:9": "21:9 (Ultrawide)"}
    resolution = str(payload.get("resolution") or "360p").lower()
    megapixels = {"360p": 0.2, "360": 0.2, "720p": 1.0, "720": 1.0, "768p": 1.0, "768": 1.0, "1080p": 2.0, "1080": 2.0}.get(resolution, 0.2)
    duration = max(0.1, float(payload.get("duration") or 5))
    seed = int(payload.get("seed") or 0)
    requested_steps = max(4, min(40, int(payload.get("steps") or 20)))
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        class_type, inputs = node.get("class_type"), node.setdefault("inputs", {})
        if class_type in {"MiniMaxH3ImageToVideo", "MiniMaxH3ReferenceToVideo"}:
            inputs["prompt"] = str(payload.get("prompt") or "")
        elif class_type == "ResolutionSelector":
            inputs["aspect_ratio"] = aspect_names.get(str(payload.get("aspect") or "16:9"), "16:9 (Widescreen)")
            inputs["megapixels"] = megapixels
            inputs["multiple"] = 32
        elif class_type == "PrimitiveFloat":
            inputs["value"] = duration
        elif class_type == "PrimitiveStringMultiline":
            inputs["value"] = str(payload.get("prompt") or "")
        elif class_type == "RandomNoise":
            inputs["noise_seed"] = seed
        elif class_type == "PrimitiveBoolean":
            inputs["value"] = requested_steps <= 8
        elif class_type == "PrimitiveInt" and inputs.get("value") in {4, 20}:
            inputs["value"] = min(requested_steps, 8) if inputs.get("value") == 4 else requested_steps
        elif class_type == "SaveVideo":
            inputs["filename_prefix"] = "douyin_creator/h3"
    if kind == "reference_pack_i2v":
        old_image_nodes={str(node_id) for node_id,node in graph.items() if isinstance(node,dict) and node.get("class_type")=="LoadImage"}
        for node_id in old_image_nodes: graph.pop(node_id,None)
        reference_count=max(1,min(9,int(payload.get("reference_count") or 1)));references={}
        for index in range(reference_count):
            node_id=f"multi_ref_{index+1}";graph[node_id]={"class_type":"LoadImage","inputs":{"image":"reference.png" if index==0 else f"reference_{index+1}.png"}}
            references[f"ref_image_{index+1}"]=[node_id,0]
        for node in graph.values():
            if not isinstance(node,dict) or node.get("class_type")!="MiniMaxH3ReferenceToVideo": continue
            inputs=node.setdefault("inputs",{})
            for key in list(inputs):
                if key.startswith("ref_image") or key.startswith("ref_video"): inputs.pop(key,None)
            inputs["ref_images"]=references;inputs["ref_image_size"]="match"
            break
    if kind == "i2v":
        graph["16"] = {"class_type": "LoadImage", "inputs": {"image": "reference.png"}}
        for node in graph.values():
            if isinstance(node, dict) and node.get("class_type") == "MiniMaxH3ImageToVideo":
                node.setdefault("inputs", {})["first_frame"] = ["16", 0]
                break
    return graph


def canvas_to_api(workflow: dict) -> dict:
    """Flatten a ComfyUI canvas workflow into the graph accepted by /prompt."""
    links = {}
    for item in workflow.get("links", []):
        if isinstance(item, dict) and item.get("id") is not None:
            links[str(item["id"])] = item
        elif isinstance(item, list) and len(item) >= 5:
            # ComfyUI canvas exports links as [link_id, origin_id, origin_slot, target_id, target_slot, type].
            links[str(item[0])] = {"origin_id": item[1], "origin_slot": item[2], "target_id": item[3], "target_slot": item[4]}
    result = {}
    for node in workflow.get("nodes", []):
        if not isinstance(node, dict) or node.get("type") in {"MarkdownNote", "Reroute"} or str(node.get("id", "")).startswith("-"):
            continue
        node_id = str(node.get("id"))
        named = node.get("widgets_values_named") or {}
        values = iter(node.get("widgets_values") or [])
        inputs = {}
        for entry in node.get("inputs", []):
            name = entry.get("name")
            if not name:
                continue
            link_id = entry.get("link")
            if link_id is not None and str(link_id) in links:
                link = links[str(link_id)]
                inputs[name] = [str(link.get("origin_id")), link.get("origin_slot", 0)]
                continue
            widget = entry.get("widget") or {}
            widget_name = widget.get("name") if isinstance(widget, dict) else None
            if widget_name in named:
                inputs[name] = named[widget_name]
            elif name in named:
                inputs[name] = named[name]
            elif widget_name or entry.get("type") in {"COMBO", "STRING", "FLOAT", "INT", "BOOLEAN"}:
                try:
                    inputs[name] = next(values)
                except StopIteration:
                    pass
        result[node_id] = {"class_type": node.get("type"), "inputs": inputs}
    return result


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


def qwen_image(prompt: str, width: int, height: int, count: int, seed: int, lora: str | None = None, lora_strength: float = 1.0, reference: str | None = None, reference_type: str = "identity") -> dict:
    """Build the native Qwen-Image text-to-image graph."""
    graph = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_fp8_e4m3fn.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": ""}},
        "6": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": count}},
        "7": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.1}},
        "8": {"class_type": "KSampler", "inputs": {"model": ["7", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0], "seed": seed, "steps": 8 if lora else 20, "cfg": 4.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"filename_prefix": "douyin_creator/qwen_image", "images": ["9", 0]}},
    }
    if lora:
        graph["11"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": lora, "strength_model": float(lora_strength)}}
        graph["7"]["inputs"]["model"] = ["11", 0]
    if reference:
        graph["12"] = {"class_type": "LoadImage", "inputs": {"image": reference}}
        graph["13"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["12", 0], "vae": ["3", 0]}}
        graph["8"]["inputs"]["latent_image"] = ["13", 0]
        graph["8"]["inputs"]["denoise"] = {"identity": 0.55, "style": 0.72, "composition": 0.65, "pose": 0.62}.get(reference_type, 0.55)
    return graph


def video_workflow(kind: str, payload: dict) -> dict:
    full_template = load_full_h3_template(kind, payload)
    if full_template is not None:
        return full_template
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
            # Preserve the selected resolution's pixel area while changing
            # aspect ratio. The previous 1:1 branch kept 1344 as both sides.
            area = width * height
            width = max(32, int(round((area * ratio_w / ratio_h) ** 0.5 / 32) * 32))
            height = max(32, int(round((area * ratio_h / ratio_w) ** 0.5 / 32) * 32))
    length = max(5, int(payload.get("frames") or int(payload.get("duration") or 5) * 24))
    # H3 is trained on the 17n+5 frame grid; direct ComfyUI workflows snap
    # user durations to that grid instead of sending duration * 24 directly.
    length += (5 - length % 17) % 17
    if resolution in {"720p", "720", "768p", "768"} and length > 124:
        raise ValueError("当前本地 H3 在 12GB 显存下，720p 最多支持 5 秒（124 帧）；请降低清晰度或时长")
    if resolution in {"1080p", "1080"} and length > 73:
        raise ValueError("当前本地 H3 在 12GB 显存下，1080p 最多支持 3 秒（73 帧）；请降低清晰度或时长")
    prompt = str(payload.get("prompt") or "")
    video_model = str(payload.get("model") or "")
    if video_model not in {"minimax_h3_fl2va_pruned_int8_convrot.safetensors", "minimax_h3_ref2va_pruned_int8_convrot.safetensors"}:
        video_model = "minimax_h3_ref2va_pruned_int8_convrot.safetensors" if kind in {"i2v", "r2v", "reference_pack_i2v"} else "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
    elif kind in {"i2v", "r2v", "reference_pack_i2v"}:
        # Reference conditioning requires the ref2va checkpoint even if the UI retained fl2va.
        video_model = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
    graph = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": video_model, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
        "5": {"class_type": "MiniMaxH3ReferenceToVideo" if kind in {"r2v", "reference_pack_i2v"} else "MiniMaxH3ImageToVideo", "inputs": {"clip": ["2", 0], "vae": ["3", 0], "prompt": prompt, "width": width, "height": height, "length": length}},
        "6": {"class_type": "RandomNoise", "inputs": {"noise_seed": int(payload.get("seed") or 0)}},
        "7": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["1", 0], "shift_video": 12.0, "shift_audio": 3.0}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "9": {"class_type": "BasicScheduler", "inputs": {"model": ["7", 0], "scheduler": "simple", "steps": max(4, min(40, int(payload.get("steps") or 20))), "denoise": 1.0}},
        "10": {"class_type": "BasicGuider", "inputs": {"model": ["7", 0], "conditioning": ["5", 0]}},
        "11": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["6", 0], "guider": ["10", 0], "sampler": ["8", 0], "sigmas": ["9", 0], "latent_image": ["5", 1]}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["11", 0], "vae": ["4", 0]}},
        "14": {"class_type": "CreateVideo", "inputs": {"images": ["12", 0], "fps": 24.0, "audio": ["13", 0]}},
        "15": {"class_type": "SaveVideo", "inputs": {"video": ["14", 0], "filename_prefix": "douyin_creator/h3", "format": "auto", "codec": "auto"}},
    }
    aspect_names = {"1:1": "1:1 (Square)", "2:3": "2:3 (Portrait Photo)", "3:2": "3:2 (Photo)", "3:4": "3:4 (Portrait Standard)", "4:3": "4:3 (Standard)", "9:16": "9:16 (Portrait Widescreen)", "16:9": "16:9 (Widescreen)", "21:9": "21:9 (Ultrawide)"}
    megapixels = {"360p": 0.2, "360": 0.2, "720p": 1.0, "720": 1.0, "768p": 1.0, "768": 1.0, "1080p": 2.0, "1080": 2.0}.get(resolution, 0.2)
    graph[15] = {"class_type": "ResolutionSelector", "inputs": {"aspect_ratio": aspect_names.get(aspect, "16:9 (Widescreen)"), "megapixels": megapixels, "multiple": 32}}
    graph["5"]["inputs"]["width"] = ["15", 0]
    graph["5"]["inputs"]["height"] = ["15", 1]
    if kind in {"r2v", "reference_pack_i2v"}:
        graph["5"]["inputs"].update({"audio_vae": ["4", 0], "ref_image_size": "match"})
    if kind == "i2v":
        graph["16"] = {"class_type": "LoadImage", "inputs": {"image": "reference.png"}}
        graph["5"]["inputs"]["first_frame"] = ["16", 0]
    elif kind == "r2v":
        graph["16"] = {"class_type": "LoadVideo", "inputs": {"file": "reference.mp4"}}
        graph["17"] = {"class_type": "GetVideoComponents", "inputs": {"video": ["16", 0]}}
        graph["5"]["inputs"]["ref_videos"] = {"ref_video_1": ["17", 0]}
        graph["5"]["inputs"]["ref_video_audios"] = {"ref_video_audio_1": ["17", 1]}
    elif kind == "reference_pack_i2v":
        reference_count=max(1,min(9,int(payload.get("reference_count") or 1)))
        references={}
        for index in range(reference_count):
            node_id=str(16+index);graph[node_id]={"class_type":"LoadImage","inputs":{"image":"reference.png" if index==0 else f"reference_{index+1}.png"}}
            references[f"ref_image_{index+1}"]=[node_id,0]
        graph["5"]["inputs"]["ref_images"]=references
    return graph


def bind_media(workflow: dict, image: str | None = None, video: str | None = None, image2: str | None = None, images: list[str] | None = None) -> dict:
    """Bind uploaded media to conventional LoadImage/LoadVideo API nodes."""
    import copy
    graph = copy.deepcopy(workflow);images=list(images or [item for item in (image,image2) if item])[:9]
    remove_ids = set()
    image_node_ids = []
    image_index = 0
    for node_id, node in list(graph.items()):
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if node.get("class_type") == "LoadImage":
            image_node_ids.append(str(node_id))
            selected = images[image_index] if image_index < len(images) else None
            if selected:
                inputs["image"] = selected
            elif image_index > 0:
                remove_ids.add(str(node_id))
            image_index += 1
        if node.get("class_type") == "LoadVideo" and video:
            inputs["file"] = video
    if remove_ids:
        for node_id in remove_ids:
            graph.pop(node_id, None)
        for node in graph.values():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            for name, value in list(inputs.items()):
                if isinstance(value, list) and value and str(value[0]) in remove_ids:
                    inputs.pop(name, None)
                elif isinstance(value, dict):
                    inputs[name] = {key: link for key, link in value.items() if not (isinstance(link, list) and link and str(link[0]) in remove_ids)}
    image_node_ids = [node_id for node_id in image_node_ids if node_id not in remove_ids]
    if image_node_ids:
        for node in graph.values():
            if not isinstance(node, dict) or node.get("class_type") != "MiniMaxH3ReferenceToVideo":
                continue
            inputs = node.setdefault("inputs", {})
            for key in list(inputs):
                if key.startswith("ref_images"):
                    inputs.pop(key, None)
            for index, node_id in enumerate(image_node_ids):
                inputs[f"ref_images.ref_image_{index}"] = [node_id, 0]
    return graph
