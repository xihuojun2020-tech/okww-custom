"""Native output storage, using the data directory's configuration authority."""
from pathlib import Path

from gameframe.process_locks import data_lease
from src.account_change_lock import get_account_change_lock
from src.native_maintenance import MaintenanceCommittedError
from src.runtime import storage_bootstrap as storage
from src.runtime.diagnostic_storage import storage_path
from src.storage import resolve_config_backup_dir


class NativeStorageCommittedError(MaintenanceCommittedError):
    def __init__(self, error):
        self.operation = 'storage'
        RuntimeError.__init__(self, f'输出目录配置已提交，但迁移收尾失败；请重新加载管理窗口：{error}')


class NativeStorageService:
    def __init__(self, data_root, *, quiesce=None):
        self.root = Path(data_root).resolve()
        self.quiesce = quiesce

    def paths(self):
        defaults = {kind: self.root / kind for kind in storage.KINDS}
        defaults.update(diagnostics=self.root / 'okww监控室/diagnostics',
            CompletionEvidence=self.root / 'okww监控室/CompletionEvidence',
            screenshots=self.root / 'okww监控室', recordings=self.root / 'okww监控室',
            backups=resolve_config_backup_dir(self.root), exports=self.root / 'export_accounts')
        return {'data': self.root, 'runtime': self.root / 'okww监控室/runtime',
                **{kind: storage_path(kind, path, repo=self.root).resolve()
                                   for kind, path in defaults.items()}}

    def preview(self, destination):
        target = storage.local_path(destination)
        if target.anchor.casefold() != self.root.anchor.casefold():
            raise ValueError('目标必须位于数据根所在本机磁盘')
        if target == self.root or target.is_relative_to(self.root) or self.root.is_relative_to(target):
            raise ValueError('输出目录必须位于数据根之外')
        paths = self.paths()
        sources = {kind: {'source': str(paths[kind]), 'history': []} for kind in storage.KINDS}
        if paths['screenshots'] == paths['recordings'] == self.root / 'okww监控室':
            sources['screenshots']['inventory'] = {'include_files': ['*.png'], 'include_directories': ['log']}
            sources['recordings']['inventory'] = {'exclude_files': ['*.png'],
                'exclude_directories': ['log', 'diagnostics', 'CompletionEvidence', 'runtime']}
        for row in sources.values():
            source = storage.local_path(row['source'])
            if source == target or target.is_relative_to(source) or source.is_relative_to(target):
                raise ValueError(f'迁移来源与目标相互包含：{source}')
        journal = storage.read_json(target / 'migration/progress.json', {})
        if journal and journal.get('repo') != str(self.root):
            raise ValueError('目标属于其他安装实例')
        if target.exists() and not journal and any(target.iterdir()):
            raise ValueError('目标存在未归属资料，不能覆盖')
        inventories = {kind: storage.inventory(row['source'], row.get('inventory')) for kind, row in sources.items()}
        return {'data_root': str(self.root), 'destination': str(target), 'sources': sources,
            'configuration': storage.read_json(self.root / 'configs/runtime_storage.json', {}),
            'files': sum(len(items) for items in inventories.values()),
            'bytes': sum(size for items in inventories.values() for size, _ in items.values()),
            'originals_retained': True, 'scope': 'outputs'}

    def migrate(self, preview):
        with data_lease(self.root, exclusive=True), get_account_change_lock(self.root / 'configs'):
            current = self.preview(preview['destination'])
            if any(current[key] != preview[key] for key in ('data_root','sources','configuration')):
                raise ValueError('输出目录预览已变化，请重新预览')
            config = self.root / 'configs/runtime_storage.json'
            before = storage.read_json(config, {})
            try:
                result = storage.migrate(self.root, preview['destination'], sources=current['sources'],
                                         quiesce=self.quiesce)
            except Exception as error:
                after = storage.read_json(config, {})
                if after != before and after.get('root') == preview['destination']:
                    raise NativeStorageCommittedError(error) from error
                raise
            return {'committed': True, 'scope': 'outputs', 'originals_retained': True,
                    'storage': result, 'paths': self.paths()}
