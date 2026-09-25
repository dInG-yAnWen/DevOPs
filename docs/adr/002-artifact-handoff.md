# ADR-002：可解析的逻辑产物 URI 与来源绑定

- 日期：2026-09-25
- 状态：A14 已接受 E2 1.0，回复已记录；正式版本发布待完成
- 责任：B14/A14 接口负责人

## Context

图、日志和 patch 不宜全部放进 Job 响应。课件第 24 页要求 URI 读取方式和生产来源明确。A14 尚未提供 registry 或对象存储，不能假设公共 URL 已经存在。

## Decision

保留 `artifact://b14-draft/{job_id}/{artifact_name}`，并为 REPAIR、A14 检测样例使用 b14-repair、a14-check 命名空间。E2 用随仓库分发的 manifest 将完整 URI 精确映射至 contracts/artifacts 内的真实文件，读取时核验 SHA-256。

每份产物记录生产 Job、仓库 URL、commit、configuration_id 和媒体类型；JSON 内容与元数据必须一致。Docker 镜像单独使用 image_ref + digest。image.json 是元数据文件，不是镜像。

baseline actual graph 与旧报告绑定 base_commit 和同配置。REPAIR 的 MD 报告绑定当前修复基线。候选重检报告另绑定 patch_uri，避免把不同候选的重检结果混用。

2026-09-25 根据 A14 回复补充：E2 1.0 不新增 `baseline.build_commands_uri`。EChecker 历史构建命令快照由 A14 内部按 `repository_url + base_commit + configuration_id` 保存，E3 落实内部持久化，并评审后续是否公开字段。这样保留历史命令来源，同时避免单方扩展严格 Schema 导致消费者拒绝；本次没有实现或验证该内部存储。

## Alternatives

- 只给 URI 字符串不提供解析器：格式好看但无法实际读取。
- 把全部内容嵌入 Job：便于小样例展示，但大日志和图导致重复传输。
- 直接预设某个公共 registry 已可用：缺少 A14 资料，不能据此声称交付可运行镜像。

## Consequences

本包可在本机/另一个获取了同包的机器离线读取样例。真实下载地址、镜像拉取权限和配置生成策略仍需 E3 联调。当前生成的产物均标识为人工样例，不作为真实构建日志。

E12 实际跨组读取证据不能用本地校验代替。E2 已提供读取方法，Backlog E3-02 保留真实读取待办。

## Evidence

artifact-manifest.json、validate.py 的 resolve/bound、各产物记录、未知/越界 URI 的拒绝检查。

A14 接受回复及本次 19 份产物、20 份正例、7 份反例交接检查见 [协作记录](../collaboration/交接确认.md)。真实项目与存储由 A/B 在 E3 共同选定，不再作为等待 A14 单方提供资料的 E2 前置事项。
