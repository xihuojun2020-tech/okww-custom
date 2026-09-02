"""Audit one character from a pinned upstream Git commit without touching production files."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class SourceInspection:
    class_name: str
    imports: tuple[str, ...]
    labels: tuple[str, ...]
    self_calls: tuple[str, ...]
    task_calls: tuple[str, ...]


@dataclass(frozen=True)
class AllocatedIds:
    image_ids: tuple[int, ...]
    category_ids: tuple[int, ...]
    annotation_ids: tuple[int, ...]


@dataclass(frozen=True)
class CanvasPlan:
    upstream_file: str
    output_file: str
    width: int
    height: int
    annotations: tuple[dict, ...]


@dataclass(frozen=True)
class CocoPortPlan:
    fragment: dict
    canvases: tuple[CanvasPlan, ...]


class GitObjectReader:
    def __init__(self, repository: Path):
        self.repository = repository.resolve()

    def _run(self, *args: str) -> bytes:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repository,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result.stdout

    def read_bytes(self, ref: str, path: str) -> bytes:
        return self._run("show", f"{ref}:{path}")

    def read_text(self, ref: str, path: str) -> str:
        return self.read_bytes(ref, path).decode("utf-8-sig")

    def list_files(self, ref: str) -> tuple[str, ...]:
        paths = self._run("ls-tree", "-r", "--name-only", ref).decode("utf-8").splitlines()
        return tuple(sorted(path.replace("\\", "/") for path in paths))


def inspect_character_source(source: str) -> SourceInspection:
    tree = ast.parse(source)
    imports: set[str] = set()
    labels: set[str] = set()
    self_calls: set[str] = set()
    task_calls: set[str] = set()
    class_name = ""

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and not class_name:
            class_name = node.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "Labels":
                labels.add(node.attr)
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if isinstance(owner, ast.Name) and owner.id == "self":
            self_calls.add(node.func.attr)
        elif (
            isinstance(owner, ast.Attribute)
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "self"
            and owner.attr == "task"
        ):
            task_calls.add(node.func.attr)

    if not class_name:
        raise ValueError("character source does not define a class")
    return SourceInspection(
        class_name=class_name,
        imports=tuple(sorted(imports)),
        labels=tuple(sorted(labels)),
        self_calls=tuple(sorted(self_calls)),
        task_calls=tuple(sorted(task_calls)),
    )


def allocate_ids(
    local_coco: dict,
    image_count: int,
    category_count: int,
    annotation_count: int,
) -> AllocatedIds:
    def sequence(items: list[dict], count: int) -> tuple[int, ...]:
        start = max((int(item["id"]) for item in items), default=0) + 1
        return tuple(range(start, start + count))

    return AllocatedIds(
        image_ids=sequence(local_coco.get("images", []), image_count),
        category_ids=sequence(local_coco.get("categories", []), category_count),
        annotation_ids=sequence(local_coco.get("annotations", []), annotation_count),
    )


def build_coco_port_plan(
    character: str,
    labels: tuple[str, ...],
    local_coco: dict,
    upstream_coco: dict,
) -> CocoPortPlan:
    categories_by_name = {item["name"]: item for item in upstream_coco.get("categories", [])}
    missing = [label for label in labels if label not in categories_by_name]
    if missing:
        raise ValueError(f"missing upstream labels: {', '.join(missing)}")

    selected_categories = [categories_by_name[label] for label in labels]
    category_ids = {int(item["id"]) for item in selected_categories}
    selected_annotations = sorted(
        (
            annotation
            for annotation in upstream_coco.get("annotations", [])
            if int(annotation["category_id"]) in category_ids
        ),
        key=lambda item: int(item["id"]),
    )
    count_by_category = {
        category_id: sum(int(annotation["category_id"]) == category_id for annotation in selected_annotations)
        for category_id in category_ids
    }
    invalid = [
        item["name"] for item in selected_categories
        if count_by_category[int(item["id"])] != 1
    ]
    if invalid:
        raise ValueError(f"labels require exactly one annotation: {', '.join(sorted(invalid))}")

    images_by_id = {int(item["id"]): item for item in upstream_coco.get("images", [])}
    selected_image_ids = sorted({int(item["image_id"]) for item in selected_annotations})
    missing_images = [image_id for image_id in selected_image_ids if image_id not in images_by_id]
    if missing_images:
        raise ValueError(f"missing upstream image records: {missing_images}")

    allocated = allocate_ids(
        local_coco,
        image_count=len(selected_image_ids),
        category_count=len(selected_categories),
        annotation_count=len(selected_annotations),
    )
    image_id_map = dict(zip(selected_image_ids, allocated.image_ids))
    category_id_map = {
        int(category["id"]): new_id
        for category, new_id in zip(selected_categories, allocated.category_ids)
    }
    slug = re.sub(r"[^a-z0-9]+", "_", character.lower()).strip("_")

    fragment_images = []
    canvases = []
    for upstream_image_id in selected_image_ids:
        image = images_by_id[upstream_image_id]
        width, height = int(image["width"]), int(image["height"])
        if (width, height) != (3840, 2160):
            raise ValueError(
                f"unsupported upstream template canvas {image['file_name']}: {width}x{height}"
            )
        stem = Path(image["file_name"]).stem
        output_file = f"images/characters/{slug}_source_{stem}.png"
        fragment_images.append({
            "id": image_id_map[upstream_image_id],
            "file_name": output_file,
            "width": width,
            "height": height,
        })
        canvases.append(CanvasPlan(
            upstream_file=image["file_name"],
            output_file=output_file,
            width=width,
            height=height,
            annotations=(),
        ))

    fragment_categories = []
    for category in selected_categories:
        fragment_categories.append({
            "id": category_id_map[int(category["id"])],
            "name": category["name"],
            "supercategory": category.get("supercategory", ""),
        })

    fragment_annotations = []
    for annotation, new_id in zip(selected_annotations, allocated.annotation_ids):
        fragment_annotations.append({
            "id": new_id,
            "image_id": image_id_map[int(annotation["image_id"])],
            "category_id": category_id_map[int(annotation["category_id"])],
            "bbox": list(annotation["bbox"]),
            "area": annotation.get("area", annotation["bbox"][2] * annotation["bbox"][3]),
            "iscrowd": annotation.get("iscrowd", 0),
        })

    canvas_by_image_id = {
        image["id"]: index for index, image in enumerate(fragment_images)
    }
    for image_id, index in canvas_by_image_id.items():
        canvas = canvases[index]
        canvases[index] = CanvasPlan(
            upstream_file=canvas.upstream_file,
            output_file=canvas.output_file,
            width=canvas.width,
            height=canvas.height,
            annotations=tuple(
                annotation for annotation in fragment_annotations
                if annotation["image_id"] == image_id
            ),
        )

    return CocoPortPlan(
        fragment={
            "images": fragment_images,
            "categories": fragment_categories,
            "annotations": fragment_annotations,
        },
        canvases=tuple(canvases),
    )


def prepare_output_directory(output: Path) -> Path:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    return output


def write_reports(output: Path, report: dict) -> None:
    output.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    (output / "report.json").write_text(rendered, encoding="utf-8")
    markdown = (
        f"# {report.get('character', 'Character')} upstream port audit\n\n"
        "```json\n"
        f"{rendered}"
        "```\n"
    )
    (output / "report.md").write_text(markdown, encoding="utf-8")


def _class_methods(source: str) -> set[str]:
    return {
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _scan_references(
    reader: GitObjectReader,
    ref: str,
    paths: tuple[str, ...],
    source_path: str,
    needles: tuple[str, ...],
) -> list[str]:
    results: list[str] = []
    routine_files = {"src/Labels.py", "src/char/CharFactory.py"}
    for path in paths:
        if (
            path == source_path
            or path in routine_files
            or path.startswith("tests/")
            or not path.endswith(".py")
        ):
            continue
        text = reader.read_text(ref, path)
        for line_number, line in enumerate(text.splitlines(), start=1):
            if any(needle in line for needle in needles):
                results.append(f"{path}:{line_number}: {line.strip()}")
    return sorted(results)


def render_canvases(
    reader: GitObjectReader,
    ref: str,
    plan: CocoPortPlan,
    output: Path,
) -> None:
    template_dir = output / "templates"
    template_dir.mkdir(parents=True, exist_ok=True)
    for canvas_plan in plan.canvases:
        encoded = np.frombuffer(reader.read_bytes(ref, f"assets/{canvas_plan.upstream_file}"), dtype=np.uint8)
        source = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if source is None or source.shape[:2] != (canvas_plan.height, canvas_plan.width):
            raise ValueError(f"invalid upstream template image: {canvas_plan.upstream_file}")
        canvas = np.zeros_like(source)
        for annotation in canvas_plan.annotations:
            x, y, width, height = (int(round(value)) for value in annotation["bbox"])
            if x < 0 or y < 0 or x + width > source.shape[1] or y + height > source.shape[0]:
                raise ValueError(f"annotation outside source image: {annotation['bbox']}")
            canvas[y:y + height, x:x + width] = source[y:y + height, x:x + width]
        destination = template_dir / Path(canvas_plan.output_file).name
        if not cv2.imwrite(str(destination), canvas):
            raise OSError(f"failed to write template canvas: {destination}")


def build_report(
    repository: Path,
    reader: GitObjectReader,
    character: str,
    ref: str,
) -> tuple[dict, CocoPortPlan]:
    source_path = f"src/char/{character}.py"
    source = reader.read_text(ref, source_path)
    inspection = inspect_character_source(source)
    upstream_coco = json.loads(reader.read_text(ref, "assets/coco_annotations.json"))
    local_coco = json.loads((repository / "assets/coco_annotations.json").read_text(encoding="utf-8"))
    expected_label = f"char_{re.sub(r'[^a-z0-9]+', '_', character.lower()).strip('_')}"
    labels = tuple(sorted(set(inspection.labels) | {expected_label}))
    plan = build_coco_port_plan(character, labels, local_coco, upstream_coco)

    source_methods = _class_methods(source)
    base_methods = set()
    for path in ("src/char/BaseChar.py", "src/char/Healer.py"):
        candidate = repository / path
        if candidate.exists():
            base_methods.update(_class_methods(candidate.read_text(encoding="utf-8-sig")))
    task_methods = set()
    for path in (
        repository / "src/task/BaseCombatTask.py",
        repository / "src/task/BaseWWTask.py",
        repository / ".venv/Lib/site-packages/ok/task/task.py",
    ):
        if path.exists():
            task_methods.update(_class_methods(path.read_text(encoding="utf-8-sig")))
    paths = reader.list_files(ref)
    cross_references = _scan_references(
        reader,
        ref,
        paths,
        source_path,
        (character, expected_label),
    )
    report = {
        "character": character,
        "source_path": source_path,
        "upstream_ref": ref,
        "safe_findings": {
            "inspection": asdict(inspection),
            "labels": list(labels),
            "proposed_images": plan.fragment["images"],
            "proposed_categories": plan.fragment["categories"],
            "proposed_annotations": plan.fragment["annotations"],
        },
        "manual_review": {
            "cross_references": cross_references,
            "missing_base_methods": sorted(set(inspection.self_calls) - source_methods - base_methods),
            "missing_task_methods": sorted(set(inspection.task_calls) - task_methods),
        },
    }
    return report, plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("character", help="Python character class name, for example Qingxiao")
    parser.add_argument("--ref", required=True, help="Pinned Git commit already present locally")
    parser.add_argument("--repository", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    repository = args.repository.resolve()
    output = (args.output or repository / "build/character_ports" / args.character).resolve()
    prepare_output_directory(output)
    reader = GitObjectReader(repository)
    report, plan = build_report(repository, reader, args.character, args.ref)
    write_reports(output, report)
    (output / "coco_fragment.json").write_text(
        json.dumps(plan.fragment, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    render_canvases(reader, args.ref, plan, output)
    print(output)


if __name__ == "__main__":
    main()
