"""Real isolated native character storage/validation without devices or models."""
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
CODE = 'from src.char.BaseChar import BaseChar\nclass Mortefi(BaseChar):\n    marker = 1\n'


class TestNativeCharacterStore(unittest.TestCase):
    def probe(self, body):
        with tempfile.TemporaryDirectory() as directory:
            prefix = f'''import sys\nsys.path.insert(0, {str(ROOT)!r})\nfrom pathlib import Path\nfrom src.runtime.native_characters import NativeCharacterService, CharacterConflict, CharacterValidationError\nroot=Path({directory!r})\nservice=NativeCharacterService(root)\ncode={CODE!r}\n'''
            result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', '-c', prefix+textwrap.dedent(body)],
                cwd=directory, capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_builtin_read_identity_and_external_boundaries(self):
        self.probe(r'''
            listing=service.list()
            assert len(listing['characters'])>50
            row=service.read('Mortefi')
            assert 'class Mortefi' in row['builtin_code'] and row['custom_code'] is None
            assert not row['use_custom'] and not row['has_custom']
            assert row['saved_revision']==listing['saved_revision']
            for name in ('../escape','Mortefi.py','NotRegistered'):
                try: service.read(name)
                except ValueError: pass
                else: raise AssertionError(name)
            try: service.set_mode('Mortefi',True,expected_revision=row['saved_revision'])
            except ValueError: pass
            else: raise AssertionError('enabled missing source')
            service.root.mkdir(parents=True)
            service.modes_path.write_text('{broken',encoding='utf-8')
            try: service.load_snapshot()
            except ValueError: pass
            else: raise AssertionError('corrupt modes silently accepted')
            assert not any(name.split('.')[0] in ('ok','PySide6','onnxocr') for name in sys.modules)
        ''')

    def test_owner_snapshot_digest_and_default_solo(self):
        self.probe(r'''
            import os
            from types import SimpleNamespace
            from src.char.Mortefi import Mortefi
            from src.char.CustomCharLoader import (bind_native_character_classes,load_custom_char_class,
                get_native_character_revision,get_native_character_classes)
            initial=service.load_snapshot()
            bind_native_character_classes(initial['classes'],initial['revision'])
            saved=service.save('Mortefi',code,expected_revision=initial['revision'])
            assert load_custom_char_class(Mortefi) is Mortefi
            snapshot=service.load_snapshot()
            other=next(cls for cls in snapshot['classes'] if cls is not Mortefi)
            bind_native_character_classes(snapshot['classes'],snapshot['revision'])
            first=load_custom_char_class(Mortefi)
            assert first.marker==1 and get_native_character_revision()==snapshot['revision']
            detached=get_native_character_classes(); detached.clear()
            assert load_custom_char_class(Mortefi) is first
            source=service._source_path('Mortefi'); stamp=source.stat()
            source.write_text(code.replace('marker = 1','marker = 2'),encoding='utf-8')
            os.utime(source,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            second=service.load_snapshot()
            assert second['classes'][Mortefi].marker==2 and second['revision']!=snapshot['revision']
            assert second['classes'][other] is snapshot['classes'][other]
            assert load_custom_char_class(Mortefi) is first
            bind_native_character_classes(second['classes'],second['revision'])
            assert load_custom_char_class(Mortefi) is second['classes'][Mortefi]
            assert service.load_snapshot()['classes'][Mortefi] is second['classes'][Mortefi]
            solo=code+'    def do_perform(self):\n        self.used="custom"\n'
            row=service.save('Mortefi',solo,expected_revision=second['revision'])
            cls=service.load_snapshot()['classes'][Mortefi]
            task=SimpleNamespace(chars=[],solo_rotation_enabled=True)
            char=cls(task,0); task.chars=[char]; char.perform()
            assert char.used=='custom'
        ''')

    def test_invalid_candidates_preserve_published_source_and_original_configs(self):
        self.probe(r'''
            saved=service.save('Mortefi',code,expected_revision=service.list()['saved_revision'])
            originals={path.relative_to(root):path.read_bytes() for path in (root/'configs').rglob('*') if path.is_file()}
            invalid=['bad syntax!!!','import nonexistent_character_dependency\n'+code,
                'class Mortefi: pass','from src.char.BaseChar import BaseChar\nclass Different(BaseChar): pass',
                code+'    def __init__(self,*a,**k):\n        raise ValueError("constructor fault")\n',
                code+'    def __init__(self,*a,**k):\n        super().__init__(*a,**k)\n        self.task.click()\n']
            for candidate in invalid:
                try: service.save('Mortefi',candidate,expected_revision=saved['saved_revision'])
                except (SyntaxError,CharacterValidationError): pass
                else: raise AssertionError(candidate)
                assert service.read('Mortefi')['custom_code']==code
                assert service.list()['saved_revision']==saved['saved_revision']
                current={path.relative_to(root):path.read_bytes() for path in (root/'configs').rglob('*') if path.is_file()}
                assert current==originals, 'candidate wrote original configuration'
            from src.char.CustomCharLoader import bind_native_character_classes,load_custom_char_class
            from src.char.Mortefi import Mortefi
            snapshot=service.load_snapshot(); bind_native_character_classes(snapshot['classes'],snapshot['revision'])
            original=load_custom_char_class(Mortefi)
            service._source_path('Mortefi').write_text('class Mortefi: pass',encoding='utf-8')
            try: service.load_snapshot()
            except CharacterValidationError: pass
            else: raise AssertionError('invalid active script fell back')
            assert load_custom_char_class(Mortefi) is original
        ''')

    def test_conflicts_and_validation_race_do_not_overwrite_other_editor(self):
        self.probe(r'''
            row=service.read('Mortefi')
            saved=service.save('Mortefi',code,expected_revision=row['saved_revision'])
            for token in (None,row['saved_revision']):
                try: service.save('Mortefi',code.replace('1','2'),expected_revision=token)
                except CharacterConflict: pass
                else: raise AssertionError('stale token accepted')
            other=NativeCharacterService(root)
            validate=service._validate
            def racing(name,candidate):
                other.save(name,code.replace('1','3'),expected_revision=saved['saved_revision'])
                validate(name,candidate)
            service._validate=racing
            try: service.save('Mortefi',code.replace('1','2'),expected_revision=saved['saved_revision'])
            except CharacterConflict: pass
            else: raise AssertionError('validation race overwrote other editor')
            assert service.read('Mortefi')['custom_code']==code.replace('1','3')
        ''')

    def test_modes_reset_builtin_equality_and_publication_rollback(self):
        self.probe(r'''
            from unittest.mock import patch
            row=service.save('Mortefi',code,expected_revision=service.list()['saved_revision'])
            row=service.set_mode('Mortefi',False,expected_revision=row['saved_revision'])
            assert row['has_custom'] and not row['use_custom'] and row['custom_code']==code
            row=service.set_mode('Mortefi',True,expected_revision=row['saved_revision'])
            assert row['use_custom']
            old_source=service._source_path('Mortefi').read_bytes(); old_modes=service.modes_path.read_bytes()
            atomic=service._atomic_bytes
            def failed_mode(path,payload):
                if path==service.modes_path: raise OSError('mode publication fault')
                atomic(path,payload)
            with patch.object(service,'_atomic_bytes',side_effect=failed_mode):
                try: service.save('Mortefi',code.replace('1','2'),expected_revision=row['saved_revision'])
                except OSError: pass
                else: raise AssertionError('publication failure hidden')
            assert service._source_path('Mortefi').read_bytes()==old_source
            assert service.modes_path.read_bytes()==old_modes
            row=service.save('Mortefi',row['builtin_code'],expected_revision=row['saved_revision'])
            assert not row['has_custom'] and not row['use_custom']
            row=service.save('Mortefi',code,expected_revision=row['saved_revision'])
            row=service.reset('Mortefi',expected_revision=row['saved_revision'])
            assert not row['has_custom'] and not row['use_custom']
        ''')

if __name__=='__main__': unittest.main()
