"""Compose the existing E5-E10 teaching components using versioned artifacts."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'labs/e8e10'), str(ROOT / 'labs/e11e12/vendor'), '/app']
from lab import scan, patch, validate
from pair14 import run_pair14, write_json
from live_report import preflight_fixed_report, bind_live_inputs

class Failure(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)

def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, obj)

def artifact(path, out, job_id):
    return {'uri': f'artifact://{job_id}/{path.relative_to(out).as_posix()}',
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes':path.stat().st_size}

def check_envelope(report, commit, kind=None):
    if report.get('schema_version') != 'e11e12-1':
        raise Failure('SCHEMA_MISMATCH', 'Expected e11e12-1')
    if report.get('commit') != commit:
        raise Failure('STALE_REPORT', 'Report belongs to another commit')
    if report.get('status') != 'SUCCEEDED':
        raise Failure('UPSTREAM_FAILED', 'Upstream stage did not succeed')
    if kind and report.get('kind') != kind:
        raise Failure('ARTIFACT_TYPE_MISMATCH', kind)

def load_artifact(path, expected_sha256):
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=expected_sha256:
        raise Failure('ARTIFACT_HASH_MISMATCH','Artifact content changed during transfer')
    return json.loads(data)

def command(argv, cwd, log):
    log.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=120)
    log.write_text(p.stdout+p.stderr, encoding='utf-8')
    if p.returncode:
        raise Failure('COMMAND_FAILED', f'{argv[0]} failed; see {log.name}')
    return p.stdout.strip()

def project_directory(snapshot_root, project_path='.'):
    # Repository paths use portable, relative slash-separated names. Resolve
    # again after checkout so a symlink cannot escape the isolated snapshot.
    if (not isinstance(project_path, str) or not project_path or '\\' in project_path
            or re.match(r'^[A-Za-z]:', project_path)):
        raise Failure('INVALID_REQUEST', 'project_path must be a repository-relative path')
    relative = Path(project_path)
    if relative.is_absolute() or '..' in relative.parts or '.git' in relative.parts:
        raise Failure('INVALID_REQUEST', 'project_path must stay inside the repository')
    root = snapshot_root.resolve()
    project = (root / relative).resolve()
    if not project.is_relative_to(root):
        raise Failure('INVALID_REQUEST', 'project_path escapes the repository snapshot')
    return project


def snapshot(repo, revision, dest, logs, project_path='.'):
    project_directory(dest, project_path)
    sha = command(['git','rev-parse','--verify',revision+'^{commit}'], repo, logs/(dest.name+'-resolve.log'))
    command(['git','clone','--no-hardlinks','--no-checkout',str(repo),str(dest)], repo, logs/(dest.name+'-clone.log'))
    relative = Path(project_path).as_posix()
    if relative != '.':
        # Use one anchored, escaped gitignore-style directory pattern. Cone
        # mode would also check out unrelated files from ancestor directories.
        pattern = '/' + re.sub(r'([*?\[\]])', r'\\\1', relative) + '/'
        command(['git','sparse-checkout','set','--no-cone','--',pattern], dest,
                logs/(dest.name+'-sparse.log'))
    command(['git','checkout','--detach',sha], dest, logs/(dest.name+'-checkout.log'))
    project = project_directory(dest, project_path)
    # E8-E10 profile; fail early instead of silently ignoring other targets.
    names = {p.name for p in project.glob('*.c')}
    if (names != {'main.c','helper.c'} or not (project/'config.h').is_file()
            or not (project/'Makefile').is_file()
            or any(p.is_symlink() for p in project.rglob('*'))):
        raise Failure('UNSUPPORTED_PROJECT', 'Expected main.c/helper.c/config.h and explicit Make rules')
    return sha

def full(project, folder):
    from buildchecker.fullcheck import full_check
    report = full_check(project, folder)
    if report.get('status') != 'SUCCEEDED':
        raise Failure('FULL_CHECK_FAILED', str(report.get('error', report.get('error_code'))))
    return report

def normalized(findings):
    return sorted((f['type'],f['target'],f['dependency']) for f in findings if f['target'] in ('main.o','helper.o'))

def execute(request, out, job_id=None):
    job_id = job_id or 'job-'+uuid.uuid4().hex
    if out.exists() and any(out.iterdir()):
        raise Failure('OUTPUT_EXISTS', 'Use a fresh output directory')
    out.mkdir(parents=True, exist_ok=True)
    result = {'schema_version':'e11e12-1','job_id':job_id,'trace_id':'trace-'+uuid.uuid4().hex,'status':'RUNNING','stages':[]}
    save(out/'request.json',request)
    def stage(name, commit, payload, files=(), status='SUCCEEDED'):
        envelope = {'schema_version':'e11e12-1','job_id':job_id,'trace_id':result['trace_id'],'kind':name,
                    'commit':commit,'status':status,'data':payload,
                    'artifacts':[artifact(p,out,job_id) for p in files]}
        save(out/(name+'.json'),envelope)
        result['stages'].append({'name':name,'artifact':artifact(out/(name+'.json'),out,job_id)})
        return envelope
    try:
        mode=request['mode']
        if mode not in ('e11-a','e11-b','e12'):
            raise Failure('INVALID_REQUEST','Unknown mode')
        if mode == 'e12' and 'handoff' in request:
            run_pair14(request, out, result, stage)
            result['status'] = 'SUCCEEDED'
            return finish(out, result, job_id)
        repo=Path(request['repo']).resolve()
        if not repo.is_dir():
            raise Failure('INVALID_REQUEST','Repository missing')
        prepared=preflight_fixed_report(request,out) if mode=='e11-b' else None
        project_path=request.get('project_path','.')
        base_root=out/'base-project'; target_root=out/'target-project'
        base_sha=snapshot(repo,request['base'],base_root,out/'logs',project_path)
        target_sha=snapshot(repo,request['target'],target_root,out/'logs',project_path)
        base=project_directory(base_root,project_path)
        target=project_directory(target_root,project_path)
        result.update(base_commit=base_sha,target_commit=target_sha)
        if prepared is not None:
            fixed_data,binding_files=bind_live_inputs(prepared,repo,target_sha,target,project_path,out)
        if mode in ('e11-b','e12'):
            from draft.autobuild import auto_build
            candidate=Path(request['candidate']).resolve()
            draft=auto_build(target,candidate,out/'draft-build',request.get('expected_output','1'),timeout=request.get('build_timeout',600))
            if draft['status']!='SUCCEEDED':
                raise Failure('DRAFT_FAILED',draft.get('error','Inspect draft-build logs'))
            stage('draft',target_sha,draft,[out/'draft-build/result.json'])
        if mode in ('e11-a','e12'):
            base_full=full(base,out/'baseline-full')
            old=scan(base)
            edges=json.loads((out/'baseline-full/actual-graph.json').read_text())
            projected={t:sorted({e['dependency'] for e in edges if e['target']==t}) for t in ('main.o','helper.o')}
            if projected != old['actual']:
                raise Failure('GRAPH_MISMATCH','BuildChecker baseline differs from GCC observations')
            old['actual']=projected
            save(out/'baseline-cache.json',old)
            baseline=stage('full-check',base_sha,base_full,[out/'baseline-full/actual-graph.json',out/'baseline-full/findings.json',out/'baseline-cache.json'])
            check_envelope(baseline,base_sha,'full-check')
            current=scan(target,old)
            save(out/'incremental-report.json',current)
            reference=full(target,out/'target-full')
            if normalized(reference['findings']) != normalized(current['findings']):
                raise Failure('FINDINGS_MISMATCH','Incremental/full object-target findings differ')
            md_envelope=stage('incremental-check',target_sha,current,[out/'incremental-report.json',out/'target-full/findings.json'])
        else:
            # Preserve A's original bytes; any verified legacy input binding is B evidence.
            current=fixed_data
            md_envelope=stage('fixed-md',target_sha,current,[out/'fixed-md-input.json',*binding_files])
        if mode in ('e11-b','e12'):
            reference=result['stages'][-1]['artifact']
            md_envelope=load_artifact(out/(md_envelope['kind']+'.json'),reference['sha256'])
            check_envelope(md_envelope,target_sha)
            current=md_envelope['data']
            before=(target/'Makefile').read_bytes()
            diff,edits=patch(target,current)
            if not diff:
                raise Failure('NO_MISSING_DEPENDENCY','No MD to repair')
            patchfile=out/'candidate.patch';patchfile.write_bytes(diff.encode('utf-8'))
            save(out/'repair-plan.json',edits)
            stage('repair',target_sha,{'edits':edits,'input_report':artifact(out/(md_envelope['kind']+'.json'),out,job_id)},[patchfile,out/'repair-plan.json'])
            verdict=validate(target,patchfile,out/'validation',
                             expected_output=request.get('expected_output','1'),
                             header_probe=request.get('header_probe'))
            if not verdict['accepted']:
                raise Failure('REPAIR_REJECTED',str(verdict))
            final=full(target,out/'final-full')
            if any(f['type']=='MISSING' for f in final['findings']):
                (target/'Makefile').write_bytes(before)
                raise Failure('RECHECK_FAILED','MD remains; working-copy declaration restored')
            stage('recheck',target_sha,{'validation':verdict,'findings':final['findings'],'patched_makefile_sha256':hashlib.sha256((target/'Makefile').read_bytes()).hexdigest()},[out/'validation/validation.json',out/'final-full/findings.json'])
        result['status']='SUCCEEDED'
    except (ValueError, OSError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        code = getattr(exc, 'code', 'EXECUTION_FAILED')
        timed_out = isinstance(exc, subprocess.TimeoutExpired) or code == 'RECHECK_TIMEOUT'
        result.update(status='TIMED_OUT' if timed_out else 'FAILED',
                      error={'code': code, 'message': str(exc)})
    return finish(out, result, job_id)


def finish(out, result, job_id):
    result['artifacts']=[artifact(p,out,job_id) for p in sorted(out.rglob('*')) if p.is_file() and '.git' not in p.parts and not p.is_symlink()]
    save(out/'result.json',result)
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();r=execute(json.loads(a.request.read_text(encoding='utf-8')),a.out.resolve());print(json.dumps(r,ensure_ascii=False,indent=2));return 0 if r['status']=='SUCCEEDED' else 1

if __name__=='__main__':raise SystemExit(main())
