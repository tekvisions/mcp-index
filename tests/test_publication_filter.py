"""Publication filter: only registry-active servers updated within the recency window.

Excluded identities that were already published keep their URLs as labelled,
noindex references; the catalog can never be empty and the record budget stays.
"""
import contextlib, datetime, io, json, pathlib, re, shutil, tempfile, unittest, zlib
from unittest import mock
import release_pipeline
from registry_collect import collect, OFFICIAL
from release_pipeline import build, ReleaseError, RECENCY_DAYS

SOURCE = pathlib.Path(__file__).resolve().parents[1]


def ts(days_ago):
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)).isoformat().replace('+00:00', 'Z')


def record(name, status='active', updated_days=1, message=None):
    meta = {'isLatest': True, 'status': status, 'publishedAt': ts(updated_days + 5), 'updatedAt': ts(updated_days)}
    if message:
        meta['statusMessage'] = message
    return {'server': {'name': name, 'title': name.split('/')[-1], 'description': 'Publisher declaration', 'version': '1.0.0', 'packages': []},
            '_meta': {OFFICIAL: meta}}


class PublicationFilter(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name); self.repo = self.root / 'repo'; self.repo.mkdir()
        for f in ['index.source.html', 'packed_pages.js', 'vercel.json', 'style.css', 'app.js']:
            shutil.copyfile(SOURCE / f, self.repo / f)

    def build(self, records, history, name='built'):
        capture = self.root / ('capture-' + name); out = self.root / name
        page = json.dumps({'servers': records, 'metadata': {'count': len(records)}}).encode()
        (self.repo / 'route-history.json').write_text(json.dumps({'schema_version': 1, 'routes': history}))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            collect(capture, fetch=lambda _: page, delay=0)
            return build(capture, out, self.repo), out

    def pages(self, out):
        func = out / '.vercel/output/functions/details.func'
        pages = json.loads((func / 'pages.json').read_text()); pack = (func / 'pages.bin').read_bytes(); dictionary = (func / 'dictionary.bin').read_bytes()
        def body(slug):
            row = pages[slug]; d = zlib.decompressobj(-15, zdict=dictionary)
            return d.decompress(pack[row['offset']:row['offset'] + row['length']]).decode()
        return pages, body

    def test_only_active_recent_servers_are_listed_and_dropped_routes_are_retained(self):
        records = [record('org.example/fresh'), record('org.example/edge', updated_days=RECENCY_DAYS - 1),
                   record('org.example/dormant', updated_days=RECENCY_DAYS + 1),
                   record('org.example/old', status='deprecated', message='Superseded by org.example/fresh'),
                   record('org.example/gone', status='deleted')]
        history = {'fresh': {'name': 'org.example/fresh', 'title': 'Fresh'}, 'dormant': {'name': 'org.example/dormant', 'title': 'Dormant'},
                   'old': {'name': 'org.example/old', 'title': 'Old'}, 'gone': {'name': 'org.example/gone', 'title': 'Gone'},
                   'absent': {'name': 'org.example/absent', 'title': 'Absent'}}
        manifest, out = self.build(records, history)
        static = out / '.vercel/output/static'
        data = json.loads((static / 'data.json').read_text())
        self.assertEqual(sorted(x['name'] for x in data['servers']), ['org.example/edge', 'org.example/fresh'])
        self.assertEqual(data['publication_filter'], {'registry_status': 'active', 'updated_within_days': RECENCY_DAYS})
        self.assertEqual((data['deleted_count'], data['deprecated_count'], data['outside_window_count']), (1, 1, 1))
        snapshot = json.loads((static / 'snapshot.json').read_text())
        self.assertEqual(snapshot['search_records'], 2); self.assertEqual(snapshot['deleted_records'], 1)
        self.assertEqual(snapshot['publication_filter'], data['publication_filter'])
        # Every previously published route survives with an explicit state; nothing is silently dropped.
        self.assertEqual(manifest['historical_routes_missing'], [])
        pages, body = self.pages(out)
        self.assertEqual({k: v['state'] for k, v in pages.items() if k in history},
                         {'fresh': 'current', 'dormant': 'dormant_reference', 'old': 'deprecated_reference', 'gone': 'deleted_reference', 'absent': 'unobserved_reference'})
        for slug in ('dormant', 'old', 'gone', 'absent'):
            text = body(slug)
            self.assertIn('noindex,follow', text); self.assertIn('historical registry reference', text)
            self.assertIn('rel="canonical" href="https://mcp.kymatalabs.com/s/' + slug + '/"', text)
        self.assertIn('marks this server as deprecated', body('old')); self.assertIn('Superseded by org.example/fresh', body('old'))
        self.assertIn('updated within the last ' + str(RECENCY_DAYS) + ' days', body('dormant'))
        self.assertRegex(body('dormant'), r'last updated \d{4}-\d{2}-\d{2}')
        self.assertIn('marks this server as deleted', body('gone'))
        urls = re.findall(r'<loc>([^<]+)</loc>', (static / 'sitemap.xml').read_text())
        for slug in ('dormant', 'old', 'gone', 'absent'):
            self.assertNotIn('https://mcp.kymatalabs.com/s/' + slug, urls)
        self.assertIn('updated within the last ' + str(RECENCY_DAYS) + ' days', (static / 'llms.txt').read_text())
        self.assertIn('updated within the last ' + str(RECENCY_DAYS) + ' days', (static / 'index.html').read_text())

    def test_catalog_can_never_be_empty(self):
        records = [record('org.example/dormant', updated_days=RECENCY_DAYS + 3), record('org.example/old', status='deprecated'), record('org.example/gone', status='deleted')]
        with self.assertRaisesRegex(ReleaseError, 'Empty catalog'):
            self.build(records, {'old': {'name': 'org.example/old', 'title': 'Old'}})
        self.assertFalse((self.root / 'built').exists())

    def test_record_budget_guard_still_fails_closed(self):
        records = [record('org.example/a'), record('org.example/b'), record('org.example/c', updated_days=RECENCY_DAYS + 3)]
        with mock.patch.object(release_pipeline, 'MAX_RECORDS', 1), self.assertRaisesRegex(ReleaseError, 'Record budget'):
            self.build(records, {}, 'over')
        self.assertFalse((self.root / 'over').exists())
        with mock.patch.object(release_pipeline, 'MAX_RECORDS', 2):
            manifest, out = self.build(records, {}, 'fits')
        self.assertEqual(manifest['snapshot']['search_records'], 2)

    def test_recency_window_and_cap_are_fixed_and_documented(self):
        self.assertEqual(RECENCY_DAYS, 30)
        self.assertEqual(release_pipeline.MAX_RECORDS, 60000)
        self.assertIn('updated within the last 30 days', (SOURCE / 'RELEASE_ACCEPTANCE.md').read_text())


if __name__ == '__main__':
    unittest.main()
