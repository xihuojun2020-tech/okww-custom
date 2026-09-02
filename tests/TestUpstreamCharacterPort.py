import json
import tempfile
import unittest
from pathlib import Path

from scripts.port_upstream_character import (
    allocate_ids,
    build_coco_port_plan,
    inspect_character_source,
    prepare_output_directory,
    write_reports,
)


class TestUpstreamCharacterPort(unittest.TestCase):
    def test_inspection_separates_self_and_task_calls(self):
        source = """
from src.Labels import Labels


class Demo(BaseChar):
    def run(self):
        self.click_resonance()
        self.task.find_one(Labels.demo_ready)
"""

        result = inspect_character_source(source)

        self.assertEqual(result.class_name, "Demo")
        self.assertEqual(result.labels, ("demo_ready",))
        self.assertEqual(result.self_calls, ("click_resonance",))
        self.assertEqual(result.task_calls, ("find_one",))
        self.assertEqual(result.imports, ("src.Labels",))

    def test_allocate_ids_starts_after_each_local_maximum(self):
        local = {
            "images": [{"id": 283}],
            "categories": [{"id": 274}],
            "annotations": [{"id": 440}],
        }

        ids = allocate_ids(local, image_count=3, category_count=4, annotation_count=4)

        self.assertEqual(ids.image_ids, (284, 285, 286))
        self.assertEqual(ids.category_ids, (275, 276, 277, 278))
        self.assertEqual(ids.annotation_ids, (441, 442, 443, 444))

    def test_coco_plan_keeps_each_upstream_source_image_separate(self):
        upstream = {
            "images": [
                {"id": 6, "file_name": "images/6.png", "width": 3840, "height": 2160},
                {"id": 34, "file_name": "images/34.png", "width": 3840, "height": 2160},
            ],
            "categories": [
                {"id": 9, "name": "demo_h1", "supercategory": ""},
                {"id": 10, "name": "demo_h2", "supercategory": ""},
            ],
            "annotations": [
                {"id": 20, "image_id": 6, "category_id": 9,
                 "bbox": [100, 100, 40, 40], "area": 1600, "iscrowd": 0},
                {"id": 21, "image_id": 34, "category_id": 10,
                 "bbox": [100, 100, 40, 40], "area": 1600, "iscrowd": 0},
            ],
        }

        plan = build_coco_port_plan(
            character="Demo",
            labels=("demo_h1", "demo_h2"),
            local_coco={"images": [{"id": 10}], "categories": [], "annotations": []},
            upstream_coco=upstream,
        )

        self.assertEqual(
            [image["file_name"] for image in plan.fragment["images"]],
            ["images/characters/demo_source_6.png", "images/characters/demo_source_34.png"],
        )
        self.assertEqual(len(plan.canvases), 2)
        self.assertEqual(plan.canvases[0].annotations[0]["bbox"], [100, 100, 40, 40])
        self.assertEqual(plan.canvases[1].annotations[0]["bbox"], [100, 100, 40, 40])

    def test_missing_requested_label_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing_label"):
            build_coco_port_plan(
                character="Demo",
                labels=("missing_label",),
                local_coco={"images": [], "categories": [], "annotations": []},
                upstream_coco={"images": [], "categories": [], "annotations": []},
            )

    def test_existing_non_empty_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "port"
            output.mkdir()
            keep = output / "keep.txt"
            keep.write_text("keep", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                prepare_output_directory(output)

            self.assertEqual(keep.read_text(encoding="utf-8"), "keep")

    def test_reports_are_deterministic(self):
        report = {
            "character": "Demo",
            "safe_findings": {"labels": ["demo_h1"]},
            "manual_review": {"cross_references": ["src/char/Support.py:7"]},
        }
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_root = Path(first)
            second_root = Path(second)
            write_reports(first_root, report)
            write_reports(second_root, report)

            self.assertEqual(
                (first_root / "report.json").read_bytes(),
                (second_root / "report.json").read_bytes(),
            )
            self.assertEqual(
                (first_root / "report.md").read_bytes(),
                (second_root / "report.md").read_bytes(),
            )
            parsed = json.loads((first_root / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(parsed["character"], "Demo")


if __name__ == "__main__":
    unittest.main()
