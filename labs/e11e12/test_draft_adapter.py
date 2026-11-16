import unittest

from draft.autobuild import prepare_candidate


BROKEN = """FROM python:3.13-slim
WORKDIR /work
COPY main.c helper.c config.h extra.h unused.h Makefile ./
RUN make app
CMD ["./app"]
"""

CANDIDATE = """FROM m.daocloud.io/docker.io/library/python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
WORKDIR /work
COPY main.c helper.c config.h extra.h unused.h Makefile ./
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
RUN make app
CMD ["./app"]
"""


class DraftMirrorAdapterTests(unittest.TestCase):
    def test_accepts_mirror_for_same_digest_pinned_base(self):
        baseline = prepare_candidate(BROKEN, CANDIDATE)
        self.assertTrue(
            baseline.startswith(
                "FROM m.daocloud.io/docker.io/library/python:3.13-slim@sha256:"
            )
        )

    def test_rejects_a_different_base_tag_on_mirror(self):
        changed = CANDIDATE.replace(
            "python:3.13-slim@sha256:",
            "python:3.14-slim@sha256:",
            1,
        )
        with self.assertRaisesRegex(
            ValueError, "Candidate changed the original base image tag"
        ):
            prepare_candidate(BROKEN, changed)


if __name__ == "__main__":
    unittest.main()
