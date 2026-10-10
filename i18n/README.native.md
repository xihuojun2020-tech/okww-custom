# Native gamepack language resources

The `native.po` and `native.mo` catalogs in this directory were authored for
the native Wuthering Waves gamepack on 2026-10-11. They translate the package's
fixed UI text into Simplified Chinese, Traditional Chinese, English, Spanish,
Japanese and Korean. They are distributed under AGPL-3.0-or-later with the
gamepack source.

The existing tracked `ok.po` and `ok.mo` catalogs are reused without changes
for production task metadata. The English task source text uses gettext's
`NullTranslations`, because the repository has no English `ok` catalog.
There is no separate OCR translation domain.

The v74 notification labels, credential editor text and launcher hotkey/account
messages are included in the native catalogs. `Discord Webhook` reuses the
existing `ok` translation in the five non-English locales, without a duplicate
native entry. Other new labels use native entries. Configuration keys, saved
credentials and user-entered text are never translated.

No catalogs or other resources were copied from the installed `ok-script`,
Qt or qfluentwidgets dependencies. qfluentwidgets' translator is loaded from
the installed dependency at runtime. Package catalogs stay in the AGPL
gamepack payload; the MIT GameFrame core receives a translation callable
and does not contain these catalogs.

The native archive includes this notice and each locale's PO/MO files.
Resources are resolved relative to the gamepack manifest's `source_root`,
independently of the working directory. Language preference is owned by
`configs/Language.json`; the legacy `configs/ui_config.json` value is imported
once when no native language preference exists. Changes require restarting
the application and task session.
