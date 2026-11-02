from pathlib import Path
import sys, json, hashlib, difflib
sys.path.insert(0, str(Path('e5/scripts').resolve()))
import run_e5 as driver
root = Path('work/e5-20261030-run01').resolve()
selected = json.loads((root/'candidates/context-mirror/result.json').read_text())
image = selected['image_id']
driver.run_command(['python3', '-m', 'unittest', 'discover', '-s', 'e5/tests', '-v'], Path.cwd(), root/'checks/unit-tests', 180)
driver.run_command(['python3', 'validator/validate.py', '--suite'], Path.cwd(), root/'checks/contract-suite', 180)
driver.run_command(['sh', '-c', 'cat /etc/os-release; uname -a; nproc; free -m; df -h /; docker version; git --version; python3 --version'], Path.cwd(), root/'environment/host-details', 30)
driver.run_command(['docker','run','--rm','--network','none',image,'sh','-c','gcc --version; make --version; dpkg-query -W build-essential gcc make libc6-dev; sha256sum /work/main.c /work/Makefile /work/hello; od -An -tx1 -N4 /work/hello'], Path.cwd(), root/'environment/final-image-tools', 30)
driver.run_command(['docker','ps','--all','--filter','name=e5-'+driver.read_json(root/'run.json')['run_id'],'--format','{{.ID}} {{.Names}} {{.Status}}'], Path.cwd(), root/'checks/remaining-containers', 30)
driver.run_command(['git','rev-parse','HEAD'], Path.cwd(), root/'checks/execution-source', 30)
for strategy in ['error-driven','context-driven']:
    source=Path('e5/model-records')/strategy
    for name in ['prompt.txt','model-input.txt']:
        driver.write_new(root/'candidates'/strategy/name,(source/name).read_bytes())
driver.write_new(root/'candidates/context-mirror/repair.diff',Path('e5/candidates/context-mirror/repair.diff').read_bytes())
normalized={name:driver._instructions((root/'candidates'/name/'Dockerfile').read_text()) for name in ['error-driven','context-driven']}
# Collapse continuation whitespace only for the classroom comparison, retain raw files.
normalized={name:[(kind,' '.join(value.split())) for kind,value in entries] for name,entries in normalized.items()}
decision={'selected':'context-mirror','normalized_original_candidates_equal':normalized['error-driven']==normalized['context-driven'],'normalization':'Ignore formatting whitespace and Dockerfile backslash-newline continuations for comparison only','R1':'The two original model candidates are equivalent after classroom normalization; preserve both raw responses and count one distinct dependency repair.','R2':'No independent multi-candidate majority experiment was performed.','R3':'Both install build-essential, which supplies GNU Make and the C toolchain; the original missing-make error is addressed.','R4':'No additional model-based tie-break was necessary.','selection_reason':'Both original candidates exhausted the equal 240-second budgets while downloading Debian packages. The context candidate was retained in readable multiline form; a separately recorded dependency-download source/IPv4/retry adaptation built successfully and ran the exact image ID offline. No prompt-strategy superiority or mirror-only speedup is claimed because adaptation also changes download options and budget.','base_digest_unchanged':True,'project_files_unchanged':True,'limits':['One course-authored TinyGreeting fixture','Model/API billing calls made by the driver: 0','No E6 service or E7 CI completion claim']}
driver.write_json(root/'decision.json',decision)
for rel in ['checks/unit-tests','checks/contract-suite','environment/host-details','environment/final-image-tools','checks/remaining-containers','checks/execution-source']:
    assert driver.succeeded(driver.read_json(root/rel/'command.json')), rel
assert not (root/'checks/remaining-containers/stdout.log').read_bytes().strip()
print(json.dumps({'augmentation':'complete','normalized_original_candidates_equal':decision['normalized_original_candidates_equal']},indent=2))
