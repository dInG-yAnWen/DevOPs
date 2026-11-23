# B14 E14 四服务运行与证据

状态：候选待发布。此目录从 `学生发放包_20261116.zip` 原版导入，原始文件字节哈希见 `import-source.json`。改动限于本仓库的构建上下文、真实项目子目录及行为探针、HTTP 任务身份核对和故障证据保存。服务共用教学镜像，只有 DRAFT 挂载 Docker socket。

## 1. 输入与候选准备

在新的独立仓库中执行。已有 `data/integration-sample` 或 `data/e14-inputs` 时会拒绝覆盖；保留旧实验并换新工作副本。

```bash
git config --local user.name 241880284
git config --local user.email 241880284@localhost
python3 -m py_compile labs/e13e14/*.py
python3 -m unittest discover -s labs/e13e14/tests -p 'test_*.py' -v

# 构建上下文必须是 labs/e8e10/environment。
docker build --progress=plain \
  -f labs/e11e12/environment/services/buildchecker/Dockerfile \
  -t course-e11e12:241880284 labs/e8e10/environment
python3 run_e11e12.py prepare

# 路径替换为本次上传的原件；不连接远程仓库。
python3 labs/e13e14/prepare_requests.py \
  --a14-bundle /input/a14-source.bundle \
  --a14-package /input/a14-evidence.zip \
  --b14-bundle /input/b14-native.bundle \
  --b14-spec /input/b14-spec.json
```

生成 `data/e14-requests/` 的五份请求：

| 请求 | 目的 | 断言 |
| --- | --- | --- |
| `fixed.json` | 原课程样例独立回归 | 初始输出 1，头文件探针输出 2 |
| `a14.json` | A14 实际项目，`e13/projects/a14` | 初始输出 15，`adjustment.h` 的 3→6 后输出 18 |
| `b14.json` | B14 实际项目，`e13/projects/b14` | 初始输出 1，`alert_policy.h` 阈值 50→40 后输出 2 |
| `fault-timeout.json` | B14 请求的隔离 DRAFT 构建超时 | `build_timeout=0.01`，实际 DRAFT 必须为 TIMED_OUT；其他失败不能代替 |
| `recovery.json` | 恢复正常时限后的新任务 | 新 job/trace，五阶段成功 |

A14 项目提交固定为 `6723e99c0f155db19f655e8d3b47367dc7ed4d47` → `ce25b2025174fc716d585fafe2d98e29810350d9`；B14 为 `db7ad8c0df5f8801b4147f3d204610bd6400bd4b` → `785f54324c915e4c4987cafea46a5ab0714be167`。`data/e14-inputs/input-manifest.json` 保存本轮输入原件和请求哈希。A14 使用对方提供的候选原字节，B14 使用目标提交中的候选；不修改双方项目历史。

## 2. 四服务与完整复验

由实际执行人确认镜像、端口和该 Compose 项目属于本次隔离实验后启动。`run_suite.py` 本身不启动、停止或部署服务，不创建标签。

共享云机可分别设置 `E14_BUILDCHECKER_PORT`、`E14_ECHECKER_PORT`、`E14_DRAFT_PORT`、`E14_MDFIXER_PORT` 为本次确认空闲的本机端口；Compose 与编排读取同一组环境变量，默认仍为 18081–18084。

```bash
export E14_ROOT="$PWD" E14_IMAGE=course-e11e12:241880284
export E14_UID="$(id -u)" E14_GID="$(id -g)"
export E14_DOCKER_GID="$(stat -c %g /var/run/docker.sock)"
docker compose -f labs/e13e14/compose.yaml -p e14-241880284 config --quiet
docker compose -f labs/e13e14/compose.yaml -p e14-241880284 up -d --wait
mkdir -p work
python3 labs/e13e14/run_suite.py --image "$E14_IMAGE" \
  --compose-project e14-241880284 --out work/e14-four-services-01 \
  > work/e14-four-services-console.log 2>&1
```

每轮输出独立目录，快照仅检出请求指定的项目子树，Git HEAD 仍为原完整提交 SHA。编排经本机四端口的 `/v1/run` 顺序调用，五阶段共用同一 job_id/trace_id；服务响应中的角色和两个 ID 必须与请求一致。MDFixer 校验本轮报告哈希和身份，行为探针在验证沙箱执行，原项目头文件保持不变。

`run_suite.py` 保留五轮请求、结果、原始阶段证据、各轮服务日志与健康输出、实际镜像信息、Compose 状态、最后容器及 DRAFT 进程列表。成功用例核对五阶段和全部产物字节哈希；超时须由 DRAFT 的原始结果证明，恢复须使用新任务完成五阶段。日志扫描或必要证据采集失败时，汇总仍为 FAILED。失败记录不会删除，后续用例仍分别运行。

执行人还须审阅故障前后 DRAFT 进程列表及 Docker 容器列表，确认没有该故障遗留的构建客户端、验证容器，并检查其他任务的目录与产物。原始 DRAFT 实现会终止超时客户端进程组，实际清理结论以本次观察为准。

仅关闭本次项目：

```bash
docker compose -f labs/e13e14/compose.yaml -p e14-241880284 down
```

## 3. 验收边界

本地静态和单元检查、请求准备只证明代码与输入可复现。实际四容器 E2E、故障恢复、镜像 ID、云端 CI、E13 双方签收和阻断缺陷清零由真实证据补入。即使五轮运行全部成功，`summary.json` 的发布状态仍保持“候选待发布”；最终标签与发布判定由有权限者在总门禁通过后完成。

CI 模板保持固定样例回归；配对项目依赖交换的 Git bundle 和课程原 ZIP，未把本地私有绝对路径或他人的预跑结果写入 CI 成功结论。模板使用本库既有 action 版本、正确的 Docker build context，失败时仍收集服务日志和 `work/`。
