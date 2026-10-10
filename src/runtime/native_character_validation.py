# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validate trusted character Python in a separate disposable native process.

This isolates configuration/runtime state; it is not a security sandbox.
"""
import argparse
import json
from pathlib import Path
import sys
import threading


def validate_candidate(code_path, class_name, data_dir):
    from src.runtime import combat_api
    combat_api.configure(native=True, data_dir=data_dir)
    from src.runtime.account_runtime_bootstrap import initialize_account_runtime
    initialize_account_runtime(data_dir, 'character-validation', install_start_guard=False,
        backup_dir=Path(data_dir) / 'configs_backup', restore_prepared=True)
    from src.runtime.native_characters import NativeCharacterService
    from src.char.CustomCharLoader import bind_native_character_classes, load_native_character_source
    service = NativeCharacterService(data_dir)
    builtin = service._class(class_name)
    # Constructors may consult teammates; bind only trusted builtins here.
    bind_native_character_classes({info['cls']: info['cls'] for info in service.registered.values()},
                                   'character-validation-builtins')
    candidate = load_native_character_source(builtin, code_path, Path(code_path).read_bytes())
    from gameframe.api import TaskContext
    from src.runtime.native_combat_host import NativeCombatHost
    from src.combat.settings import COMBAT_GLOBAL_DEFAULTS, TEMPLATE_MATCHING_DEFAULTS
    context = TaskContext(None, {}, Path(data_dir), threading.Event(), 'character-validation', lambda value: None)
    host = NativeCombatHost(context, coco_path=Path(__file__).resolve().parents[2] / 'assets/coco_annotations.json',
        global_options=COMBAT_GLOBAL_DEFAULTS, ocr_engine=None,
        template_matching=TEMPLATE_MATCHING_DEFAULTS, device_identity='configuration', load_characters=False)
    info = service.registered[class_name]
    from src.char.BaseChar import CharType
    character = candidate(host.task, 0, char_name=info['canonical_name'], confidence=.99,
        ring_index=info.get('ring_index', -1), char_type=info.get('char_type', CharType.MAIN_DPS),
        buff_time=info['buff_time'])
    if character.task is not host.task or character.index != 0:
        raise ValueError('角色构造必须保留task和槽位index')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-root', type=Path, required=True)
    parser.add_argument('--code-path', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--class-name', required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    sys.path.append(str(args.core_root))
    try:
        validate_candidate(args.code_path, args.class_name, args.data_dir)
        result, status = {'ok': True}, 0
    except Exception as error:
        result, status = {'ok': False, 'type': type(error).__name__, 'error': str(error)}, 1
    finally:
        from src.evidence.service import close_existing_evidence_service
        close_existing_evidence_service()
    args.result.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return status


if __name__ == '__main__':
    raise SystemExit(main())
