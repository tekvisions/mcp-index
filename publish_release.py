"""Explicit reviewed MCP publisher. CLI calls never retry ambiguous mutations.
Existing Vercel project only. Candidate verification precedes any promotion.
"""
import argparse,datetime,hashlib,json,os,pathlib,re,subprocess
from release_pipeline import verify_package,ReleaseError,source_binding
import publication_state
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

def publish(package,receipts,promote=False,all_historical=False,runner=cli,checker=verify,root=ROOT,state_writer=publication_state.persist,state_checker=publication_state.validate,state_confirmer=publication_state.confirm,resume=False):
 package=pathlib.Path(package).resolve();receipts=pathlib.Path(receipts).resolve()
 if receipts.exists() and not resume:raise ReleaseError('Publishing receipts must be new; inspect prior attempt instead of retrying')
 if resume and (not promote or not receipts.is_dir()):raise ReleaseError('Resume requires an existing verified candidate and explicit promotion')
 m=verify_package(package)
 age=(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(m['created_at'])).total_seconds()
 if not 0<=age<=36*3600:raise ReleaseError('Candidate capture is stale')
 if source_binding(root)!=m['source_binding']:raise ReleaseError('Candidate source inputs or revision differ')
 receipts.mkdir(mode=0o700,parents=True,exist_ok=resume)
 link=package/'.vercel/project.json'
 binding={'projectId':m['target_project'],'orgId':m['target_team'],'projectName':'mcp-index'}
 if link.exists() and json.loads(link.read_text())!=binding:raise ReleaseError('Existing project binding differs')
 link.write_text(json.dumps(binding))
 previous=runner(['inspect','https://mcp.kymatalabs.com','--format','json'],package,receipts,'resume-before' if resume else 'before')
 if previous.get('name')!='mcp-index' or previous.get('target')!='production' or previous.get('readyState')!='READY' or not re.fullmatch('dpl_[A-Za-z0-9]+',previous.get('id','')):raise ReleaseError('Current deployment identity unverified')
 prior_state=state_checker(root,previous['id']) if promote else None
 if promote and prior_state is None:all_historical=True
 manifest_sha=hashlib.sha256((package/'package-manifest.json').read_bytes()).hexdigest()
 if resume:
  saved=json.loads((receipts/'release.json').read_text());proof=json.loads((receipts/'candidate-verification.json').read_text())
  if saved.get('status')!='candidate_verified' or saved.get('promoted') is not False or saved.get('previous_id')!=previous['id'] or saved.get('package_sha256')!=manifest_sha:raise ReleaseError('Candidate resume state differs')
  proof_age=(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(proof['finished_at'])).total_seconds()
  if proof.get('status')!='passed' or proof.get('package_sha256')!=manifest_sha or proof.get('origin')!=saved['origin'] or not 0<=proof_age<=3600 or (prior_state is None and proof.get('all_historical') is not True):raise ReleaseError('Candidate verification is missing, stale, or incomplete')
  deployment={'url':saved['origin'],'id':saved['deployment_id']}
 else:
  deployment=runner(['deploy','--prebuilt','--prod','--skip-domain','--yes','--format','json','--meta','reviewedPackage='+manifest_sha],package,receipts,'candidate-deploy')
  deployment=deployment.get('deployment',deployment)
 url=deployment.get('url')
 if not isinstance(url,str):raise ReleaseError('Deployment response has no URL; inspect provider before retry')
 origin=url if url.startswith('https://') else 'https://'+url
 candidate=runner(['inspect',origin,'--format','json'],package,receipts,'candidate-reinspect' if resume else 'candidate-inspect')
 if candidate.get('id')!=deployment.get('id') or candidate.get('readyState')!='READY' or candidate.get('name')!='mcp-index' or candidate.get('target')!='production':raise ReleaseError('Candidate deployment identity unverified')
 check=checker(package,origin,receipts/('candidate-recheck.json' if resume else 'candidate-verification.json'),False if resume else all_historical)
 result={'status':'candidate_verified','origin':origin,'deployment_id':candidate['id'],'package_sha256':manifest_sha,'previous_id':previous['id'],'previous_url':previous['url'],'promoted':False}
 if promote:
  state=state_writer(root,package,result)
  result['durable_state_revision']=state['durable_revision']
  current=runner(['inspect','https://mcp.kymatalabs.com','--format','json'],package,receipts,'before-promote')
  if current.get('id')!=previous['id']:raise ReleaseError('Production changed concurrently; do not overwrite')
  runner(['promote',origin,'--yes'],package,receipts,'promote')
  result['promoted']=True
  result['status']='promoted_pending_public_verification'
  (receipts/'promotion-checkpoint.json').write_text(json.dumps(result,indent=2))
  try:
   checker(package,'https://mcp.kymatalabs.com',receipts/'production-verification.json',False)
  except Exception:
   current=runner(['inspect','https://mcp.kymatalabs.com','--format','json'],package,receipts,'before-rollback')
   if current.get('id')==candidate['id']:
    runner(['rollback',previous['url'],'--yes'],package,receipts,'rollback')
    result.update(status='rolled_back_after_failed_verification')
   else:result.update(status='production_changed_requires_reconciliation')
   (receipts/'release.json').write_text(json.dumps(result,indent=2));raise
  result['production_verification_sha256']=hashlib.sha256((receipts/'production-verification.json').read_bytes()).hexdigest()
  try:result['confirmed_state_revision']=state_confirmer(root,state,result)
  except Exception:
   result['status']='production_verified_pending_durable_confirmation';(receipts/'release.json').write_text(json.dumps(result,indent=2));raise
  result['status']='production_verified'
 (receipts/'release.json').write_text(json.dumps(result,indent=2));return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--package',required=True);p.add_argument('--receipts',required=True);p.add_argument('--promote',action='store_true');p.add_argument('--all-historical',action='store_true');p.add_argument('--resume-candidate',action='store_true');a=p.parse_args();print(json.dumps(publish(a.package,a.receipts,a.promote,a.all_historical,resume=a.resume_candidate),indent=2))
