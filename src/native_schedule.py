"""Windows interactive-user schedules for explicit GameFrame installations."""
import hashlib
import json
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

NS = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
ET.register_namespace('', NS)


def current_user():
    import win32api
    return win32api.GetUserNameEx(2)


def schedulable_tasks(schema):
    tasks = schema['tasks'] if isinstance(schema, dict) else schema
    return [task for task in tasks if task['kind'] == 'one-shot'
            and task.get('visible', True) and task.get('support_schedule_task', False)]


class NativeSchedule:
    folder = '\\GameFrame'

    def __init__(self, package, data_dir, *, core_dir=None, interpreter=None, user=None, service=None):
        import gameframe
        self.package = str(Path(package).resolve())
        self.data_dir = str(Path(data_dir).resolve())
        self.core_dir = str(Path(core_dir or Path(gameframe.__file__).resolve().parent.parent).resolve())
        self.interpreter = str(Path(interpreter or sys.executable).resolve())
        self.user = user or current_user()
        self.service = service
        identity = json.dumps([self.package.casefold(), self.data_dir.casefold(), self.user.casefold()])
        self.prefix = 'gf-' + hashlib.sha256(identity.encode()).hexdigest()[:16] + '-'

    def launcher_device(self):
        path = Path(self.data_dir) / 'launcher.json'
        return json.loads(path.read_text(encoding='utf-8'))['device'] if path.exists() else {}

    def preview(self, task_id, device, *, start, trigger='daily', interval=1, enabled=True, timeout_hours=0):
        if not isinstance(device, dict) or not device or not device.get('type'):
            raise ValueError('An explicit device JSON with type is required')
        if trigger not in ('once', 'daily', 'weekly', 'monthly', 'days', 'hours'):
            raise ValueError('Unknown schedule trigger')
        if trigger in ('days', 'hours') and interval < 1:
            raise ValueError('Schedule interval must be positive')
        start = datetime.fromisoformat(start).isoformat(timespec='seconds')
        argv = ['-m', 'gameframe', 'run', self.package, '--task', task_id,
                '--data-dir', self.data_dir, '--device', json.dumps(device, ensure_ascii=False)]
        arguments = subprocess.list2cmdline(argv)
        binding = dict(package=self.package, data_dir=self.data_dir, task_id=task_id,
                       device=device, start=start, trigger=trigger, interval=interval,
                       enabled=enabled, timeout_hours=timeout_hours)
        root = ET.Element(f'{{{NS}}}Task', version='1.2')
        def node(parent, tag, text=None):
            child = ET.SubElement(parent, f'{{{NS}}}{tag}')
            if text is not None:
                child.text = str(text)
            return child
        registration = node(root, 'RegistrationInfo')
        node(registration, 'Description', json.dumps(binding, ensure_ascii=False))
        triggers = node(root, 'Triggers')
        calendar = trigger in ('daily', 'weekly', 'monthly', 'days')
        timing = node(triggers, 'CalendarTrigger' if calendar else 'TimeTrigger')
        if trigger == 'hours':
            repetition = node(timing, 'Repetition')
            node(repetition, 'Interval', f'PT{interval}H')
            node(repetition, 'StopAtDurationEnd', 'false')
        node(timing, 'StartBoundary', start)
        node(timing, 'Enabled', 'true')
        if trigger in ('daily', 'days'):
            node(node(timing, 'ScheduleByDay'), 'DaysInterval', interval if trigger == 'days' else 1)
        elif trigger == 'weekly':
            weekly = node(timing, 'ScheduleByWeek')
            node(weekly, 'WeeksInterval', 1)
            node(node(weekly, 'DaysOfWeek'), 'Monday')
        elif trigger == 'monthly':
            monthly = node(timing, 'ScheduleByMonth')
            node(node(monthly, 'DaysOfMonth'), 'Day', 1)
            months = node(monthly, 'Months')
            for month in ('January February March April May June July August September October November December').split():
                node(months, month)
        principal = node(node(root, 'Principals'), 'Principal')
        principal.set('id', 'Author')
        node(principal, 'UserId', self.user)
        node(principal, 'LogonType', 'InteractiveToken')
        node(principal, 'RunLevel', 'HighestAvailable')
        settings = node(root, 'Settings')
        for key, value in dict(MultipleInstancesPolicy='IgnoreNew', DisallowStartIfOnBatteries='false',
                               StopIfGoingOnBatteries='true', AllowHardTerminate='true',
                               StartWhenAvailable='false', AllowStartOnDemand='true',
                               Enabled=str(enabled).lower(), ExecutionTimeLimit=f'PT{timeout_hours}H' if timeout_hours else 'PT0S').items():
            node(settings, key, value)
        actions = node(root, 'Actions')
        actions.set('Context', 'Author')
        action = node(actions, 'Exec')
        node(action, 'Command', self.interpreter)
        node(action, 'Arguments', arguments)
        node(action, 'WorkingDirectory', self.core_dir)
        return dict(xml=ET.tostring(root, encoding='unicode'), command=self.interpreter,
                    arguments=arguments, argv=argv, binding=binding)

    def _service(self):
        if self.service is None:
            import win32com.client
            self.service = win32com.client.Dispatch('Schedule.Service')
            self.service.Connect()
        return self.service

    def list(self):
        service = self._service()
        # Enumerating root folders avoids treating an absent owned folder as a COM failure.
        folders = service.GetFolder('\\').GetFolders(0)
        folder = next((entry for entry in folders if entry.Path == self.folder), None)
        if folder is None:
            return []
        result = []
        for task in folder.GetTasks(0):
            if not task.Name.startswith(self.prefix):
                continue
            root = ET.fromstring(task.Xml)
            binding = json.loads(root.findtext(f'{{{NS}}}RegistrationInfo/{{{NS}}}Description'))
            if binding['package'] != self.package or binding['data_dir'] != self.data_dir:
                raise ValueError('Schedule ownership binding does not match')
            result.append(dict(name=task.Name, binding=binding, enabled=task.Enabled,
                               next_run=str(task.NextRunTime), last_result=task.LastTaskResult, xml=task.Xml))
        return result

    def create(self, preview, *, name=None):
        name = name or self.prefix + uuid.uuid4().hex
        if not name.startswith(self.prefix):
            raise ValueError('Schedule is outside this installation')
        service = self._service()
        root = service.GetFolder('\\')
        folder = next((entry for entry in root.GetFolders(0) if entry.Path == self.folder), None)
        if folder is None:
            folder = root.CreateFolder(self.folder)
        folder.RegisterTask(name, preview['xml'], 6, self.user, None, 3)
        return name

    def delete(self, name):
        if not name.startswith(self.prefix):
            raise ValueError('Schedule is outside this installation')
        self._service().GetFolder(self.folder).DeleteTask(name, 0)
