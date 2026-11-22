"""Repository/subdirectory adapters and real Make rebuild probes; no Docker needed."""
import difflib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch as mock_patch

import pipeline
import lab


PROJECT_PATH = 'e13/projects/a14'
HEADER_PROBE = {
    'file': 'adjustment.h', 'before': '#define ADJUSTMENT 3',
    'after': '#define ADJUSTMENT 6', 'expected_output': '18',
}


def project_repo(root, nested=False):
    """Synthetic project with A14's published 5 + 7 + 3 behavior."""
    root.mkdir()
    project = root / PROJECT_PATH if nested else root
    project.mkdir(parents=True, exist_ok=True)
    (project/'main.c').write_text(
        '#include <stdio.h>\n#include "config.h"\n#include "adjustment.h"\n'
        'int helper(void);\nint main(void){printf("%d\\n",'
        'BASE+helper()+ADJUSTMENT);return 0;}\n')
    (project/'helper.c').write_text('int helper(void){return 7;}\n')
    (project/'config.h').write_text('#define BASE 5\n')
    (project/'adjustment.h').write_text('#define ADJUSTMENT 3\n')
    (project/'Makefile').write_text(
        'CFLAGS = -O0\napp: main.o helper.o\n\tgcc main.o helper.o -o app\n'
        'main.o: main.c config.h\n\tgcc $(CFLAGS) -c main.c -o main.o\n'
        'helper.o: helper.c\n\tgcc $(CFLAGS) -c helper.c -o helper.o\n'
        '.PHONY: clean\nclean:\n\trm -f main.o helper.o app\n')
    (root/'.gitignore').write_text('*.o\napp\n')
    if nested:
        # Root-level C sources must not alter the selected project's profile.
        (root/'unrelated.c').write_text('/* repository metadata project */\n')
    lab.run(['git', 'init', '-b', 'main'], root)
    lab.run(['git', 'config', 'user.name', 'ProfileTest'], root)
    lab.run(['git', 'config', 'user.email', 'profile@localhost'], root)
    sha = lab.commit(root, 'Synthetic project input')
    return project, sha


class ProjectPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_default_root_snapshot_keeps_original_commit(self):
        repo = self.root/'repo'
        _, sha = project_repo(repo)
        dest = self.root/'snapshot'
        self.assertEqual(pipeline.snapshot(repo, sha, dest, self.root/'logs'), sha)
        self.assertEqual(pipeline.project_directory(dest), dest.resolve())
        self.assertEqual(lab.run(['git', 'rev-parse', 'HEAD'], dest).strip(), sha)

    def test_subdirectory_snapshot_keeps_repository_target_identity(self):
        repo = self.root/'repo'
        _, sha = project_repo(repo, nested=True)
        dest = self.root/'snapshot'
        self.assertEqual(pipeline.snapshot(repo, sha, dest, self.root/'logs', PROJECT_PATH), sha)
        project = pipeline.project_directory(dest, PROJECT_PATH)
        self.assertEqual(project, dest/PROJECT_PATH)
        self.assertTrue((project/'main.c').is_file())
        self.assertFalse((dest/'unrelated.c').exists())
        self.assertFalse((dest/'.gitignore').exists())
        self.assertEqual(lab.run(['git', 'rev-parse', 'HEAD'], project).strip(), sha)
        self.assertEqual(lab.run(['git', 'status', '--porcelain'], repo), '')

    def test_rejects_absolute_parent_metadata_and_nonportable_paths(self):
        for value in ('../elsewhere', '/tmp/project', 'C:/project', 'C:\\project',
                      'a/../../elsewhere', '.git', 'a/.git', '', None):
            with self.subTest(value=value), self.assertRaises(pipeline.Failure) as caught:
                pipeline.project_directory(self.root/'snapshot', value)
            self.assertEqual(caught.exception.code, 'INVALID_REQUEST')

    def test_sparse_path_metacharacters_are_literal(self):
        repo = self.root/'repo'
        project_repo(repo, nested=True)
        special = 'e13/projects/a14[case]'
        lab.run(['git', 'mv', PROJECT_PATH, special], repo)
        neighbor = repo/'e13/projects/a14c'
        neighbor.mkdir()
        (neighbor/'unrelated.txt').write_text('must not enter the snapshot')
        sha = lab.commit(repo, 'Literal directory name, not a sparse pattern')
        dest = self.root/'snapshot'
        pipeline.snapshot(repo, sha, dest, self.root/'logs', special)
        self.assertTrue((dest/special/'Makefile').is_file())
        self.assertFalse((dest/'e13/projects/a14c').exists())

    def test_invalid_path_fails_before_cloning(self):
        with mock_patch.object(pipeline, 'command') as command:
            with self.assertRaises(pipeline.Failure):
                pipeline.snapshot(self.root, 'HEAD', self.root/'dest', self.root/'logs', '../bad')
            command.assert_not_called()

    def test_symlink_cannot_escape_snapshot(self):
        dest = self.root/'snapshot'
        dest.mkdir()
        outside = self.root/'outside'
        outside.mkdir()
        try:
            (dest/'project').symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Creating symlinks requires platform support/permission')
        with self.assertRaises(pipeline.Failure) as caught:
            pipeline.project_directory(dest, 'project')
        self.assertEqual(caught.exception.code, 'INVALID_REQUEST')

    def test_missing_subdirectory_is_reported_as_unsupported(self):
        repo = self.root/'repo'
        _, sha = project_repo(repo)
        with self.assertRaises(pipeline.Failure) as caught:
            pipeline.snapshot(repo, sha, self.root/'dest', self.root/'logs', 'missing')
        self.assertEqual(caught.exception.code, 'UNSUPPORTED_PROJECT')


class PipelineProfileWiringTests(unittest.TestCase):
    def test_selected_paths_and_behavior_reach_stage_adapters(self):
        # This is a unit test of stage wiring. Docker and full-check are mocked;
        # the snapshot and commit identities are verified with real Git.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, sha = project_repo(root/'repo', nested=True)
            out = root/'out'
            graph = [{'target': 'main.o', 'dependency': x} for x in ('config.h', 'main.c')]
            graph += [{'target': 'helper.o', 'dependency': 'helper.c'}]
            missing = [{'type': 'MISSING', 'target': 'main.o', 'dependency': 'adjustment.h'}]
            old = {'actual': {'main.o': ['config.h', 'main.c'], 'helper.o': ['helper.c']},
                   'commit': sha, 'findings': []}
            current = dict(old, findings=missing)

            def full(project, folder):
                findings = missing if folder.name == 'target-full' else []
                pipeline.save(folder/'actual-graph.json', graph)
                pipeline.save(folder/'findings.json', {'findings': findings})
                return {'status': 'SUCCEEDED', 'findings': findings}

            def draft(project, candidate, folder, expected, timeout):
                data = {'status': 'SUCCEEDED'}
                pipeline.save(folder/'result.json', data)
                return data

            def validate(project, candidate, folder, **kwargs):
                pipeline.save(folder/'validation.json', {'accepted': True})
                return {'accepted': True}

            request = {'mode': 'e12', 'repo': str(source.parents[2]), 'base': sha, 'target': sha,
                       'project_path': PROJECT_PATH, 'candidate': str(root/'Dockerfile'),
                       'expected_output': '15', 'header_probe': HEADER_PROBE, 'build_timeout': 42}
            with mock_patch.object(pipeline, 'full', side_effect=full) as full_mock, \
                    mock_patch.object(pipeline, 'scan', side_effect=[old, current]), \
                    mock_patch.object(pipeline, 'patch', return_value=('synthetic diff', [])), \
                    mock_patch.object(pipeline, 'validate', side_effect=validate) as validate_mock, \
                    mock_patch('draft.autobuild.auto_build', side_effect=draft) as draft_mock:
                result = pipeline.execute(request, out)
            self.assertEqual(result['status'], 'SUCCEEDED', result)
            target = out/'target-project'/PROJECT_PATH
            self.assertEqual(full_mock.call_args_list[0].args[0], out/'base-project'/PROJECT_PATH)
            self.assertEqual(draft_mock.call_args.args, (
                target, root/'Dockerfile', out/'draft-build', '15'))
            self.assertEqual(draft_mock.call_args.kwargs, {'timeout': 42})
            self.assertEqual(validate_mock.call_args.args[0], target)
            self.assertEqual(validate_mock.call_args.kwargs, {
                'expected_output': '15', 'header_probe': HEADER_PROBE})
            self.assertEqual(result['target_commit'], sha)
            self.assertEqual(lab.run(['git', 'rev-parse', 'HEAD'], target).strip(), sha)
            self.assertEqual((source/'adjustment.h').read_text(), '#define ADJUSTMENT 3\n')


class ProbeInputTests(unittest.TestCase):
    def test_unsafe_or_inapplicable_probe_is_rejected_before_build(self):
        # Rejection only needs Git, so these safety checks also run on Windows.
        for overrides, expected_error in (
                ({'file': '../outside.h'}, 'UNSAFE_HEADER_PROBE'),
                ({'file': '/tmp/outside.h'}, 'UNSAFE_HEADER_PROBE'),
                ({'file': 'C:/outside.h'}, 'UNSAFE_HEADER_PROBE'),
                ({'file': '.git/config'}, 'UNSAFE_HEADER_PROBE'),
                ({'before': '#define ADJUSTMENT 999'}, 'HEADER_PROBE_MISMATCH'),
                ({'after': HEADER_PROBE['before']}, 'INVALID_HEADER_PROBE')):
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                project, _ = project_repo(root/'repo')
                before = (project/'Makefile').read_bytes()
                result = lab.validate(project, root/'unused.patch', root/'evidence',
                                      expected_output='15', header_probe=dict(HEADER_PROBE, **overrides))
                self.assertFalse(result['accepted'])
                self.assertEqual(result['error'], expected_error)
                self.assertTrue(result['rollback'])
                self.assertEqual((project/'Makefile').read_bytes(), before)


@unittest.skipUnless(shutil.which('gcc') and shutil.which('make'),
                     'Real rebuild probes require local GCC/Make, never Docker')
class RealRebuildProbeTests(unittest.TestCase):
    def test_legacy_fixture_still_passes_without_profile_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root/'project'
            lab.fixture(project)
            candidate = root/'candidate.patch'
            candidate.write_bytes(lab.patch(project, lab.scan(project))[0].encode())
            result = lab.validate(project, candidate, root/'evidence')
            self.assertTrue(result['accepted'], result)
            self.assertEqual((root/'evidence/test.log').read_text().strip(), '1')
            self.assertEqual((root/'evidence/header-probe.log').read_text().strip(), '2')

    def test_custom_probe_rebuilds_15_to_18_and_keeps_source_header_and_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, sha = project_repo(root/'repo', nested=True)
            source_header = (project/'adjustment.h').read_bytes()
            candidate = root/'candidate.patch'
            candidate.write_bytes(lab.patch(project, lab.scan(project))[0].encode())
            result = lab.validate(project, candidate, root/'evidence',
                                  expected_output='15', header_probe=HEADER_PROBE)
            self.assertTrue(result['accepted'], result)
            self.assertTrue(all(result['checks'].values()))
            self.assertEqual((root/'evidence/test.log').read_text().strip(), '15')
            self.assertEqual((root/'evidence/header-probe.log').read_text().strip(), '18')
            self.assertIn('gcc -O0 -c main.c', (root/'evidence/incremental.log').read_text())
            self.assertEqual((project/'adjustment.h').read_bytes(), source_header)
            self.assertEqual(lab.run(['git', 'rev-parse', 'HEAD'], project).strip(), sha)
            self.assertEqual(lab.run(['git', 'diff', '--name-only'], project).strip(), PROJECT_PATH+'/Makefile')

    def test_buildable_patch_without_header_dependency_fails_rebuild_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, _ = project_repo(root/'repo')
            original = (project/'Makefile').read_text()
            changed = original.replace('CFLAGS = -O0', 'CFLAGS = -O1')
            candidate = root/'candidate.patch'
            candidate.write_bytes(''.join(difflib.unified_diff(
                original.splitlines(True), changed.splitlines(True),
                fromfile='a/Makefile', tofile='b/Makefile')).encode())
            result = lab.validate(project, candidate, root/'evidence',
                                  expected_output='15', header_probe=HEADER_PROBE)
            self.assertFalse(result['accepted'])
            self.assertTrue(result['checks']['build'])
            self.assertTrue(result['checks']['test'])
            self.assertFalse(result['checks']['header_change'])
            self.assertFalse(result['checks']['no_missing'])
            self.assertEqual((root/'evidence/header-probe.log').read_text().strip(), '15')
            self.assertTrue(result['rollback'])
            self.assertEqual((project/'Makefile').read_text(), original)

    def test_wrong_expected_output_rejects_a_buildable_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, _ = project_repo(root/'repo')
            original = (project/'Makefile').read_bytes()
            candidate = root/'candidate.patch'
            candidate.write_bytes(lab.patch(project, lab.scan(project))[0].encode())
            result = lab.validate(project, candidate, root/'evidence',
                                  expected_output='999', header_probe=HEADER_PROBE)
            self.assertFalse(result['accepted'])
            self.assertFalse(result['checks']['test'])
            self.assertTrue(result['checks']['header_change'])
            self.assertTrue(result['rollback'])
            self.assertEqual((project/'Makefile').read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
