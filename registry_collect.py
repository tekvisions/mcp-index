"""Read-only, bounded traversal of the official latest-version registry.

Completion means the declared cursor traversal ended, not a transactional
snapshot or independent validation of publishers' declarations. No publishing.
"""
import argparse, datetime, hashlib, json, pathlib, ssl, time
import urllib.error, urllib.parse, urllib.request

ENDPOINT = 'https://registry.modelcontextprotocol.io/v0.1/servers'
FILTERS = {'limit': '100', 'version': 'latest', 'include_deleted': 'true'}
MAX_PAGES = 1000
MAX_BYTES = 160_000_000
MAX_PAGE_BYTES = 2_000_000
OFFICIAL = 'io.modelcontextprotocol.registry/official'

class CollectionError(ValueError): pass
def stamp(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def digest(b): return hashlib.sha256(b).hexdigest()
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise CollectionError('Registry redirect requires source review')

def fetch_page(url):
    opener = urllib.request.build_opener(NoRedirect())
    request = urllib.request.Request(url, headers={'User-Agent': 'Kymata-MCP-Index/2.0 (+https://mcp.kymatalabs.com/)', 'Accept': 'application/json'})
    for attempt in range(4):
        try:
            with opener.open(request, timeout=35) as response:
                if response.status != 200: raise CollectionError('Non-200 registry response')
                data = response.read(MAX_PAGE_BYTES + 1)
                if len(data) > MAX_PAGE_BYTES: raise CollectionError('Registry page exceeds byte budget')
                return data
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 3: raise
            wait = error.headers.get('Retry-After', '')
            time.sleep(min(30, max(1, int(wait))) if wait.isdigit() else 2 ** attempt)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            reason = getattr(error, 'reason', error)
            if isinstance(reason, ssl.SSLError) or not isinstance(reason, (TimeoutError, ConnectionError)) or attempt == 3: raise
            time.sleep(2 ** attempt)
    raise CollectionError('Registry attempts exhausted')

def collect(out, fetch=fetch_page, max_pages=MAX_PAGES, max_bytes=MAX_BYTES, delay=0.5):
    out = pathlib.Path(out)
    if out.exists(): raise CollectionError('Collection destination must be new')
    if not 1 <= max_pages <= MAX_PAGES or not 1 <= max_bytes <= MAX_BYTES: raise CollectionError('Invalid bounded collection limits')
    out.mkdir(parents=True, mode=0o700)
    cursor = None; cursors = set(); records = {}; pages = []; total = 0
    receipt = {'schema_version': 1, 'endpoint': ENDPOINT, 'filters': FILTERS, 'started_at': stamp(), 'complete': False, 'pages': pages, 'limitations': 'Cursor exhaustion across a moving registry, not an atomic snapshot; publisher content is untrusted and no endpoint or package is executed.'}
    try:
        for number in range(1, max_pages + 1):
            query = dict(FILTERS)
            if cursor is not None: query['cursor'] = cursor
            url = ENDPOINT + '?' + urllib.parse.urlencode(query)
            raw = fetch(url)
            if not isinstance(raw, bytes) or len(raw) > MAX_PAGE_BYTES: raise CollectionError('Invalid page bytes')
            total += len(raw)
            if total > max_bytes: raise CollectionError('Collection byte budget exceeded')
            name = f'page-{number:04d}.json'; (out/name).write_bytes(raw)
            page = json.loads(raw)
            if not isinstance(page, dict) or not isinstance(page.get('servers'), list) or not isinstance(page.get('metadata'), dict): raise CollectionError('Malformed registry response')
            rows = page['servers']; meta = page['metadata']; nxt = meta.get('nextCursor')
            if nxt is not None and (not isinstance(nxt, str) or len(nxt) > 4096): raise CollectionError('Invalid cursor')
            if 'count' in meta and (type(meta['count']) is not int or meta['count'] != len(rows)): raise CollectionError('Page count mismatch')
            if len(rows) > 100 or (not rows and nxt): raise CollectionError('Invalid page size or empty continuation')
            for item in rows:
                if not isinstance(item, dict): raise CollectionError('Invalid record')
                server = item.get('server'); official = (item.get('_meta') or {}).get(OFFICIAL)
                if not isinstance(server, dict) or not isinstance(official, dict): raise CollectionError('Missing record identity or official metadata')
                ident = server.get('name')
                if not isinstance(ident, str) or not 1 <= len(ident) <= 255 or any(ord(c)<32 for c in ident): raise CollectionError('Invalid server identity')
                if official.get('isLatest') is not True: raise CollectionError('Latest filter not honored')
                if official.get('status') not in ('active','deprecated','deleted'): raise CollectionError('Unknown registry status')
                if ident in records: raise CollectionError('Repeated server identity; moving-source consistency must be reviewed')
                records[ident] = item
            pages.append({'file': name, 'sha256': digest(raw), 'bytes': len(raw), 'count': len(rows), 'request_url': url, 'cursor_in': cursor, 'cursor_out': nxt, 'captured_at': stamp()})
            print(f'page {number}: {len(rows)} records; total {len(records)}', flush=True)
            if not nxt:
                receipt.update(complete=True, terminal_cursor=nxt, total_records=len(records), total_bytes=total, finished_at=stamp())
                break
            if nxt in cursors or nxt == cursor: raise CollectionError('Cursor cycle')
            cursors.add(nxt); cursor = nxt
            if delay: time.sleep(delay)
        if not receipt['complete']: raise CollectionError('Page budget exhausted with continuation; no complete snapshot')
        if not records: raise CollectionError('Empty registry; needs operator review')
        rows = json.dumps({'servers': list(records.values())}, ensure_ascii=False, separators=(',', ':')).encode()
        (out/'records.json').write_bytes(rows); receipt['records_sha256'] = digest(rows)
    except Exception as error:
        receipt.update(complete=False, error=type(error).__name__+': '+str(error), finished_at=stamp())
        raise
    finally:
        (out/'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    return receipt

def verify(out):
    out = pathlib.Path(out); r = json.loads((out/'receipt.json').read_text())
    if r.get('schema_version') != 1 or r.get('complete') is not True or r.get('endpoint') != ENDPOINT or r.get('filters') != FILTERS or r.get('terminal_cursor'): raise CollectionError('No valid complete traversal receipt')
    if not 1 <= len(r['pages']) <= MAX_PAGES: raise CollectionError('Invalid page ledger')
    previous = None; names = set(); total = 0; all_rows = []
    for page in r['pages']:
        if page['cursor_in'] != previous: raise CollectionError('Broken cursor chain')
        path = pathlib.PurePosixPath(page['file'])
        if len(path.parts)!=1 or not path.name.startswith('page-') or path.suffix!='.json': raise CollectionError('Unsafe page path')
        raw = (out/path).read_bytes(); total += len(raw)
        if digest(raw)!=page['sha256'] or len(raw)!=page['bytes'] or len(raw)>MAX_PAGE_BYTES: raise CollectionError('Page hash or size mismatch')
        payload=json.loads(raw); rows=payload['servers']
        if payload['metadata'].get('nextCursor')!=page['cursor_out'] or len(rows)!=page['count']: raise CollectionError('Page/receipt mismatch')
        for item in rows:
            ident=item['server']['name']
            if ident in names: raise CollectionError('Duplicate source identity')
            names.add(ident);all_rows.append(item)
        previous=page['cursor_out']
    raw=(out/'records.json').read_bytes()
    if previous or total>MAX_BYTES or total!=r['total_bytes'] or len(names)!=r['total_records'] or digest(raw)!=r['records_sha256'] or json.loads(raw)['servers']!=all_rows: raise CollectionError('Snapshot does not match complete source traversal')
    return r

if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--verify',action='store_true');a=p.parse_args()
    print(json.dumps(verify(a.out) if a.verify else collect(a.out),ensure_ascii=False,indent=2))
