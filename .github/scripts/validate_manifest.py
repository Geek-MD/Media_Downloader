import json
import sys
import os

def validate_file(path: str, required_keys: list[str]) -> None:
    if not os.path.exists(path):
        print(f"::error file={path}::❌ {path} not found")
        sys.exit(1)

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"::error file={path},line={e.lineno},col={e.colno}::❌ Failed to parse {path}: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"::error file={path}::❌ Failed to load {path}: {e}")
        sys.exit(1)

    missing = [k for k in required_keys if k not in data]
    if missing:
        print(f"::error file={path}::❌ {path} is missing keys: {missing}")
        sys.exit(1)

    print(f"✅ {path} passed validation.")

if __name__ == "__main__":
    validate_file("custom_components/media_downloader/manifest.json", [
        "domain", "name", "codeowners", "version"
    ])
    validate_file("hacs.json", [
        "name", "content_in_root", "domains", "category"
    ])
