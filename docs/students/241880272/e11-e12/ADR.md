# ADR：E11–E12 DRAFT 镜像交付

编号、日期、作者：ADR-241880272-e11e12 / 2026-11-16 / 杨王旭（241880272）

问题：

下游需要使用 C1 上实际构建出的 DRAFT 镜像做检测与动态复验，但本机镜像 ID 不可直接跨机使用，且仅有镜像 ID 无法说明输入、配置和验证过程。

候选方案：

- A：只提供本地镜像 ID，由对方自行准备环境。
- B：推送到公共镜像仓库，提供 `image_ref@sha256:…`。
- C：本地 `docker save` 归档，附 image ID、输入哈希、配置 ID 与日志，对方 `docker load` 后按 ID 运行。
- D：同时支持 B 与 C，按可用仓库条件选择。

采用方案与原因：

采用 D。脚本默认生成 C 的完整本地证据，并保留 `--push-ref` 选项；有可用仓库时可额外得到仓库 digest。这样在没有仓库凭据时也能交付可复核的镜像，有仓库时可直接 `docker pull`。

输入输出字段：

- 输入：C1 项目目录（`main.c`、`config.h`、`feature.h`、`Makefile`）、候选 Dockerfile、期望输出、镜像 tag、可选推送引用。
- 输出：`configuration_id`、`job_id`、`trace_id`、镜像 ID、构建/运行/保存日志、镜像归档 SHA-256、`manifest.json`。
- `configuration_id` 为输入文件哈希、Dockerfile 哈希与期望输出的规范化 JSON 的 SHA-256，保证同一配置得到同一 ID。

兼容性与测试：

- 不改变现有 `run_e11e12.py` 和 `labs/e11e12` 其他入口，仅新增模块与测试。
- 单元测试 5 项通过；真实 C1 构建退出 0，镜像运行退出 0，stdout 精确为 `12\n`。
- 局限：镜像跨运行不可复现（apt 包未锁版本）；本次以同一次构建产生的镜像 ID 和归档作为交付依据。
