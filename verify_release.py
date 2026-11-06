"""Verify an immutable candidate or production against exact build bytes.
Read-only, HTTPS, no redirects, bounded response sizes and sequential requests.
"""
import argparse,datetime,hashlib,json,pathlib,time,urllib.error,urllib.parse,urllib.request
from release_pipeline import verify_package,ReleaseError
MAX_BODY=65_000_000
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):raise ReleaseError('Unexpected release redirect')
def fetch(url,method='GET'):
 req=urllib.request.Request(url,method=method,headers={'User-Agent':'Kymata-MCP-Release-Verification/1.0','Accept-Encoding':'identity'})
 try:
  with urllib.request.build_opener(NoRedirect()).open(req,timeout=60) as r:
   body=r.read(MAX_BODY+1)
   if len(body)>MAX_BODY:raise ReleaseError('Response byte bound')
   return r.status,dict(r.headers.items()),body
 except urllib.error.HTTPError as e:return e.code,dict(e.headers.items()),e.read(4096)
def verify(out,base,receipt,all_historical=False,fetcher=fetch,delay=.15):
 out=pathlib.Path(out);receipt=pathlib.Path(receipt)
 if receipt.exists():raise ReleaseError('Verification receipt must be new')
 m=verify_package(out);u=urllib.parse.urlsplit(base)
 if u.scheme!='https' or u.username or u.password or u.port not in (None,443) or u.path not in ('','/') or u.query or u.fragment:raise ReleaseError('Invalid release origin')
 if u.hostname!='mcp.kymatalabs.com' and not (u.hostname or '').endswith('-techtalevisions-projects.vercel.app'):raise ReleaseError('Unapproved release host')
 root=out/'.vercel/output';files={x['path']:x for x in m['files']};routes=json.loads((root/'functions/details.func/pages.json').read_text())
 observations=[];result={'schema_version':1,'origin':base,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'package_sha256':hashlib.sha256((out/'package-manifest.json').read_bytes()).hexdigest(),'all_historical':all_historical,'candidate_policy':'Each candidate response must retain provider noindex; this is crawler exclusion, not access authentication.','status':'failed','observations':observations}
 def check(path,expected=None,method='GET',status=200):
  code,h,b=fetcher(base.rstrip('/')+path,method);h={k.lower():v for k,v in h.items()};d=hashlib.sha256(b).hexdigest() if method=='GET' else h.get('x-content-sha256')
  row={'path':path,'method':method,'status':code,'sha256':d,'bytes':len(b),'content_type':h.get('content-type'),'x_robots_tag':h.get('x-robots-tag')};observations.append(row)
  if code!=status or (expected and d!=expected):raise ReleaseError('Release response mismatch: '+path)
  if code==200 and (h.get('x-content-type-options')!='nosniff' or 'frame-ancestors' not in h.get('content-security-policy','')):raise ReleaseError('Security headers missing: '+path)
  if u.hostname=='mcp.kymatalabs.com' and code==200 and h.get('x-robots-tag') and 'noindex' in h['x-robots-tag'].lower():raise ReleaseError('Unexpected provider noindex: '+path)
  if u.hostname!='mcp.kymatalabs.com' and code==200 and 'noindex' not in h.get('x-robots-tag','').lower():raise ReleaseError('Candidate provider noindex missing: '+path)
  if delay:time.sleep(delay)
 try:
  static=['index.html','data.json','snapshot.json','app.js','style.css','privacy.html','robots.txt','llms.txt','ai.txt','og.png','sitemap.xml']+[p[7:] for p in files if p.startswith('static/sitemap-')]
  last=m['static_pagination']['pages']
  if last>1:static+=['catalog/2/index.html',f'catalog/{last}/index.html']
  for p in static:
   public='/' if p=='index.html' else ('/'+p.replace('index.html','') if p.startswith('catalog/') else '/'+p)
   check(public,files['static/'+p]['sha256'])
  selected=set(list(routes)[:8]+list(routes)[-8:])
  for state in set(x['state'] for x in routes.values()):selected.update([k for k,v in routes.items() if v['state']==state][:8])
  for slug in sorted(selected):check('/s/'+slug+'/',routes[slug]['sha256'])
  # Every pre-existing route is checked on initial release. New routes are decoded
  # and hash-checked offline; runtime selection is stated explicitly above.
  if all_historical:
   old=json.loads((out/'previous-route-slugs.json').read_text())
   if len(old)!=m['historical_routes_before']:raise ReleaseError('Historical verification inventory differs')
   for slug in sorted(set(old)-selected):check('/s/'+slug+'/',routes[slug]['sha256'],'HEAD')
  check('/s/discovery-release-nonexistent-20261106/',method='GET',status=404)
  result['status']='passed'
 except Exception as e:
  result['error']=type(e).__name__+': '+str(e);raise
 finally:
  result['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();receipt.parent.mkdir(parents=True,exist_ok=True);receipt.write_text(json.dumps(result,indent=2))
 return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--origin',required=True);p.add_argument('--receipt',required=True);p.add_argument('--all-historical',action='store_true');a=p.parse_args();r=verify(a.out,a.origin,a.receipt,a.all_historical);print(json.dumps({'status':r['status'],'requests':len(r['observations']),'origin':r['origin']}))
