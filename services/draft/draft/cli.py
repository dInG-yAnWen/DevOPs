"""DRAFT CLI: E4 smoke and E6 two-attempt build/verification workflow."""
import argparse
import json

from . import __version__
from .smoke import run_smoke
from .autobuild import auto_build, verify_evidence


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return number


def build_parser():
    ap = argparse.ArgumentParser(prog="draft")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version", help="打印版本")
    sp = sub.add_parser("smoke", help="E4 冒烟测试：在容器里通过宿主机 Docker 构建 E3 的 Dockerfile.broken")
    sp.add_argument("--fixture", default="fixtures/draft")
    sp.add_argument("--tag", default="e4-smoke-broken:latest")
    sp = sub.add_parser("auto-build", help="E6: build baseline and saved candidate, then verify the same image")
    sp.add_argument("--fixture", default="fixtures/draft")
    sp.add_argument("--candidate", required=True)
    sp.add_argument("--provenance", help="Existing JSON source record, copied without inventing model activity")
    sp.add_argument("--out", required=True, help="New output directory; existing evidence is never overwritten")
    sp.add_argument("--expected-output", default="hello E3", help="One expected line, without its final newline")
    sp.add_argument("--timeout", type=positive_int, default=600, help="Budget per build in seconds")
    sp.add_argument("--verify-timeout", type=positive_int, default=30)
    sp = sub.add_parser("verify-evidence", help="Read-only verification of saved E6 artifacts")
    sp.add_argument("--run-dir", required=True)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "version":
        print(f"draft {__version__}")
        return 0
    if args.cmd == "smoke":
        result = run_smoke(args.fixture, args.tag)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 1
    try:
        if args.cmd == "auto-build":
            result = auto_build(args.fixture, args.candidate, args.out, args.expected_output,
                                args.timeout, args.verify_timeout, args.provenance)
            passed = result["status"] == "SUCCEEDED"
        else:
            result = verify_evidence(args.run_dir)
            passed = result["verified"] and result["status"] == "SUCCEEDED"
    except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        result = {"status": "FAILED", "error": str(exc)}
        passed = False
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 1
