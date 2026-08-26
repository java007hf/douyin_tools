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

The Chrome extension version is defined only in `services/douyin/chrome_extension/manifest.json`; Python and JavaScript read it at runtime.

When changing extension bridge behavior, update all matching version references together:

- `services/douyin/chrome_extension/manifest.json`
- `services/douyin/chrome_extension/background.js`
- `services/douyin/chrome_extension/content.js`
- `services/douyin/chrome_extension/injected.js`
- `services/douyin/service.py` expected extension version warning
- `README.md`

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
