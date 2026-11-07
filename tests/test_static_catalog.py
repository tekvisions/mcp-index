import unittest,tempfile,pathlib,json,hashlib,re
from render_catalog import render
from build_data import assign_slugs
class StaticCatalogTests(unittest.TestCase):
 def test_pages_cover_each_server_once_and_escape_untrusted_text(self):
  source=pathlib.Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d);data={'generated_at':'2026-11-03T00:00:00Z','servers':[{'name':'x/'+str(n),'title':'<script>bad</script>','description':'<img onerror=bad>','updated_at':'2026-11-03'} for n in range(121)]};raw=json.dumps(data).encode();(p/'data.json').write_bytes(raw)
   result=render(p,(source/'index.source.html').read_text());self.assertEqual(result['pages'],2)
   texts=[(p/'index.html').read_text(),(p/'catalog/2/index.html').read_text()];urls=[]
   for t in texts:
    self.assertNotIn('<script>bad</script>',t);self.assertNotIn('<img onerror=bad>',t);self.assertIn(hashlib.sha256(raw).hexdigest(),t);urls+=re.findall(r'<a class="row" href="([^"]+)"',t)
   self.assertEqual(len(urls),121);self.assertEqual(len(set(urls)),121);self.assertTrue(all(not u.endswith('/') for u in urls))
   self.assertIn('href="https://mcp.kymatalabs.com/catalog/2/"',texts[1]);self.assertNotIn('<script src="app.js">',texts[1]);self.assertEqual((p/'data.json').read_bytes(),raw)
 def test_collision_slugs_are_unique_and_stable(self):
  rows=assign_slugs([{'name':'a/b'},{'name':'a.b'}]);self.assertEqual([x['slug'] for x in rows],['a-b','a-b-2']);self.assertEqual(assign_slugs(rows),rows)
if __name__=='__main__':unittest.main()
