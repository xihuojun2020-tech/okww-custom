# Compact Task Headers Implementation Plan

> Execute inline in the current task; the user has approved the task-row design and its extension to other modules.

**Goal:** Replace separate expansion bars with compact clickable headers and independent actions.

**Architecture:** Share a native Qt DisclosureHeader between ConfigCard and SectionPanel. Preserve task controllers, detached account drafts, update workers and confirmation dialogs.

**Tech Stack:** Python, PySide6, existing QFluentWidgets; no additional dependencies.

**Spec:** User-approved design in this task: icon/title/status/action/arrow, default closed, flat detail content, independent expansion, no nested page scrolling.

## Constraints

- Only header clicks toggle; actions and detail editors do not.
- Account stamina and weekly sections are separate UI groups; execution logic is unchanged.
- All real operation callbacks, confirmations, and refresh state retention remain intact.
- Version 1.46.00; update docs, run isolated tests and DPI rendering before publishing.
- Exclude pre-existing docs/reviews deletions from commits.

## Implementation and verification

- [x] Add `src/gui/DisclosureHeader.py`: `add_action(widget)`, `set_summary(text)`, `set_expanded(bool)`, `toggled(bool)`.
- [x] Integrate `ConfigCard.py`, `TaskCard.py` and `SectionPanel.py`; retain their framework-facing APIs.
- [x] Add `TestFlatUI.test_header_clicks_and_actions_are_independent`; test real Qt mouse/keyboard events with a mocked controller.
- [x] Split account form groups and keep Save/Discard near the selector. Preserve weekly records in details.
- [x] Apply headers to connection, hotkeys, diagnostics, updates, sequences and maintenance.
- [x] Run `.\.venv\Scripts\python.exe -m unittest tests.TestFlatUI`, then `.\run_tests.ps1 -Group ui` and `-Group all`; repair regressions. Results are recorded in `docs/references/ui-disclosure-verification.md`.
- [x] Run `scripts/render_flat_ui.py` at widths 760/1100, collapsed/expanded, scales 1/1.25/1.5/2; inspect screenshots and layout checks.
- [x] Update README, changelog, UI reference/verification, structure and handoff docs; validate release.
- Publishing step: stage only this change, commit, create annotated v1.46.00 tag, push branch and tag; use the remote tag as publication evidence. Do not equate push with successful installer/NAS publication.
