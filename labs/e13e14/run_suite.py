"""Run against already-started E14 services; preserve all failures, never deploy/release."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from orchestrate import ROOT, PORTS, execute, save
from scan_runtime_logs import main as scan_logs

STAGES = ['draft','full-check','incremental-check','repair','recheck']


def verify(out):
    result = json.loads((out/'result.json').read_text(encoding='utf-8'))
    if result['status'] != 'SUCCEEDED' or [x['name'] for x in result['stages']] != STAGES:
        raise ValueError('Five stages did not succeed')
    for stage in STAGES:
        value = json.loads((out/(stage+'.json')).read_text(encoding='utf-8'))
        if (value['job_id'],value['trace_id'],value['status']) != (
                result['job_id'],result['trace_id'],'SUCCEEDED'):
            raise ValueError('Stage identity/status mismatch')
    repair = json.loads((out/'repair.json').read_text(encoding='utf-8'))['data']
    incremental = json.loads((out/'incremental-check.json').read_text(encoding='utf-8'))['data']
    report = out/'incremental/incremental-check.json'
    if hashlib.sha256(report.read_bytes()).hexdigest() != incremental['sha256']:
        raise ValueError('Transferred incremental report SHA mismatch')
    consumed = repair['input_report']
    if (consumed['uri'],consumed['sha256'],consumed['commit'],consumed['job_id'],consumed['trace_id']) != (
            incremental['report'],incremental['sha256'],result['target_commit'],result['job_id'],result['trace_id']):
        raise ValueError('MDFixer did not consume this task/target/report SHA')
    if not repair['validation']['accepted']:
        raise ValueError('Repair was rejected')
    recheck = json.loads((out/'recheck.json').read_text(encoding='utf-8'))
    if (recheck['commit']!=result['target_commit'] or recheck['data']['remaining_missing']!=0
            or any(f['type']=='MISSING' for f in recheck['data']['result']['result']['findings'])):
        raise ValueError('Final recheck target/findings do not prove the repair')
    for item in result['artifacts']:
        path = (out/item['uri']).resolve()
        if not path.is_relative_to(out.resolve()) or not path.is_file():
            raise ValueError('Artifact escapes or is missing')
        if path.stat().st_size != item['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Artifact bytes/SHA mismatch: '+item['uri'])
    return result


def health():
    states = {}
    for role, port in PORTS.items():
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=5) as response:
                value = json.load(response)
            states[role] = value
        except Exception as exc:
            states[role] = {'error':str(exc)}
    return states


def capture(argv, path, env):
    try:
        result = subprocess.run(argv,capture_output=True,text=True,env=env,timeout=60)
        path.write_text(result.stdout+result.stderr,encoding='utf-8')
        return result.returncode
    except (OSError,subprocess.TimeoutExpired) as exc:
        path.write_text(str(exc),encoding='utf-8')
        return -1


def run(requests, out, compose_project, image):
    if out.exists() or not out.resolve().is_relative_to((ROOT/'work').resolve()) or out.resolve()==(ROOT/'work').resolve():
        raise ValueError('Choose a fresh child directory under work/')
    out.mkdir(parents=True)
    env = dict(os.environ,E14_ROOT=str(ROOT),E14_IMAGE=image)
    compose = ['docker','compose','-f',str(ROOT/'labs/e13e14/compose.yaml'),'-p',compose_project]
    summary = {'status':'RUNNING','release_status':'候选待发布','cases':[],
               'started_at':datetime.now(timezone.utc).isoformat(),'image':image,'evidence_errors':[]}
    def recorded(argv,path):
        code = capture(argv,path,env)
        if code:
            summary['evidence_errors'].append({'file':path.name,'exit_code':code})
        return code
    save(out/'health-before.json',health())
    recorded(['git','rev-parse','HEAD'],out/'source-commit.log')
    recorded(['git','status','--porcelain'],out/'source-worktree.log')
    input_manifest = ROOT/'data/e14-inputs/input-manifest.json'
    if input_manifest.is_file():
        (out/'input-manifest.json').write_bytes(input_manifest.read_bytes())
    recorded(compose+['ps','--format','json'],out/'compose-before.log')
    recorded(compose+['images','--format','json'],out/'compose-images.json')
    recorded(['docker','image','inspect',image],out/'image-inspect.json')
    fault = None
    process_reader = "import pathlib,json; print(json.dumps([p.read_bytes().replace(bytes([0]),b' ').decode(errors='replace') for p in pathlib.Path('/proc').glob('[0-9]*/cmdline') if p.exists()]))"
    def runtime_snapshot(prefix):
        recorded(['docker','ps','--no-trunc','--format','{{json .}}'],out/(prefix+'-containers.log'))
        recorded(compose+['exec','-T','draft','python3','-c',process_reader],out/(prefix+'-draft-processes.json'))
    for name in ('fixed','a14','b14','fault-timeout','recovery'):
        case = {'name':name,'passed':False}
        try:
            request = json.loads((requests/(name+'.json')).read_text(encoding='utf-8'))
            if name=='fault-timeout':
                runtime_snapshot('fault-before')
            result = execute(request,out/name)
            if name=='fault-timeout':
                runtime_snapshot('fault-immediate-after')
            case.update(status=result['status'],job_id=result['job_id'],trace_id=result['trace_id'])
            if name == 'fault-timeout':
                draft_result = json.loads((out/name/'draft-build/result.json').read_text(encoding='utf-8'))
                if result['status']!='TIMED_OUT' or draft_result['status']!='TIMED_OUT':
                    raise ValueError('Injection did not reproduce a DRAFT timeout; other failures do not count')
                fault = result
            else:
                verify(out/name)
                if name == 'recovery' and (fault is None or fault['job_id']==result['job_id'] or fault['trace_id']==result['trace_id']):
                    raise ValueError('Recovery needs a new successful task after a proven timeout')
            case['passed'] = True
        except Exception as exc:
            case['error'] = str(exc)
        summary['cases'].append(case)
        states = health()
        save(out/(name+'-health-after.json'),states)
        if any(value.get('status')!='ok' or value.get('role')!=role for role,value in states.items()):
            summary['evidence_errors'].append({'case':name,'error':'one or more role health checks failed'})
        recorded(compose+['logs','--no-color'],out/(name+'-services.log'))
        save(out/'summary.json',summary)
    recorded(compose+['ps','--format','json'],out/'compose-after.log')
    recorded(['docker','ps','--no-trunc','--format','{{json .}}'],out/'running-containers-after.log')
    # Read the DRAFT container's process command lines without installing ps.
    recorded(compose+['exec','-T','draft','python3','-c',process_reader],out/'draft-processes-after.json')
    scan_code = scan_logs([str(out)])
    summary.update(status='SUCCEEDED' if all(x['passed'] for x in summary['cases']) and scan_code==0 and not summary['evidence_errors'] else 'FAILED',
                   runtime_scan_exit=scan_code,finished_at=datetime.now(timezone.utc).isoformat(),
                   acceptance='E14 candidate evidence only; E13 sign-off, CI and release approval are separate.')
    save(out/'summary.json',summary)
    save(out/'manifest.json',[{'uri':p.relative_to(out).as_posix(),'bytes':p.stat().st_size,
          'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(out.rglob('*'))
          if p.is_file() and '.git' not in p.parts and not p.is_symlink()])
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requests',type=Path,default=ROOT/'data/e14-requests')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--compose-project',default='e14-241880284')
    parser.add_argument('--image',required=True)
    args = parser.parse_args()
    result = run(args.requests,args.out.resolve(),args.compose_project,args.image)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='SUCCEEDED' else 1


if __name__ == '__main__':
    sys.exit(main())
