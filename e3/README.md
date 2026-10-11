# B14 E3 并行测试基线

课程《E3 并行测试基线》B 组交付（B14）。按课件第 6 页 B 组清单，B14 在 E3 准备
两类可直接让别人复现的测试基线：**DRAFT 环境生成样本**与 **MDFixer 缺失依赖修复样本**。
配对组 A14 负责 BuildChecker（FULL_CHECK）与 EChecker（INCREMENTAL_CHECK）。

主交付说明：[B14 E3 交付说明](B14_E3交付说明.md)。真实运行记录：[2026-09-25 基线记录](验证记录_20260925.md)、[2026-10-07 Docker 补测](验证记录_20261007.md)。

**当前状态**：仓库已有 2026-10-07 Docker 补测证据，失败样例准确报告 `make: not found`，参考镜像构建成功并输出 `hello E3`。本页同步已有结果；下文 9 月 25 日环境限制属于历史状态。

## 交付物一览

| 路径 | 内容 |
| --- | --- |
| [`B14_E3交付说明.md`](B14_E3交付说明.md) | 主文档：需求对照、样本说明、证据与限制 |
| [`验证记录_20260925.md`](验证记录_20260925.md) | 9 月 25 日真实执行的命令、退出码与观察结果 |
| [`验证记录_20261007.md`](验证记录_20261007.md) | 10 月 7 日 Docker 失败定位、参考构建与容器运行补测 |
| [`fixtures/draft/`](fixtures/draft/README.md) | DRAFT 样本：TinyGreeting 源码、Makefile、失败/参考 Dockerfile |
| [`fixtures/mdfixer/`](fixtures/mdfixer/README.md) | MDFixer 样本：缺 `config.h` 的 Makefile、参考补丁、固定 MD 报告 |
| [`scripts/run_b14_e3.py`](scripts/run_b14_e3.py) | 一键真实执行脚本，按运行时间写入证据目录 |
| [`evidence/20260925-b14-e3/`](evidence/20260925-b14-e3/observations.json) | 9 月 25 日真实证据：日志、退出码、观察、绑定报告 |
| [`evidence/20261007-b14-e3/`](evidence/20261007-b14-e3/) | Docker 补测日志、镜像 ID、容器输出与校验清单 |

## 一键复现

需要 Linux + GNU Make + `cc`/`gcc` + Git + Python 3.8+。无需网络，无需 Docker
（此脚本不执行 Docker；容器补测结果见“Docker 状态与限制”）。

```sh
cd <仓库根目录>
python3 e3/scripts/run_b14_e3.py                 # 按当前时间新建证据目录
python3 e3/scripts/run_b14_e3.py --run-id my-run # 使用固定 run-id，便于对照
```

脚本每次新建 `e3/evidence/<run-id>/`，不覆盖历史证据；`e3/work/` 为临时构建目录
（已在 `.gitignore` 中忽略）。

## 2026-09-25 实测环境（历史记录）

| 项目 | 值 |
| --- | --- |
| 平台 | Linux 6.6 WSL2，x86_64 |
| 系统 | Ubuntu 22.04.5 LTS |
| MAKE | GNU Make 4.3 |
| 编译器 | cc / gcc 11.4.0 |
| Git | 2.34.1 |
| Python | 3.10.12 |
| Shell | `/bin/sh` → dash |
| Docker | 未安装，无网络（因此未产生真实镜像 ID） |

## 2026-09-25 真实结论速览（run-id `20260925-b14-e3`）

| 场景 | 实际观察 | 含义 |
| --- | --- | --- |
| DRAFT 构建 | `make` 退出码 0，生成 `hello` | 第一层成功判据（编译通过） |
| DRAFT 验证 | `./hello` 退出码 0，stdout `hello E3` | 第二层成功判据（功能验证） |
| DRAFT 失败候选 | `Dockerfile.broken` 的 `RUN make` 语义复现：退出码 127，`make: not found` | 失败可定位到具体工具缺失 |
| MDFixer 初次构建 | `./app` 输出 `1` | 初始值 |
| MDFixer 只改头文件 | 普通 `make` 报 `'app' is up to date`，`./app` 仍输出 `1` | **MD 的真实行为证据**（未重编译） |
| MDFixer clean 对照 | `make clean && make` 后 `./app` 输出 `2` | 完整重建才反映新头文件 |
| MDFixer 参考补丁 | `git apply --check`/`git apply` 退出码 0，Makefile 与参考版哈希一致 | 参考修复可用 |
| MDFixer 修复后 | 再只改头文件为 3，普通 `make` 自动重编译，`./app` 输出 `3` | 补丁恢复触发关系 |
| MDFixer 无效候选 | 故意失败命令使 `make` 退出码 2 | 候选应被拒绝 |
| MDFixer 恢复 | 恢复参考 Makefile 后 `make` 退出码 0，`./app` 输出 `3` | 副本可恢复 |

## Docker 状态与限制

- **Docker 证据已于 2026-10-07 补齐**：9 月 25 日环境无 Docker/网络，当时仅保存宿主机编译和受限 PATH 失败证据；这些历史日志及 `observations.json` 保留不变。后续在 B14 服务器完成真实 Docker 补测：失败构建退出码 1、参考构建退出码 0、容器输出 `hello E3`，补测说明记录容器退出码 0。镜像 ID 为 `sha256:e21f3cbc2e958d337c95606f9624c103d6157bf634255c8c2d783484e2067093`（amd64）。详见 [补测记录](验证记录_20261007.md) 与 [当前 Docker 状态](fixtures/draft/docker_status.json)。
- **未做真实联调**：这些是 B14 自备的人工基线，尚未接入 A14 的真实检测数据（E12）。
- **人工标签不入准确率**：MD 报告来源为 `INSTRUCTOR_ORACLE`，只作预期答案，不计入
  工具准确率。

## 相关文档

- E2 接口契约（REPAIR 消费 MD）：[`contracts/API.md`](../contracts/API.md)
- Backlog：[`docs/backlog.md`](../docs/backlog.md)
- 贡献与版本记录：[`docs/contributions.md`](../docs/contributions.md)
- AI 使用记录：[`docs/AI_USAGE.md`](../docs/AI_USAGE.md)
