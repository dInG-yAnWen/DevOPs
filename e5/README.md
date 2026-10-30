# B14 E5 DRAFT 复现操作

执行与整理：丁彦文。课程验收依据见 [requirements.md](requirements.md)，AI 使用记录集中见 [docs/AI_USAGE.md](../docs/AI_USAGE.md)。本说明给出可复现步骤，实际结果以本轮报告及原始证据为准。

以下为本组 Linux 云主机上的 Bash 命令，均在仓库根目录执行。需要 Python 3、Git、Docker 客户端和可用的 Docker daemon。`e5/scripts/run_e5.py` 使用 Python 标准库，不调用模型 API。

## 1. 新目录采集真实失败

```bash
docker version
python3 e5/scripts/run_e5.py --help
run="work/e5-$(date +%Y%m%d-%H%M%S)"
python3 e5/scripts/run_e5.py baseline --out "$run" --build-timeout 600
echo "BASELINE_DRIVER_EXIT=$?"
cat "$run/baseline/result.json"
```

`--out` 必须是尚不存在的目录；重跑换新目录，不清空旧结果。程序自动从 `fixtures/draft/` 按原始字节复制 `main.c`、`Makefile`、`README.md`、`.dockerignore`、`Dockerfile.broken` 到本轮 `project/`，记录输入哈希、Git 状态和工具信息。后续不能修改该快照。

预期是 `EXPECTED_MISSING_MAKE`、`expected_failure=true`，原始日志到达 `RUN make` 并出现 `make: not found`、命令退出127，Docker 构建退出1；采集脚本将这次预期失败视为取证完成，退出0。Docker 不可用、镜像拉取失败或网络超时不是目标失败，需保留结果、解决环境后新建目录重跑。

完整命令和 stdout/stderr 分别在 `baseline/build/command.json`、`stdout.log`、`stderr.log`。只有检测到真实目标失败才生成 `baseline/error-localization.json` 和以下两个提示。

## 2. 取得并保存两类候选

```bash
cat "$run/baseline/prompt-error-driven.txt"
cat "$run/baseline/prompt-context-driven.txt"
mkdir -p "$run/model-inputs/error-driven" "$run/model-inputs/context-driven"
```

分别将两个文件的全文提交给对话模型，保存两次完整原始回复，路径如下。不能只留下最终 Dockerfile，或把人工修订后的文字写回原始回复。

```text
<run>/model-inputs/error-driven/model-response.txt
<run>/model-inputs/error-driven/provenance.json
<run>/model-inputs/context-driven/model-response.txt
<run>/model-inputs/context-driven/provenance.json
```

回复须包含一个明确的 Dockerfile 代码块；不要手工修改该代码块的换行或内容。若额外加入模型指令，也保存实际发送的完整 `model-input.txt`。两份 `provenance.json` 先按实际情况填写以下字段，不能把示例文字当作真实来源：

```json
{
  "provider": "实际模型提供方",
  "platform": "实际使用平台",
  "model": "实际模型版本；未知写未记录",
  "generation_date": "实际生成日期 YYYY-MM-DD",
  "generation_mode": "FRESH_MODEL_RESPONSE",
  "human_edits": []
}
```

执行下列代码，从两份原文提取 Dockerfile 原始字节，并补录策略、提示/回复/候选哈希和保存时间。它不生成候选。

```bash
python3 - "$run" <<'PY'
import hashlib, json, re, sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
digest = lambda data: hashlib.sha256(data).hexdigest()
for strategy in ("error-driven", "context-driven"):
    folder = root / "model-inputs" / strategy
    response = (folder / "model-response.txt").read_bytes()
    blocks = re.findall(
        rb"^```[ \t]*(?:dockerfile)?[ \t]*\r?\n(.*?)^```[ \t]*(?:\r?\n|$)",
        response, flags=re.I | re.M | re.S)
    if len(blocks) != 1:
        raise SystemExit(f"{strategy}: expected one Dockerfile code block")
    prompt = (root / "baseline" / f"prompt-{strategy}.txt").read_bytes()
    provenance = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
    for field in ("provider", "platform", "model", "generation_date", "generation_mode"):
        if not provenance.get(field):
            raise SystemExit(f"{strategy}: missing {field}")
    (folder / "prompt.txt").write_bytes(prompt)
    (folder / "Dockerfile").write_bytes(blocks[0])
    provenance.update(strategy=strategy, prompt_sha256=digest(prompt),
        response_sha256=digest(response), candidate_sha256=digest(blocks[0]),
        recorded_utc=datetime.now(timezone.utc).isoformat())
    if (folder / "model-input.txt").is_file():
        provenance["model_input_sha256"] = digest((folder / "model-input.txt").read_bytes())
    (folder / "provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
```

CLI 对模型证据核验 `strategy`、当前提示的 `prompt_sha256`、非空原文和围栏内候选字节一致；`generation_mode` 以 fresh 开头计为新回复，以 replay 开头计为回放，不区分大小写。平台、模型、日期及人工改动须如实说明。实际 `model-input.txt` 与其哈希另行保存供提交核对，CLI 不单独核验该输入文件。`human_edits=[]` 仅适用于未修改候选；修改版本另存并记录差异，不能冒充原文提取。

## 3. 人工选择输入，构建并运行验证

本驱动保留固定 FROM、原有 WORKDIR、COPY、`RUN make`、CMD 的顺序和内容。FROM 后、WORKDIR 前的新增 `RUN` 严格限定为：

- `apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*`，或将安装包按顺序换成 `gcc make libc6-dev`。
- 独立的软件源适配命令：`sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources`。
- apt 命令可增加 `-o Acquire::ForceIPv4=true`、`-o Acquire::Retries=2`、`-o Acquire::http::Timeout=30`。不接受其他命令或安装包。

先核对两个候选，再分别执行：

```bash
python3 e5/scripts/run_e5.py candidate --run-dir "$run" \
  --name error-driven \
  --dockerfile "$run/model-inputs/error-driven/Dockerfile" \
  --response "$run/model-inputs/error-driven/model-response.txt" \
  --provenance "$run/model-inputs/error-driven/provenance.json" \
  --build-timeout 600 --run-timeout 30
echo "ERROR_CANDIDATE_EXIT=$?"

python3 e5/scripts/run_e5.py candidate --run-dir "$run" \
  --name context-driven \
  --dockerfile "$run/model-inputs/context-driven/Dockerfile" \
  --response "$run/model-inputs/context-driven/model-response.txt" \
  --provenance "$run/model-inputs/context-driven/provenance.json" \
  --build-timeout 600 --run-timeout 30
echo "CONTEXT_CANDIDATE_EXIT=$?"
```

这是逐候选发起的构建与验证，不是自动生成/修复循环。每个名字只用一次；继续试验应换新候选名。程序先检查 Dockerfile，再以本轮 `project/` 为上下文构建；成功后读取 `--iidfile`、检查镜像 ID，按同一 ID 禁网运行，限制1核、256 MiB内存、64进程，并确认本次容器已清理。

查看 `candidates/<name>/result.json`。成功要求 `passed=true`、`build_exit_code=0`、`verify_exit_code=0`、`output_matches=true`，原始 stdout 必须精确为 `hello E3\n`。构建、运行与清理的命令和原始流分别保存在同目录下的 `build/`、`verify/`、`cleanup/`、`cleanup-inspect/`。候选失败或超时不能写成成功。

若原候选遇到软件源网络问题，保留原始候选及失败记录；可另存适配 Dockerfile，仅增加上述固定 sed 命令或 apt 选项。适配目录例如 `model-inputs/context-mirror/`，另写 `provenance.json`：

```json
{
  "generation_mode": "MANUAL_ENVIRONMENT_ADAPTATION",
  "parent_candidate_name": "context-driven",
  "parent_sha256": "填写本轮 candidates/context-driven/Dockerfile 的 SHA256",
  "reason": "填写本轮网络故障证据及适配理由"
}
```

`parent_sha256` 可用 `sha256sum "$run/candidates/context-driven/Dockerfile"` 取得。将实际父候选名字、哈希和理由填完整后执行，不附虚构模型回复：

```bash
python3 e5/scripts/run_e5.py candidate --run-dir "$run" \
  --name context-mirror \
  --dockerfile "$run/model-inputs/context-mirror/Dockerfile" \
  --provenance "$run/model-inputs/context-mirror/provenance.json" \
  --build-timeout 600 --run-timeout 30
```

适配来源模式必须精确为 `MANUAL_ENVIRONMENT_ADAPTATION`；父项须有有效的新模型原文证据。封存会核对父哈希，并要求移除固定 sed 和允许的 apt 选项后指令完全一致，包括安装包。适配版本不计新的模型回复；两类新回复证据仍由原始候选提供。

## 4. 选择、封存与校验

比较两类候选和实际结果，按课程 R1—R4 记录本次适用的选择理由。把下例的候选名和理由替换为实际结论；选择必须有成功构建及精确输出证据。

```bash
python3 e5/scripts/run_e5.py finalize --run-dir "$run" \
  --selected error-driven --reason '填写本次实际候选比较、适用规则和选择依据'
echo "FINALIZE_EXIT=$?"
python3 e5/scripts/run_e5.py verify --run-dir "$run"
echo "VERIFY_EXIT=$?"
```

`finalize` 写入 `result.json` 和 `SHA256SUMS.json` 并立即校验。两类新模型证据齐全、所选项有真实成功证据且来源有效时，`e5_records_complete=true`、`pending=[]`、退出0。选择环境适配版本时，替换示例的 `--selected`，结果应显示 `selected_source_kind=ENVIRONMENT_ADAPTATION` 及父来源，不称原模型候选直接成功。不齐全时仍可能留下封存文件并退出2，应如实查看 `pending`。封存后不再往该目录增加、删除或修改文件；继续实验另起新轮次。

`verify` 只读核对文件集合/哈希、各命令原始 stdout/stderr 的 SHA256、固定输入、实际目标失败、构建/运行/清理的命令及结果、同镜像 ID、模型证据及适配来源，不重新构建，不要求原镜像仍保存在本机。其他未通过或操作错误均退出2，不能只看终端是否正常结束。

## 5. 已保存候选与归档复核

仓库 `e5/model-records/{error-driven,context-driven}/` 保存本次已取得的两类提示、输入、原始回复、Dockerfile 和来源。它们的 `prompt_sha256` 绑定原轮次的真实日志。新轮次日志可能变化，不能直接复制旧 provenance 并声称它对应新提示。

推荐新实验按第2节重新取得回复。若仅复核提交的既有结果，可直接对解压后的完整归档目录运行：

```bash
archive_run='e5/evidence/20261030-241880284-e5'
python3 e5/scripts/run_e5.py verify --run-dir "$archive_run"
```

若重用已保存 Dockerfile进行另一次真实构建，`generation_mode` 应以 replay 开头，保留原生成提示/哈希/日期及当前输入信息；不能将旧回复改称对新提示的生成结果，也不能仅改 `prompt_sha256` 通过校验。结果中回放来源为 `COURSE_REPLAY`，不补足 `fresh_strategies`，也不能作为完整 E5 记录的最终来源。未取得匹配本轮提示的两类新原始回复时，不声明新轮次模型证据完整。

## 6. 固定镜像、缓存与网络

当前 `fixtures/draft/Dockerfile.broken` 与驱动共同固定：

```text
m.daocloud.io/docker.io/library/python@sha256:f82c96458eedc847b233e582eb31336f4954b39cae020b6dcf5b3ed0e5cbcd74
```

该来源与课程 PPT 的示例 FROM 不同，应在实验报告记录环境差异。实验中不替换 digest；更换基础环境应另起实验并同步解释输入差异。

两轮 `docker build` 都启用 `--no-cache --progress=plain`，强制重新执行 Dockerfile 构建层；没有使用 `--pull`，基础镜像本身可来自本机缓存。首次拉取、远端元数据检查，以及候选的 `apt-get` 安装仍可能需要网络和相应软件源。无缓存不代表无网络，验证阶段的 `--network none` 也不作用于构建阶段。网络或软件源失败应保留为环境失败证据，不能当作缺 make 或候选修复成功。
