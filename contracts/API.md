# B14 / A14 E2 接口契约 1.0

日期：2026-09-25。责任方：B14（DRAFT、REPAIR）；配对方：A14（FULL_CHECK、INCREMENTAL_CHECK）。状态：**A14 已接受 E2 1.0 契约，B14 已记录回复并完成本地交接校验；B14 契约基线已发布（`689539119e60afd4b224d3163d1ba292992baa95`），A14 指定交付 SHA 待补充**。依据见 [协作确认与交接记录](../docs/collaboration/交接确认.md) 和 [已发布版本记录](../docs/release.md)。本文件与 `task.schema.json`、`validator/validate.py` 共同组成约束。Schema 约束结构，校验器约束跨字段相等、产物内容与业务语义。

本仓库给出可离线验收的契约，未部署 HTTP 服务。所有 `example.invalid` 地址、重复数字 SHA、镜像 digest、构建和重检结果均为人工样例。可读取样例文件不等于可拉取真实镜像。

## 1. 服务与端点

| 操作 | 端点 | 所有者 | 成功受理 |
| --- | --- | --- | --- |
| 生成环境 | `POST /v1/dockerfile-jobs` | B14 / DRAFT | 202 |
| 全量检测 | `POST /v1/full-check-jobs` | A14 / BuildChecker | 202 |
| 增量检测 | `POST /v1/incremental-check-jobs` | A14 / EChecker | 202 |
| 修复 MD | `POST /v1/repair-jobs` | B14 / MDFixer | 202 |
| 查询 | `GET /v1/jobs/{job_id}` | 产生该任务的服务 | 200 |

POST 使用 `Content-Type: application/json`，返回 `Accepted` 对象与 `Location: /v1/jobs/{job_id}`。job_id 由服务端生成。GET 返回完整 Job；未知 job_id 返回 404。查询到 FAILED / TIMED_OUT / CANCELLED 的现有 Job 仍返回 HTTP 200。HTTP 状态与任务状态分别表达受理/查询结果和执行结果。

四类请求与结果入口分别为 `examples/valid/{draft,full,incremental,repair}_{request,result}.json`。受理样例以 `_accepted.json` 结尾；错误响应为 `input_error.json`。

## 2. 公共字段与默认值

| 对象 | 字段 | 类型、必填与约束 |
| --- | --- | --- |
| 创建请求 | `schema_version` | 必填字符串，固定 `1.0` |
| 创建请求 | `trace_id` | 必填非空字符串，同一流程贯穿四类 Job |
| 创建请求 | `job_type` | 必填，四种枚举之一，必须与 POST 端点一致 |
| 创建请求 | `idempotency_key` | 必填非空字符串，重试同一请求使用相同值 |
| 创建请求 | `execution` | 必填对象，`timeout_seconds` 为正整数；DRAFT 另有正整数 `max_iterations` |
| 创建请求 | `input` | 必填，对应任务的专有对象 |
| Job | `job_id/status/input/output/error` | 均必填；此外保留版本、trace_id、job_type、execution；不回显 idempotency_key |
| Accepted | `schema_version/job_id/trace_id/status/status_url` | 均必填，status 固定 QUEUED，status_url 必须对应 job_id |
| ApiError | `schema_version/trace_id/http_status/error` | 均必填，无 job_id，不创建 Job |

canonical JSON 必须显式写出 `timeout_seconds`，DRAFT 必须显式写出 `max_iterations`。B14 SDK/调用方缺省配置为 1800 秒和 3 次，发送前填入请求。Schema 的 `default` 只是说明，不会自动填充字段。`max_iterations` 包括首次构建尝试；仅适用于 DRAFT。其他任务只使用总超时限制。

所有字段均使用 snake_case。`$defs` 中对象默认拒绝额外字段；只有环境变量字典和 `error.details` 可以自定义键。没有隐含的大小写转换或短 SHA 补全。

### 幂等和重试

以“调用方身份 + 端点 + idempotency_key”为作用域保存幂等记录，本版约定保存 24 小时。去掉 idempotency_key 后，对请求 JSON 做键排序的规范化比较：同键同内容返回原 job_id；同键不同内容返回 HTTP 409 / INPUT_1006。终态不复用为新运行。业务失败重跑须更换幂等键并生成新 Job，trace_id 可沿用。幂等 TTL、身份接入和持久化是 E3 实现事项，E2 尚无运行时证明。

## 3. 四类任务边界

| 任务 | 输入 | 正常输出 | 目标未达成 | 系统异常 |
| --- | --- | --- | --- | --- |
| DRAFT | 固定 repo/commit、build/verify、环境要求、迭代与时间限制 | Dockerfile、镜像元数据、configuration、逐轮修改与选择理由、日志和最终验证 | 尝试耗尽仍无法构建或验证 | 执行器崩溃、环境设施故障、总超时 |
| FULL_CHECK | 固定 repo/commit、DRAFT 环境、clean build、执行目录 | actual/declared graph、含 MD/RD 的 ERROR_REPORT | 不把发现 MD/RD 定义为失败 | 分析器崩溃、执行环境异常 |
| INCREMENTAL_CHECK | 当前 repo/commit、base_commit、baseline graph/report、同配置环境 | 当前图与报告、added/removed finding_id | baseline 不匹配在受理前拒绝 | 分析器崩溃、执行环境异常 |
| REPAIR | 同版本 MD-only 报告、Makefile 列表、环境、build/verify | 接受的 Git patch、所有候选的声明风格、构建/测试/重检结果 | 所有候选被拒绝 | 修复器/执行器故障、总超时 |

### 通用输入值对象

`repository` 必含 `url` 和 `commit`。url 接受 HTTPS、ssh:// 或 git@host:path 形式；commit 为小写 40 位十六进制完整 SHA。校验器验证格式，不联网确认仓库存在。真实执行器必须检出并核验指定提交，不能回落到 main 或最新版本。

`build` 必含 `command`、`verify_command`、`working_directory`。命令是 Linux 容器中 `/bin/sh -lc` 执行的非空字符串；执行目录相对检出仓库根目录，`.` 表示根目录。目录及 Makefile/依赖路径不得绝对化、含 Windows 盘符、反斜杠或 `..` 跳出片段。构建命令完成后执行验证命令，两者退出码必须为 0 才算通过。本契约不支持自定义成功退出码；A14 如需要，应包装为退出码 0 或提出版本修改。

`environment` 必含 `image_ref`（锁定 `@sha256:` digest）、`configuration_id`、`dockerfile_uri`、`producer_job_id`。configuration_id 标识平台、工具链、构建选项和环境变量等影响依赖图的配置，**不等于 commit**。任一影响分析的配置改变时换新 ID 并重新生成 baseline。DRAFT 产生 ID，下游原样沿用；命名算法和真实配置注册由双方在 E3 落实。

### DRAFT

`input.requirements` 必含：`platform`、`language`、`toolchain`（非空字符串数组）、`base_image`、`system_dependencies`、`network`（REQUIRED/OPTIONAL/DISABLED）、`environment_variables`（字符串字典）、`ports`（1–65535 数组）、`test_data`（项目相对路径数组）。无附加值时使用空数组/对象，不省略。A14 回复中的“E2 网络 DISABLED”描述离线验收环境；请求中的 requirements.network 描述目标项目构建网络需求，两者范围不同，样例的 REQUIRED 保持不变。基础镜像在示例中允许 tag；最终输出 image_ref 必须锁 digest。真实凭据由执行环境注入，不写进契约样例。

`output` 必含 environment（失败可为 null）、iterations、build、verify、artifacts。每轮记录 index（从 1 连续）、change_summary、selection_reason、patch_uri（首次/无修改为 null）、build、verify。大段 Dockerfile 修改通过 ITERATION_PATCH 产物引用。最终 build/verify 与成功的最后一轮一致。

`CommandResult` 固定为 status、exit_code、log_uri：PASSED 对应 0 和有效日志；FAILED 对应非零退出码和日志；NOT_RUN 对应两个 null。成功必须有可读取 Dockerfile、镜像元数据和正确生产任务标识，且实际构建/验证均成功。样例里的 `available: false` 与 `source: MANUAL_FIXTURE` 明确说明镜像不存在，此样例仅展示成功响应形状。

### FULL_CHECK 与 INCREMENTAL_CHECK

输出以 URI 引用 `ACTUAL_GRAPH`、`DECLARED_GRAPH`、`ERROR_REPORT`，三份产物必须在 artifacts 中登记。graph 样例节点用字符串标识，边明确为 `{target, dependency}`，含义为 target 依赖 dependency；不把示例简图当成论文完整内部图格式。

INCREMENTAL_CHECK 的 baseline 必含 repository_url、commit、configuration_id、actual_graph_uri、error_report_uri。强制：baseline.commit == base_commit，baseline.repository_url == 当前仓库 URL，baseline.configuration_id == environment.configuration_id。图/报告内容及产物元数据必须与这些字段一致。当前 commit 与 base_commit 不同。

根据 A14 本次回复，**E2 1.0 不新增 `baseline.build_commands_uri`**。EChecker 所需历史构建命令快照由 A14 在服务内部按 `repository_url + base_commit + configuration_id` 保存；该保存机制是 E3 实现职责，不是本次已经运行的能力。是否在后续版本公开该字段列入双方 E3 评审，不能在严格 1.0 Schema 中单方面增加字段。

同一配置的 DRAFT 环境可用于后续增量提交，但执行器必须重新挂载/检出当前源码，不能误用镜像内旧源码。若配置依赖已改变，调用方必须重新准备环境与全量基线。本地验收只检查版本和配置绑定，不证明新提交能在旧镜像上运行。

`findings_delta.added/removed` 为当前与 baseline 报告 finding_id 集合之差。finding_id 对同仓库、同配置、同 type/target/dependency/声明定位的同一发现保持稳定，commit 单独记录。位置语义改变或被识别为新发现时使用新 ID；具体稳定 ID 算法由 A14 实现。

### ERROR_REPORT 与 REPAIR

报告必含 schema_version、repository、configuration_id、producer_job_id、findings。每条 finding 必含 finding_id、type、target、dependency、commit、detector、location（path、line）、evidence（kind、description）。证据类型为 DYNAMIC_TRACE、STATIC_INFERENCE、MANUAL_FIXTURE 或 INSTRUCTOR_ORACLE。人工样例不得假装由检测器产生。

REPAIR 的 md_report_uri 必须指向非空、全部 `MISSING` 的报告；如全量报告含 RD，由 A14 过滤并发布独立 MD-only 报告，保留 finding_id 和生产来源。REPAIR 不静默丢弃 RD。报告仓库、commit、配置须与修复请求完全一致，所有 location.path 必须包含在 makefiles 中。实际执行时还须检查该 SHA 中 Makefile 存在、行定位有效；本地校验不会检出 A14 仓库。

REPAIR 输出包含 patch_uri（无接受补丁时为 null）、candidates、artifacts。每个候选必含 candidate_id、patch_uri、declaration_style、style_explanation、decision、reason、build、verify、recheck。风格枚举 ATOMIC/MACRO/HYBRID 映射论文的原子依赖、宏依赖、混合风格。重检由 B14 发起，A14 提供检测能力，B14 按同一源码基线加候选 patch 的结果作出最终接受决定。产物 commit 仍为补丁的基线 SHA，patch_uri 唯一标识候选工作树变化；不得伪造“修复后 commit”。

候选接受条件：build、verify、recheck 全 PASSED，remaining_missing 为 0，重检报告明确绑定当前 patch_uri。本版要求清除输入报告的全部目标 MD，不要求顺便修 RD。候选失败时保留 REJECTED 与原因并可继续下一候选。全部候选失败才产生 GOAL_UNMET。示例只有一个候选，但数组支持多个。

## 4. 状态与错误

允许迁移：QUEUED → RUNNING → SUCCEEDED/FAILED/TIMED_OUT/CANCELLED；排队时也可因取消或总时限到达而进入 CANCELLED/TIMED_OUT，调度设施失败可进入 FAILED。终态不可逆。timeout_seconds 从受理时计时，包括排队；超时/取消停止执行并保留已经产生的证据。E2 约定取消语义但未定义公开取消端点，取消由平台/执行器发起，接口扩展需新增 ADR。

- QUEUED/RUNNING：output=null，error=null，本版本不暴露部分进度。
- SUCCEEDED：output 为对应结果，error=null。MD/RD 发现仍属于成功完成的分析。
- FAILED：error.category 为 GOAL_UNMET 或 SYSTEM。GOAL_UNMET 必须保留 output 中的候选/迭代证据。
- TIMED_OUT：EXEC_4002 / SYSTEM，output 可为 null 或已有部分结果。
- CANCELLED：EXEC_4004 / CONTROL，output 可为 null 或已有部分结果。

| code | category / 使用位置 | 含义与处理 |
| --- | --- | --- |
| INPUT_1001 | INPUT / HTTP 400 或 422 | JSON/字段/仓库 SHA/命令无效，修正后重发 |
| INPUT_1002 | INPUT / HTTP 422 | 必需跨服务输入缺失，如 baseline |
| INPUT_1003 | INPUT / HTTP 422 | repo、commit 或 configuration 不匹配 |
| INPUT_1004 | INPUT / HTTP 422 | REPAIR 收到 RD 或空报告 |
| INPUT_1005 | INPUT / HTTP 422 | URI 不可读取、类型不符或完整性校验失败 |
| INPUT_1006 | INPUT / HTTP 409 | 幂等键对应不同内容 |
| JOB_2001 | INPUT / HTTP 404 | 查询不存在的 Job |
| ENV_3002 | GOAL_UNMET 或 SYSTEM / FAILED | Docker 环境构建未解决，或环境设施故障；category 明确区分 |
| EXEC_4001 | SYSTEM / FAILED | 执行器崩溃或内部错误 |
| EXEC_4002 | SYSTEM / TIMED_OUT | 整个任务超过时间预算 |
| EXEC_4003 | GOAL_UNMET 或 SYSTEM / FAILED | 最终 build/verify 未通过，或无法正常执行命令；中间尝试失败只写迭代/候选 |
| EXEC_4004 | CONTROL / CANCELLED | 平台请求取消 |
| ANALYSIS_5001 | SYSTEM / FAILED | 分析器执行失败 |
| REPAIR_6001 | GOAL_UNMET / FAILED | 所有修复候选无效 |

`error` 必含 code、category、message、retryable、details。retryable 是提示，不触发后台无限重试。INPUT/GOAL_UNMET 通常需修正输入/策略后使用新幂等键重发；系统故障可在排除故障后重试。

此表保留原协作消息中的错误码并补充缺项。对话中出现过描述性 `DRAFT_BUILD_UNRESOLVED` 建议；本版使用既有 ENV_3002 + GOAL_UNMET + details.reason=ITERATION_LIMIT，避免同时维护两套错误码。

## 5. 产物与本地读取

每个 Artifact 必含 artifact_id、type、uri、media_type、producer_job_id、repository_url、commit、configuration_id、sha256。B14 DRAFT 使用 `artifact://b14-draft/{job_id}/{artifact_name}`；REPAIR 使用 `b14-repair`；A14 样例使用 `a14-check`。authority 是逻辑命名空间，不是可直接访问的 HTTP 域名。

本地解析步骤：

1. 按完整 URI 精确查询 `contracts/artifact-manifest.json`。
2. 将 manifest 中 path 相对仓库根目录解析，只允许落在 `contracts/artifacts/` 内。
3. 读取文件字节并核验 sha256。
4. 按 type 校验 JSON 内容及 repo/commit/configuration/producer，交给下游。

```sh
python validator/validate.py --read-artifact artifact://b14-draft/job-draft01/Dockerfile
python validator/validate.py --read-artifact artifact://a14-check/job-full01/md.json
```

A14 已在回复中确认可通过 manifest 和校验器读取人工产物，并提供了本地验证记录。B14 已对其交付包进行样例与产物兼容性复核，见 [交接记录](../docs/collaboration/交接确认.md)。这些记录不等于真实镜像或服务联调成功。真实仓库、registry 和对象存储尚未提供，E3 可由 manifest 映射到经双方批准的下载接口，URI 逻辑身份与生产来源保持稳定。镜像单独用 image_ref 拉取，不把 image.json 当作镜像本体。

本地套件证明文件存在、SHA 一致、元数据匹配及协议数据可消费；不证明 registry 可达、容器可运行、补丁正确或 A14 的网络权限。实际运行前的这些检查由 E3 执行器负责。

## 6. 版本与变更

本版严格拒绝额外字段。即使新增可选字段，旧严格消费者也可能拒绝，因此仍需同时更新 Schema、样例、校验器、ADR，并由 A14 确认。字段删除、改名、语义修改和状态枚举变化视为破坏性变化，发布新 schema_version；请求旧版本时明确拒绝，不能静默解释为新语义。

## 7. 依据

- E2 课件第 3、5–10、19–27 页：分工、统一任务、状态、错误、四服务 I/O、产物与验证。
- `A14_协作确认消息.md`：B14 已提出的端点、版本、默认值、错误码和 A14 回复格式。消息中“当前仓库内容包括”仅为原消息描述；本次执行前仓库实际只有 README。
- [论文与接口依据](../docs/paper-notes.md)：说明哪些是论文概念，哪些是课程约束或本组契约设计。
