# SPDX-License-Identifier: AGPL-3.0-or-later
"""Three native update policies over the existing authenticated release transport."""

from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
import re
import tempfile
import urllib.parse

from src.runtime.nas_location import DEFAULT_TARGET, candidates
from src.update.lan_transport import FileShareClient, HttpsPinnedClient, ReleaseNotPublished
from src.update.native_release_manifest import (NativeReleaseError, artifact_path,
    artifacts, identity_key, parse_release, validate_artifacts)


MANUAL_UPDATE = 'MANUAL_UPDATE'
AUTO_UPDATE = 'AUTO_UPDATE'
AUTO_UPDATE_PRE_RELEASE = 'AUTO_UPDATE_PRE_RELEASE'
UPDATE_METHODS = (MANUAL_UPDATE, AUTO_UPDATE, AUTO_UPDATE_PRE_RELEASE)
DEFAULT_UPDATE_METHOD = AUTO_UPDATE


@dataclass(frozen=True)
class NativeReleaseAvailability:
    status: str
    release: dict | None = None
    unpublished_channels: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerifiedRelease:
    bundle: dict
    artifact_root: Path


class NativeReleaseService:
    def __init__(self, *, package_id, data_dir, source_root=None,
                 certificate_sha256='', ca_file='', enabled=True, transport=None):
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', package_id):
            raise NativeReleaseError('Invalid selected package ID')
        source_root = source_root or DEFAULT_TARGET + rf'\GameFrame-Packages\{package_id}'
        self.source_root = candidates(source_root)[0].rstrip('/\\')
        self.is_unc = self.source_root.startswith('\\\\')
        if self.is_unc:
            path = PureWindowsPath(self.source_root)
            if not path.is_absolute() or any(part in ('.', '..') for part in self.source_root.replace('/', '\\').split('\\')):
                raise NativeReleaseError('Invalid UNC release root')
        else:
            url = HttpsPinnedClient._url(self.source_root)
            if url.query:
                raise NativeReleaseError('Release root cannot contain a URL query')
            if not re.fullmatch(r'[0-9a-f]{64}', certificate_sha256):
                raise NativeReleaseError('HTTPS release root requires its certificate pin')
        self.package_id = package_id
        self.data_dir = Path(data_dir).resolve()
        self.enabled, self.transport = enabled, transport
        self.certificate_sha256, self.ca_file = certificate_sha256, ca_file

    def _transport(self):
        if self.transport is None:
            self.transport = (FileShareClient() if self.is_unc else
                HttpsPinnedClient(self.certificate_sha256, Path(self.ca_file) if self.ca_file else None))
        return self.transport

    def _source(self, channel, relative):
        if self.is_unc:
            return self.source_root + '\\' + channel + '\\' + relative.replace('/', '\\')
        base = self.source_root + '/' + channel + '/'
        source = urllib.parse.urljoin(base, relative)
        if not source.startswith(base):
            raise NativeReleaseError('Artifact address escapes its release source')
        return source

    def check(self, current, policy=DEFAULT_UPDATE_METHOD, *, automatic=True):
        if policy not in UPDATE_METHODS:
            raise NativeReleaseError('Unsupported native update policy')
        if not self.enabled:
            return NativeReleaseAvailability('disabled')
        if automatic and policy == MANUAL_UPDATE:
            return NativeReleaseAvailability('manual')
        current_key = identity_key(current)
        channels = ('stable',) if policy == AUTO_UPDATE else ('stable', 'beta', 'alpha')
        releases = []
        unpublished = []
        for channel in channels:
            try:
                data = self._transport().get_bytes(self._source(channel, 'latest.json'),
                    max_bytes=65536, deadline_seconds=15.0)
            except ReleaseNotPublished:
                unpublished.append(channel)
                continue
            releases.append(parse_release(data, package_id=self.package_id, expected_channel=channel))
        if not releases:
            return NativeReleaseAvailability('no_release', unpublished_channels=tuple(unpublished))
        newest = max(releases, key=identity_key)
        if identity_key(newest) <= current_key:
            return NativeReleaseAvailability('up_to_date', unpublished_channels=tuple(unpublished))
        return NativeReleaseAvailability('available', newest, tuple(unpublished))

    def download(self, release):
        # A public handoff may originate from an explicit check or persisted request.
        import json
        bundle = parse_release(json.dumps(release).encode('utf-8'), package_id=self.package_id)
        staging = self.data_dir / 'configs/native-release-staging'
        staging.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='download-', dir=staging) as temporary:
            pending = Path(temporary).resolve()
            for artifact in artifacts(bundle):
                self._transport().download(self._source(bundle['channel'], artifact['path']),
                    artifact_path(pending, artifact), expected_size=artifact['size'],
                    expected_sha256=artifact['sha256'])
            validate_artifacts(bundle, pending)
            # Move only fully verified trees out of TemporaryDirectory cleanup.
            ready = pending.with_name('verified-' + pending.name.removeprefix('download-'))
            pending.rename(ready)
        return VerifiedRelease(bundle, ready)
