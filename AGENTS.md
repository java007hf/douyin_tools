# Agent Notes

## Project Files

Keep the repository root clean. The root should contain only source code and documentation, such as:

- `douyin_work_urls.py`
- `requirements.txt`
- `README.md`
- `AGENTS.md`

## Cache And Test Artifacts

Put all local test files, temporary browser profiles, downloaded media, scratch outputs, and generated URL lists under `cache/`.

Examples:

```powershell
python douyin_work_urls.py "主页地址" -o cache\urls.txt
python douyin_work_urls.py --download "作品地址" --download-dir cache\downloads
python douyin_work_urls.py "主页地址" --user-data-dir cache\.douyin-browser -o cache\urls.txt
```

Do not create `downloads_test*`, `urls.txt`, `__pycache__`, or browser profile folders in the project root.
