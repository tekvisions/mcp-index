"""Reviewed MCP build path. Never deploys, commits, or removes a prior release.

Produces immutable Build Output API v3 artifacts from a hash-bound completed
registry traversal. Pre-rendered detail HTML is packed behind a read-only
function to bound provider upload count without dropping public routes.
"""
import argparse, collections, datetime, gzip, hashlib, html, json, pathlib, re, shutil, tempfile, zlib
import build_data as legacy
import registry_collect
from render_catalog import render

ROOT=pathlib.Path(__file__).resolve().parent
SITE='https://mcp.kymatalabs.com'
MAX_RECORDS=60000
MAX_PACKAGE_BYTES=220_000_000
MAX_FUNCTION_BYTES=160_000_000
MAX_FILES=1600
ASSETS=('style.css','app.js','advertising.js','favicon.svg','privacy.html','ads.txt','robots.txt','og.png','og-20261030.png','061be3a140873a0279322a63c48f10ef.txt')
class ReleaseError(ValueError): pass
def sha(b):return hashlib.sha256(b).hexdigest()
def encoded(x):return json.dumps(x,ensure_ascii=False,separators=(',',':')).encode()
def writejson(path,x):path.write_bytes(encoded(x))
def source_binding(root):
 root=pathlib.Path(root)
 names=set(ASSETS)|{'index.source.html','vercel.json','.catalog-state.json.gz','publication-state.json'}
 names.update(p.name for p in root.iterdir() if p.is_file() and p.suffix in ('.py','.js'))
 files={name:sha((root/name).read_bytes()) for name in sorted(names) if (root/name).is_file()}
 files['route_identity_manifest']=sha(encoded(identity_manifest(root)))
 files['historical_badge_paths']=sha(encoded(sorted(p.name for p in (root/'badge').glob('*.svg'))))
 import subprocess
 revision=subprocess.run(['git','rev-parse','HEAD'],cwd=root,capture_output=True,text=True)
 return {'files':files,'revision':revision.stdout.strip() if revision.returncode==0 else None}
def clean_slug(s):
 if not isinstance(s,str) or not re.fullmatch('[a-z0-9-]{1,300}',s):raise ReleaseError('Invalid route slug')
 return s
def identity_manifest(root=ROOT):
 """Recover exact server identities from existing published HTML, not slugs."""
 saved=root/'route-history.json'
 if saved.exists():
  result=json.loads(saved.read_text())
  if result.get('schema_version')!=1:raise ReleaseError('Unknown route history schema')
  for slug,row in result['routes'].items():
   clean_slug(slug)
   if not isinstance(row.get('name'),str) or not row['name']:raise ReleaseError('Missing route identity')
  return result
 routes={}
 for p in sorted((root/'s').glob('*/index.html')):
  clean_slug(p.parent.name);raw=p.read_bytes();text=raw.decode()
  scripts=re.findall(r'<script type="application/ld\+json">(.*?)</script>',text,re.S)
  apps=[a for s in scripts for a in (json.loads(s) if s.lstrip().startswith('[') else [json.loads(s)]) if a.get('@type')=='SoftwareApplication']
  if len(apps)!=1 or not isinstance(apps[0].get('identifier'),str):raise ReleaseError('Cannot prove historical route identity: '+str(p))
  app=apps[0];routes[p.parent.name]={'name':app['identifier'],'title':app.get('name') or app['identifier'],'original_sha256':sha(raw),'observed_source':'ea77c400973804d67d826755ff51fcacf02fec99'}
 if not routes:raise ReleaseError('No historical route inventory')
 return {'schema_version':1,'routes':routes}

def stable_slugs(records,history):
 by_name=collections.defaultdict(list)
 for slug,row in history['routes'].items():by_name[row['name']].append(slug)
 used=set(history['routes']);result={}
 for row in sorted(records,key=lambda x:x['name']):
  name=row['name']
  if by_name[name]:slug=sorted(by_name[name])[0]
  else:
   slug=legacy.slugify(name)
   if slug in used:slug+='-'+sha(name.encode())[:12]
   if slug in used:raise ReleaseError('Unresolved stable identity collision')
  used.add(slug);row['slug']=clean_slug(slug);result[name]=slug
 return result

def normalized(source,receipt,history,prior):
 rows=[];now=datetime.datetime.fromisoformat(receipt['finished_at']);today=now.date().isoformat()
 prior_rows={x['name']:x for x in prior.get('servers',[])} if prior.get('collection_scope')=='official-v0.1-latest-including-deleted' else {}
 for item in source:
  server=item['server'];meta=item['_meta'][registry_collect.OFFICIAL]
  if meta['status']=='deleted':continue
  name=server['name'];title=server.get('title') or name.split('/')[-1];desc=server.get('description') or ''
  if not isinstance(title,str) or not isinstance(desc,str) or len(title)>2000 or len(desc)>20000:raise ReleaseError('Unbounded or invalid publisher text')
  packages=server.get('packages') or [];remotes=server.get('remotes') or []
  if not isinstance(packages,list) or not isinstance(remotes,list) or not all(isinstance(x,dict) for x in packages+remotes):raise ReleaseError('Invalid connection declarations')
  updated=meta.get('updatedAt') or meta.get('publishedAt');days=None
  if updated:
   try:days=(now-datetime.datetime.fromisoformat(updated.replace('Z','+00:00'))).total_seconds()/86400
   except (ValueError,TypeError):raise ReleaseError('Invalid registry timestamp')
   if days < -1/288:raise ReleaseError('Future registry timestamp')
  published=meta.get('publishedAt');pd=None
  if published:
   try:pd=(now-datetime.datetime.fromisoformat(published.replace('Z','+00:00'))).total_seconds()/86400
   except (ValueError,TypeError):raise ReleaseError('Invalid publication timestamp')
  row={'name':name,'title':title,'description':desc,'version':server.get('version'),'registry_status':meta['status'],'status_message':meta.get('statusMessage'),
       'transport':legacy.transport_of(server),'registries':legacy.registries(server),
       'pkg_ids':{x['registryType']:x['identifier'] for x in packages if isinstance(x.get('registryType'),str) and isinstance(x.get('identifier'),str)},
       'packages':packages,'remotes':remotes,'repository':legacy.safe_url((server.get('repository') or {}).get('url')) if isinstance(server.get('repository'),dict) else None,
       'website':legacy.safe_url(server.get('websiteUrl')),'published_at':published,'updated_at':updated,'is_latest':True,'updated_days':round(max(0,days),1) if days is not None else None,
       'health':'unknown' if days is None else 'active' if days<=30 else 'maintained' if days<=120 else 'stale','is_new':pd is not None and 0<=pd<=7,
       'category':legacy.categorize(title+' '+desc+' '+name)}
  rows.append(row)
 if not 1<=len(rows)<=MAX_RECORDS:raise ReleaseError('Record budget or empty catalog')
 stable_slugs(rows,history);rows.sort(key=lambda x:(x['updated_at'] or '',x['name']),reverse=True)
 for rank,row in enumerate(rows,1):
  rh=[p for p in prior_rows.get(row['name'],{}).get('rank_history',[]) if isinstance(p,dict) and type(p.get('rank')) is int and p.get('date','')<today][-89:]
  row.update(rank=rank,rank_prev=rh[-1]['rank'] if rh else None,rank_delta=rh[-1]['rank']-rank if rh else None,peak_rank=min([rank]+[p['rank'] for p in rh]),tracked_days=len(rh)+1,rank_history=rh+[{'date':today,'rank':rank}])
 cats=collections.Counter(x['category'] for x in rows)
 return {'generated_at':receipt['finished_at'],'generated_date':today,'source':'Official MCP Registry v0.1; publisher declarations','collection_complete':True,'collection_scope':'official-v0.1-latest-including-deleted',
         'collection_receipt_sha256':sha(encoded(receipt)),'server_count':len(rows),'registry_records':len(source),'deleted_count':len(source)-len(rows),
         'new_this_week':sum(x['is_new'] for x in rows),'active_count':sum(x['health']=='active' for x in rows),'categories':sorted(cats),'category_counts':dict(cats),
         'new_names':[x['name'] for x in rows if x['is_new']][:12],'movers':[{'name':x['name'],'title':x['title'],'slug':x['slug'],'category':x['category'],'rank':x['rank'],'rank_delta':x['rank_delta'],'is_new':x['is_new']} for x in sorted(rows,key=lambda x:x['rank_delta'] or 0,reverse=True) if (x['rank_delta'] or 0)>0][:5],
         'servers':rows}

def retained_page(slug,row,reason,date):
 e=lambda x:html.escape(str(x),quote=True)
 return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
  '<meta name="robots" content="noindex,follow"><title>'+e(row['title'])+' — historical registry reference | The MCP Index</title>'
  '<link rel="canonical" href="'+SITE+'/s/'+slug+'/"><link rel="stylesheet" href="/style.css"><link rel="icon" href="/favicon.svg"></head>'
  '<body><main class="detail"><div class="wrap"><a class="back" href="/">The MCP Index · Kymata Labs</a><h1>'+e(row['title'])+'</h1>'
  '<p class="d-name">'+e(row['name'])+'</p><section class="d-card"><h2>Historical registry reference</h2><p>'+e(reason)+'</p><p>Current traversal completed '+e(date)+'. This retained URL preserves the original server identity; it is not a recommendation or a working connection.</p>'
  '<p>Old install commands are withheld. Verify publisher identity, safety, availability and current documentation before using any server.</p><a href="/">Browse the current registry snapshot</a></section></div></main></body></html>').encode()

def updated_template(text):
 replacements={
  'Health · updated':'Registry freshness',
  'This legacy snapshot has no verified cursor-exhaustion receipt, so source completeness is unknown. Updates remain paused while the replacement publishing pipeline is validated.':'The snapshot is built only after the official latest-version cursor traversal completes. Deleted records are excluded from search and retained historical URLs are labeled. A moving registry is not an atomic census; listings are not independently tested.',
  'Completeness and current server availability are unverified.':'The declared latest-version traversal is complete; endpoint availability and safety are not independently verified.',
  'current availability and completeness are unverified.':'current availability and safety are not independently verified.',
  'completeness is unverified.':'latest-version traversal completed; runtime availability is unverified.',
  'Saved official-registry snapshot · source completeness unverified':'Official latest-version snapshot · cursor traversal verified',
  'Source completeness and current endpoint availability remain unverified. The daily refresh is paused pending validation of the replacement pipeline.':'The declared latest-version cursor traversal completed. Current endpoint availability and safety are not independently verified. Refresh is scheduled daily; the last successful snapshot date is shown.',
  'Saved snapshot; refresh paused':'Last successful snapshot shown · refresh scheduled daily'}
 for a,b in replacements.items():text=text.replace(a,b)
 return text

def build(capture,out,root=ROOT):
 capture=pathlib.Path(capture);out=pathlib.Path(out)
 if out.exists() or out.is_symlink():raise ReleaseError('Build destination must be new')
 if shutil.disk_usage(out.parent).free<2_000_000_000:raise ReleaseError('Insufficient safe temporary disk headroom')
 receipt=registry_collect.verify(capture)
 age=(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(receipt['finished_at'])).total_seconds()
 if not 0<=age<=36*3600:raise ReleaseError('Complete source capture is stale')
 source=json.loads((capture/'records.json').read_text())['servers'];history=identity_manifest(root)
 prior_path=root/'.catalog-state.json.gz';prior=json.loads(gzip.decompress(prior_path.read_bytes())) if prior_path.exists() else {}
 data=normalized(source,receipt,history,prior);current={x['name']:x for x in data['servers']};statuses={x['server']['name']:x['_meta'][registry_collect.OFFICIAL]['status'] for x in source}
 original=set(history['routes'])
 for row in data['servers']:
  history['routes'].setdefault(row['slug'],{'name':row['name'],'title':row['title'],'first_complete_capture':receipt['finished_at']})
 out.mkdir(mode=0o700,parents=True);output=out/'.vercel/output';static=output/'static';static.mkdir(parents=True);func=output/'functions/details.func';func.mkdir(parents=True)
 for name in ASSETS:
  p=root/name
  if p.is_file():shutil.copyfile(p,static/name)
 if (root/'gen_og.py').is_file():
  import gen_og
  gen_og.render(data,static/'og.png');gen_og.render(data,static/'og-20261030.png')
 # Long history belongs in the detail output/state, not every browser's search download.
 public=dict(data);public['servers']=[{k:v for k,v in x.items() if k not in ('rank_history','packages','remotes')} for x in data['servers']]
 writejson(static/'data.json',public)
 with tempfile.TemporaryDirectory(prefix='mcp-html-',dir=out) as rawfolder:
  raw=pathlib.Path(rawfolder);badges=legacy.generate_badges(data['servers'],str(static));legacy.generate_feed(data,badges,str(static));legacy.generate_rss(data,str(static))
  legacy.generate_details(data,str(raw),badges)
  dictionary=(raw/'s'/data['servers'][0]['slug']/'index.html').read_bytes()[-32768:]
  (func/'dictionary.bin').write_bytes(dictionary)
  pages={};route_status={};offset=0
  with (func/'pages.bin').open('wb') as packed:
   for slug,row in sorted(history['routes'].items()):
    active=current.get(row['name'])
    if active:
     body=(raw/'s'/active['slug']/'index.html').read_bytes()
     # Existing canonical identity stays stable even when a historical alias exists.
     body=body.replace(b'checks freshness.',b'checks recorded update timestamps, not runtime health.')
     body=body.replace(b'Updated daily from the official registry',b'Last successful snapshot: '+data['generated_at'].encode())
     if active['registry_status']=='deprecated':
      warning='<aside class="d-card"><strong>Publisher registry status: deprecated.</strong> '+html.escape(active.get('status_message') or 'Consult the publisher before use.')+'</aside>'
      body=body.replace(b'<div class="d-head">',warning.encode()+b'<div class="d-head">')
     route_status[slug]='current' if active['slug']==slug else 'historical_alias'
    else:
     state=statuses.get(row['name'])
     reason='The official registry marks this server as deleted.' if state=='deleted' else 'This identity was absent from the completed latest-version traversal. Absence alone does not establish why it is unavailable.'
     body=retained_page(slug,row,reason,data['generated_at']);route_status[slug]='deleted_reference' if state=='deleted' else 'unobserved_reference'
    if len(body)>1_000_000:raise ReleaseError('Detail page exceeds bound')
    encoder=zlib.compressobj(9,zlib.DEFLATED,-15,zdict=dictionary)
    zipped=encoder.compress(body)+encoder.flush();packed.write(zipped)
    pages[slug]={'offset':offset,'length':len(zipped),'bytes':len(body),'sha256':sha(body),'identity':row['name'],'state':route_status[slug]}
    offset+=len(zipped)
    if offset>MAX_FUNCTION_BYTES-10_000_000:raise ReleaseError('Function package byte budget exceeded')
  writejson(func/'pages.json',pages)
 shutil.copyfile(root/'packed_pages.js',func/'index.js')
 writejson(func/'.vc-config.json',{'runtime':'nodejs22.x','handler':'index.js','launcherType':'Nodejs','shouldAddHelpers':True,'maxDuration':5})
 presentation=render(static,updated_template((root/'index.source.html').read_text()))
 # Preserve previously published badge paths without misrepresenting old ranks as current.
 for p in (root/'badge').glob('*.svg'):
  clean_slug(p.stem)
  if not (static/'badge'/p.name).exists():
   (static/'badge'/p.name).write_text('<svg xmlns="http://www.w3.org/2000/svg" width="170" height="20"><title>Historical MCP Index badge; current registry rank is not asserted</title><rect width="170" height="20" fill="#555"/><text x="8" y="14" fill="white" font-size="11">MCP Index · historical reference</text></svg>')
 urls=[SITE+'/']+[SITE+'/s/'+x['slug'] for x in data['servers']]+[SITE+'/catalog/'+str(i)+'/' for i in range(2,presentation['pages']+1)]
 chunks=[urls[i:i+25000] for i in range(0,len(urls),25000)]
 sitemap_names=[]
 for i,chunk in enumerate(chunks,1):
  name='sitemap.xml' if len(chunks)==1 else f'sitemap-{i}.xml';sitemap_names.append(name)
  (static/name).write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join('<url><loc>'+html.escape(u)+'</loc></url>' for u in chunk)+'</urlset>')
 if len(chunks)>1:(static/'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join('<sitemap><loc>'+SITE+'/'+n+'</loc></sitemap>' for n in sitemap_names)+'</sitemapindex>')
 (static/'llms.txt').write_text('# The MCP Index\n\nOfficial registry latest-version snapshot. Cursor traversal completed '+data['generated_at']+'.\n\nSearchable non-deleted records: '+str(data['server_count'])+'. Registry-deleted identities are historical references, not recommendations. Freshness is a registry timestamp, not GitHub adoption, package safety or tested runtime availability. Listings are publisher declarations. No automatic connection or execution is performed.\n\n- Homepage: '+SITE+'/\n- Sitemap: '+SITE+'/sitemap.xml\n- Snapshot provenance: '+SITE+'/snapshot.json\n')
 (static/'ai.txt').write_text('The MCP Index is a Kymata Labs directory of publisher-declared official MCP registry records. See /snapshot.json for dated collection scope and /llms.txt for limitations. No safety or availability certification is implied.\n')
 snapshot={'schema_version':1,'captured_at':data['generated_at'],'source_endpoint':registry_collect.ENDPOINT,'filters':registry_collect.FILTERS,'traversal_complete':True,'atomic_snapshot':False,'source_pages':len(receipt['pages']),'source_records':receipt['total_records'],'records_sha256':receipt['records_sha256'],'search_records':data['server_count'],'deleted_records':data['deleted_count'],'data_sha256':sha((static/'data.json').read_bytes()),'route_states':dict(collections.Counter(route_status.values())),'limits':['Publisher declarations, not independently verified functionality, safety or licensing.','Historical routes are retained; missing identities are not guessed to be deleted.','Freshness is the recorded registry timestamp.']}
 writejson(static/'snapshot.json',snapshot)
 security=json.loads((root/'vercel.json').read_text())['headers'][0]['headers']
 config={'version':3,'routes':[{'src':'/(.*)','headers':{x['key']:x['value'] for x in security},'continue':True},{'src':'/s/([a-z0-9-]+)/?','dest':'/details?route=$1'},{'src':'/catalog/([0-9]+)/?','dest':'/catalog/$1/index.html'},{'handle':'filesystem'}]}
 writejson(output/'config.json',config)
 writejson(out/'previous-route-slugs.json',sorted(original));writejson(out/'route-history.json',history)
 state=dict(data);state['servers']=[{k:v for k,v in x.items() if k in ('name','rank','rank_history','first_seen','last_seen','slug')} for x in data['servers']]
 (out/'.catalog-state.json.gz').write_bytes(gzip.compress(encoded(state),mtime=0))
 files=[]
 for p in sorted(output.rglob('*')):
  if p.is_symlink():raise ReleaseError('Symlink in deployment package')
  if p.is_file():files.append({'path':str(p.relative_to(output)),'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())})
 if len(files)>MAX_FILES or sum(x['bytes'] for x in files)>MAX_PACKAGE_BYTES:raise ReleaseError('Deployment file/byte budget exceeded')
 if sum(p.stat().st_size for p in func.iterdir())>MAX_FUNCTION_BYTES:raise ReleaseError('Function budget exceeded')
 manifest={'schema_version':1,'created_at':data['generated_at'],'target_host':'mcp.kymatalabs.com','target_project':'prj_SAGAzK3ApYyopzV82TdMlS6vNXqO','target_team':'team_L6hpqgg8pEHznOzrnU66JuoW','source_records_sha256':receipt['records_sha256'],'snapshot':snapshot,'historical_routes_before':len(original),'historical_routes_missing':sorted(original-set(pages)),'routes':len(pages),'files':files,'static_pagination':presentation,'source_binding':source_binding(root),'release_status':'candidate_not_deployed'}
 manifest['state_files']={name:{'sha256':sha((out/name).read_bytes()),'bytes':(out/name).stat().st_size} for name in ('route-history.json','.catalog-state.json.gz','previous-route-slugs.json')}
 writejson(out/'package-manifest.json',manifest);verify_package(out)
 return manifest

def verify_package(out):
 out=pathlib.Path(out);manifest=json.loads((out/'package-manifest.json').read_text());root=out/'.vercel/output'
 if manifest.get('schema_version')!=1 or manifest.get('target_host')!='mcp.kymatalabs.com' or manifest.get('historical_routes_missing'):raise ReleaseError('Invalid candidate target or missing routes')
 expected={x['path']:x for x in manifest['files']}
 actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
 if set(expected)!=actual or len(actual)>MAX_FILES:raise ReleaseError('Package file set differs')
 for rel,row in expected.items():
  path=pathlib.PurePosixPath(rel)
  if path.is_absolute() or '..' in path.parts or (root/path).is_symlink():raise ReleaseError('Unsafe package path')
  raw=(root/path).read_bytes()
  if sha(raw)!=row['sha256'] or len(raw)!=row['bytes']:raise ReleaseError('Package file hash mismatch: '+rel)
 if sum(x['bytes'] for x in expected.values())>MAX_PACKAGE_BYTES:raise ReleaseError('Package byte bound')
 pages=json.loads((root/'functions/details.func/pages.json').read_text());pack=(root/'functions/details.func/pages.bin').read_bytes();dictionary=(root/'functions/details.func/dictionary.bin').read_bytes()
 if not 1<=len(dictionary)<=32768:raise ReleaseError('Invalid shared dictionary')
 if len(pages)!=manifest['routes']:raise ReleaseError('Route count mismatch')
 end=0
 for slug,row in pages.items():
  clean_slug(slug)
  if row['offset']!=end or not 0<row['length']<=1_000_000 or not 0<row['bytes']<=1_000_000:raise ReleaseError('Invalid packed range')
  decoder=zlib.decompressobj(-15,zdict=dictionary)
  raw=decoder.decompress(pack[end:end+row['length']],1_000_001);end+=row['length']
  if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:raise ReleaseError('Invalid bounded compressed page')
  if len(raw)!=row['bytes'] or sha(raw)!=row['sha256']:raise ReleaseError('Packed HTML integrity failure')
 if end!=len(pack):raise ReleaseError('Trailing or missing packed pages')
 data=(root/'static/data.json').read_bytes();home=(root/'static/index.html').read_text()
 if manifest['snapshot']['data_sha256']!=sha(data) or f'data-snapshot-sha256="{sha(data)}"' not in home:raise ReleaseError('Client/snapshot binding failure')
 names=('route-history.json','.catalog-state.json.gz','previous-route-slugs.json')
 if set(manifest.get('state_files',{}))!=set(names):raise ReleaseError('Missing bound publication state')
 for name in names:
  p=out/name;row=manifest['state_files'][name]
  if p.is_symlink() or p.stat().st_size>30_000_000:raise ReleaseError('Unsafe publication state file')
  raw=p.read_bytes()
  if len(raw)!=row['bytes'] or sha(raw)!=row['sha256']:raise ReleaseError('Publication state hash mismatch: '+name)
 history=json.loads((out/'route-history.json').read_text())
 if history.get('schema_version')!=1 or {k:v['name'] for k,v in history['routes'].items()}!={k:v['identity'] for k,v in pages.items()}:raise ReleaseError('Publication route identities differ')
 old=json.loads((out/'previous-route-slugs.json').read_text())
 if not isinstance(old,list) or any(not isinstance(s,str) for s in old) or len(old)!=len(set(old)) or len(old)!=manifest['historical_routes_before'] or not set(old)<=set(pages):raise ReleaseError('Historical route inventory differs or contains duplicates')
 with gzip.open(out/'.catalog-state.json.gz','rb') as stream:
  raw=stream.read(50_000_001)
  if len(raw)>50_000_000:raise ReleaseError('Expanded catalog state exceeds bound')
 state=json.loads(raw);public=json.loads(data)
 expected_state={x['name']:(x['slug'],x['rank']) for x in public['servers']}
 if len(state['servers'])!=len(expected_state) or {x['name']:(x['slug'],x['rank']) for x in state['servers']}!=expected_state or state['generated_at']!=public['generated_at'] or any('packages' in x or 'remotes' in x for x in state['servers']):raise ReleaseError('Catalog state differs from the verified public snapshot')
 return manifest

if __name__=='__main__':
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True);b=s.add_parser('build');b.add_argument('--capture',required=True);b.add_argument('--out',required=True);v=s.add_parser('verify');v.add_argument('--out',required=True);a=p.parse_args()
 result=build(a.capture,a.out) if a.cmd=='build' else verify_package(a.out)
 print(json.dumps({k:result[k] for k in ('target_host','routes','historical_routes_before','historical_routes_missing','snapshot')},indent=2))
