"""Fetch the two reviewed data-structures exercise sources into vendor/.

Only text question files are mirrored. Runtime question-bank generation is then
fully local and does not depend on GitHub availability.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"
HEADERS = {"User-Agent": "StudyShip-question-importer"}
OPENDSA_TOPICS = {
    "AlgAnal", "Background", "Binary", "Graph", "Hashing", "Indexing",
    "List", "Pointers", "RecurTutor", "Searching", "Sorting",
}


def get_bytes(url: str, attempts: int = 4) -> bytes:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read()
        except Exception as exc:  # network retry boundary
            last = exc
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"download failed: {url}: {last}")


def api_json(url: str) -> dict:
    return json.loads(get_bytes(url).decode("utf-8"))


def raw_url(repo: str, branch: str, path: str) -> str:
    encoded = "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{encoded}"


def download_many(repo: str, branch: str, paths: list[str], target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)

    def one(path: str) -> str:
        output = target / Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(get_bytes(raw_url(repo, branch, path)))
        return path

    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(one, path) for path in paths]
        for i, future in enumerate(as_completed(futures), 1):
            future.result()
            if i % 100 == 0 or i == len(futures):
                print(f"{repo}: {i}/{len(futures)}")


def main() -> None:
    opendsa_repo = "OpenDSA/OpenDSA"
    opendsa_branch = "master"
    opendsa_tree = api_json(
        f"https://api.github.com/repos/{opendsa_repo}/git/trees/{opendsa_branch}?recursive=1"
    )
    opendsa_paths = []
    for item in opendsa_tree["tree"]:
        parts = item["path"].split("/")
        if (item["type"] == "blob" and len(parts) >= 3 and parts[0] == "Exercises"
                and parts[1] in OPENDSA_TOPICS and parts[-1].lower().endswith(".html")):
            opendsa_paths.append(item["path"])
    opendsa_paths.extend(["MIT-license.txt"])
    download_many(opendsa_repo, opendsa_branch, sorted(opendsa_paths),
                  VENDOR / "OpenDSAExerciseBank")

    yan_repo = "kangjianwei/Data-Structure"
    yan_branch = "master"
    yan_tree = api_json(
        f"https://api.github.com/repos/{yan_repo}/git/trees/{yan_branch}?recursive=1"
    )
    yan_paths = [item["path"] for item in yan_tree["tree"]
                 if item["type"] == "blob"
                 and item["path"].startswith("习题解析/")
                 and item["path"].lower().endswith(".md")]
    yan_paths.append("README.md")
    download_many(yan_repo, yan_branch, sorted(yan_paths),
                  VENDOR / "YanweiminExerciseBank")

    manifest = {
        "opendsa": {
            "repo": opendsa_repo,
            "commit": opendsa_tree.get("sha", ""),
            "files": len(opendsa_paths) - 1,
            "topics": sorted(OPENDSA_TOPICS),
        },
        "yanweimin": {
            "repo": yan_repo,
            "commit": yan_tree.get("sha", ""),
            "files": len(yan_paths) - 1,
        },
    }
    output = VENDOR / "question_sources.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
