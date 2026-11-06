import json, pathlib, tempfile, unittest
from urllib.parse import parse_qs,urlsplit
from unittest.mock import patch
from registry_collect import collect, verify, CollectionError, OFFICIAL

def page(name='org.example/server',cursor=None,status='active'):
 return json.dumps({'servers':[{'server':{'name':name,'version':'1.0.0'},'_meta':{OFFICIAL:{'isLatest':True,'status':status}}}],'metadata':{'count':1,'nextCursor':cursor}}).encode()

class RegistryCollection(unittest.TestCase):
 def run_pages(self,pages,**kwargs):
  root=pathlib.Path(self.temp.name)/'capture';iterator=iter(pages);self.urls=[]
  def fetch(url):self.urls.append(url);return next(iterator)
  return root,collect(root,fetch=fetch,delay=0,**kwargs)
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
 def test_terminal_cursor_is_required_and_filters_are_preserved(self):
  root,r=self.run_pages([page('a/server','a/server:1'),page('b/server')]);self.assertTrue(r['complete']);self.assertEqual(verify(root)['total_records'],2)
  for u in self.urls:self.assertEqual(parse_qs(urlsplit(u).query)['version'],['latest']);self.assertEqual(parse_qs(urlsplit(u).query)['include_deleted'],['true'])
  self.assertEqual(parse_qs(urlsplit(self.urls[1]).query)['cursor'],['a/server:1'])
 def test_page_budget_never_reports_partial_success(self):
  with self.assertRaises(CollectionError):self.run_pages([page('a/server','next')],max_pages=1)
  self.assertFalse(json.loads((pathlib.Path(self.temp.name)/'capture/receipt.json').read_text())['complete'])
  self.assertFalse((pathlib.Path(self.temp.name)/'capture/records.json').exists())
 def test_cursor_loop_is_rejected(self):
  with self.assertRaises(CollectionError):self.run_pages([page('a/server','same'),page('b/server','same')])
 def test_duplicate_identity_aborts_moving_source(self):
  with self.assertRaises(CollectionError):self.run_pages([page('a/server','next'),page('a/server')])
 def test_malformed_or_incomplete_pages_abort(self):
  for bad in [b'{}',b'{"servers":[],"metadata":{"nextCursor":"x"}}',b'not json']:
   with tempfile.TemporaryDirectory() as t:
    with self.assertRaises((CollectionError,ValueError)):collect(pathlib.Path(t)/'capture',fetch=lambda _:bad,delay=0)
 def test_byte_budget_aborts(self):
  with self.assertRaises(CollectionError):self.run_pages([page()],max_bytes=10)
 def test_unfiltered_old_version_is_rejected(self):
  j=json.loads(page());j['servers'][0]['_meta'][OFFICIAL]['isLatest']=False
  with self.assertRaises(CollectionError):self.run_pages([json.dumps(j).encode()])
 def test_deleted_status_is_preserved_as_source_evidence(self):
  root,r=self.run_pages([page(status='deleted')]);self.assertEqual(json.loads((root/'records.json').read_text())['servers'][0]['_meta'][OFFICIAL]['status'],'deleted')
 def test_hash_mutation_is_rejected(self):
  root,r=self.run_pages([page()]);(root/'page-0001.json').write_bytes(page('altered/server'))
  with self.assertRaises(CollectionError):verify(root)
 def test_no_existing_capture_is_overwritten(self):
  root,r=self.run_pages([page()]);before=(root/'receipt.json').read_bytes()
  with self.assertRaises(CollectionError):collect(root,fetch=lambda _:b'',delay=0)
  self.assertEqual(before,(root/'receipt.json').read_bytes())

if __name__=='__main__':unittest.main()
