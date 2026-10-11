# SPDX-License-Identifier: AGPL-3.0-or-later
"""Device-free paired release checks and managed preparation; never hot-switch core."""
import argparse
import json
from pathlib import Path
import sys

POLICIES=('MANUAL_UPDATE','AUTO_UPDATE','AUTO_UPDATE_PRE_RELEASE')


def _source_config(data_dir):
    path=Path(data_dir)/'configs/gamepack-update.json'
    if not path.is_file():return None
    from src.update.lan_service import LanUpdateConfig
    config=LanUpdateConfig.load(path)
    if not config.enabled:return {'enabled':False}
    suffix='\\stable\\latest.json' if config.manifest_url.startswith('\\\\') else '/stable/latest.json'
    if not config.manifest_url.endswith(suffix):
        raise ValueError('Configured gamepack source must identify stable/latest.json')
    return {'enabled':True,'source_root':config.manifest_url[:-len(suffix)],
            'certificate_sha256':config.certificate_sha256,'ca_file':config.ca_file}


def _installation(root,data_dir,package_id):
    root=Path(root).resolve()
    value=json.loads((root/'installation.json').read_text(encoding='utf-8'))
    if value['managed_root']!=str(root):raise ValueError('Managed installation root changed')
    from gameframe.launcher_context import load_context,local_root
    launcher_root=Path(value['data_dir'])
    context=load_context(launcher_root/'launcher-context.json')
    effective_root=local_root(context.get('data_root',launcher_root.resolve()))
    if Path(data_dir).resolve()!=(effective_root/package_id).resolve():
        raise ValueError('Update data directory differs from the managed package data root')
    return root,value


def migration_entry():
    from gameframe.update_controls import managed_install_command
    return managed_install_command()


def execute(args,*,service_factory=None,prepare=None):
    manifest=json.loads(Path(args.manifest).read_text(encoding='utf-8'))
    package_id=manifest['id']
    current={'version':manifest['version'],'channel':manifest.get('channel','stable'),'revision':manifest.get('revision',0)}
    event={'event':'native-update','action':args.action,'policy':args.policy,
           'automatic':args.automatic,'package_id':package_id,'current':current}
    if args.automatic and args.policy=='MANUAL_UPDATE':
        return {**event,'status':'manual','message':'Manual policy: no automatic source check.'}
    managed=None
    if args.managed_root is not None:
        managed,installation=_installation(args.managed_root,args.data_dir,package_id)
    if args.action=='retry':
        if managed is None:raise ValueError('Retry requires an explicit managed installation')
        from gameframe.managed_install import request_pending_retry
        request_pending_retry(managed)
        return {**event,'status':'retry-requested','message':'Pending retry will run at the next normal launch.'}
    if args.automatic and managed is None:
        return {**event,'status':'needs-managed-installation','install_command':migration_entry(),
            'message':'Automatic paired updates require the complete managed environment installation.'}
    source=_source_config(args.data_dir)
    if source is None:
        return {**event,'status':'source_unconfigured',
            'message':'Configure the independent gamepack release source before checking updates.'}
    if not source['enabled']:return {**event,'status':'disabled','message':'The configured release source is disabled.'}
    if service_factory is None:
        from src.update.native_release_service import NativeReleaseService
        service_factory=NativeReleaseService
    service=service_factory(package_id=package_id,data_dir=args.data_dir,**source)
    availability=service.check(current,args.policy,automatic=args.automatic)
    event.update(status=availability.status,source=service.source_root,
        unpublished_channels=list(availability.unpublished_channels))
    if availability.release is None:return event
    event['release']=availability.release
    if args.action=='check':
        if managed is None:
            event.update(install_command=migration_entry(),
                message='Release available; complete managed environment installation is required to apply it.')
        return event
    if managed is None:
        return {**event,'status':'needs-managed-installation','install_command':migration_entry(),
            'message':'This environment has no managed ownership; no artifacts were downloaded or installed.'}
    pending_path=managed/'pending.json'
    if pending_path.exists():
        from gameframe.managed_install import atomic_json
        from gameframe.managed_bootstrap import check_ready
        from gameframe.process_locks import _file_lease
        with _file_lease(managed/'.leases/switch.lock',True):
            pointer=json.loads(pending_path.read_text(encoding='utf-8'))
            if pointer['bundle']==availability.release:
                check_ready(managed,pointer)
                if not args.automatic and pointer['automatic']:
                    pointer['automatic']=False
                    atomic_json(pending_path,pointer)
                return {**event,'status':'pending','environment':pointer['environment'],
                    'message':'Verified paired environment remains pending for the next normal launch.'}
    verified=service.download(availability.release)
    if prepare is None:
        from gameframe.managed_install import prepare_environment
        prepare=prepare_environment
    pointer=prepare(managed,verified.artifact_root,verified.bundle,
        base_python=installation['base_python'],automatic=args.automatic)
    return {**event,'status':'pending','environment':pointer['environment'],
        'message':'Downloaded and verified paired environment; apply at the next normal launch.'}


def main(argv=None,*,service_factory=None,prepare=None,emit=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--managed-root',type=Path)
    parser.add_argument('--policy',choices=POLICIES,default='AUTO_UPDATE')
    parser.add_argument('--automatic',action='store_true')
    parser.add_argument('action',choices=('check','prepare','retry'))
    args=parser.parse_args(argv)
    if emit is None:emit=lambda value:print(json.dumps(value,ensure_ascii=False),flush=True)
    try:
        result=execute(args,service_factory=service_factory,prepare=prepare)
    except Exception as error:
        result={'event':'native-update','status':'failed','phase':args.action,
                'failure':type(error).__name__,'message':str(error),'pending':None}
        emit(result)
        return 1
    emit(result)
    return 0


if __name__=='__main__':raise SystemExit(main())
