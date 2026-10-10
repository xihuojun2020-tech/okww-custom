# SPDX-License-Identifier: AGPL-3.0-or-later
"""Independent public HTTP notification APIs; no legacy manager or desktop input.

Images must be explicitly supplied as PNG bytes. A Future from submit() denotes
queued work; only its completed per-route result can describe delivery.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit, quote

NAME = 'Native Notifications'
DEFAULTS = {
    'Discord Notification': False, 'Discord Webhook': '',
    'Telegram Notification': False, 'Telegram Bot Token': '', 'Telegram Chat ID': '',
    'Enterprise WeChat Webhook Notification': False, 'Enterprise WeChat Webhook URL': '',
    'QQ Bot API Notification': False, 'QQ Bot API App ID': '', 'QQ Bot API Token': '',
    'QQ Bot API Channel ID': '',
    'QQ Desktop Notification (Not Reliable)': False, 'QQ Desktop Nickname': '',
    'WeChat Desktop Notification (Not Reliable)': False, 'WeChat Desktop Nickname': '',
}
SECRET_KEYS = frozenset({'Discord Webhook', 'Telegram Bot Token',
                         'Enterprise WeChat Webhook URL', 'QQ Bot API Token'})
LEGACY_ALIASES = {
    'QQ Notification': 'QQ Desktop Notification (Not Reliable)',
    'QQ Desktop Notification': 'QQ Desktop Notification (Not Reliable)',
    'QQ Nickname': 'QQ Desktop Nickname',
    'WeChat Notification': 'WeChat Desktop Notification (Not Reliable)',
    'WeChat Desktop Notification': 'WeChat Desktop Notification (Not Reliable)',
    'WeChat Nickname': 'WeChat Desktop Nickname',
}
ROUTES = {'discord': 'Discord Notification', 'telegram': 'Telegram Notification',
          'wecom': 'Enterprise WeChat Webhook Notification', 'qq-channel': 'QQ Bot API Notification'}


def masked_config(values):
    """Diagnostic snapshot, never a config update payload."""
    return {key: '<redacted>' if key in SECRET_KEYS and value else value
            for key, value in values.items()}


class NativeNotificationPreferences:
    def __init__(self, data_root):
        from src.runtime.native_config import Config
        folder = Path(data_root).resolve() / 'configs'
        legacy_path = folder / 'Notification.json'
        migrated = {}
        if not (folder / (NAME + '.json')).exists() and legacy_path.exists():
            legacy = json.loads(legacy_path.read_text(encoding='utf-8'))
            if not isinstance(legacy, dict):
                raise ValueError('Legacy Notification must be a JSON object')
            for key in DEFAULTS:
                if key in legacy: migrated[key] = legacy[key]
            for old, new in LEGACY_ALIASES.items():
                if old in legacy and new not in migrated: migrated[new] = legacy[old]
            for key, value in migrated.items():
                if type(value) is not type(DEFAULTS[key]):
                    raise ValueError('Invalid notification preference: ' + key)
        # Legacy file is retained, including provider/desktop parameters not executed.
        self.config = Config(NAME, {**DEFAULTS, **migrated}, folder=str(folder))
        self.config.default = dict(DEFAULTS)


class _DeliveryFailure(Exception):
    def __init__(self, kind, code=None):
        self.kind, self.code = kind, code


class NativeNotifications:
    def __init__(self, config, *, transport=None, sender=None, sender_icon=None):
        if transport is None:
            import requests
            transport = requests.post
        self.config, self.transport = config, transport
        self.sender, self.sender_icon = sender, sender_icon
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='native-notifications')
        self._closed = False
        self._lock = threading.Lock()

    def submit(self, title, message, png_images=()):
        with self._lock:
            if self._closed: raise RuntimeError('Notification service is closed')
            return self._executor.submit(self.send, title, message, tuple(png_images),
                                         _config=dict(self.config))

    def close(self):
        with self._lock: self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _post(self, url, *, acceptance=None, **kwargs):
        if self._closed: raise _DeliveryFailure('closed')
        try:
            # Never retain/log response text, URL-bearing exceptions or request objects.
            response = self.transport(url, timeout=30, allow_redirects=False, **kwargs)
        except Exception:
            raise _DeliveryFailure('transport') from None
        if not 200 <= response.status_code < 300:
            raise _DeliveryFailure('http', response.status_code)
        if acceptance is None: return
        try:
            data = response.json()
        except Exception:
            raise _DeliveryFailure('json') from None
        if not isinstance(data, dict): raise _DeliveryFailure('json')
        if acceptance == 'telegram':
            if data.get('ok') is not True: raise _DeliveryFailure('api')
        elif acceptance == 'wecom':
            code = data.get('errcode')
            if type(code) is not int: raise _DeliveryFailure('json')
            if code != 0: raise _DeliveryFailure('api', code)
        elif acceptance == 'qq-channel':
            if not isinstance(data.get('id'), str) or not data['id']:
                raise _DeliveryFailure('api')

    @staticmethod
    def _required(config, *keys):
        values = [config.get(key) for key in keys]
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise _DeliveryFailure('configuration')
        return [value.strip() for value in values]

    @staticmethod
    def _webhook(value):
        try:
            parsed = urlsplit(value)
        except ValueError:
            raise _DeliveryFailure('configuration') from None
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise _DeliveryFailure('configuration')
        return value

    def _deliver(self, route, config, title, message, images):
        text = f'{title}\n{message}' if title else message
        completed = 0
        if route == 'discord':
            webhook, = self._required(config, 'Discord Webhook')
            data = {'content': f'**{title}**\n{message}' if title else message}
            if self.sender: data['username'] = str(self.sender)[:80]
            if self.sender_icon: data['avatar_url'] = self.sender_icon
            files = [(f'files[{i}]', (f'notification_{i+1}.png', image, 'image/png'))
                     for i, image in enumerate(images)]
            self._post(self._webhook(webhook), data=data, files=files or None)
            return 1
        if route == 'telegram':
            token, chat = self._required(config, 'Telegram Bot Token', 'Telegram Chat ID')
            base = 'https://api.telegram.org/bot' + quote(token, safe=':')
            if text:
                self._post(base + '/sendMessage', acceptance=route, json={'chat_id': chat, 'text': text})
                completed += 1
            for image in images:
                try:
                    self._post(base + '/sendPhoto', acceptance=route, data={'chat_id': chat},
                               files={'photo': ('notification.png', image, 'image/png')})
                except _DeliveryFailure as error:
                    error.completed = completed
                    raise
                completed += 1
            return completed
        if route == 'wecom':
            webhook, = self._required(config, 'Enterprise WeChat Webhook URL')
            webhook = self._webhook(webhook)
            if text:
                self._post(webhook, acceptance=route,
                           json={'msgtype': 'markdown', 'markdown': {'content': text}})
                completed += 1
            for image in images:
                try:
                    self._post(webhook, acceptance=route, json={'msgtype': 'image', 'image': {
                        'base64': base64.b64encode(image).decode('ascii'),
                        'md5': hashlib.md5(image).hexdigest()}})
                except _DeliveryFailure as error:
                    error.completed = completed
                    raise
                completed += 1
            return completed
        app, token, channel = self._required(config, 'QQ Bot API App ID', 'QQ Bot API Token',
                                            'QQ Bot API Channel ID')
        if images: text += f'\n[{len(images)} image(s); image upload is unsupported]'
        self._post('https://api.sgroup.qq.com/channels/' + quote(channel, safe='') + '/messages',
                   acceptance=route, headers={'Authorization': f'Bot {app}.{token}'}, json={'content': text})
        return 1

    def send(self, title, message, png_images=(), *, _config=None):
        if not isinstance(title, str) or not isinstance(message, str):
            raise TypeError('Notification title and message must be strings')
        images = tuple(png_images)
        if any(not isinstance(image, bytes) or not image.startswith(b'\x89PNG\r\n\x1a\n') for image in images):
            raise ValueError('Notification images must be explicitly provided PNG bytes')
        config = dict(self.config) if _config is None else _config
        results = []
        for route, enabled_key in ROUTES.items():
            if config.get(enabled_key) is not True: continue
            result = {'route': route}
            try:
                completed = self._deliver(route, config, title, message, images)
                result.update(status='delivered' if completed else 'skipped', completed_requests=completed)
            except _DeliveryFailure as error:
                result.update(status='failed', failure=error.kind,
                              completed_requests=getattr(error, 'completed', 0))
                if error.code is not None: result['code'] = error.code
            results.append(result)
        return results
