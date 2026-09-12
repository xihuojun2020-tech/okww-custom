"""Read/export permanent local material data: python -m src.materials --help."""
import argparse
import json
from dataclasses import asdict
from pathlib import Path
from src.materials.repository import MaterialRepository
from src.materials.model import aggregate_settlements


def main():
    parser=argparse.ArgumentParser(description='养成收益统计、CSV 导出与完整备份；不会删除原始记录')
    parser.add_argument('action',choices=('accounts','stats','export','backup'))
    parser.add_argument('--profile',help='账号稳定 UUID（accounts 命令可列出）')
    parser.add_argument('--root',type=Path,help='可选材料数据目录')
    parser.add_argument('--output',type=Path,help='新建的导出文件或备份目录')
    args=parser.parse_args()
    repo=MaterialRepository(args.root)
    if args.action in ('stats','export') and not args.profile:
        parser.error('stats/export 需要 --profile')
    if args.action in ('export','backup') and not args.output:
        parser.error('export/backup 需要 --output；目标必须尚不存在')
    if args.action=='accounts':
        with repo.connect() as db:
            result=[r[0] for r in db.execute('SELECT profile_id FROM claims UNION SELECT profile_id FROM snapshots')]
    elif args.action=='stats':
        records=repo.list_settlements(args.profile)
        result={group:aggregate_settlements([r for r in records if r.target_group==group])
                for group in dict.fromkeys(r.target_group for r in records)}
    elif args.action=='export':
        result=repo.export_csv(args.profile,args.output)
    else:
        result=repo.backup(args.output)
    print(json.dumps(result,ensure_ascii=False,indent=2,default=asdict))


if __name__=='__main__': main()
