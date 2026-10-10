# SPDX-License-Identifier: AGPL-3.0-or-later
"""Package-owned gettext catalogs and restart-required UI language preference."""

from dataclasses import dataclass
import gettext
import json
import locale
import os
from pathlib import Path


LANGUAGE_OPTIONS = ('zh_CN', 'zh_TW', 'en_US', 'es_ES', 'ja_JP', 'ko_KR', 'Auto')
LANGUAGE_DEFAULTS = {'Language': 'Auto'}
LANGUAGE_METADATA = {
    'description': 'Set your preferred language',
    'config_description': {'Language': 'Language changes apply after restarting the application and task session.'},
    'config_type': {'Language': {'type': 'drop_down', 'options': list(LANGUAGE_OPTIONS),
                               'restart_required': True}},
}


def language_preference(data_root):
    """Read this data owner's value; old MainWindow.Language is migrated on save."""
    root = Path(data_root).resolve()
    current = root / 'configs/Language.json'
    old = root / 'configs/ui_config.json'
    if current.is_file():
        value = json.loads(current.read_text(encoding='utf-8'))['Language']
    elif old.is_file():
        value = json.loads(old.read_text(encoding='utf-8')).get('MainWindow', {}).get('Language', 'Auto')
    else:
        value = 'Auto'
    if not isinstance(value, str) or value not in LANGUAGE_OPTIONS:
        raise ValueError(f'Unsupported language: {value}')
    return value


def create_language_config(data_root):
    """Use the existing native Config writer, importing the old value once."""
    from src.runtime.native_config import Config
    root = Path(data_root).resolve()
    value = language_preference(root)
    config = Config('Language', LANGUAGE_DEFAULTS, folder=root / 'configs')
    if config['Language'] != value:
        config['Language'] = value
    return config


def system_language():
    if os.name != 'nt':
        return locale.getlocale()[0] or 'en_US'
    import ctypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetUserDefaultLocaleName.argtypes = (ctypes.c_wchar_p, ctypes.c_int)
    kernel.GetUserDefaultLocaleName.restype = ctypes.c_int
    name = ctypes.create_unicode_buffer(85)  # LOCALE_NAME_MAX_LENGTH
    if not kernel.GetUserDefaultLocaleName(name, len(name)):
        raise ctypes.WinError(ctypes.get_last_error())
    return name.value


def resolve_language(selected, system_locale=None):
    if selected not in LANGUAGE_OPTIONS:
        raise ValueError(f'Unsupported language: {selected}')
    if selected != 'Auto':
        return selected
    system = system_locale if system_locale is not None else system_language()
    parts = system.replace('-', '_').lower().split('_')
    if parts[0] == 'zh':
        return 'zh_TW' if any(part in ('tw', 'hk', 'mo', 'hant') for part in parts[1:]) else 'zh_CN'
    return {'en': 'en_US', 'es': 'es_ES', 'ja': 'ja_JP', 'ko': 'ko_KR'}.get(parts[0], 'en_US')


def catalog_directory(pack_root=None):
    if pack_root is None:
        return Path(__file__).resolve().parents[2] / 'i18n'
    root = Path(pack_root).resolve()
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    return (root / manifest['source_root']).resolve() / 'i18n'


@dataclass(frozen=True)
class NativeLanguage:
    selected: str
    resolved: str
    catalogs: Path
    translation: gettext.NullTranslations

    def translate(self, text):
        return self.translation.gettext(str(text)) if text is not None else ''

    gettext = translate


def load_language(data_root, *, pack_root=None, system_locale=None):
    selected = language_preference(data_root)
    resolved = resolve_language(selected, system_locale)
    directory = catalog_directory(pack_root)
    catalog = gettext.translation('native', localedir=directory, languages=[resolved])
    # English task metadata is source text; no English ok catalog exists.
    production = (gettext.NullTranslations() if resolved == 'en_US' else
                  gettext.translation('ok', localedir=directory, languages=[resolved]))
    catalog.add_fallback(production)
    return NativeLanguage(selected, resolved, directory, catalog)


_active = None


def activate_language(language):
    global _active
    _active = language
    return language


def translate(text):
    """Business widgets use explicit calls, including fixed Chinese labels."""
    return _active.translate(text) if _active is not None else text


def install_qt_language(app, language):
    """Install before constructing widgets and retain translators for app life."""
    from PySide6.QtCore import QLocale, QTranslator
    from qfluentwidgets import FluentTranslator

    class PackageTranslator(QTranslator):
        def translate(self, context, source_text, disambiguation=None, n=-1):
            translated = language.translate(source_text)
            # None becomes a null QString, allowing Qt's other translators.
            return translated if translated != source_text else None

        def isEmpty(self):
            return False

    activate_language(language)
    QLocale.setDefault(QLocale(language.resolved))
    fluent = FluentTranslator(QLocale(language.resolved), app)
    package = PackageTranslator(app)
    app.installTranslator(fluent)
    app.installTranslator(package)
    app._native_language = language
    app._native_language_translators = (fluent, package)
    return language
