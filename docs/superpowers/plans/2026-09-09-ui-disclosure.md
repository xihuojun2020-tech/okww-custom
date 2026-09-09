# UI disclosure implementation plan

**Goal:** Refine the 1.44.00 desktop UI with consistent optional disclosure and single-scroll layouts.

**Architecture:** Reuse SectionPanel and ConfigCard; hide content widgets without rebuilding their values. Keep actions and status outside collapsible content. No new dependencies or task execution changes.

**Tech Stack:** Python, PySide6, QFluentWidgets.

**Spec:** User-approved whole-program UI plan and subsequent disclosure refinements in this conversation.

## Constraints

- Preserve account transactions, identity checks, confirmation flows, task scheduling and weekly boss order.
- No nested scrolling or forced accordion exclusivity. Save/stop/status remain visible.
- Existing unrelated docs/reviews deletions must not be staged.
- Release 1.45.00 after verification; update docs and annotated tag, push branch and tag.

## Tasks

- [x] Extend src/gui/SectionPanel.py with optional checkable full-width header and persistent content widget; expose set_expanded(bool), reveal_widget(widget).
- [x] Test independent expansion, retained field values, keyboard operation and error reveal in tests/TestFlatUI.py.
- [x] Apply disclosure to task parameters and low-frequency general/account sections; preserve expansion during data refresh and configuration navigation.
- [x] Refine src/gui/CodexTheme.py and shared setting rows: semantic control states, label association, consistent typography and compact controls.
- [x] Update page/dialog feedback without changing business callbacks; retain auxiliary safety flows. See verification scope matrix.
- [x] Run isolated UI/full tests and scripts/render_flat_ui.py in collapsed/expanded states at multiple DPI values; inspect screenshots.
- [x] Update config.py, README, UI reference, changelog and implementation record. Release prepared for v1.45.00; Git push result is reported in the task final response.

## Runnable checks

```powershell
Copy-Item -Path custom_ok/ok/* -Destination .venv/Lib/site-packages/ok -Recurse -Force
.\.venv\Scripts\python.exe -m unittest tests.TestFlatUI
.\run_tests.ps1 -Group ui
.\.venv\Scripts\python.exe scripts/render_flat_ui.py tests/output/disclosure-ui
.\run_tests.ps1 -Group all
```

Component assertions: collapsed content is hidden, header remains visible, expanding preserves QLineEdit.text(), separate sections may both expand, reveal_widget expands ancestors and focuses the invalid control. TaskCard updates must not change isExpand.
