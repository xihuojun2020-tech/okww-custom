# Agent Instructions

## Python

- When running Python commands in this repository, use the local virtual environment if it exists.
- On Windows/PowerShell, prefer `.\.venv\Scripts\python.exe` when present.
- On POSIX shells, prefer `./.venv/bin/python` when present.
- Fall back to `python` only when no local `.venv` interpreter exists.
- Prefer invoking the interpreter directly, for example `.\.venv\Scripts\python.exe -m pytest`, instead of relying on shell activation.

## Versioning and GitHub publishing

- Every change that modifies code must update the version in `config.py` in the same release.
- Small fixes increment the third component.
- Medium changes increment the second component and reset the third component to zero.
- Major changes increment the first component and reset both later components to zero; do this only when the user explicitly requests a major version change.
- Keep product-facing version text and release notes synchronized with `config.py`.
- After a verified version change, commit it, create the matching annotated `vX.Y.Z` tag, and push both the branch and tag to GitHub unless the user explicitly asks to keep the change local.

## Account-switch testing

- `TestAccountSwitchTask` is the focused test entry point for `MultiAccountDailyTask`; it must reuse the production account-selection, alias-matching, verification, retry, logout, and login methods instead of maintaining a separate switching implementation.
- Keep account-switch tests synchronized whenever the production multi-account switching path changes.
- The default continuous switching test order is A1, A3, A4. Resolve these as exact profile short names and cover both configured alternate login names and masked-phone identities.
