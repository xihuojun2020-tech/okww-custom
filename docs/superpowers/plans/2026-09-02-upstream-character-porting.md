# Upstream Character Porting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable, dry-run upstream character migration auditor and use Qingxiao as the first fully traced character port, including templates, team interactions, automatic Abyss recognition, offline tests, and release `1.26.00`.

**Architecture:** A single importable CLI script reads a pinned upstream commit from local Git objects, uses AST and COCO data to produce a non-destructive report and privacy-safe candidate resources under ignored `build/`. AI reviews that output and applies the smallest semantic patch to the existing `BaseChar`/`CharFactory` architecture; runtime character discovery continues to use `CharFactory.char_names` only.

**Tech Stack:** Python 3, standard library (`argparse`, `ast`, `dataclasses`, `json`, `pathlib`, `subprocess`), existing OpenCV/NumPy, unittest, gettext, Git.

**Spec:** `docs/superpowers/specs/2026-09-02-upstream-character-porting-design.md`

## Global Constraints

- Work only in `E:\AI work\ok-wuthering-waves-master`; do not modify the abandoned Better Wuwa repository.
- Use `a24c30f2ec90e56e40287bb76caf7c3a52266d77` as the pinned Qingxiao upstream source.
- Do not merge upstream branches, cherry-pick upstream commits, or overwrite current base classes and COCO data wholesale.
- The auditor is dry-run only: it may write below ignored `build/character_ports/`, but must not modify `src/`, production assets, translations, or version files.
- Add no dependency; use the repository `.venv` interpreter and already-installed OpenCV/NumPy.
- Keep `CharFactory.char_names` as the only runtime character registry used by automatic Abyss.
- Never commit complete user screenshots; commit only minimum crops without UID or performance overlays.
- Do not start or control the game. All verification is offline.
- Preserve Denia's local default `SwitchPriority.NO`; do not import upstream's global `NO + 1` behavior.
- Port the 16-second healer full-concerto switch lock with minimal fields and filtering only.
- Release code changes as fixed-width version `1.26.00`, synchronize About and changelog, build the update package, create annotated tag `v1.26.00`, and push branch and tag.

---

### Task 1: Dry-run upstream character audit engine

**Files:**
- Create: `scripts/port_upstream_character.py`
- Create: `tests/TestUpstreamCharacterPort.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: a repository root, character class name, and pinned Git ref whose objects are already available locally.
- Produces: `SourceInspection`, `CocoPortPlan`, `inspect_character_source(source: str)`, `build_coco_port_plan(...)`, `generate_report(...)`, and a CLI that writes only below `build/character_ports/<character>/`.

- [ ] **Step 1: Write failing AST and ID-allocation tests**

```python
from scripts.port_upstream_character import (
    allocate_ids,
    inspect_character_source,
)


def test_inspection_separates_self_and_task_calls():
    source = """
from src.Labels import Labels
class Demo(BaseChar):
    def run(self):
        self.click_resonance()
        self.task.find_one(Labels.demo_ready)
"""
    result = inspect_character_source(source)
    assert result.labels == ("demo_ready",)
    assert result.self_calls == ("click_resonance",)
    assert result.task_calls == ("find_one",)


def test_allocate_ids_starts_after_each_local_maximum():
    local = {
        "images": [{"id": 283}],
        "categories": [{"id": 274}],
        "annotations": [{"id": 440}],
    }
    ids = allocate_ids(local, image_count=3, category_count=4, annotation_count=4)
    assert ids.image_ids == (284, 285, 286)
    assert ids.category_ids == (275, 276, 277, 278)
    assert ids.annotation_ids == (441, 442, 443, 444)
```

- [ ] **Step 2: Run the focused test and confirm it fails before implementation**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\run_test_file.py tests.TestUpstreamCharacterPort
```

Expected: FAIL because `scripts.port_upstream_character` does not exist.

- [ ] **Step 3: Implement immutable inspection and allocation records**

```python
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


def allocate_ids(local_coco, image_count, category_count, annotation_count):
    def sequence(items, count):
        start = max((int(item["id"]) for item in items), default=0) + 1
        return tuple(range(start, start + count))
    return AllocatedIds(
        sequence(local_coco.get("images", ()), image_count),
        sequence(local_coco.get("categories", ()), category_count),
        sequence(local_coco.get("annotations", ()), annotation_count),
    )
```

Implement `inspect_character_source()` with `ast.parse`, collecting `Labels.<name>`, `self.<method>()`, `self.task.<method>()`, imported module paths, and the first class name in sorted, deterministic tuples.

- [ ] **Step 4: Write failing COCO planning and source-image separation tests**

```python
def test_coco_plan_keeps_each_upstream_source_image_separate():
    plan = build_coco_port_plan(
        character="Demo",
        labels=("demo_h1", "demo_h2"),
        local_coco={"images": [{"id": 10}], "categories": [], "annotations": []},
        upstream_coco=UPSTREAM_WITH_OVERLAPPING_H1_H2_ON_DIFFERENT_IMAGES,
    )
    assert [image["file_name"] for image in plan.fragment["images"]] == [
        "images/characters/demo_source_6.png",
        "images/characters/demo_source_34.png",
    ]
    assert len(plan.canvases) == 2
```

The fixture defines both annotations at overlapping HUD coordinates but on distinct source images; the expected plan must never combine them.

- [ ] **Step 5: Implement COCO planning and black-canvas rendering**

```python
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
```

`build_coco_port_plan()` must:

1. Resolve requested labels through upstream categories.
2. Select only their annotations and source images.
3. Fail if any requested label lacks exactly one usable annotation.
4. Allocate all three ID classes from the live local maxima.
5. Emit one 3840×2160 black canvas per upstream source image.
6. Preserve each selected annotation's original `bbox` on its corresponding canvas.
7. Name outputs `images/characters/<lowercase_character>_source_<source_stem>.png`.

`render_canvases()` decodes source PNG bytes with existing OpenCV, copies only annotated rectangles to their original coordinates, and writes the candidate canvases below the output directory.

- [ ] **Step 6: Implement Git-object reading, reference scanning, reports, and safe CLI output**

```python
class GitObjectReader:
    def __init__(self, repository: Path):
        self.repository = repository

    def read_bytes(self, ref: str, path: str) -> bytes:
        result = subprocess.run(
            ["git", "show", f"{ref}:{path}"],
            cwd=self.repository,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result.stdout
```

The CLI arguments are `character`, required `--ref`, optional `--repository`, and optional `--output`. It must reject an existing non-empty output directory, never invoke `git fetch`, and generate deterministic `report.json`, `report.md`, `coco_fragment.json`, and `templates/` content. Search all upstream `.py` paths for the class name and `char_<lowercase>` label; compare `self_calls` with local `BaseChar`/`Healer` methods and `task_calls` with local `BaseCombatTask` methods. Missing APIs and cross-file references go into `manual_review`, while resolved source, labels, resources, and proposed IDs go into `safe_findings`.

- [ ] **Step 7: Add output-safety and determinism tests**

```python
def test_existing_non_empty_output_is_not_overwritten(self):
    with tempfile.TemporaryDirectory() as temp:
        output = Path(temp) / "port"
        output.mkdir()
        (output / "keep.txt").write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            prepare_output_directory(output)
        self.assertEqual((output / "keep.txt").read_text(encoding="utf-8"), "keep")
```

Run the command twice against separate temporary output roots and assert byte-identical JSON and Markdown.

- [ ] **Step 8: Ignore generated bundles and run focused tests**

Add `/build/character_ports/` under `.gitignore` runtime artifacts.

Run:

```powershell
.\.venv\Scripts\python.exe scripts\run_test_file.py tests.TestUpstreamCharacterPort
```

Expected: PASS.

- [ ] **Step 9: Commit the audit engine**

```powershell
git add .gitignore scripts/port_upstream_character.py tests/TestUpstreamCharacterPort.py
git commit -m "feat: add dry-run upstream character auditor"
```

---

### Task 2: AI migration instructions and provenance registry

**Files:**
- Modify: `.agents/skills/ok-ww-characters/SKILL.md`
- Modify: `.agents/skills/ok-ww-characters/references/character-patterns.md`
- Create: `config/upstream_characters.json`
- Modify: `tests/TestUpstreamCharacterPort.py`

**Interfaces:**
- Consumes: the audit CLI from Task 1 and the approved design constraints.
- Produces: a repository-local AI workflow and a runtime-independent provenance JSON document.

- [ ] **Step 1: Add a failing provenance schema test**

```python
def test_qingxiao_provenance_is_pinned_and_runtime_independent(self):
    data = json.loads(Path("config/upstream_characters.json").read_text(encoding="utf-8"))
    item = data["Qingxiao"]
    self.assertEqual(item["upstream_commit"], "a24c30f2ec90e56e40287bb76caf7c3a52266d77")
    self.assertEqual(item["local_release"], "1.26.00")
    self.assertEqual(
        item["labels"],
        ["char_qingxiao", "qingxiao_e", "qingxiao_h1", "qingxiao_h2"],
    )
    self.assertNotIn("config/upstream_characters.json", Path("config.py").read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run the Task 1 focused test command. Expected: FAIL because the provenance file is absent.

- [ ] **Step 3: Create the pinned provenance entry**

Create valid UTF-8 JSON containing the exact repository, commit, source path, `1.26.00` local release, four labels, and these local customizations:

```json
[
  "preserve_local_denia_default_no",
  "minimal_healer_switch_lock_port"
]
```

- [ ] **Step 4: Extend the character skill with the approved upstream-port workflow**

Add an `Upstream Semantic Porting` section requiring: correct-repo verification, pushed backup verification, pinned ref history review, audit CLI execution, three risk buckets, no bulk base-file copying, live COCO ID allocation, privacy-safe template handling, `CharFactory` registration, gettext synchronization, offline tests, versioning, package validation, annotated tag, and push. Add the exact Qingxiao invocation as an example but keep the workflow generic.

Extend `character-patterns.md` with the rule that overlapping state labels from different source screenshots stay on separate black canvases and that a character is not complete until every label can be loaded by `FeatureSet`.

- [ ] **Step 5: Run the focused tests and inspect the skill text**

```powershell
.\.venv\Scripts\python.exe scripts\run_test_file.py tests.TestUpstreamCharacterPort
rg -n "Upstream Semantic Porting|port_upstream_character|FeatureSet|overlap" .agents/skills/ok-ww-characters
```

Expected: tests PASS and all four workflow markers are present.

- [ ] **Step 6: Commit instructions and provenance**

```powershell
git add .agents/skills/ok-ww-characters config/upstream_characters.json tests/TestUpstreamCharacterPort.py
git commit -m "docs: standardize AI character porting workflow"
```

---

### Task 3: Healer full-concerto switch lock

**Files:**
- Modify: `src/char/BaseChar.py:52-101,315-325,569-582,694-701`
- Modify: `src/task/BaseCombatTask.py:538-552`
- Modify: `tests/TestChar.py`

**Interfaces:**
- Consumes: existing `CharType`, `SwitchPriority`, freeze-aware elapsed-time accounting, and `_choose_switch_target()`.
- Produces: `BaseChar.HEALER_FULL_CON_SWITCH_LOCKOUT`, `last_full_con_switch_time`, and `healer_full_con_switch_locked() -> bool`.

- [ ] **Step 1: Write failing state-transition tests**

Add tests proving:

```python
healer = BaseChar(task, 0, char_type=CharType.HEALER)
healer.current_con = 1
healer.switch_out()
self.assertGreaterEqual(healer.last_full_con_switch_time, 0)
self.assertTrue(healer.healer_full_con_switch_locked())
healer.reset_state()
self.assertEqual(healer.last_full_con_switch_time, -1)
```

Also prove a main DPS switching out at full concerto never starts this lock.

- [ ] **Step 2: Run the selected tests and confirm missing attributes fail**

```powershell
.\.venv\Scripts\python.exe scripts\run_test_file.py tests.TestChar
```

Expected: the new lock tests FAIL before implementation.

- [ ] **Step 3: Implement the minimal freeze-aware lock in `BaseChar`**

Add constant `HEALER_FULL_CON_SWITCH_LOCKOUT = 16.0`, initialize and reset `last_full_con_switch_time = -1`, record it only when `self.is_healer` and `con_full or self.current_con == 1`, and implement:

```python
def healer_full_con_switch_locked(self):
    return (
        self.is_healer
        and self.last_full_con_switch_time >= 0
        and self.time_elapsed_accounting_for_freeze(self.last_full_con_switch_time)
        < self.HEALER_FULL_CON_SWITCH_LOCKOUT
    )
```

Do not copy unrelated upstream `BaseChar` changes.

- [ ] **Step 4: Write a failing priority-override regression test**

Create a healer subclass whose `get_switch_priority()` returns `SwitchPriority.MUST`, mark its full-concerto lock active, and assert `_choose_switch_target()` does not select it. Then expire the lock and assert it becomes selectable again. This proves the task-level filter cannot be bypassed by a character override.

- [ ] **Step 5: Add the task-level candidate filter**

In `_choose_switch_target()`, calculate `SwitchPriority.NO` whenever `char.healer_full_con_switch_locked()` is true; otherwise call the existing character override. Retain existing logging and `priority > NO` filtering.

- [ ] **Step 6: Run character tests**

Run the Task 3 focused command. Expected: PASS, including all existing switch-priority tests.

- [ ] **Step 7: Commit the lock behavior**

```powershell
git add src/char/BaseChar.py src/task/BaseCombatTask.py tests/TestChar.py
git commit -m "fix: lock full-concerto healer reswitch for 16 seconds"
```

---

### Task 4: Qingxiao combat class, registration, and team interactions

**Files:**
- Create: `src/char/Qingxiao.py`
- Modify: `src/Labels.py`
- Modify: `src/char/CharFactory.py`
- Modify: `src/char/Denia.py:65-75`
- Modify: `src/char/Mornye.py:85-91`
- Modify: `tests/TestChar.py`

**Interfaces:**
- Consumes: `Labels.qingxiao_e`, `Labels.qingxiao_h1`, `Labels.qingxiao_h2`, existing BaseChar combat helpers, and Task 3 lock behavior.
- Produces: registered `Qingxiao` main-DPS class with wind ring index and canonical label `Labels.char_qingxiao`.

- [ ] **Step 1: Write failing registration and interaction tests**

Add assertions:

```python
self.assertIs(char_dict[Labels.char_qingxiao]["cls"], Qingxiao)
self.assertEqual(char_dict[Labels.char_qingxiao]["char_type"], CharType.MAIN_DPS)
self.assertEqual(char_dict[Labels.char_qingxiao]["ring_index"], Elements.WIND)
self.assertIn(Labels.char_qingxiao, char_names)
```

Add Denia tests proving intro from Qingxiao without Denia's buff returns exactly `SwitchPriority.NORMAL`, while intro from an unrelated main DPS remains exactly `SwitchPriority.NO`. Add a Mornye test proving intro from `char_qingxiao` returns `SwitchPriority.MUST`.

- [ ] **Step 2: Run character tests and confirm imports/labels fail**

Run the Task 3 test command. Expected: FAIL because Qingxiao and labels do not exist.

- [ ] **Step 3: Add four exact labels and register Qingxiao**

Add:

```python
char_qingxiao = "char_qingxiao"
qingxiao_e = "qingxiao_e"
qingxiao_h1 = "qingxiao_h1"
qingxiao_h2 = "qingxiao_h2"
```

Import `Qingxiao` in `CharFactory.py` and register:

```python
Labels.char_qingxiao: {
    "cls": Qingxiao,
    "char_type": CharType.MAIN_DPS,
    "ring_index": Elements.WIND,
},
```

- [ ] **Step 4: Port the fixed upstream class semantically**

Use the target ref implementation with bounded 18-second rotation, 2-second heavy timeout, 0.25-second dark-state confirmation, `finally: self.task.mouse_up()`, enhanced resonance detection, second-heavy liberation follow-up, and freeze-aware timing. Preserve current BaseChar APIs and imports; do not copy unrelated upstream files.

- [ ] **Step 5: Apply only the approved team interactions**

In Denia, import Qingxiao inside the intro branch and accept `(Aemeath, Qingxiao)` for the existing unbuffed `SwitchPriority.NORMAL` exception. Leave the fallback as `SwitchPriority.NO`, not `NO + 1`.

In Mornye, extend the existing set to `{"char_aemeath", "char_qingxiao"}` without changing Linnai behavior.

- [ ] **Step 6: Add bounded-action tests for Qingxiao**

Use a fake task with deterministic `find_one`, `next_frame`, `mouse_down`, and `mouse_up`. Assert `handle_heavy()` always releases the mouse when `find_one` raises and returns the matched label name only after two dark observations separated by the confirmation sleep. Assert the no-buff path attempts enhanced resonance and then switches instead of entering the 18-second loop.

- [ ] **Step 7: Run character and syntax tests**

```powershell
.\.venv\Scripts\python.exe scripts\run_test_file.py tests.TestChar
.\.venv\Scripts\python.exe -m py_compile src/char/Qingxiao.py src/char/Denia.py src/char/Mornye.py src/char/CharFactory.py
```

Expected: PASS.

- [ ] **Step 8: Commit character logic**

```powershell
git add src/Labels.py src/char/Qingxiao.py src/char/CharFactory.py src/char/Denia.py src/char/Mornye.py tests/TestChar.py
git commit -m "feat: add Qingxiao combat support"
```

---

### Task 5: Qingxiao templates and automatic Abyss screenshot recognition

**Files:**
- Create: `assets/images/characters/qingxiao_source_34.png`
- Create: `assets/images/characters/qingxiao_source_7.png`
- Create: `assets/images/characters/qingxiao_source_6.png`
- Modify: `assets/coco_annotations.json`
- Create: `tests/images/abyss_qingxiao_card_1440p.png`
- Create: `tests/images/abyss_qingxiao_selected_1440p.png`
- Modify: `tests/TestFeatureSet.py`
- Modify: `tests/TestAutoAbyssTask.py`

**Interfaces:**
- Consumes: Task 1 audit output, four Task 4 labels, upstream images `images/34.png`, `images/7.png`, `images/6.png`, and user-provided 2560×1440 screenshots.
- Produces: four loadable feature annotations and privacy-safe fixtures proving Qingxiao roster recognition, energy `10`, and level `90`.

- [ ] **Step 1: Ensure the pinned upstream object is available and run the auditor**

```powershell
if (-not (git remote get-url upstream 2>$null)) { git remote add upstream https://github.com/ok-oldking/ok-wuthering-waves.git }
git fetch upstream a24c30f2ec90e56e40287bb76caf7c3a52266d77
.\.venv\Scripts\python.exe scripts\port_upstream_character.py Qingxiao --ref a24c30f2ec90e56e40287bb76caf7c3a52266d77
```

Expected report: categories `qingxiao_h1`, `char_qingxiao`, `qingxiao_e`, `qingxiao_h2`; source images 34, 7, 6; local ID conflict on upstream category 274; newly proposed IDs computed from the current file rather than hard-coded.

- [ ] **Step 2: Write failing FeatureSet label tests**

Add a test that creates `FeatureSet`, passes a 3840×2160 zero frame to `get_feature_by_name(frame, label)`, and asserts the returned feature exists with a non-empty `feature.mat` for all four Qingxiao labels.

- [ ] **Step 3: Merge only the generated Qingxiao fragment**

Copy the three generated black canvases into `assets/images/characters/`. Append only the generated image, category, and annotation records to the existing COCO arrays, retaining all existing records. Re-read maxima immediately before merging; expected current starting points before this task are image 284, category 275, annotation 441, but the merge must use generated values if earlier changes alter those maxima.

- [ ] **Step 4: Produce privacy-safe image fixtures**

From `鸣潮   2026_9_2 20_21_20.png`, crop only the first-row first character card containing Qingxiao, energy `10`, and level `90`. From `鸣潮   2026_9_2 20_11_37.png`, crop only the first-row second selected Qingxiao card. Exclude top performance overlays, bottom UID, other account context, and unused characters. Save the two minimal PNG crops named above; do not copy full screenshots.

- [ ] **Step 5: Add offline ORB and OCR regression tests**

Construct a synthetic 2560×1440 frame by placing the card fixture at the normalized first-card rectangle from `AutoAbyssTask.character_card_slots()`. Assert `_identify_character()` returns canonical `Labels.char_qingxiao`. Exercise `_recognize_character_screen()` through a test subclass whose `ocr()` returns deterministic `Box` values `10` and `Lv.90` at the fixture's energy and level coordinates; assert the record has energy `10`, level `90`, and `available is True`. Repeat avatar recognition with the selected fixture and assert its gold border/selection number do not change the canonical character.

Downscale the synthetic frame to 1920×1080 and assert the same canonical result. Tune only existing ORB thresholds if both the new Qingxiao fixtures and representative existing character tests justify the adjustment; do not introduce a Qingxiao-only runtime path.

- [ ] **Step 6: Run asset and Abyss tests**

```powershell
.\.venv\Scripts\python.exe scripts\run_test_file.py tests.TestFeatureSet
.\.venv\Scripts\python.exe scripts\run_test_file.py tests.TestAutoAbyssTask
```

Expected: all four features load, Qingxiao is recognized at 1440P and 1080P, and no game process is started.

- [ ] **Step 7: Commit resource support**

```powershell
git add assets/coco_annotations.json assets/images/characters tests/images/abyss_qingxiao_card_1440p.png tests/images/abyss_qingxiao_selected_1440p.png tests/TestFeatureSet.py tests/TestAutoAbyssTask.py
git commit -m "feat: add Qingxiao visual recognition assets"
```

---

### Task 6: Translation, package inclusion, and release metadata

**Files:**
- Modify: `i18n/zh_CN/LC_MESSAGES/ok.po`
- Modify: `i18n/zh_CN/LC_MESSAGES/ok.mo`
- Modify: `打包更新.py:30-49`
- Modify: `tests/TestReleaseReadiness.py:10-21,61-74`
- Modify: `config.py:21`
- Modify: `custom_ok/ok/gui/about/AboutTab.py:48-50`
- Modify: `更新日志.md:5`

**Interfaces:**
- Consumes: completed Qingxiao feature and asset directory.
- Produces: translated display name, recursively packaged character assets, synchronized `1.26.00` metadata, and release checks.

- [ ] **Step 1: Write failing release assertions**

Change the expected version to `1.26.00`; require `assets/images/characters` in `SYNC_ITEMS`; require all three strings `Qingxiao`, `清宵`, and `port_upstream_character` in both About and changelog.

- [ ] **Step 2: Run release readiness and confirm failure**

```powershell
.\.venv\Scripts\python.exe scripts\run_test_file.py tests.TestReleaseReadiness
```

Expected: FAIL on old version, missing package directory, and missing release text.

- [ ] **Step 3: Synchronize gettext catalogs**

Add `msgid "Qingxiao"` with `msgstr "清宵"` to simplified Chinese. Do not invent translations for the other locale catalogs; gettext falls back to the English class name there. Compile the changed simplified-Chinese PO to MO with the repository gettext helper or Babel already installed in `.venv`; do not hand-edit the binary MO file.

- [ ] **Step 4: Package the entire future character asset directory**

Add exactly `assets/images/characters` to `SYNC_ITEMS`, replacing the need to list every future character resource. Keep the existing explicit logout and Abyss resources unchanged. The recursive directory handling already present in `collect_files()` supplies all contained PNG files.

- [ ] **Step 5: Update fixed-width version and release notes**

Set `config.py` to `version = "1.26.00"`. Prepend an About entry and a changelog section covering the dry-run migration auditor, pinned provenance, Qingxiao combat/Denia/Mornye integration, 16-second healer lock, four visual labels, 1080P/1440P offline Abyss recognition, and the fact that no game was operated.

- [ ] **Step 6: Run focused release tests**

Run the Task 6 focused command. Expected: PASS.

- [ ] **Step 7: Commit release metadata**

```powershell
git add i18n config.py custom_ok/ok/gui/about/AboutTab.py 更新日志.md 打包更新.py tests/TestReleaseReadiness.py
git commit -m "chore: prepare Qingxiao support release 1.26.00"
```

---

### Task 7: Full offline verification, update package, and GitHub release

**Files:**
- Verify: all changed files
- Generate ignored artifact: `okww_更新包_20260902.zip`

**Interfaces:**
- Consumes: Tasks 1-6 and existing personal release scripts.
- Produces: verified commit, update archive, SHA-256, annotated `v1.26.00`, pushed branch and tag.

- [ ] **Step 1: Run syntax and focused test groups**

```powershell
.\.venv\Scripts\python.exe -m py_compile scripts/port_upstream_character.py src/char/Qingxiao.py src/char/BaseChar.py src/task/BaseCombatTask.py
.\.venv\Scripts\python.exe scripts\run_test_file.py tests.TestUpstreamCharacterPort
.\.venv\Scripts\python.exe scripts\run_test_file.py tests.TestChar
.\.venv\Scripts\python.exe scripts\run_test_file.py tests.TestFeatureSet
.\.venv\Scripts\python.exe scripts\run_test_file.py tests.TestAutoAbyssTask
.\.venv\Scripts\python.exe scripts\run_test_file.py tests.TestReleaseReadiness
```

Expected: PASS.

- [ ] **Step 2: Run the complete offline suite**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "Test*.py"
```

Expected: PASS with no game launch or input calls.

- [ ] **Step 3: Validate release metadata**

```powershell
.\.venv\Scripts\python.exe scripts\validate_release.py --root . --tag v1.26.00
git diff --check
git status --short
```

Expected: validator prints `1.26.00`, diff check is clean, and status contains no unintended user configuration or complete screenshots.

- [ ] **Step 4: Generate and inspect the update package**

```powershell
.\.venv\Scripts\python.exe 打包更新.py .
.\.venv\Scripts\python.exe scripts\package_smoke.py --dist .
Get-FileHash -Algorithm SHA256 .\okww_更新包_20260902.zip
```

Expected: the archive includes `src/char/Qingxiao.py`, `assets/coco_annotations.json`, all three `assets/images/characters/qingxiao_source_*.png`, translations, About, changelog and `config.py`; it excludes account configuration, logs, screenshots and complete user captures.

- [ ] **Step 5: Review final history and create the annotated release tag**

```powershell
git status --short --branch
git log --oneline --decorate -10
git tag -a v1.26.00 -m "Release 1.26.00: Qingxiao and AI character porting workflow"
```

Only create the tag if every prior verification passed and HEAD contains all planned changes.

- [ ] **Step 6: Push branch and tag**

```powershell
git push origin codex/account-switch-foreground-bitblt
git push origin v1.26.00
```

- [ ] **Step 7: Report completion**

Provide commit, annotated tag, branch, update package absolute path, SHA-256, test counts, and confirm explicitly that the game was never started or controlled.
