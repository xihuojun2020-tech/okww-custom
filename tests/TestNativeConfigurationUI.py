"""A real no-device configuration owner feeding every production Qt form."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestNativeConfigurationUI(unittest.TestCase):
    def test_full_form_render_global_save_and_ordered_values_without_game(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'ui_probe.py'
            script.write_text('''
import sys,time,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from tests.fixture_support import make_account_environment
from PySide6.QtWidgets import QApplication,QSpinBox,QComboBox
from src.gui.NativeConfigurationTab import NativeConfigurationTab,OrderedValues
root=Path(sys.argv[2])
make_account_environment(root/'data')
app=QApplication([])
tab=NativeConfigurationTab(root/'data','test-ui',Path(sys.argv[1])/'gamepacks/wuthering_waves_native/manifest.json')
def until(condition):
    deadline=time.monotonic()+20
    while not condition():
        app.processEvents()
        if time.monotonic()>deadline:
            raise AssertionError(tab.status.text())
        time.sleep(.01)
try:
    until(lambda:tab.schema is not None)
    assert len(tab.schema['tasks'])==29 and len(tab.schema['globals'])==3
    assert not any(row[1]=='MaterialPlannerTask' for row in tab._entries)
    for index in range(len(tab._entries)):
        tab.selection.setCurrentRow(index)
        app.processEvents()
        assert tab.form.rowCount()>0
    tab._select_global('Monthly Card Config')
    spin=tab.findChild(QSpinBox)
    previous_requests=tab._request_id
    spin.setValue(8)
    spin.editingFinished.emit()
    until(lambda:not tab._pending)
    assert tab._request_id==previous_requests+1
    assert json.loads((root/'data/configs/Monthly Card Config.json').read_text(encoding='utf-8'))['Monthly Card Time']==8
    ordered=OrderedValues(['A3','A1'],['A1','A3','A4'])
    ordered.items.setCurrentRow(1)
    ordered._move(-1)
    assert ordered.values()==['A1','A3']
    ordered.choice.setCurrentIndex(2)
    ordered._append()
    assert ordered.values()==['A1','A3','A4']
    ordered._append()
    assert ordered.values()==['A1','A3','A4']
    print('configuration-ui-real-owner-pass')
finally:
    tab.shutdown()
assert tab.process.exitCode()==0
''', encoding='utf-8')
            environment = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONPATH=str(ROOT))
            result = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(script), str(ROOT), directory],
                env=environment, capture_output=True, text=True, encoding='utf-8', timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('configuration-ui-real-owner-pass', result.stdout)


if __name__ == '__main__':
    unittest.main()
