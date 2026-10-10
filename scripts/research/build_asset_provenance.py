"""Inventory local assets against one public upstream Git tree without downloading media.

Run with .venv/Scripts/python.exe scripts/research/build_asset_provenance.py.
"""

import hashlib
import json
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM_REPO = "ok-oldking/ok-wuthering-waves"
UPSTREAM_COMMIT = "b210632a251371cc0bbb1d0e28ce16ff35657824"
TREE_URL = f"https://api.github.com/repos/{UPSTREAM_REPO}/git/trees/{UPSTREAM_COMMIT}?recursive=1"
JSON_PATH = ROOT / "docs/research/2026-10-10-framework-asset-provenance.json"
MARKDOWN_PATH = ROOT / "docs/research/2026-10-10-framework-asset-provenance.md"


def local_hashes(path):
    size = path.stat().st_size
    git_sha1 = hashlib.sha1(f"blob {size}\0".encode())
    sha256 = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            git_sha1.update(chunk)
            sha256.update(chunk)
    return size, git_sha1.hexdigest(), sha256.hexdigest()


def role(path):
    if path == "assets/coco_annotations.json":
        return "coco-annotations"
    if path.endswith(".onnx"):
        return "model"
    if path.startswith("tests/images/"):
        return "offline-fixture" if path.endswith(".png") else "fixture-metadata"
    if path.startswith("assets/materials/templates/"):
        return "material-template"
    if path.endswith(".png"):
        return "runtime-image"
    return "asset-metadata"


def main():
    request = Request(TREE_URL, headers={"User-Agent": "okww-asset-provenance-research", "Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=60) as response:
        tree = json.load(response)
    if tree["sha"] != UPSTREAM_COMMIT or tree["truncated"]:
        raise RuntimeError("Upstream tree is incomplete or is not the requested commit")
    blobs = [entry for entry in tree["tree"] if entry["type"] == "blob"]
    by_path = {entry["path"]: entry for entry in blobs}
    by_hash = {}
    for entry in blobs:
        by_hash.setdefault(entry["sha"], []).append(entry["path"])

    files = []
    for folder in (ROOT / "assets", ROOT / "tests/images"):
        for path in sorted(item for item in folder.rglob("*") if item.is_file()):
            relative = path.relative_to(ROOT).as_posix()
            size, git_sha1, sha256 = local_hashes(path)
            same_path = by_path.get(relative)
            exact_paths = by_hash.get(git_sha1, [])
            if same_path and same_path["sha"] == git_sha1:
                status = "upstream-identical"
                match_path = relative
            elif exact_paths:
                status = "upstream-identical"
                match_path = exact_paths[0]
            elif same_path:
                status = "upstream-modified"
                match_path = relative
            else:
                status = "custom-or-unverified"
                match_path = None
            upstream = by_path.get(match_path) if match_path else None
            files.append({
                "path": relative,
                "role": role(relative),
                "size_bytes": size,
                "sha256": sha256,
                "git_blob_sha1": git_sha1,
                "status": status,
                "upstream_path": match_path,
                "upstream_size_bytes": upstream["size"] if upstream else None,
                "upstream_git_blob_sha1": upstream["sha"] if upstream else None,
            })

    coco = json.loads((ROOT / "assets/coco_annotations.json").read_text(encoding="utf-8-sig"))
    image_refs = sorted({item["file_name"] for item in coco["images"]})
    coco_summary = {
        "image_records": len(coco["images"]),
        "unique_image_references": len(image_refs),
        "referenced_images_present": sum((ROOT / "assets" / name).is_file() for name in image_refs),
        "annotation_records": len(coco["annotations"]),
        "category_records": len(coco["categories"]),
        "note": "COCO records describe image regions and labels; crops/templates derived from game frames retain source provenance. This annotation file and the ONNX model are separate inventory items. COCO license metadata does not establish ownership of game pixels or model weights.",
    }
    counts = Counter(item["status"] for item in files)
    roles = Counter(item["role"] for item in files)
    fixture_groups = Counter(item["path"].split("/")[2] if len(item["path"].split("/")) > 3 else "root" for item in files if item["role"] == "offline-fixture")
    report = {
        "scope": ["assets", "tests/images"],
        "upstream_repository": UPSTREAM_REPO,
        "upstream_commit": UPSTREAM_COMMIT,
        "upstream_tree_url": TREE_URL,
        "comparison": "Git blob SHA-1 compares exact bytes; SHA-256 records local bytes. Matching a blob at another upstream path also counts as upstream-identical. A differing blob at the same path is upstream-modified. Missing upstream matches are custom-or-unverified, not proof of original authorship or license.",
        "summary": {"files": len(files), "status": dict(sorted(counts.items())), "roles": dict(sorted(roles.items())), "offline_fixture_groups": dict(sorted(fixture_groups.items()))},
        "coco": coco_summary,
        "files": files,
    }
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Framework asset provenance and offline fixtures",
        "",
        f"Compared `{len(files)}` local files under `assets/` and `tests/images/` with the public [{UPSTREAM_REPO} commit `{UPSTREAM_COMMIT[:12]}`](https://github.com/{UPSTREAM_REPO}/tree/{UPSTREAM_COMMIT}). The upstream Git tree was complete. This script downloaded tree metadata only, no remote media.",
        "",
        "## Meaning of status",
        "",
        "`upstream-identical` means the local Git blob hash exists in that commit (possibly at another path). `upstream-modified` means the same path exists but the bytes differ. `custom-or-unverified` means no matching upstream blob was found; it does **not** establish ownership or permission to reuse. File size and local SHA-256 are in the JSON inventory. Asset replacement still needs source and license review.",
        "",
        "## Counts and migration fixtures",
        "",
        "| Status | Files |",
        "| --- | ---: |",
        *[f"| {key} | {value} |" for key, value in sorted(counts.items())],
        "",
        f"There are {roles['offline-fixture']} PNG screenshots under `tests/images/` available for offline replay. They cover: " + ", ".join(f"`{key}` ({value})" for key, value in sorted(fixture_groups.items())) + ". Availability means static image tests can read them; this inventory did not execute those tests or prove live-game behavior.",
        "",
        "The `tests/images/daily_followup/README.md` and `tests/images/daily_recovery/README.md` identify reviewed diagnostic ZIP sources and masking of account identifiers. Other groups include metadata or preparation scripts in the repository, but a missing explicit source record remains unverified.",
        "",
        "## COCO annotations, derived crops, and model",
        "",
        f"`assets/coco_annotations.json` contains {coco_summary['annotation_records']} annotation records, {coco_summary['category_records']} categories, and {coco_summary['image_records']} image records ({coco_summary['unique_image_references']} unique references; {coco_summary['referenced_images_present']} currently resolve under `assets/`). COCO coordinates and category labels are annotations, while template PNGs cut from source frames are derivatives of those frames. Neither a new crop nor a changed COCO JSON automatically makes the source pixels original work. `assets/echo_model/echo.onnx` is a separate model artifact whose weights require their own provenance assessment. The COCO `licenses` field and exporter metadata do not settle rights in source images or model weights.",
        "",
        "## Per-file comparison",
        "",
        "The JSON inventory carries full SHA-256, Git blob SHA-1, byte sizes and upstream match information for every row.",
        "",
        "| Local path | Role | Status | Bytes | Upstream path |",
        "| --- | --- | --- | ---: | --- |",
        *[f"| `{item['path']}` | {item['role']} | {item['status']} | {item['size_bytes']} | `{item['upstream_path']}` |" if item["upstream_path"] else f"| `{item['path']}` | {item['role']} | {item['status']} | {item['size_bytes']} | — |" for item in files],
        "",
        "Regenerate with `.\\.venv\\Scripts\\python.exe scripts/research/build_asset_provenance.py` from the repository root. The script only reads local asset and fixture files and the fixed public GitHub tree API; it writes these two research files.",
        "",
    ]
    MARKDOWN_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {JSON_PATH.relative_to(ROOT)} and {MARKDOWN_PATH.relative_to(ROOT)} ({len(files)} files)")


if __name__ == "__main__":
    main()
