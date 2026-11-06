"""Explicit reviewed MCP publisher. CLI calls never retry ambiguous mutations.
Existing Vercel project only. Candidate verification precedes any promotion.
"""
import argparse,datetime,hashlib,json,os,pathlib,re,subprocess
from release_pipeline import verify_package,ReleaseError
from verify_release import verify
ROOT=pathlib.Path(__file__).resolve().parent

def cli(args,cwd,logdir,name):
 token=os.environ.get('VERCEL_TOKEN')
 command=['vercel',*args]+(['--token',token] if token else [])
 p=subprocess.run(command,cwd=cwd,text=True,capture_output=True,timeout=900)
 # Never serialize argv/environment, which may contain the provider token.
 clean=lambda s:s.replace(token,'[REDACTED]') if token else s
 (logdir/(name+'.stdout')).write_text(clean(p.stdout));(logdir/(name+'.stderr')).write_text(clean(p.stderr))
 if p.returncode:raise ReleaseError('Vercel '+name+' failed; inspect receipt before retrying any mutation')
 return json.loads(p.stdout) if '--format' in args else p.stdout

def publish(package,receipts,promote=False,all_historical=False,runner=cli,checker=verify):
 package=pathlib.Path(package).resolve();receipts=pathlib.Path(receipts).resolve()
 if receipts.exists():raise ReleaseError('Publishing receipts must be new; inspect prior attempt instead of retrying')
 m=verify_package(package)
 age=(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(m['created_at'])).total_seconds()
 if not 0<=age<=36*3600:raise ReleaseError('Candidate capture is stale')
 for name,digest in m['source_code'].items():
  if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise ReleaseError('Candidate source code differs: '+name)
 receipts.mkdir(mode=0o700,parents=True)
 link=package/'.vercel/project.json'
 binding={'projectId':m['target_project'],'orgId':m['target_team'],'projectName':'mcp-index'}
 if link.exists() and json.loads(link.read_text())!=binding:raise ReleaseError('Existing project binding differs')
 link.write_text(json.dumps(binding))
 previous=runner(['inspect','https://mcp.kymatalabs.com','--format','json'],package,receipts,'before')
 if previous.get('name')!='mcp-index' or previous.get('target')!='production' or previous.get('readyState')!='READY' or not re.fullmatch('dpl_[A-Za-z0-9]+',previous.get('id','')):raise ReleaseError('Current deployment identity unverified')
 manifest_sha=hashlib.sha256((package/'package-manifest.json').read_bytes()).hexdigest()
 deployment=runner(['deploy','--prebuilt','--prod','--skip-domain','--yes','--format','json','--meta','reviewedPackage='+manifest_sha],package,receipts,'candidate-deploy')
 deployment=deployment.get('deployment',deployment)
 url=deployment.get('url')
 if not isinstance(url,str):raise ReleaseError('Deployment response has no URL; inspect provider before retry')
 origin=url if url.startswith('https://') else 'https://'+url
 check=checker(package,origin,receipts/'candidate-verification.json',all_historical)
 result={'status':'candidate_verified','origin':origin,'package_sha256':manifest_sha,'previous_id':previous['id'],'previous_url':previous['url'],'promoted':False}
 if promote:
  current=runner(['inspect','https://mcp.kymatalabs.com','--format','json'],package,receipts,'before-promote')
  if current.get('id')!=previous['id']:raise ReleaseError('Production changed concurrently; do not overwrite')
  runner(['promote',origin,'--yes'],package,receipts,'promote')
  result['promoted']=True
  try:
   checker(package,'https://mcp.kymatalabs.com',receipts/'production-verification.json',False)
  except Exception:
   # Prior production was observed and identity-bound immediately before promotion.
   runner(['rollback',previous['url'],'--yes'],package,receipts,'rollback')
   result.update(status='rolled_back_after_failed_verification');(receipts/'release.json').write_text(json.dumps(result,indent=2));raise
  result['status']='production_verified'
 (receipts/'release.json').write_text(json.dumps(result,indent=2));return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--package',required=True);p.add_argument('--receipts',required=True);p.add_argument('--promote',action='store_true');p.add_argument('--all-historical',action='store_true');a=p.parse_args();print(json.dumps(publish(a.package,a.receipts,a.promote,a.all_historical),indent=2))
