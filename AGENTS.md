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

## ComfyUI Integration

The video creator service integrates with a local ComfyUI instance through its HTTP API. Set `COMFYUI_URL` when ComfyUI is not on `http://127.0.0.1:8188`. Image generation currently uses the installed Flux workflow; `qwen` and `sd` are exposed in the UI but require corresponding models/workflows. Video generation selects `t2v`, `i2v`, or `r2v` from the supplied reference media. Configure API-format workflows with `COMFYUI_T2V_WORKFLOW`, `COMFYUI_I2V_WORKFLOW`, and `COMFYUI_R2V_WORKFLOW`.

## Current Todo Tracking

The canonical task details are in `todo.md`. Keep the checklist below synchronized with that file. When a task is completed, mark it as `[x]` in both files in the same change.

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

## Current Web Controls

The unified web app exposes three tabs in this order: Douyin Tool, AI Creation Tool, and Admin. The AI Creation Tool contains the `视频抽帧`, `生图`, and `生视频` views. Image/video generation parameters such as model, aspect ratio, and resolution belong to the generation form, not provider configuration.

The Admin tab is enabled by default and runs on port `8103`. Provider configuration only stores connection parameters for MiniMax and Seedance; credentials are redacted as `********` in public responses and empty credential fields preserve the stored value. The gateway defaults to `0.0.0.0` for LAN access. Use `run.bat` for the standard Windows startup, or `--no-admin` when a public-only gateway is required.

### Visual Model Configuration

- [ ] Reference the `C:\workspace\xiaozhi-esp32-server-benyl` console model settings and implement a visual model/Provider configuration page.
- [ ] Support H3 and Seedance cloud settings such as API URL, Token, API Key, model version, and defaults.
- [ ] Mask and securely store credentials; never expose them in frontend or ordinary task logs.
- [ ] Add configuration validation, connection testing, enable/disable, default model selection, and effective-state feedback.
- [ ] Keep model configuration separate from generation tasks; tasks reference a Provider configuration ID instead of storing secrets.
