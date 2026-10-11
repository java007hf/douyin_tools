# Agent Notes

## Project Files

Keep the repository root clean. The root should contain source code, committed utilities, extension source, and documentation only:

- `analyze_extension_result.py`
- `requirements.txt`
- `README.md`
- `AGENTS.md`
- `frontend/`
- `services/`

## Cache And Test Artifacts

Put all local test files, temporary browser profiles, downloaded media, scratch outputs, generated URL lists, copied request payloads, screenshots, and debug logs under `cache/`.

Examples:

```powershell
python services\douyin\service.py "主页地址" -o cache\urls.txt
python services\douyin\service.py --download "作品地址" --download-dir cache\downloads
python services\douyin\service.py "主页地址" --user-data-dir cache\.douyin-browser -o cache\urls.txt
python services\douyin\service.py --extension-interact "作品地址" --like > cache\extension_result.json
```

Do not create `downloads_test*`, `urls.txt`, `extension_result.json`, `__pycache__`, or browser profile folders in the project root.

## Interaction Testing

For comment, like, and favorite features, avoid bulk execution during tests. Use single, user-directed work URLs only.

Prefer `--extension-interact` for real interaction tests. It uses the installed Chrome extension and the logged-in Douyin page context. The older `--api-interact` path is useful for diagnostics but is less stable because Douyin may require page runtime parameters such as `msToken`, `a_bogus`, and `verifyFp`.

The Chrome extension version is defined only in `services/douyin/chrome_extension/manifest.json`; Python and JavaScript read it at runtime. When changing extension bridge behavior, only update the manifest version and reload the extension.

The currently verified interaction endpoints are:

```text
like:     /aweme/v1/web/commit/item/digg/
favorite: /aweme/v1/web/aweme/collect/
comment:  /aweme/v1/web/comment/publish/
```

Do not switch favorite back to `/aweme/v1/web/aweme/favorite/`; that endpoint can return a favorite list instead of performing the collect action.

## Verification

Run syntax checks before committing code changes:

```powershell
python -m py_compile services\douyin\service.py services\video_creator\service.py web_app.py analyze_extension_result.py
node --check services\douyin\chrome_extension\background.js
node --check services\douyin\chrome_extension\content.js
node --check services\douyin\chrome_extension\injected.js
node --check services\douyin\chrome_extension\popup.js
```

If Python creates `__pycache__`, remove it before committing. `cache/` must remain ignored and uncommitted.

## Video Workflow Architecture

The video creation Tab uses a three-layer Workflow architecture. Keep the layers separate so new Workflows can be added without coupling business logic to HTTP handlers.

`services/core/` is reserved for infrastructure shared by multiple Tabs. Workflow execution, Workflow models, Workflow context, and Workflow registration belong to `services/video_creator/workflow/`; `services/core/registry.py` is only the top-level Tab registry.

```text
services/
  core/
    ...                  # Cross-service infrastructure only
  video_creator/
    service.py           # HTTP API layer
    workflow/
      engine.py          # Workflow execution engine
      context.py         # Runtime context and intermediate artifacts
      registry.py        # Video Workflow registration
      models.py          # Tasks, nodes, and statuses
    workflows/
      base.py
      video_recreate.py  # Concrete Workflow implementations
    tools/
      video/
        trim.py
        extract_frames.py
        merge.py
      ai/
        llm.py
        video_understanding.py
    schemas/
      requests.py
      responses.py
```

### Layer Responsibilities

- Base tools provide one focused capability, such as video trimming, frame extraction, merging, audio processing, video understanding, or LLM calls. Tools must not depend on HTTP or a specific Workflow.
- Workflows compose tools into an ordered process, including parameters, branching, intermediate artifacts, progress, retries, and failure handling. Each Workflow lives in its own module or directory.
- The service layer validates input, creates Workflow tasks, exposes task status and logs, and returns artifacts or download URLs. HTTP handlers must not contain the actual media-processing logic.

### Workflow Runtime Rules

- Treat every execution as a task with a unique ID and explicit node statuses: `pending`, `running`, `success`, and `failed`.
- Store intermediate outputs as named artifacts, such as video files, frame images, subtitles, analysis JSON, and generated media.
- Keep all task files under a task-specific directory inside `cache/`, making cleanup and download boundaries explicit.
- Record node progress, structured logs, errors, and retry information so long-running jobs are observable.
- Wrap LLM and video-understanding integrations behind Provider interfaces, allowing models or vendors to change without rewriting Workflows.
- A Workflow may be enabled, replaced, or deployed independently after registration in `video_creator/workflow/registry.py`.

### Initial Video Recreation Workflow

The first Workflow is expected to follow this shape, with generation and composition details added later:

```text
reference video upload
  -> save task input
  -> inspect basic video metadata
  -> extract frames
  -> understand video content
  -> generate a structured recreation plan from the user brief
  -> generate assets and compose the final video
```

### AI Video Continuity Workflow

AI Video uses a fixed, observable Workflow. The LLM plans work; deterministic Workflow code validates the plan, resolves dependencies, invokes tools, stores artifacts, and controls retries. Do not let an unconstrained Agent own task state or filesystem paths.

Keep AI Video model configuration isolated from the regular generation prompt helper. The Admin item `生图&视频 LLM` is only for prompt improvement on the direct image/video forms. The sibling Admin item `AI视频` owns its own Agent API URL, API key, Agent model, system prompts, default image Provider/model, and separate T2V, I2V, and R2V Provider/model routes. AI Video must never fall back to credentials or model settings from `生图&视频 LLM`.

```text
user brief + optional reference media + total duration
  -> plan_storyboard
       - infer creative intent
       - create continuity bible
       - create timed shot plans and dependencies
  -> prepare_consistency_assets
       - register user references
       - generate missing character/location/prop references when requested
  -> generate_shots
       - topologically resolve depends_on
       - choose T2V, I2V, R2V, image_then_i2v, or previous_frame_i2v
       - extract and register each clip's first/last frame
  -> review_continuity
       - review story, identity, wardrobe, location, props, and temporal continuity
       - return machine-readable issues linked to shot IDs
  -> repair_failed_shots
       - regenerate only rejected shots, bounded by retry limits
  -> compose_video
```

The storyboard JSON is the contract between planning and execution. Its root contains `creative_intent`, `continuity_bible`, and `shots`. A shot contains `id`, `sequence`, `start_time_seconds`, `end_time_seconds`, `duration_seconds`, production descriptions, `depends_on`, `asset_dependencies`, `continuity`, and `generation_plan`. `depends_on` is reserved for preceding shot IDs and execution order; `asset_dependencies` lists character, prop, and reference-media assets and must not be used as a shot dependency. `generation_plan.mode` is one of `t2v`, `i2v`, `r2v`, `image_then_i2v`, `previous_frame_i2v`, or `reference_pack_i2v`.

Continuity must be represented as artifacts and dependencies, not only prompt wording:

- `continuity_bible.characters`, `locations`, `props`, and `visual_style` define stable identities and appearance.
- `continuity.must_preserve` names the attributes a downstream reviewer must compare.
- `depends_on` determines execution order. Never infer dependencies from array order alone.
- `asset_dependencies` determines which continuity assets a shot must preserve. Resolve unknown LLM aliases to registered asset IDs before execution; never silently drop a reference asset.
- `image_then_i2v` first creates a shot keyframe and passes that actual file to I2V.
- `previous_frame_i2v` passes a dependency clip's extracted last frame to the next I2V call.
- Scene changes should use character/location references instead of blindly inheriting the previous background.
- Every generated file must be registered in `WorkflowContext.artifacts`; task JSON stores portable names/IDs rather than credentials or arbitrary external paths.

Generation and review capabilities should be exposed through stable tool interfaces. The intended MCP surface is `plan_storyboard`, `generate_image`, `generate_video_t2v`, `generate_video_i2v`, `generate_video_r2v`, `extract_keyframes`, `review_video`, and `merge_video`. The local Workflow may use in-process adapters until the MCP servers exist, but the Workflow contract must not depend on Provider-specific request formats.

## ComfyUI Integration

The video creator service integrates with a local ComfyUI instance through its HTTP API. Set `COMFYUI_URL` when ComfyUI is not on `http://127.0.0.1:8188`. Image generation currently uses the installed Flux workflow; `qwen` and `sd` are exposed in the UI but require corresponding models/workflows. Video generation selects `t2v`, `i2v`, or `r2v` from the supplied reference media. Configure API-format workflows with `COMFYUI_T2V_WORKFLOW`, `COMFYUI_I2V_WORKFLOW`, and `COMFYUI_R2V_WORKFLOW`.

## Current Todo Tracking

The canonical task details are in `todo.md`. Keep the checklist below synchronized with that file. When a task is completed, mark it as `[x]` in both files in the same change.

### AI Video Agent

### Task Monitoring Requirement

- Every AI Video or long-running generation submission must be monitored from creation until a terminal state: `done`, `error`, or explicit cancellation.
- After submission, poll the parent task and all child ComfyUI/provider tasks on a fixed interval; do not report only the task ID and stop observing.
- Monitoring is active follow-up, not log collection: inspect node progress, queue position, stalled heartbeats, child task output, and generated artifacts at each interval.
- If a task fails, stalls, or produces an invalid artifact, immediately inspect the complete parent node error, child task error, provider request ID when available, and ComfyUI validation message under the task directory in `cache/`.
- For actionable failures, fix the code, workflow, prompt binding, or runtime configuration; run a focused validation; stop the invalid task; and retry automatically when the retry is safe. Do not wait for the user to ask what happened.
- Continue monitoring the retry through review and composition. Only report completion after the final artifact is available and inspectable, or report a concrete external blocker requiring user input.
- Until multimodal video inspection is implemented, the metadata-only AI review is advisory and must not block a valid set of generated clips; preserve its warnings in the task trace and continue composition.
- Before retrying, fix or explain the root cause, verify the generated workflow locally, and report whether the retry uses the corrected workflow.
- A service restart must reconcile queued/running tasks with ComfyUI state; orphaned tasks must be marked interrupted instead of remaining indefinitely in `running`.

- [x] Add an AI Video view beside image and video generation.
- [x] Implement the fixed four-stage Workflow: intent-aware production storyboard, shot generation, AI review, and composition.
- [x] Keep LLM reasoning in the intent, storyboard, and review nodes; execute generation and composition through tool boundaries.
- [x] Limit the AI Video form to the brief, optional reference media, and total duration; configure models and Agent prompts in Admin.
- [x] Support configurable storyboard-planning and review system prompts plus a default video Provider and model.
- [x] Add continuity-bible assets, shot dependencies, image-first I2V, previous-shot tail-frame inheritance, and boundary-frame extraction.
- [x] Configure separate default image, T2V, I2V, and R2V Providers/models for AI Video.
- [x] Isolate the regular image/video prompt-helper LLM from AI Video Agent credentials, model, prompts, and generation defaults.
- [x] Add an AI Video asset Trace view for node timings, creative intent, continuity bible, storyboard, review, child tasks, and artifact files.
- [x] Visualize reference-asset usage in AI Video Trace with library thumbnails, source labels, per-shot character/location/prop bindings, and unresolved-binding warnings.
- [x] Use a quality-first AI Video default of 768p/1MP, 16:9, and 24 full sampling steps; never let missing fields silently fall back to 360p.
- [ ] Expose image, T2V, I2V, R2V, and video utilities through a discoverable MCP Server with Agent tool-selection policies.
- [ ] Upgrade review to a multimodal `review_video` MCP that inspects actual video content instead of structural metadata only.
- [x] Implement true multi-reference `reference_pack_i2v`; bind the original identity reference and the previous shot tail frame to H3 `ref2va`.
- [ ] Add targeted shot regeneration after failed review, retry limits, human approval, and cancellation.
- [x] Allow queued, awaiting-confirmation, stalled, and running AI Video drafts to be cancelled and removed, including their child tasks and matching ComfyUI prompts.
- [ ] Keep two selectable dialogue pipelines and support A/B runs from the same storyboard: Plan A preserves native joint video-audio generation; Plan B uses silent video, stable-voice TTS, lip synchronization, and unified mixing.
- [ ] Record pipeline, model, seed, character-asset version, dialogue completion, voice consistency, lip sync, character consistency, and generation time for side-by-side A/B playback and human scoring.
- [ ] Require identity-critical shots to use keyframes with faces occupying 25%-35% of frame height, with explicit face-identity locking and face-detail restoration; separate wide action shots from dialogue close-ups.
- [x] Persist validated production lessons as mandatory storyboard rules even when Admin stores an older custom prompt: one speaker per shot, split transformation from reaction, bind only visible assets, use identity-critical close-ups, and treat no-dialogue as nonverbal ambience/Foley rather than total silence.
- [x] Validate narrative closure before production with one automatic storyboard rewrite: require setup, turn, resolution, and ending_payoff; validate dialogue duration, enforce a real loudness floor for non-dialogue Foley, and attach repair renders to their parent AI-video task so they never appear as standalone drafts.

### Reference-Media Recreation

- [x] Prepare and save the supplied reference video for recreation testing.
- [x] Validate I2V recreation with a reference image.
- [x] Validate R2V recreation with a reference video.
- [x] Compare T2V, I2V, and R2V outputs and failure messages.
- [x] Record real workflow validation inputs, durations, outputs, and failures under `cache/`.
- [ ] Tune prompt templates, reference strength, resolution, frame count, and timeout behavior.

### ComfyUI Workflows

- [ ] Convert and save API-format T2V, I2V, and R2V workflows.
- [ ] Bind prompt, size, aspect ratio, frame count, sampler settings, and seed.
- [ ] Validate progress, cancellation, timeout, retry, and download behavior.
- [ ] Add workflow version and model dependency checks.

### Cloud Providers

- [ ] Define a unified cloud model Provider interface.
- [ ] Integrate the H3 Provider.
- [ ] Integrate the Seedance Provider.
- [ ] Add environment-based secret configuration and redacted logging.
- [ ] Add rate limiting, retries, idempotency, and timeout handling.
- [ ] Show local/cloud provider selection in the creation page and use the same asset Feed.
- [ ] Record provider model version, request ID, duration, and billing metadata when available.

### Tests And Documentation

- [ ] Add ComfyUI workflow validation and API tests.
- [ ] Add mocked H3 and Seedance Provider tests.
- [ ] Update `README.md` with local model and cloud API deployment instructions.
- [ ] Keep this checklist and `todo.md` synchronized after each completed task.

### Long-Term Asset Library

- [x] Restrict each generated long-term asset to one independent character, location, prop, or style subject; ignore unbound mixed storyboard helper specs.
- [x] Show each asset's description/prompt JSON and allow editing its name, kind, and description metadata.
- [x] Let users edit an asset's generation prompt and create a Qwen Image improvement using the current image or an uploaded reference; preserve the original and persist the result with derivation provenance.
- [x] Refresh the asset library whenever its view opens and expose load failures instead of presenting them as an empty library.
- [ ] Upgrade generation forms from single-asset selection to multi-select and assign each asset a role: primary character, supporting character, location, prop, or visual style.
- [x] Support multi-asset selection in direct creation and retry forms, insert stable `<asset:ID>` tokens into prompts, and persist structured asset IDs independently of Provider-specific picture slots.
- [x] Resolve stable `<asset:ID>` references into per-request `<Picture N>` mappings and dynamically bind up to nine images to MiniMax H3 `ref2va`; expose the mapping in storyboard Trace.
- [ ] Add asset version and derivation relationships for character looks, wardrobe variants, and a clearly selected default version.
- [ ] Add perceptual hashing alongside SHA-256 exact deduplication to detect images changed only by compression, resizing, or format conversion.
- [ ] Add series/world asset packs that bind reusable characters, locations, props, and visual style across multiple AI videos.
- [ ] Replace permanent asset deletion with a recoverable trash workflow and show storyboard and asset-pack references before deletion.
- [ ] Replace the draft promotion prompts with a structured editor for name, kind, character traits, wardrobe, voice, location description, and tags.
- [ ] Track full asset provenance including ownership/license metadata, source task, consuming tasks, and derived assets.
- [ ] Upgrade character assets into reference packs containing the description JSON, primary image, stable voice samples, speaking style, language, pace, emotion range, and voice Provider identity. Shot boundary frames are runtime continuity artifacts and must never be treated as long-term assets.
- [ ] Generate and manage standard character views: face close-up, front full body, left/right profiles, back view, common expressions, actions, and varied scene lighting; complete missing views before video generation when the source is only a half-body image.
- [ ] Support short reference videos as character assets; retain the original video and extract identity frames, body proportions, turn-around views, motion traits, mouth-shape examples, and voice samples.
- [ ] Apply exact and perceptual/voiceprint deduplication to character-pack images, audio, and video, while tracking provenance, derivations, the default version, and intended usage scope.
- [x] Add a mandatory pre-production asset-materialization stage: automatically reuse same-name/type library assets; otherwise every recurring character, location, and key prop resolves to a newly generated independent asset that is persisted immediately before shot generation, such as Zhu Bajie and the nine-tooth rake.
- [x] Add an optional post-storyboard asset confirmation gate: when enabled, pause the task and let the user keep the planned asset, select an existing same-kind asset, or regenerate each character/location/prop before unified generation; when disabled, retain automatic resolution.
- [x] Keep asset-confirmation selections stable during draft polling; when confirmation is enabled, auto-resolve explicitly selected same-name/type assets and ask only about storyboard entities that remain missing.
- [x] Replace text-only post-storyboard asset selects with visual radio cards that show each candidate image, name, kind, full ID, and full-image link; continue only after every missing entity has a choice.
- [x] Prevent cross-character identity contamination: bind only explicitly declared shot characters/props, never inject the user's reference image globally, inherit a prior tail frame only when the character set is unchanged, and block composition after a rejected structured review.
- [ ] Persist only independent pre-production character, location, prop, and style references plus user reference videos and voice samples as candidate assets; never promote shot first/last frames into the asset library.
- [ ] Audit historical storyboards for declared but unmaterialized characters, locations, and props and allow generating the missing independent assets on demand; do not derive them from boundary frames.

## Current Web Controls

The unified web app exposes three tabs in this order: Douyin Tool, AI Creation Tool, and Admin. The AI Creation Tool contains the `视频抽帧`, `生图`, and `生视频` views. Image/video generation parameters such as model, aspect ratio, and resolution belong to the generation form, not provider configuration.

The Admin tab is enabled by default and runs on port `8103`. Provider configuration only stores connection parameters for MiniMax and Seedance; credentials are redacted as `********` in public responses and empty credential fields preserve the stored value. The gateway defaults to `0.0.0.0` for LAN access. Use `run.bat` for the standard Windows startup, or `--no-admin` when a public-only gateway is required.

### Visual Model Configuration

- [ ] Reference the `C:\workspace\xiaozhi-esp32-server-benyl` console model settings and implement a visual model/Provider configuration page.
- [ ] Support H3 and Seedance cloud settings such as API URL, Token, API Key, model version, and defaults.
- [ ] Mask and securely store credentials; never expose them in frontend or ordinary task logs.
- [ ] Add configuration validation, connection testing, enable/disable, default model selection, and effective-state feedback.
- [x] Preserve Provider HTTP error bodies for structured storyboard requests so model activation, authorization, and missing-model failures are visible in task errors instead of collapsing to a bare HTTP status.
- [ ] Keep model configuration separate from generation tasks; tasks reference a Provider configuration ID instead of storing secrets.


### 抖音视频理解

- [x] 对比 small、medium、large-v3、large-v3-turbo 和 SenseVoice，保存完整实测报告，配置选用 turbo 并开启词级对齐和静音幻觉抑制。

- [x] 每次理解自动生成完整 report.md，SQLite 保存来源链接、报告正文/路径、视频缓存路径及结果；网页展示报告并提供持久化历史入口。

- [x] 输入单个作品链接后下载视频，独立配置本地 Ollama/视觉模型，完整音频转写并按时间抽帧分析。
- [x] 展示形态/主题分类、摘要、核心要点、可跳转时间线和完整转写；保存任务进度、错误及报告，并恢复页面监控、标记服务重启中断。
