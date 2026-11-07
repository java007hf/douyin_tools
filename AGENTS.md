# Agent Notes

## Project Files

Keep the repository root clean. The root should contain source code, committed utilities, extension source, and documentation only:

- `analyze_extension_result.py`
- `requirements.txt`
- `README.md`
- `AGENTS.md`
- `frontend/`
- `services/`

`store/` and `cache/` are ignored runtime directories, not committed source.

## Persistent Store

All durable application data belongs in `store/`. `cache/` is disposable and
must never be the only copy of credentials, databases, login state, history,
reports, reusable assets, models, or user-visible generated/downloaded media.

```text
store/
  core/understanding_queue.sqlite3 # Shared cross-process understanding admission
  models/whisper/                 # ASR model weights (Whisper large-v3-turbo)
  douyin/
    understanding_history.sqlite3 # Understanding records and deletion markers
    web_jobs/                     # Persistent web task status JSON
    web_downloads/
      understanding/<task-id>/    # Video, report.md, transcript, frames, trace
      mentions/                   # Mention DB, drafts, reports and source media
      ...                        # User downloads
    web_url_lists/                # Saved creator collection results
    .douyin-browser*/             # Reusable browser login profiles
    legacy/                       # Preserved older standalone profiles/downloads
  video_creator/
    provider_configs.json        # Admin Provider/LLM credentials and settings
    image_route_state.sqlite3    # Publication image daily-quota routing state
    storage.json                 # Media storage configuration
    cloudinary.json              # Legacy Cloudinary configuration, if present
    assets.db                    # Creation task/feed records
    reference_library/           # library.db, asset JSON and original files
    ai_video_jobs/<task-id>/      # Workflow traces, input, references and outputs
    generation_jobs/<task-id>/    # Generation inputs, plans and outputs
    frame_jobs/<task-id>/         # User frame extraction results
cache/
  ...                            # Tests, diagnostics, scratch files and logs
```

Use `services/core/storage.py` to resolve persistent paths. The default store
is `<repository>/store`; `DOUYIN_STORE_DIR` or the gateway `--store-dir` can
override it. Tab service `--store-dir` denotes that service's subdirectory.
`DOUYIN_ASR_MODEL_DIR` can override the ASR weight directory independently.
Legacy persistent data in `cache/` is migrated before gateway child services
start; writers must be stopped first. Migration must not overwrite an existing
destination. Keep API media URLs and database relationships stable when moving
files; retain portable relative artifact names and update historical absolute
paths. Back up `store/`; do not commit it or include credentials in logs.

## Cache And Test Artifacts

Put local test files, temporary test browser profiles/media, scratch outputs,
test URL lists, copied request payloads, screenshots, and debug logs under
`cache/`. User downloads, reusable login profiles and saved results use `store/`.

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
node --check services\douyin\chrome_extension\mention_requests.js
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
- Keep persistent Workflow task files under a task-specific directory inside `store/video_creator/`; use `cache/` only for disposable scratch work.
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
- If a task fails, stalls, or produces an invalid artifact, immediately inspect the complete parent node error, child task error, provider request ID when available, and ComfyUI validation message under the task directory in `store/video_creator/`.
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

- [x] 实现 @我通知监听、首次基线、账号/评论持久去重、视频分析、原评论自动回复及草稿模式，并提供停止和任务状态。
- [x] 将 @我通知采集改为页面启动时捕获真实 fetch/Request/XHR 请求，保留原读取请求模板，移除 DOM/React 扫描，并展示脱敏请求状态、校验新鲜度和当前账号。
- [x] 让 run.bat 默认自动开启新 @通知监听及回复，扩展自动打开/复用个人主页并准备通知读取请求；支持等待配置重试、停止及有间隔限制的刷新恢复。
- [ ] 在已登录 Chrome 中完成 @我通知与原评论回复的单条端到端验收，核实真实通知字段及嵌套评论回复参数。
- [x] 用 Jessica 的单条顶层 @评论完成真实通知、下载、视频理解与原评论回复验收；支持 notice_list_v2[].at 和单条基线记录测试，嵌套评论仍待真实验收。
- [x] 将 @评论的视频分析纳入视频解析历史，区分来源、标注回复用户名及结果，并补入已有分析记录。
- [x] 使用持久化 FIFO 队列串行处理 @消息，展示队列数量及位置，重启后验证账号再恢复未开始任务。
- [x] 将 @自动回复限定为视频内容摘要，不向回复模型传入提及评论文字。
- [x] 升级 @处理为主 Agent 意图识别与独立视频理解/摘要问答 MCP，保留队列与确定性发送，增加工具轨迹和分析缓存复用。
- [x] 用“@Benyl 总结一下”完成主 Agent + MCP 摘要路径线上验收，确认原评论回复及历史保存。
- [x] 在 @消息入队时即创建历史，持续更新排队位置、处理阶段和最终状态，并自动刷新历史列表。

- [x] 对比 small、medium、large-v3、large-v3-turbo 和 SenseVoice，保存完整实测报告，配置选用 turbo 并开启词级对齐和静音幻觉抑制。

- [x] 每次理解自动生成完整 report.md，SQLite 保存来源链接、报告正文/路径、视频缓存路径及结果；网页展示报告并提供持久化历史入口。

- [x] 输入单个作品链接后下载视频，独立配置本地 Ollama/视觉模型，完整音频转写并按时间抽帧分析。
- [x] 展示形态/主题分类、摘要、核心要点、可跳转时间线和完整转写；保存任务进度、错误及报告，并恢复页面监控、标记服务重启中断。

### 持久存储

- [x] 将持久配置、数据库、模型、历史报告与媒体统一迁到 store/，cache/ 仅保存临时文件，并记录目录与迁移规则。

- [x] 支持图文作品理解：分析全部原图与可选配音，保留图片顺序、报告及历史，并展示原图和配音播放器。


### 豆包 Mock 工程接入

- [x] 在控制台注册豆包 Mock Provider，并允许 AI视频默认生图路由选择该配置；复用独立网页登录凭据。
- [x] 完成网页表单双参考图上传、生图和持久化结果的工程 HTTP 端到端验收。

- [x] 接入豆包 Mock T2V 与单图 I2V、网页参考图和 AI视频独立路由，并完成独立脚本及工程端到端生成验收。

- [x] AI视频 Agent 独立支持 Ollama 原生接口、可配置上下文窗口和无 Key 本地调用，保留旧 OpenAI 兼容配置。

- [x] 完成 Ollama 规划与豆包 Mock 新角色/场景/道具、参考首帧和四镜头视频验收；自动清理自身上传草稿附件，并统一混合音轨采样率后合成。

- [x] 用指定人像准备豆包 Mock 蜘蛛精参考，完成 Ollama 九个剧情候选及提示词对比；去除单次剧情硬编码，按需追加喜剧机制规则，并保留原稿与人工复盘。
- [x] 接入无人工代写的喜剧候选生成、原文证据评审及最多一轮重写，记录节点阶段与完整原稿；用 Ollama 完成两轮失败验收及评审边界单条复测，未通过时停止素材生成。
- [x] 为 AI视频接入 Ollama 思考开关/低强度、输出预算和模型默认采样，分离思考计数与最终 JSON；完成接口及同提示词开关实测，保留预算耗尽和超时记录，不将未输出的剧情误报为质量改善。
- [x] 失败的 @评论分析重试：完成服务重启、42 项测试及三条失败案例验收；重试独立目录且仅生成草稿，验收后清理旧失败历史。优先较小且含音轨的视频源，采用 20 分钟超时、最多 20 帧和语音分段归纳；支持媒体/配置校验的断点恢复及模型进程退出后的一次重试。

- [x] 修复再次失败的两条 @视频分析：流式下载避免浏览器大响应缓冲，保留系统代理；采集后释放浏览器、优先完整 MP4、限制下载阶段总时限及解码线程；48 项测试已通过；密集时间戳按30秒合并，文本归纳8K、最终摘要16K，已完成 53 分钟与 21 分钟视频真实重试验收，报告、完整转写和20帧均可访问；仅保存回复草稿，已清理两条旧失败历史及中途恢复记录。

- [x] 用17秒HEVC失败案例完成解码线程限制的线上验收：复用原媒体后抽帧、转写、画面理解及问答均成功，报告可访问；回复仅保存草稿，验收后删除旧失败历史。

- [x] 完成重复模型故障的P0治理与四条真实失败案例验收：纯@/固定摘要跳过意图模型，复杂意图4K/256输出；GPU/内存/进程错误持久化冷却并进行真实推理恢复探测，限制分析重试并禁止自动重发；55项测试通过，已重启并完成约8/51/6/10分钟四条线上草稿验收；意图路由均约1毫秒，报告及媒体可访问，旧失败历史已清理。

- [ ] 为抖音理解、AI视频及生成任务建立跨进程GPU/内存准入与资源调度，验证外部进程占用时的等待和恢复。

- [ ] 核实并统一Ollama服务实例、模型版本与启动参数，补齐GPU故障快照，并进行连续运行与故障注入回归验收。

- [x] 将视频理解最终摘要改为作者直接讲述的自媒体成稿口吻：独立AUTHOR_SYSTEM_PROMPT约束标题/摘要/观点/章节，处理限制单独保留；禁止虚构个人经历，保留事实与不确定性，版本化成稿缓存及评论口吻；63项测试和已有内容真实试写通过，空闲重启启用并保留原@监听设置。

### YouTube 素材工作台

- [x] 新增独立 YouTube 工作台、单地址下载、复用视频理解及持久化报告历史，不包含 @监听或回复。

- [x] 将 YouTube 理解历史合并到视频理解页，统一历史详情与删除交互；增加持久化 FIFO 串行队列、排队位置、连续提交及重启恢复。

- [x] 抖音手动理解、@理解 MCP、YouTube 理解及理解模型调用/卸载共用跨进程 FIFO 准入队列，展示跨平台排队状态并回收退出进程的占用。

### 分平台内容生成与发布

- [x] 发布元数据超限时复用本地LLM已选定的短封面标题，保留正文和卡片；支持脱敏原始输出追踪及经完整校验的缓存成稿复用，记录来源路径。未完成抖音本人验证时暂缓新的自动发送，手动重试可继续原生验证；区分页面加载和真实登录提示。

- [x] 隔离小红书长卡与抖音短卡提示词，超长抖音卡片增加单页有界LLM修正；为发布改写保存脱敏逐次提示词、原始输出与耗时，供失败根因检查；识别抖音发布后的本人短信验证并保留窗口等待用户完成，不读取或代填验证码。

- [x] 抖音发布终态统一成功或失败：缺少回执时自动核对一次作品记录，未确认则失败并提供复用现有文案/图片的重新发送按钮；迁移历史待核实状态，不自动重发，保留不确定提交证据，小红书核对规则不变。

- [x] 将发布生成防重从整条历史改为历史+平台：抖音与小红书可独立入队，共享模型队列仍串行执行；同平台生成/发送/待核实继续拦截。登录操作收纳为按需账号授权，未实时验证时不宣称已登录；增加跨平台及待核实防重回归。

- [x] 在平台内容顶部固定展示各平台最新状态与重新生成入口；同记录任务运行时明确解释禁用原因，并验证真实历史页小红书入口可见。

- [x] 按平台而非全局批次展开最新发布版本：单独重生成抖音后，小红书最新版本及重试入口仍可见；生成期间暂时禁用，结束后恢复，历史版本保留，并覆盖双平台失败后的回归测试。

- [x] 为已有平台版本增加重新生成内容及重新生成并发布入口：复用当前理解LLM和最新提示词生成独立版本，保留原稿/其他平台回执；口吻失败禁用旧稿直发，持续刷新生成及发送状态，重试复用请求标识，并覆盖前端流程与版本级防重测试。

- [x] 统一视频理解与平台改写的直接讲述规则：补卡、扩写、压缩共享口吻约束；摘要/观点/章节及发布正文/封面/卡片检测旁观转述，一次LLM修复后仍不符即停止出图，旧草稿发送前拦截；保留具名引用、他人案例与不确定性，不机械替换人称。

- [x] 在理解历史增加发布入口，多选小红书、微信公众号、抖音图文，并保存是否自动发布；当前平台统一显示待接入，不执行发送。
- [x] 按独立平台风格规则生成正文、主题概念插画卡片和配乐建议，在原历史中保存版本、查看状态、预览及下载素材包。
- [x] 分平台配图优先使用 Doubao Mock，明确日额度用尽后持久化切换本地 Flux / Qwen，次日恢复优先尝试；保存原图、排版图、工作流与任务轨迹。
- [x] 独立生成平台封面方案与三个标题候选，支持小红书白底红字、人物和场景等版式；图库照片优先、AI补缺，后台配置 Pixabay/Pexels 并保存作者、来源、许可和24小时搜索缓存。
- [x] 修复理解历史状态标签挤压标题的布局；增加豆包空图片响应的脱敏正文及事件诊断，并用已配置 Pixabay 为指定历史重新生成小红书，保留全部图片来源。
- [x] 重做小红书大图与内容密度版式：照片铺满画布宽度、按信息量自适应排版、正文补足观点解释并修复中文标点换行；同一历史用 Pixabay 完成六张图文验收，100项测试通过。
- [x] 发布内容按标题封面与正文内容分栏；图片及原图使用站内弹窗，支持上一张/下一张、方向键、Esc关闭与焦点恢复，完成实际页面交互验收。
- [x] 人物封面优先成年亚洲女性、高挑身形与精致自然容貌，将偏好写入平台风格、封面提示词与图库检索词，内页保持主题相关配图。
- [x] 接入小红书创作中心图文发送、独立持久登录、版本级发送锁、回执与结果核对；兼容新版自定义发布控件并等待上传完成，29项测试通过，当前六图笔记已取得真实发布ID，配乐尚未绑定。
- [x] 在理解详情页突出顶部发布按钮，并在平台内容标题旁增加发布入口，复用平台选择弹窗与理解完成状态。
- [ ] 接入各平台账号、真实配乐匹配与发布适配器，取得平台回执后标记内容已发布。

- [x] 小红书发布使用抖音与 YouTube 共用的持久化 FIFO 串行队列，显示排队位置，跨进程互斥并在关闭浏览器后释放；恢复未开始任务，提交结果不明不自动重发。

- [x] 小红书内页不足90字时自动调用AI定向扩写至110至180字，保留标题、配图和原资料边界；校验页面索引、完整性及长度，失败时限定一次整体修复。

- [x] 平台配图卡片不足时保留已有文案与封面，AI定向补齐缺少页面（小红书/抖音至少4张、公众号3张），补齐后继续字数扩写与完整校验。

- [x] 接入抖音创作者中心图文发布适配器：独立登录态、共用持久化FIFO队列、平台级版本防重、预填检查、回执与结果核对入口。
- [x] 完成抖音图文发布真实页面及单条实发验收：本地视频理解LLM改写、5张图库配图、20字标题与零宽字符兼容、完整上传检查，取得作品ID 7704583711324441882。

- [x] 分平台改写复用视频理解LLM，新增模型、平台风格文件及来源历史的脱敏追踪并在页面显示模型；抖音与小红书共用生成流程。

- [x] 小红书卡片正文为空、偏短或超过版式长度时统一调用AI定向补写/扩写/精简，覆盖封面正文并保留卡片元数据。

- [x] 抖音卡片正文超过80字时调用视频理解LLM定向压缩至50–70字，保留配图、标题及其他卡片，严格校验页面索引与长度，禁止直接截断。

- [x] 抖音图文发布强制按本地LLM配乐方案检索真实曲库、绑定歌曲并校验提交music_id及有效播放区间；未绑定即拦截，记录曲名/作者/音乐ID；完成真实页面及不发送请求验收。

- [x] 经明确确认保留原作并完成带配乐9:16图文单条实发：作品ID 7704657552637824299，Calm Piano音乐ID 7654899660881168385、60秒，完整正文与配乐参数校验通过并保存平台回执。

- [x] 对比指定抖音图文原图与正文，默认改为1080×1920竖版、大图与大字排版，图库与AI补图均支持9:16、数字单位不拆行；使用原生段落事件录入并在请求发出前校验完整正文，提供保留原作的独立重新排版版本，完成带配乐的不发送预检。

- [x] 抖音封面与内页关键文字避开顶部搜索、右侧操作及底部文案区域；采用黄白粗体描边与原文数字强调，全幅主题封面；图库照片按来源ID跨任务原子去重90天并导入既有配图使用记录，提供两条原文不变的排版预览。

- [x] 统一抖音、小红书、公众号封面三段结构（上方主标题、中间主题主视觉、下方补充文案），共享内容system prompt、生图分区要求和实际排版器；补充文案必填且不重复主标题，更新风格版本、三平台构图预览与跨链路分区测试。

- [x] 抖音提交前截取真实手机预览，与全部图卡交由项目视频理解视觉LLM通过共享FIFO质检；无法定位、模型/结论异常或视觉不合格则阻止发送并保存报告。内页文字上移、字号层级收敛，完整主图放入底部描述浮层上方；已用旧图和实际预览截图完成本地模型拦截实测，未重新发布。

- [x] 将封面策划与发布检查参考规则固化到本地生产链：视觉类型/焦点/配色/标题原文高亮词经校验传给生图及排版，关键词不拆行，逐文件验证最终尺寸；视觉检查后重新读取发布表单和上传状态，保持已授权发布及验证码边界，记录参考来源而不安装或运行第三方Skill。

- [x] 按信息量拆分图卡：小红书取消90字扩写下限，目标每页40至70字、上限100字，大图配短文且不缩成密集小字；本地LLM将超长内页拆为多个独立观点并各自策划配图，页数扩为小红书/抖音4至18张、公众号3至12张，保留封面、完整正文及其他页面，超限报错而不截断内容。

- [x] 保持已认可封面，内页改为照片主视觉与浅色阅读卡片轻叠：生活人文暖白/柔绿、财经科技纸白/灰蓝，图片下缘渐隐、标题语义换行且不缩字；三平台共用内页渲染器并保留手机安全区。更新本地LLM/生图构图规则，内页过滤纯通用人像搜词，沿用原文原图提供独立未发布试排。

- [x] 按确认的参考将内页改为整版背景排字，替代照片/文字分区和浅色独立卡片：图片连续铺满全画布、整体低对比蒙层，标题与短文直接排在背景上；本地LLM、配图画幅与构图提示词同步更新，保持封面及单页信息密度规则，提供单张未发布试排。

- [x] 将内页背景审美统一为高雅克制的风景、成年女性、生活与阅读等场景，AI生图及图库查找共用；封面按人物/非人物自适应紧邻标题组（人物上方、非人物居中），移除上下深色蒙层，质检规则同步适配。

- [x] 用指定6f7cdfd3记录完成本地LLM十页草稿重新生成及背景定向修正：保留原始LLM文案溯源、统一风景/成年女性/阅读/生活背景，图库排除卫浴、马戏团等不适合作为高雅背景的元数据；10张PNG、ZIP与发布静态预检通过，未发布。

- [x] 修正通用背景审美覆盖选题的问题：财经主题优先使用金融市场下跌、交易屏幕及相关半导体产业背景，强制覆盖风景/人物/家居类型；移除财经图表的错误排除词，保留克制排字，并为指定记录创建不发布的财经配图修正版。

- [x] 财经图库语义校验拒绝bear动物、wafer零食和普通market等同词误匹配；完成指定记录10张财经/芯片背景草稿修复，保留6张已完成的生成/图库素材及本记录4张核实金融素材来源，静态校验、主题目视复核通过，未发布。

- [x] 豆包Mock发布配图下载后、排字前裁除底部5%水印带，持久保留原始返回图并记录原图/处理尺寸与AI来源；不处理图库或本地生图，不重复裁切，不改变最终平台图卡尺寸；原图备份、裁切及真实适配器接入路径测试通过。

- [x] 内页背景蒙层由约74%减为33%，保留约67%背景细节；抖音标题96px、正文68px为默认，按阅读区域适配黑白文字与轻描边，只允许极小幅字号调整并避免末行孤字。已对指定财经10页生成新排版草稿，保持封面、原文原图和发布状态不变，尺寸/ZIP/静态发送校验通过。

- [x] 内页改用实心粗体黑/黄正文与红/黄标题，逐行按背景亮度取色，降低白色蒙层至32/255并减弱额外模糊，保留约87%照片贡献；指定财经十页已生成独立未发布排版版本，封面及原文原图不变，图片/ZIP/发送静态校验及53项发布测试通过。

- [x] 同一作品全部内页固定一套文字配色，默认红色标题/黄色正文，也支持整套黄色；取消按背景或行变色，统一描边。已重新排版指定财经十页草稿并核验所有内页颜色、封面及原文不变，未发布。

- [x] 小红书内页按确认参考独立为上方大图、下方白底黑字：图片约50%至60%，黑色粗体标题/深灰正文，字号固定并按信息量拆页；内容system prompt、拆页/补卡提示词和生图要求按平台区分，不沿用抖音整版背景红黄字，封面独立保留。
