# B14 E2 贡献与版本记录

## 已有可核验记录

- 仓库 origin：`https://github.com/dInG-yAnWen/DevOPs.git`。
- 工作起点 HEAD：`81ebd88445604956f045b0479054eb24bec72477`。
- 该已有提交作者：丁彦文；提交说明：first commit。它是本次工作前的历史记录，不能据此把本次新增文件记为已提交贡献。
- 用户已完成 E2 commit/push：`689539119e60afd4b224d3163d1ba292992baa95`，说明为 `E2 finished`，Git 作者 DingYanwen，作者时间 2026-09-25T16:48:26+08:00。本地与远程 main 已核对一致，见 [版本记录](release.md)。这项 Git 事实不代替个人工作分配及人工审阅确认。

## 本次工作来源

| 贡献来源 | 实际内容 | 证据 |
| --- | --- | --- |
| 用户 | 明确 B 组任务，纠正业务结果/失败语义，指定 A14 未回复时先预设且不提交 | 引用对话与本次请求；AI_USAGE.md |
| AI 辅助 | 材料读取、契约与样例起草、校验器、交付说明、ADR/Backlog | 已发布契约基线、validation.md |
| B14 人工审阅 | 尚未记录 | 后续由实际审阅者填写 |
| A14 协作确认 | 已收到 E2 1.0 接受回复；此项仅更新协作事实，不代替 B14 个人贡献认领 | [原文及交接记录](collaboration/交接确认.md) |

## 后续真实认领记录

| 成员姓名 | 实际负责/审阅文件 | 实际判断或修改 | 日期 | commit / Issue / PR |
| --- | --- | --- | --- | --- |
| 待本人填写 | 待实际认领 | 待实际审阅 | 待完成 | 基线 SHA 已记录，个人对应工作仍待确认 |

不得把该表当作已完成的个人贡献证明。已记录真实 Git 版本，仍需按实际情况认领工作，并检查课程平台要求的提交入口。

# B14 E3 贡献与版本记录

- 2026-09-25。范围：课程《E3 并行测试基线》B 组（DRAFT + MDFixer），主交付见[`e3/B14_E3交付说明.md`](../e3/B14_E3交付说明.md)。
- 本次提交作者：杨王旭；提交说明：完成了部分E3的工作

## 版本记录

| 项目 | 内容 |
| --- | --- |
| 工作起点 HEAD | `689539119e60afd4b224d3163d1ba292992baa95`（E2 finished） |
| 本次提交 SHA | 7d12146d678cf48c8202ecab3c8e8dd88055ae01 |
| 新增目录 | `e3/`（fixtures、scripts、evidence、说明文档） |
| 证据 run-id | `20260925-b14-e3` |
| DRAFT 样本基线 commit | `5bb9e757247b8fad2efa3fbbcd17a7ff6d47ebe3`（本地真实 Git，可复现） |
| MDFixer 样本基线 commit | `baf5f829073251b5e01e8af6af1b89314f3116c3`（本地真实 Git，可复现） |

## 本次工作来源

| 贡献来源 | 实际内容 | 证据 |
| --- | --- | --- |
| 用户 | 明确 B14 的 E3 任务（DRAFT 全过程、最简 MDFixer 样本、真实复现修复前行为），要求不伪造 | 引用对话与本次请求 |
| AI 辅助 | 样本源码/Makefile/Dockerfile、固定 MD 报告、参考补丁、执行脚本、文档起草 | `e3/` 本次未提交文件；`e3/evidence/20260925-b14-e3/` |
| B14 人工审阅 | 尚未记录 | 后续由实际审阅者填写下方认领表 |
| A14 协作 | 本次未与 A14 交互；E2 1.0 接受状态沿用 | [`docs/collaboration/交接确认.md`](collaboration/交接确认.md) |

## 本次真实执行（可复现，非模拟）

| 场景 | 实际结果 | 证据 |
| --- | --- | --- |
| DRAFT 构建/验证 | `make` 退出码 0；`./hello` 输出 `hello E3`，退出码 0 | `e3/evidence/20260925-b14-e3/draft_build.log`、`draft_verify.log` |
| DRAFT 失败候选 | 受限 PATH 复现 `RUN make`：退出码 127，`make: not found` | `draft_broken_build.log` |
| MDFixer 修复前 | 只改 `config.h` 后 `make` 不重编译，`./app` 仍输出 `1`；clean 后输出 `2` | `mdfixer_03/04/05/06_*.log` |
| MDFixer 参考补丁 | `git apply --check`/`git apply` 通过；修复后再改头文件自动重建输出 `3` | `mdfixer_07/08/09/10_*.log` |
| MDFixer 无效候选与恢复 | 失败候选 `make` 退出码 2；恢复后构建通过 | `mdfixer_11/12/13_*.log` |
| Docker 镜像 | 未执行：本机无 docker、无网络，未产生真实镜像 ID，未伪造 | `observations.json` 的 `docker` 字段 |

## 后续真实认领记录（B14 E3）

| 成员姓名 | 实际负责/审阅文件 | 实际判断或修改 | 日期 | commit / Issue / PR |
| --- | --- | --- | --- | --- |
| 待本人填写 | 待实际认领 | 待实际审阅 | 待完成 | 本次不提交 |

同 E2：本表不得当作已完成的个人贡献证明；用户允许提交后再补真实 Git 版本。Docker 镜像
证据需在有 Docker 与网络的环境按交付说明第 6 节命令补齐，补后在此登记。
