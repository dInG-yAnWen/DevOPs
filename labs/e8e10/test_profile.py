import json, tempfile, unittest
from pathlib import Path
from lab import fixture,scan,patch,commit,validate

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.p=Path(self.tmp.name)/'sample';fixture(self.p)

    def test_independent_known_edges(self):
        r=scan(self.p)
        self.assertEqual(r['actual']['main.o'],['config.h','main.c'])
        self.assertEqual({(f['type'],f['dependency']) for f in r['findings']},{('MISSING','config.h'),('REDUNDANT','unused.h')})

    def test_unchanged_reuses_both_targets(self):
        r=scan(self.p,scan(self.p));self.assertEqual(r['reused'],['main.o','helper.o']);self.assertEqual(r['refreshed'],[])

    def test_include_added_invalidates_cache(self):
        old=scan(self.p)
        (self.p/'main.c').write_text('#include "extra.h"\n'+(self.p/'main.c').read_text());commit(self.p,'new include')
        r=scan(self.p,old)
        self.assertIn(['MISSING','main.o','extra.h'],r['added']);self.assertEqual(len(r['refreshed']),2)

    def test_patch_preserves_redundant_dependency(self):
        r=scan(self.p);diff,plan=patch(self.p,r)
        self.assertIn('+main.o: main.c unused.h config.h',diff)
        self.assertNotIn('-\tgcc',diff)
        self.assertNotIn('config.h',(self.p/'Makefile').read_text())

    def test_old_report_rejected(self):
        r=scan(self.p);r['commit']='0'*40
        with self.assertRaisesRegex(ValueError,'STALE_REPORT'):patch(self.p,r)

    def test_unsafe_dependency_rejected(self):
        r=scan(self.p);r['findings']=[{'type':'MISSING','target':'main.o','dependency':'../outside.h'}]
        with self.assertRaisesRegex(ValueError,'UNSAFE_PATH'):patch(self.p,r)

    def test_unsupported_configuration_rejected(self):
        (self.p/'Makefile').write_text((self.p/'Makefile').read_text().replace('-O0','-include unknown.h'))
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED_FLAGS'):scan(self.p)


class RepairValidationTests(unittest.TestCase):
    def test_buildable_patch_with_remaining_missing_dependency_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / 'sample'
            fixture(project)
            helper = project / 'helper.c'
            helper.write_text('#include "extra.h"\n' + helper.read_text())
            commit(project, 'Add an undeclared header to helper.o')
            before = (project / 'Makefile').read_bytes()

            candidate = root / 'partial.patch'
            candidate.write_text(
                '--- a/Makefile\n'
                '+++ b/Makefile\n'
                '@@ -3,3 +3,3 @@\n'
                ' \tgcc main.o helper.o -o app\n'
                '-main.o: main.c unused.h\n'
                '+main.o: main.c unused.h config.h\n'
                ' \tgcc $(CFLAGS) -c main.c -o main.o\n'
            )

            evidence = root / 'validation'
            result = validate(project, candidate, evidence)
            self.assertEqual(result['checks'], {
                'patch_applies': True,
                'build': True,
                'test': True,
                'header_change': True,
                'no_missing': False,
            })
            self.assertFalse(result['accepted'])
            self.assertIsNone(result['error'])
            self.assertTrue(result['rollback'])
            self.assertTrue(result['source_unchanged'])
            self.assertEqual((project / 'Makefile').read_bytes(), before)

            recheck = json.loads((evidence / 'recheck.json').read_text())
            missing = {
                (finding['target'], finding['dependency'])
                for finding in recheck['findings']
                if finding['type'] == 'MISSING'
            }
            self.assertEqual(missing, {('helper.o', 'extra.h')})


if __name__=='__main__':unittest.main()
