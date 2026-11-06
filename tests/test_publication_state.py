import json, pathlib, subprocess, tempfile, unittest
import publication_state as state
from release_pipeline import ReleaseError

class DurableState(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=pathlib.Path(self.temp.name);self.repo=self.root/'repo';self.repo.mkdir()
        self.remote=self.root/'remote.git';self.package=self.root/'package';self.package.mkdir()
        self.git('init','--bare',str(self.remote),cwd=self.root)
        self.git('init','-b','main');self.git('config','user.name','Finite test');self.git('config','user.email','test@example.invalid')
        (self.repo/'source').write_text('source');self.git('add','source');self.git('commit','-m','initial')
        self.git('remote','add','origin',str(self.remote));self.git('push','origin','main')
        (self.package/'route-history.json').write_text('{"routes":{"new":"preserved"}}')
        (self.package/'.catalog-state.json.gz').write_bytes(b'bounded fixture state')
        self.result={'previous_id':state.BOOTSTRAP_DEPLOYMENT,'deployment_id':'dpl_candidate','origin':'https://fixture.vercel.app','package_sha256':'a'*64}
    def git(self,*args,cwd=None):
        p=subprocess.run(['git',*args],cwd=cwd or self.repo,capture_output=True,text=True)
        if p.returncode:raise RuntimeError(p.stderr)
        return p.stdout.strip()
    def test_union_is_durable_before_promotion_and_pending_requires_reconciliation(self):
        self.assertIsNone(state.validate(self.repo,state.BOOTSTRAP_DEPLOYMENT))
        saved=state.persist(self.repo,self.package,self.result)
        stored=json.loads(self.git('--git-dir',str(self.remote),'show','main:publication-state.json',cwd=self.root))
        self.assertEqual(stored['pending_id'],'dpl_candidate')
        self.assertEqual(self.git('ls-remote','origin','refs/heads/main').split()[0],saved['durable_revision'])
        with self.assertRaisesRegex(ReleaseError,'reconcile'):state.validate(self.repo,'dpl_candidate')
        self.assertIsNotNone(state.validate(self.repo,state.BOOTSTRAP_DEPLOYMENT))
        state.confirm(self.repo,saved,{'production_verification_sha256':'b'*64})
        self.assertEqual(state.validate(self.repo,'dpl_candidate')['status'],'production_verified')
        with self.assertRaisesRegex(ReleaseError,'outside'):state.validate(self.repo,'dpl_someone_else')
        (self.repo/'route-history.json').write_text('tampered')
        with self.assertRaisesRegex(ReleaseError,'differs'):state.validate(self.repo,'dpl_candidate')
    def test_rejected_push_stops_and_remote_does_not_advance(self):
        hook=self.remote/'hooks/pre-receive';hook.write_text('#!/bin/sh\nexit 1\n');hook.chmod(0o700)
        old=self.git('ls-remote','origin','refs/heads/main')
        with self.assertRaisesRegex(ReleaseError,'Git operation failed'):state.persist(self.repo,self.package,self.result)
        self.assertEqual(self.git('ls-remote','origin','refs/heads/main'),old)

if __name__=='__main__':unittest.main()
