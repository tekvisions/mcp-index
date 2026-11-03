import importlib.util
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location('guarded_'+name,ROOT/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class ReleaseGuardTests(unittest.TestCase):
    def test_guard_has_no_environment_bypass(self):
        import release_guard
        with patch.dict('os.environ',{'ALLOW_OVERWRITE':'1','MCP_RELEASE_APPROVED':'1'}):
            with self.assertRaises(release_guard.PublicationHeld):release_guard.require_reviewed_pipeline()

    def test_all_entrypoints_stop_before_network_or_mutation(self):
        for name in ['build_data','deploy','indexnow_ping']:
            module=load(name)
            before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'data.json',ROOT/'sitemap.xml',ROOT/'index.html']}
            with patch('urllib.request.urlopen',side_effect=AssertionError('Network must stay unused')) as network,patch('shutil.rmtree',side_effect=AssertionError('Routes must stay untouched')) as remove:
                self.assertEqual(module.main(),2,name)
                network.assert_not_called();remove.assert_not_called()
            self.assertEqual(before,{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in before})

    def test_cli_exit_status_and_snapshot_preservation(self):
        files=[ROOT/'data.json',ROOT/'sitemap.xml',ROOT/'index.html'];before=[hashlib.sha256(p.read_bytes()).hexdigest() for p in files]
        for name in ['release_guard.py','build_data.py','deploy.py','indexnow_ping.py']:
            run=subprocess.run([sys.executable,str(ROOT/name)],cwd=ROOT,text=True,capture_output=True,timeout=5)
            self.assertEqual(run.returncode,2,(name,run.stderr));self.assertIn('legacy refresh is held',run.stderr)
        self.assertEqual(before,[hashlib.sha256(p.read_bytes()).hexdigest() for p in files])

if __name__=='__main__':unittest.main()
