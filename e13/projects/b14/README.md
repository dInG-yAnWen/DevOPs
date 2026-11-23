# B14 E13 exchange project: sample alert counter

This course project evolves B14's explicit two-source C/Make fixture from
`labs/e8e10/lab.py` and `labs/e11e12/prepare.py` in the B14 repository at
`2a2cd050c4643bd0e2bfc3c9d7e6cd21c86492fe`. The alert-count behavior,
shared function header, strict output test, and later policy-header change
are new local work prepared by Codex Assistant. No group member's independent
execution or acceptance is asserted. This is a course fixture, not an
unmodified external project or a paper benchmark.

`helper.c` counts samples greater than or equal to an alert threshold in the
fixed data `{18, 31, 42, 55}`. `main.c` prints the alert count multiplied by
the reporting unit `VALUE` from `config.h` (default 1). The threshold is 50,
so exactly one sample is an alert. Normal execution exits 0 and prints the
exact bytes `1\n`.

On Linux, from `e13/projects/b14`:

```sh
make clean
make
make test
./app
```

The strict `make test` fails for a nonzero program exit or any output-byte
difference. To test an intentional configuration probe, pass the documented
expected value, for example `make test EXPECTED_OUTPUT=2`.

C0 keeps the threshold in `helper.c`; both object rules list every local
header they read. This is the no-MD full-check baseline. C1 moves the
threshold to `alert_policy.h` without adding its Make prerequisite, creating
the controlled MD `helper.o -> alert_policy.h`. Normal C0 and C1 output is 1.
There are no intentionally redundant prerequisites. Use the complete C0 and
C1 SHAs in the separately delivered handoff manifest; do not use moving
branch names as experiment identifiers.

Run this behavior probe in a disposable C1 checkout, after its normal clean
build. Preserve logs and restore the original header before a fresh run:

```sh
sleep 1
sed -i 's/B14_ALERT_THRESHOLD 50/B14_ALERT_THRESHOLD 40/' alert_policy.h
make
./app                         # expected: stale 1, because helper.o is reused
make clean
make
./app                         # expected: 2
make test EXPECTED_OUTPUT=2
```

The repair adds only `alert_policy.h` to the `helper.o` prerequisite list.
Apply the candidate patch from the repository root; paths in the patch are
`e13/projects/b14/Makefile`. After repair, repeat from the original threshold
50 and a clean build: changing only the header to 40 and running plain
`make` should rebuild `helper.o` and print 2. This is the intended behavior
to verify, not a claim that an A14 detector or Linux run has already passed.

The existing B14 reporting-unit probe also remains meaningful: changing
`config.h` from `VALUE 1` to `VALUE 2` at threshold 50 should rebuild `main.o`
and print 2. Inputs stay limited to this explicit two-object Make profile.

The Dockerfiles use this directory as the build context. `Dockerfile.broken`
omits the C toolchain intentionally; `candidate.Dockerfile` adds it while
retaining the pinned Python base, COPY, build command and runtime command.
Neither a Docker build nor a cross-group run has been claimed here.
