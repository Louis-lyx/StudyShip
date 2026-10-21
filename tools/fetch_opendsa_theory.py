from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.theory import CDN_ROOT, required_modules  # noqa: E402


def main() -> int:
    target = ROOT / "vendor" / "OpenDSA" / "RST" / "en"
    ok = failed = 0
    for index, module in enumerate(required_modules(), 1):
        path = target / f"{module}.rst"
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{CDN_ROOT}/{module}.rst"
        try:
            with urllib.request.urlopen(url, timeout=45) as response:
                path.write_bytes(response.read())
            ok += 1
            print(f"[{index:02}/{len(required_modules())}] OK   {module}")
        except Exception as exc:
            failed += 1
            print(f"[{index:02}/{len(required_modules())}] MISS {module}: {exc}")
    print(f"OpenDSA theory fetch complete: {ok} files, {failed} missing")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
