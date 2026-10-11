# SPDX-License-Identifier: MIT
"""Core release subset: three numeric components and optional alpha/beta revision."""
import importlib.metadata
import re


def release_key(value):
    if not isinstance(value, str):
        raise ValueError('Core release version must be text')
    match = re.fullmatch(r'([0-9]+)\.([0-9]+)\.([0-9]+)(?:(a|b)([1-9][0-9]*))?', value)
    if match is None:
        raise ValueError('Unsupported core release version: ' + value)
    major, minor, patch, channel, revision = match.groups()
    return (int(major), int(minor), int(patch), {None: 2, 'a': 0, 'b': 1}[channel],
            int(revision) if revision is not None else 0)


def require_core_version(required):
    minimum = release_key(required)
    try:
        installed = importlib.metadata.version('gameframe-runtime')
    except importlib.metadata.PackageNotFoundError as error:
        raise ValueError('This gamepack requires an installed gameframe-runtime >= ' + required) from error
    if release_key(installed) < minimum:
        raise ValueError(f'Gamepack requires gameframe-runtime >= {required}; installed {installed}')
