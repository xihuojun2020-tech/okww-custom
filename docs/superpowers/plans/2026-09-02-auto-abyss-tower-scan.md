# Auto Abyss Tower Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a test-page task that enters Cycle Challenge, opens the Adversity Tower, and reports every tower floor as completed, available, or locked without starting any challenge.

**Architecture:** `AutoAbyssTask` owns only navigation and scan orchestration.  Its deterministic OCR pairing and floor-status aggregation helpers accept simple values, so they are covered without a running game. Runtime code reuses `BaseWWTask` for F2, OCR, clicking, screenshots, and back navigation.

**Tech Stack:** Python, ok-script task runtime, Paddle OCR through existing task helpers, OpenCV template matching, unittest.

**Spec:** User-confirmed first phase in this conversation: enter the abyss, enter the three-tower page, and scan unfinished floors only; do not select a team or start combat.

## Global Constraints

- Support the current Chinese PC client and standard 16:9 layout only in this release.
- Reuse existing OCR/click/task APIs and introduce no dependency.
- Never click `挑战开始`, enter team selection, or call auto combat.
- Put the task in the `tests` navigation section and label it clearly as scan-only.
- Every code change updates `config.py` to `1.23.01`, release notes, tests, annotated `v1.23.01` tag, and GitHub branch/tag after verification.

---

### Task 1: Add pure scan planning helpers and their tests

**Files:**
- Create: `src/task/AutoAbyssTask.py`
- Create: `tests/TestAutoAbyssTask.py`

**Interfaces:**
- Produces: `match_travel_button(title_box, travel_boxes) -> Box | None` and `aggregate_floor_states(completed, locked) -> list[str]`.
- Consumes: OCR boxes exposing `x`, `y`, `width`, `height`, and `name`.

- [ ] **Step 1: Write the failing test**

```python
def test_match_travel_button_uses_the_same_card_row():
    title = Box(100, 400, 180, 40, name='深境区')
    near = Box(1200, 405, 80, 30, name='前往')
    wrong = Box(1200, 700, 80, 30, name='前往')
    self.assertIs(match_travel_button(title, [wrong, near]), near)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m unittest tests.TestAutoAbyssTask -v`

Expected: FAIL because `AutoAbyssTask` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
def match_travel_button(title_box, travel_boxes):
    title_y = title_box.y + title_box.height / 2
    return min(
        (box for box in travel_boxes if abs(box.y + box.height / 2 - title_y) <= title_box.height * 2),
        key=lambda box: abs(box.y + box.height / 2 - title_y), default=None,
    )
```

Add aggregation tests for all three result labels and a tower ordering test.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m unittest tests.TestAutoAbyssTask -v`

Expected: PASS.

### Task 2: Implement scan-only runtime navigation

**Files:**
- Modify: `src/task/AutoAbyssTask.py`
- Create: `assets/images/abyss_completed_icon.png`

**Interfaces:**
- Consumes: `BaseWWTask.openF2Book`, `ocr`, `wait_ocr`, `click_box`, `click_relative`, and `find_one`.
- Produces: `AutoAbyssTask.run()` which places a complete textual result in task status and logs.

- [ ] **Step 1: Implement the safe entry path**

Call `WWOneTimeTask.run()`, open the existing F2 challenge page, use OCR to click the `周期挑战` entry, locate `逆境深塔`, then click only the `前往` whose vertical midpoint matches that card. Wait for all three tower names before continuing.

- [ ] **Step 2: Implement three tower scans**

For `残响之塔`, `深境之塔`, and `回音之塔`, use its OCR name as anchor and click the below-name diamond centre. On the four-floor list, check each row's small completion ROI against `abyss_completed_icon.png`; mark completed hits, mark a lock hit as locked, and otherwise mark available. Return to the tower screen with Escape between scans.

- [ ] **Step 3: Add explicit safety guard**

```python
def _assert_scan_only(self):
    self.log_info('扫描模式：不会进入编队或点击挑战开始')
```

Call it before navigation and keep all challenge/team helpers out of this task.

- [ ] **Step 4: Run compile and focused tests**

Run: `./.venv/Scripts/python.exe -m py_compile src/task/AutoAbyssTask.py`

Run: `./.venv/Scripts/python.exe -m unittest tests.TestAutoAbyssTask -v`

Expected: PASS; no game interaction.

### Task 3: Register and release the task

**Files:**
- Modify: `config.py`
- Modify: `tests/TestTaskNavigationClassification.py`
- Modify: `run_tests.ps1`
- Modify: `tests/TestReleaseReadiness.py`
- Modify: `custom_ok/ok/gui/about/AboutTab.py`
- Modify: `更新日志.md`

**Interfaces:**
- Produces: a scan-only task visible under 测试功能 and release metadata for `1.23.01`.

- [ ] **Step 1: Add registration and navigation tests**

```python
task = object.__new__(AutoAbyssTask)
self.assertEqual(classify_task(task), TESTS)
self.assertEqual(task.navigation_section, TESTS)
```

Add `TestAutoAbyssTask.py` to the unit group.

- [ ] **Step 2: Register the task**

Add `['src.task.AutoAbyssTask', 'AutoAbyssTask']` after the account-switch test task in `config.py`. Set `navigation_section = 'tests'`, `group_name = '🧪 测试功能'`, and Chinese scan-only name/description.

- [ ] **Step 3: Synchronize release text**

Set the fixed-width version to `1.23.01`, update the release-readiness expectation, and add matching `V1.23.01` / `1.23.01` notes explaining the three-tower scan-only boundary.

- [ ] **Step 4: Run verification**

Run: `./.venv/Scripts/python.exe -m unittest tests.TestAutoAbyssTask tests.TestTaskNavigationClassification tests.TestReleaseReadiness tests.TestTestGroups -v`

Run: `./run_tests.ps1 -Group unit`

Run: `./.venv/Scripts/python.exe scripts/validate_release.py --tag v1.23.01`

Run: `git diff --check`

Expected: all pass; no game interaction.

- [ ] **Step 5: Publish verified release**

```powershell
git add src/task/AutoAbyssTask.py tests/TestAutoAbyssTask.py assets/images/abyss_completed_icon.png config.py tests/TestTaskNavigationClassification.py run_tests.ps1 tests/TestReleaseReadiness.py custom_ok/ok/gui/about/AboutTab.py 更新日志.md docs/superpowers/plans/2026-09-02-auto-abyss-tower-scan.md
git commit -m "feat: add abyss tower scan task"
git tag -a v1.23.01 -m "v1.23.01"
git push origin HEAD
git push origin v1.23.01
```
