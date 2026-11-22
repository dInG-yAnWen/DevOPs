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
header they read. This is the no-MD full-check baseline. C1 will move the
threshold to a new policy header without adding its Make prerequisite,
creating one controlled missing dependency. Use the complete C0 and C1 SHAs
in the separately delivered handoff manifest; do not use moving branch names
as experiment identifiers.

The Dockerfiles use this directory as the build context. `Dockerfile.broken`
omits the C toolchain intentionally; `candidate.Dockerfile` adds it while
retaining the pinned Python base, COPY, build command and runtime command.
Neither a Docker build nor a cross-group run has been claimed here.
