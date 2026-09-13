"""Measure a synthetic image-heavy ZIP handoff, leaving test evidence separate."""
from pathlib import Path
import json
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from src.runtime.diagnostic_session import DiagnosticSession, seal_run
from src.runtime.diagnostic_archive import build_archive, upload_archive
from src.runtime.diagnostic_policy import DEFAULT_TARGET


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)/'spool'
        session=DiagnosticSession(root,'synthetic-archive-benchmark')
        session.finish(timeout=5)
        rng=np.random.default_rng(42)
        images=[]
        for i in range(4):
            path=Path(temporary)/f'{i}.png'
            path.write_bytes(cv2.imencode('.png',rng.integers(0,256,(1080,1920,3),np.uint8))[1].tobytes())
            images.append(path)
        seal_run(session.run,'error',reviewed_images=images,sizes={})
        start=time.perf_counter(); archive=build_archive(root); packing=time.perf_counter()-start
        size=archive.stat().st_size
        target=Path(DEFAULT_TARGET)/'测试/archive-benchmark'/uuid.uuid4().hex
        start=time.perf_counter(); remote=upload_archive(archive,target); uploading=time.perf_counter()-start
        result={'synthetic':True,'bytes':size,'pack_seconds':packing,
                'upload_and_verify_seconds':uploading,'remote':remote}
        out=Path('test_out/manual-archive-benchmark.json')
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
