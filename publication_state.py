"""Durable, repository-owned route state. A failed push never permits promotion."""
import hashlib, json, os, pathlib, shutil, subprocess
from release_pipeline import ReleaseError

BOOTSTRAP_DEPLOYMENT = 'dpl_BmhNqkCRCcGdNLRm2aJ2JmDA3jXS'
FILES = ('route-history.json', '.catalog-state.json.gz')

def git(root, *args):
    result = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ReleaseError('Durable publication state Git operation failed: ' + args[0])
    return result.stdout.strip()

def validate(root, production_id):
    root = pathlib.Path(root)
    path = root / 'publication-state.json'
    if not path.exists():
        if production_id != BOOTSTRAP_DEPLOYMENT:
            raise ReleaseError('Missing publication state for the observed production deployment')
        return None
    state = json.loads(path.read_text())
    if state.get('schema_version') != 1:
        raise ReleaseError('Unknown publication state schema')
    for name in FILES:
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != state['files'].get(name):
            raise ReleaseError('Publication state file differs: ' + name)
    if production_id == state['pending_id'] and state.get('status') != 'production_verified':
        raise ReleaseError('Pending deployment is public without durable verification; reconcile retained package first')
    if production_id not in (state['previous_id'], state['pending_id']):
        raise ReleaseError('Production is outside the recorded publication state; reconcile before publishing')
    return state

def commit(root, names, message):
    git(root, 'add', '--', *names)
    git(root, '-c', 'user.name=mcp-index-bot', '-c', 'user.email=actions@users.noreply.github.com', 'commit', '-m', message)
    revision = git(root, 'rev-parse', 'HEAD')
    git(root, 'push', 'origin', 'HEAD:main')
    if git(root, 'ls-remote', 'origin', 'refs/heads/main').split()[0] != revision:
        raise ReleaseError('Durable state revision is no longer main; reconcile before promotion')
    return revision

def store(root, state):
    path = pathlib.Path(root) / 'publication-state.json'
    temporary = path.with_suffix('.pending')
    with temporary.open('x') as stream:
        json.dump(state, stream, indent=2); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)

def persist(root, package, result):
    root, package = pathlib.Path(root), pathlib.Path(package)
    if git(root, 'status', '--porcelain'):
        raise ReleaseError('Source must be clean before persisting publication state')
    revision = git(root, 'rev-parse', 'HEAD')
    if git(root, 'ls-remote', 'origin', 'refs/heads/main').split()[0] != revision:
        raise ReleaseError('Publishing source must equal current main')
    state = dict(schema_version=1, status='candidate_verified_pending_promotion',
                 previous_id=result['previous_id'], pending_id=result['deployment_id'],
                 pending_url=result['origin'], project_id='prj_SAGAzK3ApYyopzV82TdMlS6vNXqO',
                 team_id='team_L6hpqgg8pEHznOzrnU66JuoW',
                 package_sha256=result['package_sha256'], source_revision=revision, files={})
    for name in FILES:
        shutil.copyfile(package/name, root/name)
        state['files'][name] = hashlib.sha256((root/name).read_bytes()).hexdigest()
    store(root, state)
    state['durable_revision'] = commit(root, [*FILES, 'publication-state.json'], 'data: persist verified candidate route union before promotion')
    return state

def confirm(root, state, result):
    # A failure here leaves a durable pending state. Next publication stops until
    # this exact retained package is reverified and confirmation is committed.
    state = {k:v for k,v in state.items() if k != 'durable_revision'}
    state.update(status='production_verified', production_verification_sha256=result['production_verification_sha256'])
    store(root, state)
    return commit(root, ['publication-state.json'], 'data: record successful public release verification')
