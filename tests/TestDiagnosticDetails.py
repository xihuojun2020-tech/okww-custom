import json,tempfile,unittest
from pathlib import Path
from datetime import datetime
from src.runtime.diagnostic_status import DiagnosticIndex,backfill_preview,retry_batches

class TestDiagnosticDetails(unittest.TestCase):
    def batch(self,root,name,status,revision=1):
        batch=root/'run'/'batches'/name;batch.mkdir(parents=True)
        relative=f'日志/okww-custom/2026-09-13/run/{name}/incident.json'
        path=batch/relative;path.parent.mkdir(parents=True)
        path.write_text(json.dumps(dict(run_id='run',incident_id='same',revision=revision,
            state='incomplete',frames=[],incomplete_reasons=['stale_frame'])))
        (batch/'manifest.json').write_text(json.dumps(dict(run_id='run',files=[dict(path=relative,size=10)],created_at=revision)))
        (batch/'_READY').touch();(root/'states').mkdir(exist_ok=True)
        (root/'states'/f'run--{name}.json').write_text(json.dumps(dict(status=status)))
        return batch
    def test_revision_dedup_and_success_does_not_imply_complete(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);self.batch(r,'one','retrying');self.batch(r,'two','uploaded',2)
            index=DiagnosticIndex(r);s=index.snapshot()
            self.assertEqual(1,len(s['incidents']));self.assertEqual('incomplete',s['incidents'][0]['state'])
            self.assertEqual('uploaded',s['incidents'][0]['upload_status'])
            s['incidents'][0]['state']='mutated'
            self.assertEqual('incomplete',index.snapshot()['incidents'][0]['state'])
    def test_corrupt_state_unknown_and_blocked_not_retried(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);self.batch(r,'one','blocked');self.batch(r,'two','pending')
            (r/'states'/'run--two.json').write_text('{')
            self.assertEqual('unknown',DiagnosticIndex(r).snapshot()['batches'][1]['status'])
            self.assertEqual(0,retry_batches(r,['run--one']))
    def test_backfill_time_filter_keeps_traceback_and_does_not_touch_cursors(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);(r/'logs').mkdir()
            (r/'logs'/'ok.log').write_text('2026-09-13 14:59:00 before\n2026-09-13 15:01:00 error\n traceback\n2026-09-13 16:00:00 after\n')
            rows=backfill_preview(r,datetime(2026,9,13,15),datetime(2026,9,13,16))
            self.assertIn('traceback',rows[0]['content']);self.assertNotIn('before',rows[0]['content'])
            self.assertFalse((r/'source-cursors.json').exists())

    def test_missing_frame_batch_is_not_hidden_by_uploaded_revision(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t);batch=self.batch(r,'latest','uploaded')
            path=next(batch.rglob('incident.json'))
            incident=json.loads(path.read_text());incident['frames']=[{'remote_path':'截图/missing.png'}]
            path.write_text(json.dumps(incident))
            (batch/'transfer-progress.json').write_text('[]')
            event=DiagnosticIndex(r).snapshot()['incidents'][0]
            self.assertEqual('partial',event['upload_status'])
            self.assertEqual('missing',event['frames'][0]['upload_status'])

    def test_collector_records_original_source_range(self):
        from src.runtime.diagnostic_collector import FileCollector
        with tempfile.TemporaryDirectory() as t:
            base=Path(t);source=base/'source';root=base/'diagnostics';root.mkdir()
            (source/'logs').mkdir(parents=True)
            collector=FileCollector(source,root)
            path=source/'logs'/'ok.log';path.write_text('2026-09-13 15:00:00 test\n')
            run=root/'run';run.mkdir();(run/'metadata.json').write_text(json.dumps({
                'started_at':'2026-09-13T15:00:00','run_id':'run'}))
            collector.collect(run)
            snapshot=DiagnosticIndex(root,source).snapshot()
            row=snapshot['sources'][0]
            self.assertEqual(path.stat().st_size,row['live_size'])
            self.assertEqual(0,row['remaining'])
            self.assertEqual(0,row['batches'][0]['range']['start'])
            self.assertEqual(path.stat().st_size,row['batches'][0]['range']['end'])

if __name__=='__main__':unittest.main()
