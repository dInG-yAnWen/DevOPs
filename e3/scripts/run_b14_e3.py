#!/usr/bin/env python3
"""B14 E3 基线执行脚本（真实执行，不伪造）。

用途
----
按课程《E3 并行测试基线》B 组清单，在本机真实执行两组样本并保留证据：

* DRAFT      : fixtures/draft   —— 构建、功能验证、失败候选、参考修复信息
* MDFixer    : fixtures/mdfixer —— 缺失依赖行为复现、参考补丁、无效候选与恢复

设计原则
--------
1. 只记录真实执行到的命令、退出码与输出；未执行的（例如需要 Docker 且当前
   环境没有 Docker/网络）显式记为未执行，并给出复现命令，绝不伪造镜像 ID。
2. 证据按运行时间写入 e3/evidence/<run-id>/，旧证据不覆盖。
3. 源码快照用真实 Git 提交（固定作者与时间）得到可复现的 40 位 SHA。

用法
----
    python3 e3/scripts/run_b14_e3.py
    python3 e3/scripts/run_b14_e3.py --run-id 20260925-120000
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

E3_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = E3_ROOT / "fixtures"
EVIDENCE_ROOT = E3_ROOT / "evidence"
WORK_ROOT = E3_ROOT / "work"

# 固定作者与时间，使 Git 提交 SHA 可复现（同样的树 -> 同样的 SHA）。
GIT_NAME = "B14 E3 Fixture"
GIT_EMAIL = "b14-e3@example.invalid"
GIT_DATE = "2026-09-25T00:00:00+08:00"

TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def run(cmd, cwd=None, env=None) -> dict:
    """执行命令并完整记录命令、退出码、stdout、stderr。"""
    started = now_iso()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return {
        "cmd": cmd if isinstance(cmd, list) else [cmd],
        "cwd": str(cwd) if cwd else None,
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "started": started,
        "finished": now_iso(),
    }


def git_env() -> dict:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": GIT_NAME,
            "GIT_AUTHOR_EMAIL": GIT_EMAIL,
            "GIT_AUTHOR_DATE": GIT_DATE,
            "GIT_COMMITTER_NAME": GIT_NAME,
            "GIT_COMMITTER_EMAIL": GIT_EMAIL,
            "GIT_COMMITTER_DATE": GIT_DATE,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
        }
    )
    return env


def init_and_commit(repo: Path, message: str, paths) -> str:
    run(["git", "init", "-q", "-b", "main"], cwd=repo, env=git_env())
    run(["git", "add", "--", *paths], cwd=repo, env=git_env())
    run(["git", "commit", "-q", "-m", message], cwd=repo, env=git_env())
    out = run(["git", "rev-parse", "HEAD"], cwd=repo, env=git_env())
    return out["stdout"].strip()


def write_log(path: Path, result: dict) -> None:
    lines = [
        f"# command : {' '.join(result['cmd'])}",
        f"# cwd     : {result['cwd']}",
        f"# started : {result['started']}",
        f"# finished: {result['finished']}",
        f"# exit_code: {result['exit_code']}",
        "# ---- stdout ----",
        result["stdout"].rstrip("\n"),
        "# ---- stderr ----",
        result["stderr"].rstrip("\n"),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def tool_versions() -> dict:
    checks = {
        "make": ["make", "--version"],
        "cc": ["cc", "--version"],
        "git": ["git", "--version"],
        "python3": ["python3", "--version"],
        "uname": ["uname", "-srmo"],
    }
    versions = {}
    for name, cmd in checks.items():
        if shutil.which(cmd[0]) is None:
            versions[name] = "NOT FOUND"
            continue
        r = run(cmd)
        text = (r["stdout"] or r["stderr"]).strip().splitlines()
        versions[name] = text[0] if text else ""
    sh = run(["/bin/sh", "-c", "readlink -f /bin/sh"])
    versions["sh"] = sh["stdout"].strip()
    return versions


def docker_status() -> dict:
    """如实检查 Docker 是否可用；不可用时不产生任何镜像 ID。"""
    binary = shutil.which("docker")
    info = {
        "docker_binary": binary,
        "docker_available": False,
        "docker_build_executed": False,
        "image_id": None,
        "container_run_executed": False,
        "reason": "",
        "reproduction_commands": [
            "docker build -f e3/fixtures/draft/Dockerfile.broken    -t b14-e3-draft-broken:20260925    e3/fixtures/draft",
            "docker build -f e3/fixtures/draft/Dockerfile.reference -t b14-e3-draft-reference:20260925 e3/fixtures/draft",
            "docker images --no-trunc --format '{{.ID}}' b14-e3-draft-reference:20260925",
            "docker run --rm b14-e3-draft-reference:20260925",
        ],
    }
    if binary is None:
        info["reason"] = (
            "本机未安装 docker，且无外网/无 registry 访问，无法拉取 python:3.13-slim "
            "执行镜像构建。因此本次未产生真实 image ID，也未伪造；Docker 证据留待有 "
            "Docker 的环境按 reproduction_commands 补齐。"
        )
        return info
    r = run([binary, "version"])
    if r["exit_code"] != 0:
        info["reason"] = "docker 存在但守护进程不可用：" + (r["stderr"].strip() or r["stdout"].strip())
        return info
    info["docker_available"] = True
    info["reason"] = "docker 可用但本次未执行镜像构建（脚本默认不联网拉取镜像）。"
    return info


# --------------------------------------------------------------------------
# DRAFT
# --------------------------------------------------------------------------
def run_draft(ev: Path, work: Path) -> dict:
    src = FIXTURES / "draft"
    repo = work / "draft"
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    # 只把真正参与构建的源码放进快照，文档/Dockerfile 不进入基线提交。
    for name in ["main.c", "Makefile"]:
        shutil.copy(src / name, repo / name)

    obs: dict = {"fixture": "draft", "files": {}}
    for name in ["main.c", "Makefile", "Dockerfile.broken", "Dockerfile.reference"]:
        obs["files"][name] = sha256_file(src / name)

    baseline_sha = init_and_commit(
        repo, "DRAFT baseline: TinyGreeting sample", ["main.c", "Makefile"]
    )
    obs["baseline_commit"] = baseline_sha

    build = run(["make"], cwd=repo)
    write_log(ev / "draft_build.log", build)
    obs["build"] = {"exit_code": build["exit_code"], "log": "draft_build.log"}

    hello_exists = (repo / "hello").is_file() and os.access(repo / "hello", os.X_OK)
    obs["executable_created"] = bool(hello_exists)

    verify = run(["./hello"], cwd=repo)
    write_log(ev / "draft_verify.log", verify)
    obs["verify"] = {
        "exit_code": verify["exit_code"],
        "stdout": verify["stdout"].replace("\n", "\\n"),
        "log": "draft_verify.log",
        "expected_stdout": "hello E3\\n",
        "expected_exit_code": 0,
    }
    obs["draft_success"] = (
        build["exit_code"] == 0
        and hello_exists
        and verify["exit_code"] == 0
        and verify["stdout"] == "hello E3\n"
    )

    # 失败候选：还原 Dockerfile.broken 的 RUN make —— python:3.13-slim 里没有 make。
    # 本机没有 Docker，用受限 PATH 真实触发同一失败语义（make: not found）。
    empty_path = work / "empty-path"
    empty_path.mkdir(exist_ok=True)
    broken_env = dict(os.environ)
    broken_env["PATH"] = str(empty_path)
    # 用 `sh -c`（与 Dockerfile 的 RUN 一致，非 login shell，避免 /etc/profile 重置 PATH）
    broken = run(["/bin/sh", "-c", "make"], cwd=repo, env=broken_env)
    write_log(ev / "draft_broken_build.log", broken)
    obs["broken_candidate"] = {
        "simulated_base_image": "python:3.13-slim (no make / no C toolchain)",
        "reproduced_by": "在受限 PATH(空目录) 下真实执行 `sh -c make`（与该镜像的 RUN make 相同的调用形式）",
        "exit_code": broken["exit_code"],
        "stderr": broken["stderr"].strip(),
        "log": "draft_broken_build.log",
        "locatable": "make" in broken["stderr"] and "not found" in broken["stderr"],
    }
    return obs


# --------------------------------------------------------------------------
# MDFixer
# --------------------------------------------------------------------------
def run_mdfixer(ev: Path, work: Path) -> dict:
    src = FIXTURES / "mdfixer"
    repo = work / "mdfixer"
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    for name in ["main.c", "config.h", "Makefile.before", "Makefile.after",
                 "reference.patch", "md_report.json"]:
        shutil.copy(src / name, repo / name)
    # 用修复前 Makefile 作为基线（真实 Git，可复现 SHA）。
    shutil.copy(repo / "Makefile.before", repo / "Makefile")

    obs: dict = {"fixture": "mdfixer", "files": {}, "steps": []}
    for name in ["main.c", "config.h", "Makefile.before", "Makefile.after",
                 "reference.patch", "md_report.json"]:
        obs["files"][name] = sha256_file(src / name)

    # 基线快照只包含参与编译与声明判断的源码。
    baseline_sha = init_and_commit(
        repo,
        "MDFixer baseline: Makefile missing config.h",
        ["main.c", "config.h", "Makefile"],
    )
    baseline_hashes = {
        name: sha256_file(repo / name) for name in ["main.c", "config.h", "Makefile"]
    }
    obs["baseline_commit"] = baseline_sha
    obs["baseline_content_sha256"] = baseline_hashes
    obs["md_report_location"] = {"path": "Makefile", "line": 7,
                                 "line_text": "main.o: main.c"}

    def set_value(value: int) -> None:
        text = (repo / "config.h").read_text(encoding="utf-8")
        new = "\n".join(
            "#define VALUE %d" % value if line.startswith("#define VALUE") else line
            for line in text.splitlines()
        )
        (repo / "config.h").write_text(new + "\n", encoding="utf-8")

    def step(idx: int, name: str, cmd, value_note: str) -> dict:
        r = run(cmd, cwd=repo)
        log_name = f"mdfixer_{idx:02d}_{name}.log"
        write_log(ev / log_name, r)
        return {
            "step": idx,
            "name": name,
            "note": value_note,
            "cmd": " ".join(cmd),
            "exit_code": r["exit_code"],
            "stdout": r["stdout"],
            "log": log_name,
        }

    # 步骤 1：初始完整构建，程序输出 1
    set_value(1)
    run(["make", "clean"], cwd=repo)
    s1 = step(1, "make_initial", ["make"], "config.h VALUE=1，干净构建")
    s2 = step(2, "app_initial", ["./app"], "期望输出 1")
    obs["steps"] += [s1, s2]

    # 步骤 3：只改头文件为 2，普通 make
    set_value(2)
    s3 = step(3, "make_after_header_only", ["make"],
              "只改 config.h=2，未声明依赖 -> 期望 make 不重编译")
    s4 = step(4, "app_after_header_only", ["./app"],
              "期望仍输出旧值 1（MD 的证据）")
    obs["steps"] += [s3, s4]

    # 步骤 5：clean build 对照
    run(["make", "clean"], cwd=repo)
    s5 = step(5, "make_clean_rebuild", ["make"], "clean 后完整重建")
    s6 = step(6, "app_clean_rebuild", ["./app"], "期望输出 2")
    obs["steps"] += [s5, s6]

    # 步骤 7：应用参考补丁
    check = run(["git", "apply", "--check", "reference.patch"], cwd=repo, env=git_env())
    write_log(ev / "mdfixer_07_patch_check.log", check)
    apply = run(["git", "apply", "reference.patch"], cwd=repo, env=git_env())
    write_log(ev / "mdfixer_08_patch_apply.log", apply)
    diff = run(["git", "diff", "--", "Makefile"], cwd=repo, env=git_env())
    (ev / "mdfixer_applied.diff").write_text(diff["stdout"], encoding="utf-8")
    obs["patch"] = {
        "check_exit_code": check["exit_code"],
        "apply_exit_code": apply["exit_code"],
        "applied_makefile_sha256": sha256_file(repo / "Makefile"),
        "expected_makefile_sha256": sha256_file(src / "Makefile.after"),
        "matches_reference": sha256_file(repo / "Makefile") == sha256_file(src / "Makefile.after"),
    }

    # 步骤 9：修复后再次改头文件为 3，不 clean
    set_value(3)
    s9 = step(9, "make_after_fix_header_only", ["make"],
              "已声明 config.h -> 期望自动重编译")
    s10 = step(10, "app_after_fix_header_only", ["./app"], "期望输出 3")
    obs["steps"] += [s9, s10]

    # 步骤 11：无效候选（故意放进失败命令）与恢复
    bad = (repo / "Makefile").read_text(encoding="utf-8").replace(
        "\t$(CC) main.o -o app", "\t$(CC) does_not_exist.o -o app"
    )
    (repo / "Makefile").write_text(bad, encoding="utf-8")
    run(["make", "clean"], cwd=repo)
    s11 = step(11, "make_invalid_candidate", ["make"],
               "候选故意引用不存在的 does_not_exist.o -> 期望非零退出")
    obs["steps"].append(s11)

    shutil.copy(repo / "Makefile.after", repo / "Makefile")
    run(["make", "clean"], cwd=repo)
    s12 = step(12, "make_recovered", ["make"], "恢复参考 Makefile -> 期望重新构建成功")
    s13 = step(13, "app_recovered", ["./app"], "期望输出 3")
    obs["steps"] += [s12, s13]

    # 真实绑定报告：把真实基线 SHA 与内容哈希写入绑定的 MD 报告。
    # 说明：这里保持课程第 23 页的 oracle 报告形态并附绑定信息，不冒充 E2 REPAIR
    # 的 md.json —— E2 的 Report 要求已发布 repository.url 与同仓库 commit。
    report = json.loads((src / "md_report.json").read_text(encoding="utf-8"))
    report.pop("note", None)
    report["binding"] = {
        "baseline_commit": baseline_sha,
        "snapshot_dir": str(repo),
        "configuration_id": "cfg-b14-e3-host-ubuntu2204-gcc11-make43",
        "content_sha256": baseline_hashes,
        "note": (
            "E3 人工固定报告（INSTRUCTOR_ORACLE）。绑定本次真实 Git 基线提交与内容哈希；"
            "转成 E2 REPAIR 的 md.json 需要已发布的 repository.url 与同仓库 commit，留待 E12。"
        ),
    }
    for f in report["findings"]:
        f["commit"] = baseline_sha
    (ev / "md_report.bound.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    obs["md_report_bound"] = "md_report.bound.json"
    return obs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()
    run_id = args.run_id or datetime.now(TZ).strftime("%Y%m%d-%H%M%S")

    ev = EVIDENCE_ROOT / run_id
    work = WORK_ROOT / run_id
    ev.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print(f"[B14 E3] run-id = {run_id}")
    print(f"[B14 E3] evidence = {ev}")

    versions = tool_versions()
    print(f"[B14 E3] make: {versions.get('make')} | cc: {versions.get('cc')}")

    draft = run_draft(ev, work)
    print(f"[B14 E3] DRAFT success = {draft['draft_success']}, "
          f"broken exit = {draft['broken_candidate']['exit_code']}")

    mdfixer = run_mdfixer(ev, work)
    key = {s["name"]: s for s in mdfixer["steps"]}
    print(f"[B14 E3] MDFixer: header-only output = "
          f"{key['app_after_header_only']['stdout'].strip()!r}, "
          f"clean-build output = {key['app_clean_rebuild']['stdout'].strip()!r}, "
          f"after-fix output = {key['app_after_fix_header_only']['stdout'].strip()!r}")

    summary = {
        "run_id": run_id,
        "generated_at": now_iso(),
        "duration_seconds": round(time.time() - t0, 3),
        "environment": versions,
        "docker": docker_status(),
        "draft": draft,
        "mdfixer": mdfixer,
    }
    out = ev / "observations.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    (ev / "commands.json").write_text(
        json.dumps(
            {
                "draft": [s for s in [draft["build"], draft["verify"],
                                      draft["broken_candidate"]]],
                "mdfixer": [
                    {"name": s["name"], "cmd": s["cmd"], "exit_code": s["exit_code"]}
                    for s in mdfixer["steps"]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"[B14 E3] wrote {out}")
    print(f"[B14 E3] docker: available={summary['docker']['docker_available']}, "
          f"image_id={summary['docker']['image_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
