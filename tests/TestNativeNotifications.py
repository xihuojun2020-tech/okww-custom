"""HTTP contract fixtures: no real requests, input, OCR, windows or messenger."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace

from src.runtime import native_notifications as module

PNG = b'\x89PNG\r\n\x1a\nfixture'


class NotificationTests(unittest.TestCase):
    def configured(self):
        return dict(module.DEFAULTS, **{
            'Discord Notification': True, 'Discord Webhook': 'https://discord.test/webhooks/secret',
            'Telegram Notification': True, 'Telegram Bot Token': '123:telegram-secret', 'Telegram Chat ID': '456',
            'Enterprise WeChat Webhook Notification': True,
            'Enterprise WeChat Webhook URL': 'https://wecom.test/send?key=wecom-secret',
            'QQ Bot API Notification': True, 'QQ Bot API App ID': '123',
            'QQ Bot API Token': 'qq-secret', 'QQ Bot API Channel ID': '789'})

    def test_all_payloads_and_api_acceptance(self):
        calls = []
        def transport(url, **kwargs):
            calls.append((url, kwargs))
            data = {'ok': True} if 'telegram.org' in url else {'id': 'message-id'} if 'sgroup' in url else {'errcode': 0}
            return SimpleNamespace(status_code=200, json=lambda: data)
        service = module.NativeNotifications(self.configured(), transport=transport, sender='fixture')
        self.addCleanup(service.close)
        result = service.send('title', 'message', [PNG])
        self.assertEqual([item['status'] for item in result], ['delivered'] * 4)
        self.assertEqual([item['completed_requests'] for item in result], [1, 2, 2, 1])
        self.assertEqual(len(calls), 6)
        self.assertEqual(calls[0][1]['data']['content'], '**title**\nmessage')
        self.assertEqual(calls[0][1]['files'][0][1][1], PNG)
        self.assertEqual(calls[1][1]['json'], {'chat_id': '456', 'text': 'title\nmessage'})
        self.assertTrue(calls[2][0].endswith('/sendPhoto'))
        self.assertEqual(calls[4][1]['json']['image'],
                         {'base64': base64.b64encode(PNG).decode(), 'md5': hashlib.md5(PNG).hexdigest()})
        self.assertEqual(calls[5][1]['headers']['Authorization'], 'Bot 123.qq-secret')
        self.assertIn('image upload is unsupported', calls[5][1]['json']['content'])
        for _, kwargs in calls:
            self.assertEqual(kwargs['timeout'], 30)
            self.assertFalse(kwargs['allow_redirects'])

    def test_disabled_and_desktop_do_not_execute(self):
        def forbidden(*args, **kwargs): self.fail('Disabled route called transport')
        config = dict(module.DEFAULTS, **{'QQ Desktop Notification (Not Reliable)': True})
        service = module.NativeNotifications(config, transport=forbidden)
        self.addCleanup(service.close)
        self.assertEqual(service.send('', 'test'), [])
        config['QQ Desktop Notification (Not Reliable)'] = False
        config['Discord Notification'] = 'False'
        self.assertEqual(service.send('', 'test'), [])

    def test_transport_http_json_failure_and_secret_redaction(self):
        config = self.configured()
        def transport(url, **kwargs):
            if 'discord' in url: raise OSError('secret:' + url)
            if 'telegram' in url: return SimpleNamespace(status_code=401, json=lambda: {'token': 'secret'})
            if 'wecom' in url: return SimpleNamespace(status_code=200, json=lambda: {'errcode': 40058, 'errmsg': url})
            return SimpleNamespace(status_code=200, json=lambda: {'code': 123, 'message': 'qq-secret'})
        service = module.NativeNotifications(config, transport=transport)
        self.addCleanup(service.close)
        result = service.send('', 'test')
        self.assertEqual([item['failure'] for item in result], ['transport', 'http', 'api', 'api'])
        self.assertEqual(result[1]['code'], 401)
        self.assertEqual(result[2]['code'], 40058)
        serialized = json.dumps(result) + json.dumps(module.masked_config(config))
        for key in module.SECRET_KEYS: self.assertNotIn(config[key], serialized)
        service.transport = lambda *args, **kwargs: SimpleNamespace(status_code=200, json=lambda: [])
        self.assertEqual(service.send('', 'test')[1]['failure'], 'json')

    def test_partial_delivery_is_failure_not_success(self):
        config = dict(module.DEFAULTS, **{'Telegram Notification': True,
                       'Telegram Bot Token': 'secret', 'Telegram Chat ID': 'chat'})
        count = []
        def transport(*args, **kwargs):
            count.append(True)
            return SimpleNamespace(status_code=200, json=lambda: {'ok': len(count) == 1})
        service = module.NativeNotifications(config, transport=transport)
        self.addCleanup(service.close)
        self.assertEqual(service.send('', 'text', [PNG]),
                         [{'route': 'telegram', 'status': 'failed', 'failure': 'api', 'completed_requests': 1}])
        self.assertEqual(len(count), 2)

    def test_migration_preserves_false_and_legacy_file(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'configs'
            folder.mkdir()
            old = folder / 'Notification.json'
            raw = json.dumps({'Discord Notification': False, 'Discord Webhook': 'secret',
                              'QQ Notification': True, 'QQ Desktop Notification (Not Reliable)': False,
                              'QQ Nickname': 'contact', 'unknown-provider-json': {'token': 'legacy'}})
            old.write_text(raw, encoding='utf-8')
            first = module.NativeNotificationPreferences(root)
            self.assertIs(first.config['Discord Notification'], False)
            self.assertIs(first.config['QQ Desktop Notification (Not Reliable)'], False)
            self.assertEqual(first.config['QQ Desktop Nickname'], 'contact')
            self.assertEqual(old.read_text(encoding='utf-8'), raw)
            old.write_text('{}', encoding='utf-8')
            self.assertEqual(module.NativeNotificationPreferences(root).config['Discord Webhook'], 'secret')

    def test_queue_is_not_delivery_and_close_cancels_queued(self):
        started, release, closing = threading.Event(), threading.Event(), threading.Event()
        def transport(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(2))
            return SimpleNamespace(status_code=204)
        config = dict(module.DEFAULTS, **{'Discord Notification': True,
                                          'Discord Webhook': 'https://discord.test/secret'})
        service = module.NativeNotifications(config, transport=transport)
        first = service.submit('', 'test')
        self.assertTrue(started.wait(2))
        second = service.submit('', 'queued')
        second.add_done_callback(lambda future: closing.set())
        self.assertFalse(first.done())
        self.assertFalse(second.done())
        def close():
            service.close()
        thread = threading.Thread(target=close)
        thread.start()
        self.assertTrue(closing.wait(2))
        release.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(second.cancelled())
        self.assertEqual(first.result()[0]['status'], 'delivered')
        with self.assertRaisesRegex(RuntimeError, 'closed'): service.submit('', 'late')


if __name__ == '__main__': unittest.main()
