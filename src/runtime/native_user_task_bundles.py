# SPDX-License-Identifier: AGPL-3.0-or-later
"""Archive metadata, immutable bundle content and explicit legacy source migration."""

import ast
import difflib
import hashlib
import io
import json
import keyword
import math
from pathlib import Path, PurePosixPath
import tokenize
import uuid


FORMAT = 'okww-native-user-bundle'
_ERRORS = frozenset({'TaskDisabledException', 'FinishedException', 'CaptureException',
                     'WaitFailedException', 'CannotFindException'})
_LEGACY_IMPORTS = {
    'ok': frozenset({'BaseTask', 'TriggerTask', 'Box', 'Logger', 'Config',
                     'find_boxes_by_name', 'sort_boxes', 'find_color_rectangles', 'safe_get'}) | _ERRORS,
    'ok.task.task': frozenset({'BaseTask', 'TriggerTask'}),
    'ok.feature.Box': frozenset({'Box', 'find_boxes_by_name', 'sort_boxes'}),
    'ok.util.logger': frozenset({'Logger'}),
    'ok.util.config': frozenset({'Config'}),
    'ok.task.exceptions': _ERRORS | {'HotkeyConfigException'},
    'ok.util.collection': frozenset({'safe_get'}),
    'ok.util.color': frozenset({'find_color_rectangles'}),
}


def digest_json(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def bundle_identity(file_name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'okww:user-bundle:' + file_name))


def task_identity(bundle_id, key):
    return str(uuid.uuid5(uuid.UUID(bundle_id), key))


def relative_file(root, value, *, root_python=False):
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value
            or value.startswith('/') or any(part in {'', '.', '..'} for part in value.split('/'))):
        raise ValueError(f'Invalid bundle relative path: {value!r}')
    path = PurePosixPath(value)
    if root_python and (len(path.parts) != 1 or path.suffix != '.py'):
        raise ValueError(f'Task source must be a root Python file: {value}')
    target = (Path(root) / value).resolve()
    if not target.is_relative_to(Path(root).resolve()) or not target.is_file():
        raise ValueError(f'Bundle file missing or outside snapshot: {value}')
    return target


def file_index(root):
    root = Path(root)
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob('*')) if path.is_file() and path != root / 'files.json'}


def write_index(root):
    index = file_index(root)
    (Path(root) / 'files.json').write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')
    return digest_json(index)


def check_manifest(value, root, *, native=True):
    if not isinstance(value, dict):
        raise ValueError('Bundle manifest must be an object')
    for key in ('file_name', 'script_name', 'version'):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(f'Bundle manifest requires a nonempty {key}')
    if ('/' in value['file_name'] or '\\' in value['file_name'] or value['file_name'] in {'.', '..'}):
        raise ValueError('Bundle file_name must be a logical filename, not a path')
    if not native:
        return
    if value.get('format') != FORMAT or type(value.get('format_version')) is not int or value['format_version'] != 1:
        raise ValueError('Unsupported native bundle format')
    if not isinstance(value.get('tasks'), list) or not value['tasks']:
        raise ValueError('Native bundle must explicitly declare tasks')
    keys, exports = set(), set()
    for task in value['tasks']:
        if not isinstance(task, dict) or not isinstance(task.get('key'), str) or not task['key'].strip():
            raise ValueError('Bundle task requires a stable key')
        if task['key'] in keys:
            raise ValueError('Duplicate bundle task key')
        keys.add(task['key'])
        relative_file(root, task.get('path'), root_python=True)
        class_name = task.get('class_name')
        if not isinstance(class_name, str) or not class_name.isidentifier() or keyword.iskeyword(class_name):
            raise ValueError('Bundle task requires an exact exported class_name')
        exported = task['path'], class_name
        if exported in exports:
            raise ValueError('Duplicate bundle class export')
        exports.add(exported)
        capabilities = task.get('required_capabilities')
        if (not isinstance(capabilities, list)
                or any(not isinstance(item, str) or not item for item in capabilities)):
            raise ValueError('Bundle task must explicitly declare required_capabilities')


def check_assets(root):
    """Validate the actual COCO inputs used by native FeatureSet, without capture."""
    root = Path(root)
    coco = root / 'assets/coco_annotations.json'
    if not coco.exists():
        return None
    relative_file(root, 'assets/coco_annotations.json')
    data = json.loads(coco.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or any(not isinstance(data.get(key), list)
                                         for key in ('images', 'categories', 'annotations')):
        raise ValueError('Bundle COCO requires images, categories and annotations lists')
    from PIL import Image
    images, categories = {}, set()
    for image in data['images']:
        if not isinstance(image, dict) or type(image.get('id')) is not int or image['id'] in images:
            raise ValueError('Bundle COCO image IDs must be unique integers')
        filename = image.get('file_name')
        relative_file(coco.parent, filename)
        # COCO references resolve relative to its folder, within the snapshot.
        image_path = relative_file(root, 'assets/' + filename)
        with Image.open(image_path) as bitmap:
            size = bitmap.size
            bitmap.verify()
        images[image['id']] = size
    for category in data['categories']:
        if (not isinstance(category, dict) or type(category.get('id')) is not int
                or category['id'] in categories or not isinstance(category.get('name'), str)
                or not category['name']):
            raise ValueError('Bundle COCO categories require unique integer IDs and names')
        categories.add(category['id'])
    for annotation in data['annotations']:
        if (not isinstance(annotation, dict) or type(annotation.get('image_id')) is not int
                or type(annotation.get('category_id')) is not int
                or annotation['image_id'] not in images or annotation['category_id'] not in categories):
            raise ValueError('Bundle COCO annotation references an unknown image/category')
        bbox = annotation.get('bbox')
        if (not isinstance(bbox, list) or len(bbox) != 4
                or any(type(number) not in (int, float) or not math.isfinite(number) for number in bbox)):
            raise ValueError('Bundle COCO annotation requires four finite bbox coordinates')
        x, y, width, height = bbox
        image_width, image_height = images[annotation['image_id']]
        if (x < 0 or y < 0 or round(x + width) <= round(x) or round(y + height) <= round(y)
                or round(x + width) > image_width or round(y + height) > image_height):
            raise ValueError('Bundle COCO bbox must crop a nonempty region inside its image')
    return coco


def transform_legacy(code, path, local_modules=()):
    """Change supported import targets only; return explicit, reviewable differences."""
    tree = ast.parse(code, filename=path)
    errors, replacements = [], []
    lines = code.splitlines(keepends=True)
    offsets, offset = [], 0
    for line in lines:
        offsets.append(offset)
        offset += len(line.encode('utf-8'))
    bases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and (node.module == 'ok' or node.module.startswith('ok.')):
            allowed = _LEGACY_IMPORTS.get(node.module, ())
            unknown = [item.name for item in node.names if item.name not in allowed]
            if unknown or node.level:
                errors.append({'path': path, 'line': node.lineno,
                               'message': 'Unsupported legacy import: ' + node.module + ' / ' + ', '.join(unknown)})
                continue
            start = offsets[node.lineno - 1] + node.col_offset
            end = offsets[node.end_lineno - 1] + node.end_col_offset
            fragment = code.encode('utf-8')[start:end].decode('utf-8')
            tokens = list(tokenize.generate_tokens(io.StringIO(fragment).readline))
            module_start = next(token.end for token in tokens if token.string == 'from')
            import_start = next(token.start for token in tokens if token.string == 'import')
            fragment_lines = fragment.splitlines(keepends=True)
            a = sum(len(line) for line in fragment_lines[:module_start[0] - 1]) + module_start[1]
            b = sum(len(line) for line in fragment_lines[:import_start[0] - 1]) + import_start[1]
            replacement = fragment[:a] + ' src.runtime.combat_api ' + fragment[b:]
            replacements.append((start, end, replacement.encode('utf-8')))
            if node in tree.body:
                for item in node.names:
                    if item.name in {'BaseTask', 'TriggerTask'}:
                        bases[item.asname or item.name] = item.name
        elif isinstance(node, ast.Import):
            for item in node.names:
                if item.name == 'ok' or item.name.startswith('ok.') or item.name in local_modules:
                    errors.append({'path': path, 'line': node.lineno,
                                   'message': 'Unsupported legacy module import: ' + item.name})
        elif isinstance(node, ast.ImportFrom) and (node.level or node.module in local_modules):
            errors.append({'path': path, 'line': node.lineno,
                           'message': 'Cross-file legacy imports require explicit manual migration'})
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            target = node.args[0].value
            dynamic_import = ((isinstance(node.func, ast.Name) and node.func.id == '__import__')
                              or (isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module'))
            if dynamic_import and isinstance(target, str) and (target == 'ok' or target.startswith('ok.')):
                errors.append({'path': path, 'line': node.lineno,
                               'message': 'Dynamic legacy ok imports require manual migration'})
    payload = code.encode('utf-8')
    for start, end, replacement in sorted(replacements, reverse=True):
        payload = payload[:start] + replacement + payload[end:]
    converted = payload.decode('utf-8')
    ast.parse(converted, filename=path)
    classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)
               and any(isinstance(base, ast.Name) and base.id in bases for base in node.bases)]
    difference = ''.join(difflib.unified_diff(code.splitlines(keepends=True), converted.splitlines(keepends=True),
                                            fromfile=path, tofile=path + ' (native)'))
    return {'path': path, 'original_code': code, 'code': converted, 'diff': difference}, errors, classes


def inspect_staged(root, archive_sha256):
    root = Path(root)
    manifest = json.loads(relative_file(root, 'manifest.json').read_text(encoding='utf-8'))
    native = isinstance(manifest, dict) and 'format' in manifest
    check_manifest(manifest, root, native=native)
    files = sorted(path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file())
    if any(PurePosixPath(path).suffix == '.pyc' or '__pycache__' in PurePosixPath(path).parts for path in files):
        raise ValueError('Bundle must contain source files, not Python bytecode caches')
    check_assets(root)
    differences, errors, tasks = [], [], []
    if native:
        from gameframe.packages import verify_index
        verify_index(root, required=True)
        tasks = manifest['tasks']
    else:
        sources = sorted(root.glob('*.py'))
        local_modules = {path.stem for path in sources}
        local_modules.update(path.relative_to(root).parts[0] for path in root.rglob('*.py') if path.parent != root)
        for source in sources:
            try:
                difference, source_errors, classes = transform_legacy(
                    source.read_bytes().decode('utf-8'), source.name, local_modules)
            except (SyntaxError, UnicodeError) as error:
                errors.append({'path': source.name, 'line': getattr(error, 'lineno', None), 'message': str(error)})
                continue
            differences.append(difference)
            errors.extend(source_errors)
            tasks.append({'key': source.name, 'path': source.name,
                          'class_name': classes[0] if classes else None,
                          'required_capabilities': ['frames', 'keyboard', 'mouse']})
        # Unselected Python still ships in a legacy archive. It must not hide
        # unsupported legacy imports in a nested helper file.
        for source in sorted(root.rglob('*.py')):
            if source.parent == root:
                continue
            path = source.relative_to(root).as_posix()
            try:
                difference, source_errors, _ = transform_legacy(source.read_bytes().decode('utf-8'), path, local_modules)
            except (SyntaxError, UnicodeError) as error:
                errors.append({'path': path, 'line': getattr(error, 'lineno', None), 'message': str(error)})
                continue
            differences.append(difference)
            errors.extend(source_errors)
    return {'format': 'native' if native else 'legacy', 'archive_sha256': archive_sha256,
            'manifest': manifest, 'tasks': tasks, 'code_diffs': differences, 'errors': errors, 'files': files}


def stage_archive(archive_path, root, *, expected_sha256=None):
    """Hash and extract the same bytes, so preview cannot approve another file."""
    from gameframe.packages import extract_zip
    payload = Path(archive_path).read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError('Script archive changed after preview; inspect it again')
    extract_zip(io.BytesIO(payload), Path(root).resolve())
    return inspect_staged(root, digest)


def prepare_legacy(root, preview, migration_tasks):
    if preview['errors']:
        raise ValueError('; '.join(f"{item['path']}:{item['line']}: {item['message']}" for item in preview['errors']))
    if migration_tasks is None:
        raise ValueError('Legacy migration requires explicit tasks/classes/capabilities confirmation')
    original = preview['manifest']
    manifest = {key: original[key] for key in ('file_name', 'script_name', 'version')}
    manifest.update(format=FORMAT, format_version=1, tasks=migration_tasks)
    check_manifest(manifest, root)
    for difference in preview['code_diffs']:
        relative_file(root, difference['path']).write_text(difference['code'], encoding='utf-8', newline='')
    (Path(root) / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    write_index(root)
    return manifest
