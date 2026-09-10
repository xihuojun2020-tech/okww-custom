"""Strict, local preparation of diagnostic files; never fall back to raw bytes."""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path, PurePosixPath

from src.observability import redact_data, redact_message

MAX_FILE = 64 * 1024 * 1024
MAX_BATCH = 256 * 1024 * 1024
PRIVATE = re.compile(r'(?i)(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|session[_ -]?id|secret|password|cookie|authorization|私钥|身份证)')
ASSIGNMENT = re.compile(r'''(?im)((?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|session[_ -]?id|secret|password|cookie|authorization)["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\r\n]+)''')
PEM = re.compile(r'-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?(?:-----END [^-\r\n]*PRIVATE KEY-----|\Z)', re.S)


def sanitize_text(value):
    text = PEM.sub('[REDACTED_PRIVATE_KEY]', str(value))
    text = ASSIGNMENT.sub(lambda m: m[1] + '[REDACTED]', text)
    text = re.sub(r'\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{12,}', '[REDACTED_TOKEN]', text)
    text = re.sub(r'(?<!\w)\d{17}[0-9Xx](?!\w)', '[REDACTED_ID]', text)
    text = re.sub(r'(?i)[A-Z]:[\\/]Users[\\/][^\\/\s]+', '<USERPROFILE>', text)
    return redact_message(text)


def sanitize_data(value):
    if isinstance(value, dict):
        return {sanitize_text(k): '[REDACTED]' if PRIVATE.search(str(k)) else sanitize_data(v)
                for k, v in redact_data(value, redact=sanitize_text).items()}
    if isinstance(value, list):
        return [sanitize_data(v) for v in value]
    return sanitize_text(value) if isinstance(value, str) else value


def sanitize_identity(value):
    """Generated protocol identifiers aren't phone numbers embedded in free text."""
    cleaned = sanitize_data(value)
    for key in ('device_id', 'installation_id', 'run_id', 'incident_id', 'continued_from'):
        item = value.get(key)
        if isinstance(item, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', item):
            cleaned[key] = item
    return cleaned


def sanitize_incident(value):
    cleaned = sanitize_identity(value)
    for original, frame in zip(value.get('frames', []), cleaned.get('frames', [])):
        for key, pattern in (('frame_id', r'[a-f0-9]{32}'), ('sha256', r'[a-f0-9]{64}'),
                             ('batch_id', r'[0-9]{6}-[a-f0-9]{12}'),
                             ('remote_path', r'截图/okww-custom/[0-9-]+/[a-zA-Z0-9_-]+/[0-9]{6}-[a-f0-9]{12}/[a-f0-9]{32}\.png')):
            item = original.get(key)
            if isinstance(item, str) and re.fullmatch(pattern, item):
                frame[key] = item
    return cleaned


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with pending.open('w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def safe_path(root, relative):
    root = Path(root).absolute()
    if any(p.is_symlink() or p.is_junction() for p in (root, *root.parents)):
        raise ValueError('diagnostic root contains links')
    root = root.resolve()
    relative = str(relative)
    parts = PurePosixPath(relative).parts
    if (not parts or '\\' in relative or ':' in relative or relative.startswith('/')
            or any(p in ('..', '.') or p.endswith((' ', '.'))
                   or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', p)
                   for p in parts)):
        raise ValueError('invalid diagnostic path')
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink() or path.is_junction():
            raise ValueError('diagnostic links are forbidden')
    if not path.resolve().is_relative_to(root):
        raise ValueError('diagnostic path escapes root')
    return path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sanitize_file(path, *, reviewed_image=False, prepared_png=False):
    path = Path(path)
    if path.is_symlink() or path.is_junction() or path.stat().st_size > MAX_FILE:
        raise ValueError('diagnostic file is linked or too large')
    suffix = path.suffix.lower()
    if suffix in ('.png', '.jpg', '.jpeg'):
        if not reviewed_image:
            raise ValueError('needs_review: image identities require review')
        if path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError('image too large')
        from PIL import Image
        from io import BytesIO
        with Image.open(path) as picture:
            if picture.width * picture.height > 32_000_000:
                raise ValueError('image dimensions too large')
            if prepared_png and picture.format == 'PNG' and picture.mode == 'RGB' and not picture.info:
                # Our frame encoder already strips metadata. Verify CRCs without
                # re-encoding ten large pre-frames on the one-second sampling path.
                picture.verify()
                return path.read_bytes()
            output = BytesIO()
            picture.convert('RGB').save(output, format='PNG')
            return output.getvalue()
    text = path.read_text(encoding='utf-8-sig')
    if suffix == '.json':
        text = json.dumps(sanitize_data(json.loads(text)), ensure_ascii=False)
    elif suffix == '.jsonl':
        text = '\n'.join(json.dumps(sanitize_data(json.loads(line)), ensure_ascii=False)
                         for line in text.splitlines() if line.strip()) + '\n'
    elif suffix in ('.log', '.txt'):
        text = sanitize_text(text)
    else:
        raise ValueError('unsupported diagnostic type')
    return text.encode('utf-8')


def validate_manifest(root, manifest):
    if not isinstance(manifest, dict) or manifest.get('schema_version') != 1 or not isinstance(manifest.get('files'), list):
        raise ValueError('unsupported diagnostic manifest')
    if not 1 <= len(manifest['files']) <= 4096:
        raise ValueError('too many diagnostic files')
    total, seen = 0, set()
    for item in manifest['files']:
        if (not isinstance(item, dict) or not isinstance(item.get('path'), str)
                or type(item.get('size')) is not int or item['size'] < 0
                or not isinstance(item.get('sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', item['sha256'])):
            raise ValueError('malformed diagnostic member')
        name = item['path']
        if (name.casefold() in seen or not name.startswith(('日志/', '截图/'))
                or Path(name).suffix not in ('.log', '.txt', '.json', '.jsonl', '.png')):
            raise ValueError('duplicate or invalid diagnostic member')
        seen.add(name.casefold())
        path = safe_path(root, name)
        size = path.stat().st_size
        total += size
        if size != item['size'] or size > MAX_FILE or total > MAX_BATCH:
            raise ValueError('diagnostic size mismatch or limit exceeded')
        if digest(path.read_bytes()) != item['sha256']:
            raise ValueError('diagnostic checksum mismatch')
    return manifest
