import json
import sys
from pathlib import Path


def load_json(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8"
    return json.loads(raw.decode(encoding)), encoding


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("cache/extension_result.json")
    data, encoding = load_json(path)

    print("file:", path)
    print("encoding:", encoding)
    print("top ok:", data.get("ok"))

    result = data.get("result") or {}
    print("extension ok:", result.get("ok"))
    print("extension error:", result.get("error"))

    body = result.get("data") or {}
    print("workId:", body.get("workId"))
    print("version:", body.get("version"))
    print("version_warning:", data.get("version_warning"))
    print("readiness:", json.dumps(body.get("readiness"), ensure_ascii=False))
    print("usedCapturedCommentList:", body.get("usedCapturedCommentList"))
    print("capturedCount:", body.get("capturedCount"))

    for name, item in (body.get("result") or {}).items():
        print(f"\nACTION {name}")
        print(json.dumps(item, ensure_ascii=False, indent=2)[:8000])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
