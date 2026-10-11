import tempfile
import unittest
from pathlib import Path

from services.video_creator.workflow.context import WorkflowContext
from services.video_creator.workflows.ai_video import AIVideoWorkflow


class FakeLLM:
    def complete_json(self, system, prompt):
        if "故事板" in system:
            return {"creative_intent":{"goal":"日出短片","audience":"大众","style":"电影感","constraints":[]},"shots": [{"duration_seconds": 5, "description": "开场", "prompt": "日出延时摄影", "reference_strategy": "t2v"}]}
        if "审片" in system:
            return {"approved": True, "summary": "结构完整", "issues": []}
        return {"goal": "短视频", "audience": "大众", "style": "电影感", "duration_seconds": 5, "constraints": []}


class AIVideoWorkflowTests(unittest.TestCase):
    def test_storyboard_contract_requires_resolution_and_audible_design(self):
        result={"creative_intent":{},"shots":[
            {"story_function":"setup","duration_seconds":2,"audio":{"dialogue":"","sound_effects":"脚步","ambience":"风声"}},
            {"story_function":"turn","duration_seconds":2,"audio":{"dialogue":"识破你了","sound_effects":"","ambience":"风声"}},
            {"story_function":"escalation","duration_seconds":2,"audio":{"dialogue":"","sound_effects":"","ambience":""}},
        ]}
        issues=AIVideoWorkflow._storyboard_contract_issues(result,6)
        self.assertTrue(any("ending_payoff" in item for item in issues))
        self.assertTrue(any("resolution" in item for item in issues))
        self.assertTrue(any("音效或环境声" in item for item in issues))

    def test_complete_storyboard_contract_passes(self):
        result={"creative_intent":{"ending_payoff":"主角用一句话回扣冲突"},"shots":[
            {"story_function":"setup","duration_seconds":2,"audio":{"dialogue":"","sound_effects":"脚步","ambience":"风声"}},
            {"story_function":"turn","duration_seconds":3,"audio":{"dialogue":"识破你了","sound_effects":"衣料","ambience":"风声"}},
            {"story_function":"resolution","duration_seconds":3,"audio":{"dialogue":"下次换个新把戏","sound_effects":"金箍棒轻响","ambience":"鸟鸣"}},
        ]}
        self.assertEqual(AIVideoWorkflow._storyboard_contract_issues(result,8),[])

    def test_appends_learned_rules_to_admin_custom_storyboard_prompt(self):
        class Planner:
            def __init__(self): self.system=""
            def complete_json(self,system,prompt):
                self.system=system
                return {"shots":[{"duration_seconds":2,"prompt":"测试镜头"}]}
        with tempfile.TemporaryDirectory() as directory:
            planner=Planner();root=Path(directory)
            workflow=AIVideoWorkflow(planner,lambda shot,context:root/"unused.mp4",lambda nodes:None,prompts={"storyboard":"自定义故事板提示词"})
            workflow._storyboard(WorkflowContext("learned-rules",root,"测试",params={"total_duration":2}))
            self.assertIn("no_dialogue 仅表示没有语言",planner.system)
            self.assertIn("变形镜头只表现变形主体",planner.system)
            self.assertIn("人物集合变化时禁止继承",planner.system)

    def test_compiles_explicit_mandarin_or_no_dialogue_audio_contract(self):
        dialogue=AIVideoWorkflow._compile_video_prompt({"audio":{"speaker":"蜘蛛精","dialogue":"现在，还觉得我好看吗？","speech_timing":"0.8-2.8秒"}}, {})
        silent=AIVideoWorkflow._compile_video_prompt({"audio":{"dialogue":"","ambience":"茶馆环境声"}}, {})
        self.assertIn("标准普通话逐字说出",dialogue)
        self.assertIn('"mode":"dialogue"',dialogue)
        self.assertIn("禁止生成任何人声",silent)
        self.assertIn('"mode":"no_dialogue"',silent)

    def test_structured_character_and_location_ids_resolve_to_assets(self):
        class Planner:
            def complete_json(self,system,prompt):
                return {"continuity_bible":{
                    "characters":[{"id":"sun_wukong","reference_asset_id":"sun_asset"}],
                    "locations":[{"id":"mountain_path","reference_asset_id":"path_asset"}],
                    "props":[],
                    "assets":[
                        {"id":"sun_asset","kind":"character","source":"generate_image","entity_id":"sun_wukong","prompt":"孙悟空"},
                        {"id":"path_asset","kind":"location","source":"generate_image","entity_id":"mountain_path","prompt":"山路"},
                    ]},"shots":[{"duration_seconds":2,"prompt":"孙悟空走山路","characters":[{"character_id":"sun_wukong"}],"scene":{"location_id":"mountain_path"}}]}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);workflow=AIVideoWorkflow(Planner(),lambda shot,context:root/"unused.mp4",lambda nodes:None)
            result=workflow._storyboard(WorkflowContext("structured-ids",root,"测试",params={"total_duration":2}))
            bindings=result["shots"][0]["asset_bindings"]
            self.assertEqual(bindings["character_ids"],["sun_asset"])
            self.assertEqual(bindings["location_id"],"path_asset")

    def test_empty_scene_props_do_not_inherit_global_props(self):
        class Planner:
            def complete_json(self,system,prompt):
                return {"continuity_bible":{
                    "characters":[{"id":"woman","reference_asset_id":"woman_asset"}],
                    "locations":[{"id":"road","reference_asset_id":"road_asset"}],
                    "props":[{"id":"staff","reference_asset_id":"staff_asset"}],
                    "assets":[
                        {"id":"woman_asset","kind":"character","source":"generate_image","entity_id":"woman","prompt":"女人"},
                        {"id":"road_asset","kind":"location","source":"generate_image","entity_id":"road","prompt":"山路"},
                        {"id":"staff_asset","kind":"prop","source":"generate_image","entity_id":"staff","prompt":"棍"},
                    ]},"shots":[{"duration_seconds":2,"prompt":"女人独自说话","characters":[{"character_id":"woman"}],"scene":{"location_id":"road","props":[]}}]}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);workflow=AIVideoWorkflow(Planner(),lambda shot,context:root/"unused.mp4",lambda nodes:None)
            result=workflow._storyboard(WorkflowContext("empty-scene-props",root,"测试",params={"total_duration":2}))
            self.assertEqual(result["shots"][0]["asset_bindings"]["prop_ids"],[])

    def test_runs_continuity_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clip = root / "generated.mp4"
            clip.write_bytes(b"video")
            snapshots = []
            workflow = AIVideoWorkflow(FakeLLM(), lambda shot, context: clip, lambda nodes: snapshots.append(nodes))
            result = workflow.run(WorkflowContext("task-1", root, "制作日出短片", params={"total_duration": 5}))
            self.assertEqual(result["output"].read_bytes(), b"video")
            self.assertTrue((root / "storyboard.json").is_file())
            self.assertTrue((root / "review.json").is_file())
            self.assertEqual([node["status"] for node in snapshots[-1]], ["success"] * 5)
            shot=result["storyboard"][0]
            self.assertEqual((shot["sequence"],shot["start_time_seconds"],shot["end_time_seconds"],shot["duration_seconds"]),(1,0.0,5.0,5.0))
            self.assertIn("shot_and_transition",shot)
            self.assertIn("audio_and_dialogue",shot)
            self.assertEqual(shot["generation_plan"]["mode"],"t2v")

    def test_image_then_i2v_and_previous_frame_dependency(self):
        class Planner:
            def complete_json(self,system,prompt):
                if "审片" in system:return {"approved":True,"summary":"连续","issues":[]}
                return {"continuity_bible":{"assets":[]},"shots":[
                    {"id":"shot-1","duration_seconds":2,"prompt":"人物入场","generation_plan":{"mode":"image_then_i2v","image_prompt":"人物定帧"}},
                    {"id":"shot-2","duration_seconds":2,"prompt":"人物继续前行","depends_on":["shot-1"],"generation_plan":{"mode":"previous_frame_i2v"}}
                ]}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);references=[]
            def image_tool(spec,context):
                path=root/(spec["id"]+".png");path.write_bytes(b"image");return path
            def video_tool(shot,context):
                references.append(context.artifacts.get("active_reference_image"));path=root/(shot["id"]+".mp4");path.write_bytes(b"video");return path
            def keyframe_tool(clip,shot,context):
                first=root/(shot["id"]+"_first.jpg");last=root/(shot["id"]+"_last.jpg");first.write_bytes(b"first");last.write_bytes(b"last");return {"first":first,"last":last}
            from unittest.mock import patch
            with patch("services.video_creator.workflows.ai_video.merge_videos",side_effect=lambda clips,output: clips[0]):
                workflow=AIVideoWorkflow(Planner(),video_tool,lambda nodes:None,generate_image=image_tool,extract_keyframes=keyframe_tool)
                workflow.run(WorkflowContext("task-2",root,"连续人物",params={"total_duration":4}))
            self.assertEqual(references[0].name,"shot-1_keyframe.png")
            self.assertEqual(references[1].name,"shot-1_last.jpg")

    def test_materializes_missing_character_location_and_prop_assets_before_shots(self):
        class Planner:
            def complete_json(self,system,prompt):
                return {"continuity_bible":{
                    "characters":{"zhu_bajie":{"identity":"猪八戒","appearance":"猪耳猪鼻，体型壮实","wardrobe":"绿色短打"}},
                    "locations":[{"id":"bamboo_teahouse","description":"花果山竹木茶馆"}],
                    "props":[{"id":"nine_tooth_rake","description":"金属九齿钉耙"}],
                    "assets":[]},"shots":[{"duration_seconds":5,"prompt":"猪八戒手持钉耙进入茶馆","continuity":{"character_ids":["zhu_bajie"],"location_id":"bamboo_teahouse","prop_ids":["nine_tooth_rake"]},"generation_plan":{"mode":"t2v"}}]}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);generated=[]
            def image_tool(spec,context):
                generated.append(spec);path=root/(spec["id"]+".png");path.write_bytes(b"image");return path
            workflow=AIVideoWorkflow(Planner(),lambda shot,context:root/"unused.mp4",lambda nodes:None,generate_image=image_tool)
            context=WorkflowContext("task-assets",root,"猪八戒拿着九齿钉耙进入茶馆",params={"total_duration":5})
            workflow._storyboard(context);result=workflow._prepare_assets(context)
            self.assertEqual({item["id"] for item in generated},{"zhu_bajie","bamboo_teahouse","nine_tooth_rake"})
            self.assertEqual(set(context.artifacts["assets"]),{"zhu_bajie","bamboo_teahouse","nine_tooth_rake"})
            shot=context.artifacts["storyboard"][0]
            self.assertEqual(shot["generation_plan"]["mode"],"reference_pack_i2v")
            self.assertEqual(set(shot["generation_plan"]["reference_asset_ids"]),{"zhu_bajie","bamboo_teahouse","nine_tooth_rake"})
            self.assertIn("已准备 3 个连续性资产",result["message"])

    def test_reuses_matching_library_asset_instead_of_regenerating_it(self):
        class Planner:
            def complete_json(self,system,prompt):
                return {"continuity_bible":{"characters":[{"id":"zhu_bajie","identity":"猪八戒"}],"assets":[]},"shots":[{"duration_seconds":5,"prompt":"猪八戒入场","continuity":{"character_ids":["zhu_bajie"]},"generation_plan":{"mode":"t2v"}}]}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);existing=root/"existing.png";existing.write_bytes(b"existing")
            generated=[];resolved=[]
            workflow=AIVideoWorkflow(Planner(),lambda shot,context:root/"unused.mp4",lambda nodes:None,generate_image=lambda spec,context:generated.append(spec),resolve_library_asset=lambda asset_id:(resolved.append(asset_id) or existing))
            context=WorkflowContext("task-reuse",root,"猪八戒入场",params={"total_duration":5,"_available_library_assets":[{"id":"asset-zbj","name":"猪八戒","kind":"character","description":{}}]})
            workflow._storyboard(context);workflow._prepare_assets(context)
            self.assertEqual(generated,[])
            self.assertEqual(resolved,["asset-zbj"])
            self.assertEqual(context.artifacts["storyboard"][0]["asset_bindings"]["character_ids"],["asset-zbj"])

    def test_existing_asset_id_overrides_planner_generate_image_source(self):
        bible={"characters":[{"id":"pig","name":"猪八戒","reference_asset_id":"asset-pig"}],"locations":[],"props":[],"assets":[{"id":"asset-pig","name":"猪八戒","kind":"character","source":"generate_image"}]}
        with tempfile.TemporaryDirectory() as directory:
            context=WorkflowContext("existing-wins",Path(directory),"测试",params={"_available_library_assets":[{"id":"asset-pig","name":"猪八戒","kind":"character"}]})
            AIVideoWorkflow._materialize_asset_specs(bible,context)
        self.assertEqual(bible["assets"][0]["source"],"library_asset")
        self.assertEqual(bible["assets"][0]["library_asset_id"],"asset-pig")

    def test_does_not_generate_unbound_mixed_storyboard_assets(self):
        class Planner:
            def complete_json(self,system,prompt):
                return {"continuity_bible":{"characters":[{"id":"pig","name":"猪八戒","asset_id":"pig-only"}],"assets":[{"id":"pig-only","type":"character","source":"generate_image","description":"只包含猪八戒"},{"id":"mixed","source":"generate_image","prompt":"猪八戒、蜘蛛精、茶馆和全部道具"}]},"shots":[{"duration_seconds":5,"prompt":"猪八戒入场","continuity":{"character_ids":["pig"]},"generation_plan":{"mode":"t2v"}}]}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);generated=[]
            def image_tool(spec,context):
                generated.append(spec);path=root/(spec["id"]+".png");path.write_bytes(b"image");return path
            workflow=AIVideoWorkflow(Planner(),lambda shot,context:root/"unused.mp4",lambda nodes:None,generate_image=image_tool)
            context=WorkflowContext("single-assets",root,"测试",params={"total_duration":5})
            workflow._storyboard(context);workflow._prepare_assets(context)
            self.assertEqual([item["id"] for item in generated],["pig-only"])
            self.assertNotIn("mixed",context.artifacts["assets"])

    def test_recovers_entity_lists_when_planner_only_declares_assets(self):
        bible={"assets":[
            {"id":"pig","name":"猪八戒","kind":"character","source":"generate_image","description":"单独的猪八戒"},
            {"id":"tea","name":"竹木茶馆","kind":"location","source":"generate_image"},
            {"id":"rake-lib","name":"九齿钉耙","kind":"prop","source":"library"},
            {"id":"silk","name":"蛛丝","kind":"vfx","source":"generate_image"},
        ],"characters":[],"locations":[],"props":[]}
        with tempfile.TemporaryDirectory() as directory:
            context=WorkflowContext("recover",Path(directory),"测试",params={"_available_library_assets":[{"id":"rake-lib","name":"九齿钉耙","kind":"prop"}]})
            AIVideoWorkflow._materialize_asset_specs(bible,context)
        self.assertEqual([item["id"] for item in bible["characters"]],["pig"])
        self.assertEqual([item["id"] for item in bible["locations"]],["tea"])
        self.assertEqual({item["id"] for item in bible["props"]},{"rake-lib","silk"})
        specs={item["id"]:item for item in bible["assets"]}
        self.assertEqual(specs["rake-lib"]["source"],"library_asset")
        self.assertEqual(specs["silk"]["kind"],"prop")

    def test_asset_confirmation_can_reuse_or_regenerate_each_entity(self):
        bible={"characters":[{"id":"hero","identity":"主角","reference_asset_id":"hero-auto"}],"locations":[],"props":[{"id":"rake","description":"九齿钉耙","reference_asset_id":"rake-auto"}],"assets":[{"id":"hero-auto","kind":"character","source":"generate_image"},{"id":"rake-auto","kind":"prop","source":"generate_image"}]}
        replacements=AIVideoWorkflow._apply_asset_decisions(bible,{"hero":{"action":"reuse","asset_id":"hero-existing","name":"现有主角"},"rake":{"action":"regenerate"}})
        self.assertEqual(replacements["hero-auto"],"hero-existing")
        self.assertEqual(bible["characters"][0]["reference_asset_id"],"hero-existing")
        self.assertEqual(bible["props"][0]["reference_asset_id"],"rake")
        specs={item["id"]:item for item in bible["assets"]}
        self.assertEqual(specs["hero-existing"]["source"],"library_asset")
        self.assertEqual(specs["rake"]["source"],"generate_image")

    def test_regenerated_character_keeps_linked_storyboard_description_and_realism(self):
        bible={"characters":[{"id":"pig","name":"猪八戒","asset_id":"pig-design","reference_asset_id":"pig-auto"}],"locations":[],"props":[],"assets":[{"id":"pig-design","kind":"character","source":"generate_image","usage":"写实真人电影特效妆，猪耳猪鼻，体型壮实"},{"id":"pig-auto","kind":"character","source":"generate_image"}]}
        AIVideoWorkflow._apply_asset_decisions(bible,{"pig":{"action":"regenerate"}})
        spec=next(item for item in bible["assets"] if item["id"]=="pig")
        self.assertIn("写实真人电影特效妆",spec["prompt"])
        self.assertIn("严禁卡通",spec["prompt"])

    def test_shot_binds_only_its_declared_speaking_character(self):
        class Planner:
            def complete_json(self,system,prompt):
                return {
                    "continuity_bible":{
                        "characters":[
                            {"id":"pig","name":"猪八戒","reference_asset_id":"pig-asset"},
                            {"id":"spider","name":"蜘蛛精","reference_asset_id":"spider-asset"},
                        ],
                        "locations":[{"id":"tea","name":"茶馆","reference_asset_id":"tea-asset"}],
                        "props":[{"id":"rake","name":"钉耙","reference_asset_id":"rake-asset"}],
                        "assets":[
                            {"id":"pig-asset","kind":"character","source":"generate_image"},
                            {"id":"spider-asset","kind":"character","source":"generate_image"},
                            {"id":"tea-asset","kind":"location","source":"generate_image"},
                            {"id":"rake-asset","kind":"prop","source":"generate_image"},
                        ],
                    },
                    "shots":[{
                        "duration_seconds":5,
                        "prompt":"蜘蛛精说话",
                        "characters":["spider"],
                        "scene":{"id":"tea"},
                        "props":["rake"],
                        "audio":{"speaker":"蜘蛛精","dialogue":"先把地扫了。"},
                        "generation_plan":{"mode":"t2v"},
                    }],
                }
        with tempfile.TemporaryDirectory() as directory:
            context=WorkflowContext("speaker-binding",Path(directory),"测试",params={"total_duration":5})
            workflow=AIVideoWorkflow(Planner(),lambda shot,context:Path(directory)/"unused.mp4",lambda nodes:None)
            workflow._storyboard(context)
            shot=context.artifacts["storyboard"][0]
        self.assertEqual(shot["asset_bindings"]["character_ids"],["spider-asset"])
        self.assertNotIn("pig-asset",shot["generation_plan"]["reference_asset_ids"])
        self.assertEqual(shot["asset_bindings"]["prop_ids"],["rake-asset"])
        self.assertEqual(shot["asset_bindings"]["location_id"],"tea-asset")

    def test_uploaded_character_reference_is_not_injected_into_unrelated_shots(self):
        class Planner:
            def complete_json(self,system,prompt):
                return {
                    "continuity_bible":{
                        "characters":[
                            {"id":"pig","name":"猪八戒","reference_asset_id":"pig-asset"},
                            {"id":"spider","name":"蜘蛛精","reference_asset_id":"input_image"},
                        ],
                        "assets":[
                            {"id":"pig-asset","kind":"character","source":"generate_image"},
                            {"id":"input_image","kind":"character","source":"input_image"},
                        ],
                    },
                    "shots":[
                        {"duration_seconds":2,"prompt":"猪八戒说话","characters":["pig"],"props":[],"audio":{"speaker":"猪八戒","dialogue":"有饭吗？"}},
                        {"duration_seconds":2,"prompt":"蜘蛛精回答","characters":["spider"],"props":[],"audio":{"speaker":"蜘蛛精","dialogue":"先扫地。"}},
                    ],
                }
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);uploaded=root/"spider.png";uploaded.write_bytes(b"spider")
            context=WorkflowContext("strict-shot-assets",root,"测试",uploaded,params={"total_duration":4})
            workflow=AIVideoWorkflow(Planner(),lambda shot,context:root/"unused.mp4",lambda nodes:None)
            workflow._storyboard(context)
        first,second=context.artifacts["storyboard"]
        self.assertEqual(first["generation_plan"]["reference_asset_ids"],["pig-asset"])
        self.assertEqual(second["generation_plan"]["reference_asset_ids"],["input_image"])
        self.assertEqual(first["asset_bindings"]["prop_ids"],[])

    def test_tail_frame_is_not_inherited_across_character_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);pig=root/"pig.png";spider=root/"spider.png"
            pig.write_bytes(b"pig");spider.write_bytes(b"spider");captured=[]
            def video_tool(shot,context):
                captured.append(list(context.artifacts["active_reference_asset_ids"]));path=root/(shot["id"]+".mp4");path.write_bytes(b"video");return path
            def keyframe_tool(clip,shot,context):
                first=root/(shot["id"]+"-first.jpg");last=root/(shot["id"]+"-last.jpg");first.write_bytes(b"first");last.write_bytes(b"last");return {"first":first,"last":last}
            workflow=AIVideoWorkflow(FakeLLM(),video_tool,lambda nodes:None,extract_keyframes=keyframe_tool)
            context=WorkflowContext("no-cross-identity-tail",root,"测试",params={"total_duration":4})
            context.artifacts.update({"assets":{"pig":pig,"spider":spider},"storyboard":[
                {"id":"shot-1","sequence":1,"depends_on":[],"asset_bindings":{"character_ids":["pig"]},"generation_plan":{"mode":"reference_pack_i2v","reference_asset_ids":["pig"]}},
                {"id":"shot-2","sequence":2,"depends_on":["shot-1"],"asset_bindings":{"character_ids":["spider"]},"generation_plan":{"mode":"reference_pack_i2v","reference_asset_ids":["spider"]}},
            ]})
            workflow._generate(context)
        self.assertEqual(captured,[["pig"],["spider"]])

    def test_failed_metadata_review_is_advisory(self):
        class Reviewer:
            def complete_json(self,system,prompt): return {"approved":False,"summary":"角色身份串线","issues":[]}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);clip=root/"shot.mp4";clip.write_bytes(b"video")
            context=WorkflowContext("blocked-review",root,"测试",params={})
            context.artifacts.update({"storyboard":[],"clips":[clip]})
            workflow=AIVideoWorkflow(Reviewer(),lambda shot,context:clip,lambda nodes:None)
            result=workflow._review(context)
            self.assertIn("继续合成",result["message"])
            self.assertEqual(context.artifacts["review"]["delivery_gate"],"advisory")


if __name__ == "__main__":
    unittest.main()
