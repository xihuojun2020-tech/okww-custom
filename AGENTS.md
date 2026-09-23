# Agent Instructions

## Python

- When running Python commands in this repository, use the local virtual environment if it exists.
- On Windows/PowerShell, prefer `.\.venv\Scripts\python.exe` when present.
- On POSIX shells, prefer `./.venv/bin/python` when present.
- Fall back to `python` only when no local `.venv` interpreter exists.
- Prefer invoking the interpreter directly, for example `.\.venv\Scripts\python.exe -m pytest`, instead of relying on shell activation.

## NAS

- Use only `\\192.168.3.173\羲火君 共享给我\AI诊断` for this project's NAS diagnostics, reading, handoffs and update publishing.
- `.172`, `.161` and `.170` are legacy addresses, not fallback destinations. Retain them only for migrating old configuration and reading saved credential aliases.
- Historical reports may contain old addresses; they are not current operating instructions.
- After actually reviewing a diagnostic ZIP, write a substantive Markdown report (scope, findings, evidence, fixes and verification limits), then run `.\.venv\Scripts\python.exe -m src.runtime.diagnostic_archive_retention --review <ZIP filename> --report <report path> --sha256 <verified ZIP SHA256>`. This stores the report and marks/moves only that reviewed package. Merely opening or listing evidence is not review completion. Reports remain; reviewed evidence expires after 3 days, unreviewed packages after 30 days from verified upload.

## Versioning and GitHub publishing

- Every change that modifies code must update the version in `config.py` in the same release.
- Version text uses fixed-width `X.YY.ZZ` (for example `1.04.02`).
- Small fixes increment the third component.
- Medium changes increment the second component and reset the third component to `00`.
- Major changes increment the first component and reset both later components to `00`; do this only when the user explicitly requests a major version change.
- Keep product-facing version text and release notes synchronized with `config.py`.
- After a verified version change, commit it, create the matching annotated `vX.YY.ZZ` tag, and push both the branch and tag to GitHub unless the user explicitly asks to keep the change local.
- Commit, tag, and push ordinary project changes immediately after verification. The Beijing-time 01:00–06:00 window applies only to intermediary-system operations and restarts, switches, or deployments that may interrupt GPT availability; it does not delay ordinary project GitHub publishing.

## Account-switch testing

- `TestAccountSwitchTask` is the focused test entry point for `MultiAccountDailyTask`; it must reuse the production account-selection, alias-matching, verification, retry, logout, and login methods instead of maintaining a separate switching implementation.
- Keep account-switch tests synchronized whenever the production multi-account switching path changes.
- The default continuous switching test order is A1, A3, A4. Resolve these as exact profile short names and cover both configured alternate login names and masked-phone identities.
