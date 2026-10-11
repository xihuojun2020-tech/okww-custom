# SPDX-License-Identifier: MIT
"""Three update choices over a trusted package's separate device-free command."""
import json
from pathlib import Path
import threading
import sys

from gameframe.launcher_options import save_options
from gameframe.packages import PackageManifest,verify_index
from gameframe.process_locks import package_lease

POLICIES=('MANUAL_UPDATE','AUTO_UPDATE','AUTO_UPDATE_PRE_RELEASE')
DEFAULT_POLICY='AUTO_UPDATE'
LABELS=('手动更新','自动更新（正式版）','自动更新（含预发布）')


def load_policy(path,legacy=None):
    path=Path(path)
    policy=json.loads(path.read_text(encoding='utf-8'))['policy'] if path.exists() else (legacy if legacy is not None else DEFAULT_POLICY)
    if policy not in POLICIES:raise ValueError('Unknown native update policy')
    return policy


def managed_install_command():
    return [sys.executable,'-m','gameframe.managed_install','initialize',
        '--managed-root','<per-user-managed-root>','--bootstrap-pythonw','<stable-absolute-pythonw.exe>',
        '--base-python','<stable-absolute-python.exe>','--data-dir','<existing-launcher-data-root>']


class UpdateCoordinator:
    def __init__(self,*,data_dir,managed_root=None,controller=None):
        if controller is None:
            from gameframe.controller import Controller
            controller=Controller()
        self.controller=controller
        self.data_dir=Path(data_dir)
        self.managed_root=Path(managed_root).resolve() if managed_root is not None else None
        self.startup_checked=False

    def startup(self,manifest,policy):
        if self.startup_checked:return None
        self.startup_checked=True
        if policy=='MANUAL_UPDATE':return {'event':'native-update','status':'manual'}
        return self.execute(manifest,policy,action='prepare',automatic=True)

    def execute(self,manifest,policy,*,action='check',automatic=False):
        if policy not in POLICIES:raise ValueError('Unknown native update policy')
        if automatic and policy=='MANUAL_UPDATE':return {'event':'native-update','status':'manual'}
        if not getattr(manifest,'supports_managed_updates',False):
            return {'event':'native-update','status':'unsupported','message':'This package does not declare managed updates.'}
        if not (manifest.root/'files.json').is_file():
            return {'event':'native-update','status':'source_checkout',
                'message':'Source checkouts cannot update their environment; use the complete managed installation entry.'}
        self.controller.assert_idle()
        with package_lease(manifest.root):
            current=PackageManifest.read(manifest.root)
            identity=lambda item:(item.id,item.version,getattr(item,'channel','stable'),
                getattr(item,'revision',0),getattr(item,'required_core_version',None))
            if identity(current)!=identity(manifest):raise ValueError('Package changed before update launch')
            verify_index(manifest.root,required=True)
            hook=getattr(current.load(),'automatic_update_command',None)
            if hook is None:raise ValueError('Managed-update capability has no package command')
            launch=hook(self.data_dir/manifest.id)
            command=list(launch['command'])+['--policy',policy,action]
            if automatic:command.append('--automatic')
            if self.managed_root is not None:command.extend(['--managed-root',str(self.managed_root)])
            process=self.controller._launch(command,launch['cwd'],dict(launch['env']),'update',False)
        output,_=process.communicate()
        self.controller.assert_idle()
        self.controller.close()  # Child already exited; this cannot stop a running owner.
        replies=[json.loads(line) for line in output.splitlines() if line.startswith('{')]
        response=next((item for item in reversed(replies) if item.get('event')=='native-update'),None)
        if response is None:raise RuntimeError(f'Update process exited without a response ({process.returncode})')
        if process.returncode!=0 or response['status']=='failed':
            raise RuntimeError(response.get('message',f'Update process exited with code {process.returncode}'))
        return response


def attach_update_controls(window,form,*,managed_root=None,coordinator=None):
    """Insert controls; startup() is called after initial package selection, never configuration setup."""
    from PySide6.QtWidgets import QComboBox,QHBoxLayout,QLabel,QPushButton,QWidget
    managed=Path(managed_root).resolve() if managed_root is not None else None
    policy_path=(managed if managed is not None else window._context_path.parent)/'update-policy.json'
    legacy=window._launcher_context.get('update_policy')
    policy=load_policy(policy_path,legacy)
    if not policy_path.exists() and legacy is not None:
        if managed is not None:
            from gameframe.managed_install import set_update_policy
            set_update_policy(managed,policy)
        else:save_options(policy_path,{'policy':policy})
    combo=QComboBox()
    for label,value in zip(LABELS,POLICIES):combo.addItem(label,value)
    combo.setCurrentIndex(POLICIES.index(policy))
    check=QPushButton('检查更新');prepare=QPushButton('下载完整环境并待下次启动应用')
    retry=QPushButton('重新尝试待应用更新');retry.hide()
    status=QLabel();status.setWordWrap(True)
    row=QWidget();layout=QHBoxLayout(row)
    for control in (check,prepare,retry):layout.addWidget(control)
    form.addRow('更新策略',combo);form.addRow(row);form.addRow(status)
    bindings=UpdateBindings(window,combo,check,prepare,retry,status,policy_path,managed,
        coordinator or UpdateCoordinator(data_dir=window.data_dir,managed_root=managed))
    combo.currentIndexChanged.connect(bindings.save_policy)
    check.clicked.connect(lambda:bindings.submit('check'))
    prepare.clicked.connect(lambda:bindings.submit('prepare'))
    retry.clicked.connect(lambda:bindings.submit('retry'))
    window.update_policy=combo
    window.managed_update_bindings=bindings
    bindings.refresh()
    return bindings


class UpdateBindings:
    def __init__(self,window,combo,check,prepare,retry,status,policy_path,managed_root,coordinator):
        self.window,self.combo,self.check,self.prepare,self.retry,self.status=window,combo,check,prepare,retry,status
        self.policy_path,self.managed_root,self.coordinator=policy_path,managed_root,coordinator
        self.policy=combo.currentData()
        self.thread=None
        self.busy=False
        self.error_shown=False
        self.install_entry_shown=False
        self.labels=window._launcher_labels
        self.status_key=None
        self.status_values={}

    def set_status(self,text,**values):
        self.status_key,self.status_values=text,values
        self._render_status()

    def _render_status(self):
        text=self.labels.get(self.status_key,self.status_key)
        values=self.status_values
        self.status.setText(text.format(**values) if values else text)

    def localize(self,labels):
        self.labels=labels
        for index,label in enumerate(LABELS):self.combo.setItemText(index,labels.get(label,label))
        for control,label in ((self.check,'检查更新'),(self.prepare,'下载完整环境并待下次启动应用'),
                              (self.retry,'重新尝试待应用更新')):
            control.setText(labels.get(label,label))
        if self.status_key is not None:self._render_status()

    def wait(self):
        if self.thread is not None:self.thread.join()

    def refresh(self):
        manifest=self.window._manifest()
        supported=manifest is not None and getattr(manifest,'supports_managed_updates',False)
        for control in (self.combo,self.check):control.setEnabled(supported and not self.busy)
        self.prepare.setEnabled(False)
        self.retry.setEnabled(not self.busy)
        if not supported:self.set_status('当前游戏包没有完整环境更新入口。')
        elif self.managed_root is None:
            self.set_status('当前环境未受管理；可检查发布，完整更新须先迁入受管理环境。')
            if not self.install_entry_shown:
                import subprocess
                self.window.output.appendPlainText(self.window._launcher_labels.get(
                    '完整环境安装入口（请填入长期路径）：','完整环境安装入口（请填入长期路径）：')+
                    subprocess.list2cmdline(managed_install_command()))
                self.install_entry_shown=True
        elif (self.managed_root/'pending.json').exists():self.set_status('完整环境候选已保存，等待下一次正常启动。')
        if not self.error_shown and self.managed_root is not None:
            error_path=self.managed_root/'last-update-error.json'
            if error_path.exists():
                error=json.loads(error_path.read_text(encoding='utf-8'))
                self.error_shown=True
                self.window.output.appendPlainText(self.window._launcher_labels.get(
                    '上次完整环境更新失败：','上次完整环境更新失败：')+error['message'])
                self.set_status('上次更新未完成：{error}',error=error['message'])
                self.retry.setVisible(error.get('phase')=='precommit')

    def save_policy(self,*_):
        value=self.combo.currentData()
        try:
            if self.managed_root is not None:
                from gameframe.managed_install import set_update_policy
                set_update_policy(self.managed_root,value)
            else:save_options(self.policy_path,{'policy':value})
        except Exception as error:
            self.combo.blockSignals(True);self.combo.setCurrentIndex(POLICIES.index(self.policy));self.combo.blockSignals(False)
            self.window._error(error)
            return
        self.policy=value
        self.set_status('更新策略已保存；不会停止当前任务。')

    def startup(self):
        if self.coordinator.startup_checked:return
        manifest=self.window._manifest()
        if manifest is None or not getattr(manifest,'supports_managed_updates',False):return
        if self.policy=='MANUAL_UPDATE':
            self.coordinator.startup_checked=True
            self.set_status('手动更新：不会自动检查或下载。')
            return
        self.submit('prepare',automatic=True,startup=True)

    def submit(self,action,*,automatic=False,startup=False):
        if self.busy or self.window._closing:return
        manifest=self.window._manifest()
        self.busy=True
        for control in (self.check,self.prepare,self.retry):control.setEnabled(False)
        self.set_status('正在检查并准备完整环境…' if action=='prepare' else '正在处理更新请求…')
        policy=self.policy
        self.coordinator.data_dir=Path(self.window.data_dir)
        def work():
            try:
                result=(self.coordinator.startup(manifest,policy) if startup else
                        self.coordinator.execute(manifest,policy,action=action,automatic=automatic))
                event=('managed-update-result',result)
            except Exception as error:event=('managed-update-error',error)
            self.window._events.put(event)
        self.thread=threading.Thread(target=work,daemon=True)
        self.thread.start()

    def handle(self,kind,value):
        if kind not in ('managed-update-result','managed-update-error'):return False
        self.busy=False
        self.refresh()
        if kind=='managed-update-error':
            self.window._error(value);self.set_status('完整环境更新失败：{error}',error=str(value))
            return True
        if value is None:return True
        messages={'manual':'手动更新：不会自动检查或下载。','up_to_date':'检查完成，当前发行已是最新。',
            'no_release':'已配置源尚未发布允许通道。','available':'检查到新发行，可下载完整环境。',
            'pending':'完整环境已下载并验证，待下一次正常启动应用。',
            'retry-requested':'已允许重试待应用候选；下一次正常启动处理。',
            'source_unconfigured':'独立游戏包更新源尚未配置，不会访问默认地址。',
            'disabled':'已配置的更新源处于停用状态。',
            'needs-managed-installation':'完整更新须先迁入受管理环境，当前环境保持不变。',
            'source_checkout':'当前为源码目录，请使用完整环境安装入口。',
            'unsupported':'当前游戏包没有完整环境更新入口。'}
        self.set_status(messages.get(value['status'],value.get('message',value['status'])))
        self.prepare.setEnabled(value['status']=='available' and self.managed_root is not None)
        if 'install_command' in value:
            import subprocess
            if not self.install_entry_shown:
                self.window.output.appendPlainText(self.window._launcher_labels.get(
                    '完整环境安装入口（请填入长期路径）：','完整环境安装入口（请填入长期路径）：')+
                    subprocess.list2cmdline(value['install_command']))
                self.install_entry_shown=True
        return True
