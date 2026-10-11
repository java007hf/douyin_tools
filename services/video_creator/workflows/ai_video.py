"""Fixed AI-video workflow; LLM reasoning is isolated to selected nodes."""
from __future__ import annotations
import json
from collections.abc import Callable
from pathlib import Path
from urllib import request
from services.video_creator.tools.video.merge import merge_videos
from services.video_creator.workflow.context import WorkflowContext
from services.video_creator.workflow.engine import WorkflowEngine
from services.video_creator.workflow.models import WorkflowNode
from services.video_creator.workflow.prompts import DEFAULT_REVIEW_PROMPT, DEFAULT_STORYBOARD_PROMPT, LEARNED_PRODUCTION_RULES
from services.video_creator.workflow.plot_library import retrieve_plot_references


class AIVideoWorkflow:
    def __init__(self, llm, generate_shot: Callable[[dict, WorkflowContext], Path], on_change, prompts: dict | None = None, generate_image: Callable[[dict, WorkflowContext], Path] | None = None, extract_keyframes: Callable[[Path, dict, WorkflowContext], dict[str, Path]] | None = None, on_assets_prepared: Callable[[dict[str, Path], dict, WorkflowContext], None] | None = None, resolve_library_asset: Callable[[str], Path | None] | None = None, confirm_assets: Callable[[dict, WorkflowContext], dict] | None = None):
        self.llm, self.generate_shot, self.on_change = llm, generate_shot, on_change
        self.prompts = prompts or {}
        self.generate_image, self.extract_keyframes = generate_image, extract_keyframes
        self.on_assets_prepared = on_assets_prepared
        self.resolve_library_asset = resolve_library_asset
        self.confirm_assets = confirm_assets

    def run(self, context: WorkflowContext) -> dict:
        nodes = [
            (WorkflowNode("plan_storyboard", "理解诉求并生成故事板"), self._storyboard),
            (WorkflowNode("prepare_assets", "准备连续性资产"), self._prepare_assets),
            (WorkflowNode("generate", "生成镜头素材"), self._generate),
            (WorkflowNode("review", "AI 审片"), self._review),
            (WorkflowNode("compose", "合成短视频"), self._compose),
        ]
        WorkflowEngine(nodes, self.on_change).run(context)
        return {"creative_intent":context.artifacts["creative_intent"],"continuity_bible":context.artifacts["continuity_bible"],"storyboard": context.artifacts["storyboard"], "review": context.artifacts["review"], "output": context.artifacts["output"]}

    def _storyboard(self, context):
        prompt = json.dumps({
            "brief": context.brief,
            "has_reference_image": bool(context.reference_image),
            "has_reference_video": bool(context.reference_video),
            "total_duration_seconds": context.params["total_duration"],
            "plot_references": retrieve_plot_references(context.brief),
            "available_library_assets": context.params.get("_available_library_assets",[]),
            "execution_requirements": [
                "先梳理并固定角色、场景、道具和视觉风格资产，再设计镜头；每个 shot 必须明确 asset_bindings。",
                "执行先建资产再拍镜头：主要/重复角色、固定地点和关键道具必须解析到现有资产或 source=generate_image 的独立资产，禁止只写描述后直接生成视频。",
                "角色/地点/道具实体的 reference_asset_id、shot.asset_bindings 和 generation_plan.reference_asset_ids 必须引用 continuity_bible.assets 中存在的 ID；镜头首尾帧不是资产。",
                "每个有对白的 shot 必须填写 speaker、逐字 dialogue、voice 和 speech_timing，不能只写嘴部同步。",
                "每个 shot 的 audio.mode 必须是 dialogue 或 no_dialogue；dialogue 必须指定 zh-CN 标准普通话并禁止改词或添加人声，no_dialogue 必须禁止拟语音、耳语、哼唱和嘴部说话动作。",
                "对白只通过音频表达，默认不要生成字幕；禁止在画面中安排台词文字、招牌文字、Logo、水印或任何可读文字。",
                "采用现代电影短视频风格：干净高质量数字摄影、自然肤色、清晰细节、现代灯光和精确构图，避免老旧插画、复古滤镜、泛黄、低清晰度和过度柔焦。",
                "优先参考剧情库的节拍，但不得照抄示例；让观众仅通过画面和对白就能理解因果与反转。",
                "重要参考角色需要辨认身份、表情或说话时必须使用中近景或近景，脸部高度至少占画面高度约 12%；远景只承担身体动作和空间交代。不要在同一镜头中同时安排复杂全景动作、远景人脸表演和转近景，必要时拆成动作全景与人物反应近景两个镜头。",
                "角色切换必须使用反打镜头：有对白的镜头只让说话角色成为清晰主体，另一角色最多作为不露脸的虚化肩部；不得在同一镜头同时安排一个角色变形和另一个角色的反应，必须拆成两个镜头。",
                "每个镜头只绑定实际出镜角色与实际使用道具。空的 characters/props 表示本镜头明确不使用，禁止从全局连续性设定回填全部角色或全部道具。",
            ],
            "output_limits": {
                "prefer_compact_json": True,
                "recommended_shot_count": 4,
                "max_timeline_events_per_shot": 3,
                "keep_each_field_concise": True,
                "do_not_repeat_the_continuity_bible_verbatim_in_every_field": True
            }
        }, ensure_ascii=False)
        system_prompt=self.prompts.get("storyboard") or DEFAULT_STORYBOARD_PROMPT
        system_prompt += "\n\n" + LEARNED_PRODUCTION_RULES
        system_prompt += "\n\n强制资产规则：必须先建资产再拍镜头。每个主要或跨镜头角色、固定地点和关键道具都要解析到 continuity_bible.assets 中的现有资产，或新增 source=generate_image 的独立资产规格；characters、locations、props 的 reference_asset_id 以及每个镜头的 asset_bindings/reference_asset_ids 必须引用这些真实资产 ID。猪八戒、九齿钉耙等不得只保留文字描述。镜头首尾帧仅用于运行时衔接，绝不是长期资产。"
        result = self.llm.complete_json(system_prompt, prompt)
        if context.params.get("_enforce_story_arc"):
            issues=self._storyboard_contract_issues(result,float(context.params["total_duration"]))
            if issues:
                repair_prompt=prompt+"\n\n上一次故事板未通过制作前校验："+"；".join(issues)+"。请保留用户要求与资产 ID，重写完整 JSON 故事板。最后一镜头必须完成主角回应、结果或喜剧回扣；不要只让对手离场。"
                result=self.llm.complete_json(system_prompt,repair_prompt)
                issues=self._storyboard_contract_issues(result,float(context.params["total_duration"]))
                if issues:
                    raise ValueError("故事板制作前校验失败："+"；".join(issues))
        shots = result.get("shots")
        if not isinstance(shots, list) or not shots:
            raise ValueError("故事板没有生成有效镜头")
        total=float(context.params["total_duration"])
        for index, shot in enumerate(shots):
            plan_prompt = shot.get("generation_plan", {}).get("video_prompt") if isinstance(shot, dict) and isinstance(shot.get("generation_plan"), dict) else ""
            if isinstance(shot, dict) and not (shot.get("prompt") or shot.get("description") or plan_prompt):
                compact_fields = {key: shot.get(key) for key in ("characters", "scene", "action", "camera", "timeline", "audio") if shot.get(key)}
                plan_prompt = json.dumps(compact_fields, ensure_ascii=False, separators=(",", ":")) if compact_fields else ""
            shot_prompt = str(shot.get("prompt") or shot.get("description") or plan_prompt or "").strip() if isinstance(shot, dict) else ""
            if not shot_prompt:
                raise ValueError(f"故事板第 {index + 1} 个镜头缺少 prompt 或 description")
            shot.setdefault("prompt", shot_prompt)
            shot["sequence"]=index+1
            shot.setdefault("id", f"shot-{index + 1}")
            shot["duration_seconds"]=max(.1,float(shot.get("duration_seconds") or total/len(shots)))
            shot.setdefault("shot_and_transition", {"shot_size":"","camera_angle":"","camera_movement":"","transition_in":""})
            shot.setdefault("aesthetics", {"lighting":"","color_texture":""})
            shot.setdefault("visual_and_action", {"plot":str(shot.get("description") or ""),"body_language":""})
            shot.setdefault("audio_and_dialogue", {"sound_effect":"","music":"","dialogue":""})
            strategy=str(shot.get("reference_strategy") or "t2v").lower()
            if strategy=="i2v" and not context.reference_image or strategy=="r2v" and not context.reference_video:
                strategy="t2v"
            shot["reference_strategy"]=strategy if strategy in {"t2v","i2v","r2v"} else "t2v"
        current=sum(float(shot["duration_seconds"]) for shot in shots)
        if current<=0: raise ValueError("故事板总时长无效")
        scale=total/current
        for shot in shots: shot["duration_seconds"]=round(float(shot["duration_seconds"])*scale,2)
        shots[-1]["duration_seconds"]=round(float(shots[-1]["duration_seconds"])+(total-sum(float(shot["duration_seconds"]) for shot in shots)),2)
        cursor=0.0
        for shot in shots:
            shot["start_time_seconds"]=round(cursor,2)
            cursor+=float(shot["duration_seconds"])
            shot["end_time_seconds"]=round(cursor,2)
        result["creative_intent"]=result.get("creative_intent") or {"goal":context.brief,"audience":"","style":"","constraints":[]}
        result["continuity_bible"]=result.get("continuity_bible") if isinstance(result.get("continuity_bible"),dict) else {}
        result["continuity_bible"].setdefault("characters",[]);result["continuity_bible"].setdefault("locations",[]);result["continuity_bible"].setdefault("props",[]);result["continuity_bible"].setdefault("visual_style",{});result["continuity_bible"].setdefault("assets",[])
        bible=result["continuity_bible"]
        bible["characters"]=self._normalize_entities(bible["characters"],"character")
        bible["locations"]=self._normalize_entities(bible["locations"],"location")
        bible["props"]=self._normalize_entities(bible["props"],"prop")
        if context.reference_image and not any(isinstance(item,dict) and item.get("id") == "input_image" for item in bible["assets"]):
            bible["assets"].append({"id":"input_image","kind":"character_reference","source":"input_image","prompt":"用户提供的蜘蛛精人物参考图"})
        self._materialize_asset_specs(bible,context)
        character_ids=[str(item.get("reference_asset_id")) for item in bible["characters"] if isinstance(item,dict) and item.get("reference_asset_id")]
        location_ids=[str(item.get("reference_asset_id")) for item in bible["locations"] if isinstance(item,dict) and item.get("reference_asset_id")]
        prop_ids=[str(item.get("reference_asset_id")) for item in bible["props"] if isinstance(item,dict) and item.get("reference_asset_id")]
        entity_assets={}
        for field in ("characters","locations","props"):
            for item in bible[field]:
                if not isinstance(item,dict) or not item.get("id") or not item.get("reference_asset_id"): continue
                reference_id=str(item["reference_asset_id"])
                entity_assets[str(item["id"])]=reference_id
                if item.get("name"): entity_assets[str(item["name"])]=reference_id
                if item.get("identity"): entity_assets[str(item["identity"])]=reference_id
        id_map={str(shot["id"]):f"shot-{index+1}" for index,shot in enumerate(shots)}
        for index,shot in enumerate(shots): shot["id"]=f"shot-{index+1}"
        known_ids={str(shot["id"]) for shot in shots}
        for index,shot in enumerate(shots):
            dependencies=shot.get("depends_on") if isinstance(shot.get("depends_on"),list) else []
            if not dependencies and isinstance(shot.get("continuity"),dict) and isinstance(shot["continuity"].get("depends_on"),str):
                dependencies=[shot["continuity"]["depends_on"]]
            shot["depends_on"]=[id_map.get(str(item),str(item)) for item in dependencies if id_map.get(str(item),str(item)) in known_ids and id_map.get(str(item),str(item))!=shot["id"]]
            shot["continuity"]=shot.get("continuity") if isinstance(shot.get("continuity"),dict) else {}
            plan=shot.get("generation_plan") if isinstance(shot.get("generation_plan"),dict) else {}
            legacy=str(shot.get("reference_strategy") or "t2v").lower()
            plan.setdefault("mode",legacy if legacy in {"t2v","i2v","r2v"} else "t2v")
            plan.setdefault("image_prompt","");plan.setdefault("video_prompt",str(shot.get("prompt") or ""));plan.setdefault("reference_asset_ids",[])
            normalized_refs=[]
            known_asset_ids={str(item.get("id")) for item in bible["assets"] if isinstance(item,dict) and item.get("id")}
            for asset_id in plan.get("reference_asset_ids") if isinstance(plan.get("reference_asset_ids"),list) else []:
                value=str(asset_id)
                if value in known_asset_ids:
                    normalized_refs.append(value)
                elif context.reference_image and any(token in value.lower() for token in ("spider", "character", "face", "ref")):
                    normalized_refs.append("input_image")
            plan["reference_asset_ids"]=list(dict.fromkeys(normalized_refs))
            if plan["mode"] not in {"t2v","i2v","r2v","image_then_i2v","previous_frame_i2v","reference_pack_i2v"}: plan["mode"]="t2v"
            if len(shots) > 1 and (context.reference_image or not context.reference_video):
                if index == 0:
                    plan["mode"]="reference_pack_i2v" if context.reference_image else "image_then_i2v"
                else:
                    plan["mode"]="reference_pack_i2v" if context.reference_image else "previous_frame_i2v"
                    if f"shot-{index}" not in shot["depends_on"]:
                        shot["depends_on"].append(f"shot-{index}")
            continuity=shot["continuity"]
            def declared_ids(value):
                if not isinstance(value,list): return []
                return [str(item.get("character_id") or item.get("prop_id") or item.get("location_id") or item.get("reference_asset_id") or item.get("id") or item.get("asset_id") or item.get("name")) if isinstance(item,dict) else str(item) for item in value if item]
            declared_characters=declared_ids(shot.get("characters"))
            declared_props=declared_ids(shot.get("props"))
            scene=shot.get("scene")
            scene_props=declared_ids(scene.get("props")) if isinstance(scene,dict) and isinstance(scene.get("props"),list) else None
            declared_location=(str(scene.get("location_id") or scene.get("reference_asset_id") or scene.get("id") or scene.get("asset_id") or scene.get("name") or "") if isinstance(scene,dict) else str(scene or ""))
            raw_character_ids=declared_characters if isinstance(shot.get("characters"),list) else continuity.get("character_ids") or continuity.get("character_asset_ids") or character_ids
            raw_prop_ids=(declared_props if isinstance(shot.get("props"),list) else scene_props if scene_props is not None else continuity.get("prop_ids") or continuity.get("prop_asset_ids") or prop_ids)
            raw_location_id=continuity.get("location_id") or declared_location or (location_ids[0] if location_ids else "")
            shot["asset_bindings"]={
                "character_ids":list(dict.fromkeys(entity_assets.get(str(item),str(item)) for item in raw_character_ids if item)),
                "location_id":entity_assets.get(str(raw_location_id),str(raw_location_id)) if raw_location_id else "",
                "prop_ids":list(dict.fromkeys(entity_assets.get(str(item),str(item)) for item in raw_prop_ids if item)),
                "must_preserve": continuity.get("must_preserve") or ["人物身份", "发型", "服装", "场景布局"],
            }
            # Preserve stable asset IDs here. The Provider adapter assigns
            # temporary <Picture N> slots only when it builds each request.
            bound_asset_ids=(list(shot["asset_bindings"].get("character_ids",[]))
                + list(shot["asset_bindings"].get("prop_ids",[]))
                + ([shot["asset_bindings"].get("location_id")] if shot["asset_bindings"].get("location_id") else []))
            # The shot declaration is authoritative. Do not retain global or
            # planner-added references for characters/props absent from this shot.
            plan["reference_asset_ids"]=list(dict.fromkeys(
                asset_id for asset_id in bound_asset_ids if asset_id in known_asset_ids
            ))
            if plan["reference_asset_ids"] and plan["mode"]=="t2v": plan["mode"]="reference_pack_i2v"
            shot["asset_dependencies"]=list(dict.fromkeys(
                [str(item) for item in shot["asset_bindings"].get("character_ids",[]) if item]
                + [str(item) for item in shot["asset_bindings"].get("prop_ids",[]) if item]
                + [str(item) for item in plan["reference_asset_ids"] if item]
            ))
            shot["continuity"]["asset_dependencies"]=shot["asset_dependencies"]
            shot["generation_plan"]=plan
            shot["reference_strategy"]="r2v" if plan["mode"]=="r2v" else "reference_pack_i2v" if plan["mode"]=="reference_pack_i2v" else "i2v" if plan["mode"] in {"i2v","image_then_i2v","previous_frame_i2v"} else "t2v"
            shot["generation_plan"]["video_prompt"] = self._compile_video_prompt(shot, bible)
        context.artifacts["storyboard"] = shots
        context.artifacts["creative_intent"] = result["creative_intent"]
        context.artifacts["continuity_bible"] = result["continuity_bible"]
        (context.task_dir / "storyboard.json").write_text(json.dumps({"creative_intent":result["creative_intent"],"continuity_bible":result["continuity_bible"],"shots":shots}, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"message": f"已规划 {len(context.artifacts['storyboard'])} 个镜头", "creative_intent":result["creative_intent"],"continuity_bible":result["continuity_bible"],"shots": context.artifacts["storyboard"]}

    @staticmethod
    def _storyboard_contract_issues(result,total_duration):
        shots=result.get("shots") if isinstance(result,dict) else None
        if not isinstance(shots,list) or len(shots)<3: return ["至少需要三个镜头建立、推进并收束故事"]
        issues=[];intent=result.get("creative_intent") if isinstance(result.get("creative_intent"),dict) else {}
        if not str(intent.get("ending_payoff") or "").strip(): issues.append("creative_intent 缺少 ending_payoff")
        functions=[str(shot.get("story_function") or "").lower() for shot in shots if isinstance(shot,dict)]
        if len(functions)!=len(shots) or functions[0]!="setup": issues.append("第一镜头必须标记 story_function=setup")
        if not functions or functions[-1]!="resolution": issues.append("最后一镜头必须标记 story_function=resolution")
        if "turn" not in functions: issues.append("故事缺少 story_function=turn 的反转或识破镜头")
        for index,shot in enumerate(shots,1):
            if not isinstance(shot,dict): continue
            audio=shot.get("audio") if isinstance(shot.get("audio"),dict) else {}
            dialogue="".join(char for char in str(audio.get("dialogue") or "") if char not in "，。！？、；：,.!?;: ")
            duration=float(shot.get("duration_seconds") or total_duration/max(1,len(shots)))
            if dialogue and duration < len(dialogue)/5.5+0.4: issues.append(f"第 {index} 镜头对白过长，无法在时长内自然说完")
            if not dialogue and (not str(audio.get("sound_effects") or "").strip() or not str(audio.get("ambience") or "").strip()): issues.append(f"第 {index} 个无对白镜头缺少可执行的音效或环境声")
        return issues

    @staticmethod
    def _normalize_entities(value,kind):
        if isinstance(value,dict):
            items=[]
            for key,details in value.items():
                item=dict(details) if isinstance(details,dict) else {"description":str(details)}
                item.setdefault("id",str(key));items.append(item)
            return items
        if not isinstance(value,list): return []
        items=[]
        for index,details in enumerate(value,1):
            item=dict(details) if isinstance(details,dict) else {"description":str(details)}
            item.setdefault("id",f"{kind}_{index}");items.append(item)
        return items

    @staticmethod
    def _materialize_asset_specs(bible,context):
        assets=[dict(item) for item in bible.get("assets",[]) if isinstance(item,dict) and item.get("id")]
        by_id={str(item["id"]):item for item in assets}
        available={str(item.get("id")):item for item in context.params.get("_available_library_assets",[]) if isinstance(item,dict) and item.get("id")}
        # Some planners put well-formed independent entities only in `assets`
        # and leave characters/locations/props empty. Recover the canonical
        # entity lists deterministically instead of exposing an empty approval
        # gate that can never be submitted.
        field_kinds={"characters":{"character"},"locations":{"location"},"props":{"prop","vfx"}}
        for field,kinds in field_kinds.items():
            if bible.get(field): continue
            recovered=[]
            for spec in assets:
                if str(spec.get("kind") or spec.get("type") or "").lower() not in kinds: continue
                entity={"id":str(spec["id"]),"name":str(spec.get("name") or spec["id"]),"description":spec.get("description") or "","asset_id":str(spec["id"])}
                if spec.get("reference_asset_id"): entity["reference_asset_id"]=str(spec["reference_asset_id"])
                recovered.append(entity)
            bible[field]=recovered
        for spec in assets:
            source=str(spec.get("source") or "")
            asset_id=str(spec.get("id") or "")
            # A stable ID that already exists in the selected/available library
            # always wins over an LLM-proposed generate_image source. Otherwise
            # retries regenerate every known character and prop for hours.
            if asset_id in available and source not in {"input_image","input_video"}:
                spec["source"]="library_asset";spec["library_asset_id"]=asset_id
            if str(spec.get("kind") or "").lower()=="vfx": spec["kind"]="prop"
        for kind,field in (("character","characters"),("location","locations"),("prop","props")):
            for entity in bible.get(field,[]):
                entity_id=str(entity.get("id") or "").strip()
                if not entity_id: continue
                reference_id=str(entity.get("reference_asset_id") or "").strip()
                if reference_id not in by_id:
                    aliases=entity.get("reference_asset_ids") if isinstance(entity.get("reference_asset_ids"),list) else []
                    reference_id=next((str(item) for item in aliases if str(item) in by_id),"")
                linked_id=str(entity.get("asset_id") or "").strip()
                if not reference_id and linked_id in by_id:
                    reference_id=linked_id
                linked=by_id.get(str(entity.get("asset_id") or ""),{})
                description=" ".join(str(value or "") for value in (
                    entity.get("identity"),entity.get("appearance"),entity.get("wardrobe"),entity.get("voice"),entity.get("description"),
                    linked.get("description"),linked.get("prompt"),linked.get("usage"),linked.get("appearance"),linked.get("wardrobe"),entity.get("name")
                ))
                if not reference_id and context.reference_image and kind=="character" and any(token in description.lower() for token in ("参考图","上传","reference","锁定")):
                    reference_id="input_image"
                if not reference_id:
                    entity_name=str(entity.get("name") or entity.get("identity") or entity_id).strip().lower()
                    for candidate in context.params.get("_available_library_assets",[]):
                        if not isinstance(candidate,dict) or str(candidate.get("kind"))!=kind: continue
                        candidate_name=str(candidate.get("name") or "").strip().lower()
                        if candidate_name and (candidate_name in description.lower() or entity_name in candidate_name or candidate_name in entity_name):
                            reference_id=str(candidate.get("id"));spec={"id":reference_id,"name":candidate.get("name"),"kind":kind,"source":"library_asset","library_asset_id":reference_id,"entity_id":entity_id}
                            assets.append(spec);by_id[reference_id]=spec;break
                if not reference_id:
                    reference_id=entity_id
                    if reference_id not in by_id:
                        if kind=="character":
                            prompt=AIVideoWorkflow._independent_asset_prompt(kind,description or entity_id)
                        elif kind=="prop":
                            prompt=f"独立道具制作参考图，单一道具，无人物，无文字无水印。完整展示固定造型、材质、颜色、比例与关键结构，三分之四视角，简洁中性背景，高细节。道具设定：{description or entity_id}"
                        else:
                            prompt=f"独立场景制作参考图，无人物，无文字无水印。清晰展示固定空间布局、主要陈设、入口出口、光线、色彩与材质，高细节广角构图。场景设定：{description or entity_id}"
                        spec={"id":reference_id,"name":str(entity.get("name") or entity.get("identity") or entity_id),"kind":kind,"source":"generate_image","prompt":prompt,"entity_id":entity_id}
                        assets.append(spec);by_id[reference_id]=spec
                entity["reference_asset_id"]=reference_id
                if reference_id in by_id:
                    by_id[reference_id]["entity_id"]=entity_id
                    by_id[reference_id]["kind"]=kind
        bible["assets"]=assets

    @staticmethod
    def _compile_video_prompt(shot: dict, bible: dict) -> str:
        """Compile locked assets and exact dialogue into the model-facing prompt."""
        audio=shot.get("audio") if isinstance(shot.get("audio"),dict) else shot.get("audio_and_dialogue",{})
        dialogue=str(audio.get("dialogue") or "").strip() if isinstance(audio,dict) else ""
        segments=audio.get("dialogue_segments") if isinstance(audio,dict) else None
        has_dialogue=bool(dialogue or isinstance(segments,list) and any(str(item.get("dialogue") or "").strip() for item in segments if isinstance(item,dict)))
        if isinstance(audio,dict):
            audio=dict(audio);audio["mode"]="dialogue" if has_dialogue else "no_dialogue"
            if has_dialogue: audio["language"]="zh-CN（标准普通话）"
            else: audio.update({"speaker":"none","dialogue":"","language":"none","voice":"none","speech_timing":"none"})
        payload={
            "locked_assets": shot.get("asset_bindings",{}),
            "characters": shot.get("characters",[]),
            "scene": shot.get("scene",{}),
            "action": shot.get("action",{}),
            "camera": shot.get("camera",shot.get("shot_and_transition",{})),
            "timeline": shot.get("timeline",[]),
            "audio": audio,
            "visual_style": bible.get("visual_style",{}),
            "base_prompt": shot.get("generation_plan",{}).get("video_prompt") or shot.get("prompt",{}),
        }
        audio_rule=("音频模式为 dialogue：只允许指定说话者使用标准普通话逐字说出给定台词，不得改写、翻译、增加台词或产生其他人声；在指定时间窗内自然口型同步。" if has_dialogue else "音频模式为 no_dialogue：所有人物保持沉默且无说话口型；禁止生成任何人声、拟语音、耳语、哼唱或含混语言，只允许明确列出的环境声和音效。")
        return "MiniMax H3 executable shot plan: " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "。"+audio_rule+"保持锁定资产一致。画面中禁止字幕、台词文字、招牌文字、Logo、水印和任何可读文字，避免生成乱码；不要新增角色、服装或道具。"

    def _prepare_assets(self, context):
        if context.params.get("confirm_assets") and self.confirm_assets:
            decisions=self.confirm_assets(context.artifacts["continuity_bible"],context) or {}
            replacements=self._apply_asset_decisions(context.artifacts["continuity_bible"],decisions)
            for shot in context.artifacts.get("storyboard",[]):
                bindings=shot.get("asset_bindings",{});plan=shot.get("generation_plan",{})
                bindings["character_ids"]=[replacements.get(str(item),str(item)) for item in bindings.get("character_ids",[])]
                bindings["prop_ids"]=[replacements.get(str(item),str(item)) for item in bindings.get("prop_ids",[])]
                if bindings.get("location_id"): bindings["location_id"]=replacements.get(str(bindings["location_id"]),str(bindings["location_id"]))
                plan["reference_asset_ids"]=list(dict.fromkeys(replacements.get(str(item),str(item)) for item in plan.get("reference_asset_ids",[])))
                shot["asset_dependencies"]=list(dict.fromkeys(bindings.get("character_ids",[])+bindings.get("prop_ids",[])+([bindings.get("location_id")] if bindings.get("location_id") else [])))
        # Only entity-bound, independently reusable references belong in this
        # stage. LLM-declared helper rows without an owning entity often contain
        # the full story prompt and would produce mixed character/scene images.
        bible=context.artifacts["continuity_bible"]
        bible["assets"]=[spec for spec in bible.get("assets",[]) if isinstance(spec,dict) and (spec.get("entity_id") or spec.get("source") in {"input_image","input_video"})]
        assets={}
        if context.reference_image: assets["input_image"]=context.reference_image
        if context.reference_video: assets["input_video"]=context.reference_video
        for spec in context.artifacts["continuity_bible"].get("assets",[]):
            if not isinstance(spec,dict) or not spec.get("id"): continue
            source=str(spec.get("source") or "")
            if source=="input_image" and context.reference_image: assets[str(spec["id"])]=context.reference_image
            elif source=="input_video" and context.reference_video: assets[str(spec["id"])]=context.reference_video
            elif source=="generate_image":
                if not self.generate_image: raise RuntimeError("故事板需要生成连续性参考图，但 generate_image 工具不可用")
                assets[str(spec["id"])]=self.generate_image(spec,context)
            elif source=="library_asset":
                if not self.resolve_library_asset: raise RuntimeError("故事板引用了资产库，但资产解析工具不可用")
                path=self.resolve_library_asset(str(spec.get("library_asset_id") or spec["id"]))
                if not path: raise RuntimeError(f"资产库文件不存在：{spec.get('library_asset_id') or spec['id']}")
                assets[str(spec["id"])]=path
        context.artifacts["assets"]=assets
        if self.on_assets_prepared: self.on_assets_prepared(assets,context.artifacts["continuity_bible"],context)
        return {"message":f"已准备 {len(assets)} 个连续性资产","assets":{key:path.name for key,path in assets.items()}}

    @staticmethod
    def asset_requirements(bible,available_assets):
        asset_specs={str(item.get("id")):item for item in bible.get("assets",[]) if isinstance(item,dict) and item.get("id")}
        requirements=[]
        for kind,field in (("character","characters"),("location","locations"),("prop","props")):
            candidates=[{"id":item.get("id"),"name":item.get("name"),"kind":item.get("kind"),"href":item.get("href","")} for item in available_assets if isinstance(item,dict) and item.get("kind")==kind]
            for entity in bible.get(field,[]):
                if not isinstance(entity,dict) or not entity.get("id"): continue
                asset_id=str(entity.get("reference_asset_id") or "")
                spec=asset_specs.get(asset_id,{})
                current_action="reuse" if spec.get("source")=="library_asset" else "keep" if spec.get("source") in {"input_image","input_video"} else "regenerate"
                requirements.append({"entity_id":str(entity["id"]),"kind":kind,"name":str(entity.get("name") or entity.get("identity") or entity.get("description") or entity["id"]),"current_asset_id":asset_id,"current_action":current_action,"candidates":candidates})
        return requirements

    @staticmethod
    def _apply_asset_decisions(bible,decisions):
        assets=[dict(item) for item in bible.get("assets",[]) if isinstance(item,dict) and item.get("id")]
        asset_specs={str(item.get("id")):item for item in assets}
        entities={str(item.get("id")):item for field in ("characters","locations","props") for item in bible.get(field,[]) if isinstance(item,dict) and item.get("id")}
        kinds={str(item.get("id")):kind for kind,field in (("character","characters"),("location","locations"),("prop","props")) for item in bible.get(field,[]) if isinstance(item,dict) and item.get("id")}
        replacements={}
        for entity_id,choice in decisions.items():
            entity=entities.get(str(entity_id));choice=choice if isinstance(choice,dict) else {"action":str(choice)}
            if not entity: continue
            old_id=str(entity.get("reference_asset_id") or entity_id)
            action=str(choice.get("action") or "");selected=str(choice.get("asset_id") or "")
            if action=="reuse" and selected:
                assets=[item for item in assets if str(item.get("id"))!=old_id]
                if not any(str(item.get("id"))==selected for item in assets): assets.append({"id":selected,"name":choice.get("name") or selected,"kind":kinds[entity_id],"source":"library_asset","library_asset_id":selected,"entity_id":entity_id})
                entity["reference_asset_id"]=selected
                replacements[old_id]=selected;replacements[str(entity_id)]=selected
            elif action=="regenerate":
                assets=[item for item in assets if str(item.get("id"))!=old_id]
                generated_id=entity_id if not any(str(item.get("id"))==entity_id and item.get("source")!="generate_image" for item in assets) else entity_id+"_regenerated"
                linked=asset_specs.get(str(entity.get("asset_id") or ""),{})
                description=" ".join(str(value or "") for value in (
                    entity.get("identity"),entity.get("appearance"),entity.get("wardrobe"),entity.get("voice"),entity.get("description"),
                    linked.get("description"),linked.get("prompt"),linked.get("usage"),linked.get("appearance"),linked.get("wardrobe"),entity.get("name")
                ))
                prompt=AIVideoWorkflow._independent_asset_prompt(kinds[entity_id],description or entity_id)
                assets=[item for item in assets if str(item.get("id"))!=generated_id]
                assets.append({"id":generated_id,"name":str(entity.get("name") or entity.get("identity") or entity_id),"kind":kinds[entity_id],"source":"generate_image","prompt":prompt,"entity_id":entity_id})
                entity["reference_asset_id"]=generated_id
                replacements[old_id]=generated_id;replacements[str(entity_id)]=generated_id
        bible["assets"]=assets
        return replacements

    @staticmethod
    def _independent_asset_prompt(kind,description):
        if kind=="character":
            live_action=""
            if "猪八戒" in str(description):
                live_action="照片主体必须首先是一名真实成年中国男演员，由真人扮演；可清楚看到人类眼睛、真实皮肤毛孔和真人手掌。猪耳与猪鼻只是佩戴在演员脸上的实体硅胶电影特效妆，绝不能把主体画成猪、卡通吉祥物、动画角色或3D渲染。"
            return f"独立角色制作参考图，单一角色，无其他人物，无文字无水印。真实摄影机拍摄的真人电影定妆照，不是插画或渲染。{live_action}真实皮肤、毛发、布料和实体电影特效妆质感，严禁卡通、动画、CGI、3D玩具、Q版或儿童绘本风格。必须从头顶拍到鞋底，完整正面全身，四肢不得裁切；脸部五官、身体比例、发型、服装、材质和配饰明确，简洁中性影棚背景，现代高质量数字摄影。角色设定：{description}"
        if kind=="prop": return f"独立道具制作参考图，单一道具，无人物，无文字无水印。完整展示固定造型、材质、颜色、比例与关键结构，三分之四视角，简洁中性背景，高细节。道具设定：{description}"
        return f"独立场景制作参考图，无人物，无文字无水印。清晰展示固定空间布局、主要陈设、入口出口、光线、色彩与材质，高细节广角构图。场景设定：{description}"

    def _generate(self, context):
        pending={str(shot["id"]):shot for shot in context.artifacts["storyboard"]}; completed={}; keyframes={}
        while pending:
            ready=[shot for shot in pending.values() if all(dep in completed for dep in shot["depends_on"])]
            if not ready: raise ValueError("故事板镜头存在循环依赖或无法解析的 depends_on")
            for shot in sorted(ready,key=lambda item:item["sequence"]):
                plan=shot["generation_plan"];mode=plan["mode"];reference_image=None;reference_video=None
                referenced=[context.artifacts["assets"].get(str(asset_id)) for asset_id in plan.get("reference_asset_ids",[])];referenced=[item for item in referenced if item]
                if mode=="image_then_i2v":
                    if not self.generate_image: raise RuntimeError("image_then_i2v 需要 generate_image 工具")
                    reference_image=self.generate_image({"id":shot["id"]+"_keyframe","prompt":plan.get("image_prompt") or shot["prompt"],"kind":"shot_keyframe"},context)
                    context.artifacts["assets"][shot["id"]+"_keyframe"]=reference_image
                elif mode=="previous_frame_i2v":
                    if not shot["depends_on"]: raise ValueError(f"{shot['id']} 使用 previous_frame_i2v 但没有 depends_on")
                    reference_image=keyframes[shot["depends_on"][-1]]["last"]
                elif mode == "reference_pack_i2v":
                    visual_references=[item for item in referenced if item.suffix.lower() in {".jpg",".jpeg",".png",".webp"}]
                    if not visual_references and context.reference_image: visual_references=[context.reference_image]
                    reference_image=visual_references[0] if visual_references else None
                    active=visual_references[:9]
                    active_ids=[str(asset_id) for asset_id in plan.get("reference_asset_ids",[]) if context.artifacts["assets"].get(str(asset_id)) in active]
                    if shot["depends_on"] and len(active)<9:
                        previous=next((item for item in context.artifacts["storyboard"] if item["id"]==shot["depends_on"][-1]),None)
                        current_characters=set(shot.get("asset_bindings",{}).get("character_ids",[]))
                        previous_characters=set((previous or {}).get("asset_bindings",{}).get("character_ids",[]))
                        # A tail frame is an identity reference as well as a
                        # continuity reference. Only inherit it when identity is unchanged.
                        if current_characters and current_characters==previous_characters:
                            active.append(keyframes[shot["depends_on"][-1]]["last"]);active_ids.append("previous_shot_last_frame")
                    context.artifacts["active_reference_images"]=active
                    context.artifacts["active_reference_asset_ids"]=active_ids
                elif mode == "i2v": reference_image=next((item for item in referenced if item.suffix.lower() in {".jpg",".jpeg",".png",".webp"}),None) or context.reference_image
                elif mode=="r2v": reference_video=next((item for item in referenced if item.suffix.lower() in {".mp4",".mov",".webm",".mkv"}),None) or context.reference_video
                if mode!="t2v" and mode!="r2v" and not reference_image: raise ValueError(f"{shot['id']} 的 {mode} 没有可用参考图")
                if mode=="r2v" and not reference_video: raise ValueError(f"{shot['id']} 的 r2v 没有可用参考视频")
                if mode != "reference_pack_i2v": context.artifacts["active_reference_images"]=[reference_image] if reference_image else [];context.artifacts["active_reference_asset_ids"]=plan.get("reference_asset_ids",[])[:1] if reference_image else []
                context.artifacts["active_reference_image"]=reference_image;context.artifacts["active_reference_video"]=reference_video
                clip=self.generate_shot(shot,context);completed[shot["id"]]=clip
                if self.extract_keyframes: keyframes[shot["id"]]=self.extract_keyframes(clip,shot,context)
                pending.pop(shot["id"])
        clips=[completed[str(shot["id"])] for shot in sorted(context.artifacts["storyboard"],key=lambda item:item["sequence"])]
        context.artifacts["clips"] = clips
        context.artifacts["keyframes"] = keyframes
        return {"message": f"已生成 {len(clips)} 个镜头", "clips": [path.name for path in clips]}

    def _review(self, context):
        payload = {"brief": context.brief, "storyboard": context.artifacts["storyboard"], "generated_clips": [path.name for path in context.artifacts["clips"]]}
        review = self.llm.complete_json(self.prompts.get("review") or DEFAULT_REVIEW_PROMPT, json.dumps(payload, ensure_ascii=False))
        # This review currently sees only the storyboard and clip filenames.
        # Keep its findings in the trace, but do not block valid generated media
        # until a real multimodal reviewer can inspect the actual video content.
        if review.get("approved") is False:
            review["delivery_gate"] = "advisory"
        context.artifacts["review"] = review
        (context.task_dir / "review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
        message = str(review.get("summary") or "审片完成")
        if review.get("approved") is False:
            message = "审片建议已记录，继续合成：" + message
        return {"message": message, "review": review}

    def _compose(self, context):
        output = merge_videos(context.artifacts["clips"], context.task_dir / "final.mp4")
        context.artifacts["output"] = output
        return {"message": "镜头已合成为最终视频", "file": output.name}
