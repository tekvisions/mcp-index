import contextlib,io,json,pathlib,shutil,subprocess,tempfile,unittest
from registry_collect import collect,OFFICIAL
from release_pipeline import build,verify_package,ReleaseError,stable_slugs
from build_data import generate_details

SOURCE=pathlib.Path(__file__).resolve().parents[1]
def source_page():
 return json.dumps({'servers':[{'server':{'name':'org.example/current','title':'Current </script><script>alert(1)</script>','description':'Publisher declaration','version':'1.0.0','packages':[]},'_meta':{OFFICIAL:{'isLatest':True,'status':'active','publishedAt':'2026-01-01T00:00:00Z'}}},{'server':{'name':'org.example/removed','version':'1.0.0'},'_meta':{OFFICIAL:{'isLatest':True,'status':'deleted'}}}],'metadata':{'count':2}}).encode()
class ReviewedRelease(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=pathlib.Path(self.temp.name);self.repo=self.root/'repo';self.repo.mkdir();self.capture=self.root/'capture';self.out=self.root/'built'
  with contextlib.redirect_stdout(io.StringIO()):collect(self.capture,fetch=lambda _:source_page(),delay=0)
  for f in ['index.source.html','packed_pages.js','vercel.json','style.css','app.js']:shutil.copyfile(SOURCE/f,self.repo/f)
  (self.repo/'route-history.json').write_text(json.dumps({'schema_version':1,'routes':{'original-current':{'name':'org.example/current','title':'Original current'},'removed':{'name':'org.example/removed','title':'Removed'},'missing':{'name':'org.example/absent','title':'Absent'}}}))
 def build(self):
  with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):return build(self.capture,self.out,self.repo)
 def test_full_union_is_retained_with_explicit_status(self):
  m=self.build();self.assertEqual(m['routes'],3);self.assertEqual(m['historical_routes_missing'],[]);self.assertEqual(m['snapshot']['search_records'],1);self.assertEqual(m['snapshot']['deleted_records'],1)
  pages=json.loads((self.out/'.vercel/output/functions/details.func/pages.json').read_text());self.assertEqual(pages['missing']['state'],'unobserved_reference');self.assertEqual(pages['removed']['state'],'deleted_reference');self.assertEqual(pages['original-current']['identity'],'org.example/current')
 def test_current_identity_keeps_old_slug_and_new_collision_gets_distinct_slug(self):
  history={'routes':{'org-example-current':{'name':'some/other'},'original-current':{'name':'org.example/current'}}};rows=[{'name':'org.example/current'},{'name':'org/example/current'}];r=stable_slugs(rows,history);self.assertEqual(r['org.example/current'],'original-current');self.assertNotEqual(r['org/example/current'],'org-example-current');self.assertEqual(len(set(r.values())),2)
 def test_output_is_new_and_no_private_asset_is_included(self):
  (self.repo/'.env').write_text('SECRET=private-test');(self.repo/'private.json').write_text('private-test');m=self.build();self.assertNotIn('private-test',''.join(p.read_text(errors='ignore') for p in (self.out/'.vercel/output/static').rglob('*') if p.is_file()))
  with self.assertRaises(ReleaseError):self.build()
 def test_package_detects_static_mutation_and_unlisted_file(self):
  self.build();p=self.out/'.vercel/output/static/app.js';original=p.read_bytes();p.write_text('changed')
  with self.assertRaises(ReleaseError):verify_package(self.out)
  p.write_bytes(original);(p.parent/'private.json').write_text('private')
  with self.assertRaises(ReleaseError):verify_package(self.out)
 def test_incomplete_capture_cannot_create_package(self):
  p=self.capture/'receipt.json';j=json.loads(p.read_text());j['complete']=False;p.write_text(json.dumps(j))
  with self.assertRaises(ValueError):self.build()
  self.assertFalse(self.out.exists())
 def test_real_node_handler_preserves_html_and_rejects_unknown_input(self):
  self.build();script=SOURCE/'tests/packed-pages.test.cjs'
  run=subprocess.run(['node',str(script),str(self.out/'.vercel/output/functions/details.func/index.js')],capture_output=True,text=True,timeout=20)
  self.assertEqual(run.returncode,0,run.stdout+run.stderr)
 def test_client_and_static_snapshot_are_bound(self):
  m=self.build();html=(self.out/'.vercel/output/static/index.html').read_text();self.assertIn(m['snapshot']['data_sha256'],html);self.assertIn('cursor traversal completed',html.lower());self.assertNotIn('Completeness unverified; refresh paused',html)
 def test_provider_function_and_package_are_bounded(self):
  m=self.build();self.assertLess(len(m['files']),1600);self.assertLess(sum(x['bytes'] for x in m['files']),220000000);self.assertEqual(json.loads((self.out/'.vercel/output/functions/details.func/.vc-config.json').read_text())['maxDuration'],5)
 def test_live_verifier_rejects_noindex_even_when_bytes_match(self):
  import hashlib
  from verify_release import verify
  self.build();root=self.out/'.vercel/output/static'
  def response(url,method):
   raw=(root/'index.html').read_bytes()
   return 200,{'X-Content-Type-Options':'nosniff','Content-Security-Policy':"frame-ancestors 'none'",'X-Robots-Tag':'noindex'},raw
  with self.assertRaisesRegex(ReleaseError,'noindex'):verify(self.out,'https://mcp.kymatalabs.com',self.root/'verify.json',fetcher=response,delay=0)
  self.assertEqual(json.loads((self.root/'verify.json').read_text())['status'],'failed')
 def test_live_verifier_rejects_wrong_target_before_network(self):
  from verify_release import verify
  self.build()
  with self.assertRaisesRegex(ReleaseError,'host'):verify(self.out,'https://example.com',self.root/'verify.json',fetcher=lambda *a: self.fail('network'))
 def test_publisher_never_promotes_failed_candidate(self):
  from publish_release import publish
  self.build();calls=[]
  def runner(args,*rest):
   calls.append(args[0])
   return {'status':'ok','deployment':{'url':'https://mcp-index-fixture-techtalevisions-projects.vercel.app'}} if args[0]=='deploy' else {'id':'dpl_fixture','name':'mcp-index','target':'production','readyState':'READY','url':'old.vercel.app'}
  def checker(*args):raise ReleaseError('fixture response mismatch')
  with self.assertRaisesRegex(ReleaseError,'fixture'):publish(self.out,self.root/'receipts',True,runner=runner,checker=checker)
  self.assertEqual(calls,['inspect','deploy'])
 def test_publisher_rolls_back_failed_production_verification(self):
  from publish_release import publish
  self.build();calls=[]
  def runner(args,*rest):
   calls.append(args[0])
   return {'status':'ok','deployment':{'url':'https://mcp-index-fixture-techtalevisions-projects.vercel.app'}} if args[0]=='deploy' else {'id':'dpl_fixture','name':'mcp-index','target':'production','readyState':'READY','url':'old.vercel.app'}
  def checker(package,origin,*rest):
   if origin=='https://mcp.kymatalabs.com':raise ReleaseError('fixture public mismatch')
   return {'status':'passed'}
  with self.assertRaisesRegex(ReleaseError,'fixture'):publish(self.out,self.root/'receipts',True,runner=runner,checker=checker)
  self.assertEqual(calls,['inspect','deploy','inspect','promote','rollback'])
 def test_publisher_default_preserves_production(self):
  from publish_release import publish
  self.build();calls=[]
  def runner(args,*rest):
   calls.append(args[0]);return {'status':'ok','deployment':{'url':'https://mcp-index-fixture-techtalevisions-projects.vercel.app'}} if args[0]=='deploy' else {'id':'dpl_fixture','name':'mcp-index','target':'production','readyState':'READY','url':'old.vercel.app'}
  r=publish(self.out,self.root/'receipts',runner=runner,checker=lambda *a:{'status':'passed'})
  self.assertFalse(r['promoted']);self.assertEqual(calls,['inspect','deploy'])
 def test_large_static_catalog_has_bounded_sequential_navigation(self):
  from render_catalog import render
  data={'generated_at':'2026-11-06T00:00:00Z','servers':[{'name':'test/'+str(i),'title':'Test','slug':'test-'+str(i)} for i in range(1201)]}
  root=self.root/'navigation';root.mkdir();(root/'data.json').write_text(json.dumps(data));render(root,(self.repo/'index.source.html').read_text())
  import re
  html=(root/'catalog/5/index.html').read_text();nav=re.search(r'<nav aria-label="Catalog pages".*?</nav>',html).group()
  self.assertIn('/catalog/4/',nav);self.assertIn('/catalog/6/',nav);self.assertIn('/catalog/11/',nav);self.assertLess(nav.count('<a '),10)
if __name__=='__main__':unittest.main()
