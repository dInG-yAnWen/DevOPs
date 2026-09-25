# ADR-001：统一异步 Job 与严格版本

- 日期：2026-09-25
- 状态：A14 已接受 E2 1.0，回复已记录；B14 契约基线已发布，见 [版本记录](../release.md)
- 责任：B14/A14 接口负责人

## Context

四种任务均可能长时间运行，课件第 7、19、27 页要求先定义异步任务接口，E2 不要求服务部署。原协作消息已经提出 DRAFT 端点、版本和状态；初稿编写时 A14 尚未回复，现已在 2026-09-25 接受 E2 1.0；原文见 [协作记录](../collaboration/交接确认.md)。

## Decision

使用四个 POST 创建端点与统一 GET 查询，POST 返回 202，服务端生成 job_id。共享 schema_version、trace_id、execution 与 Job 状态。使用 idempotency_key 避免同一请求重试产生重复执行。同键不同请求返回 409；本版约定幂等记录保留 24 小时。

保持 schema_version=1.0、QUEUED/RUNNING/SUCCEEDED/FAILED/TIMED_OUT/CANCELLED。canonical 请求显式填写默认 1800 秒；DRAFT 显式填写默认 3 次，包含首次尝试。Schema 不负责填充默认值。

对象严格拒绝额外字段。字段变化需同时更新契约、样例和消费者；新增可选字段也不自动视为向后兼容。破坏性语义变更升级版本。

## Alternatives

- 同步等待：实现简单，但请求生命周期与算法运行耦合，超时后难以判断是否重复执行。
- 每项服务自定义完全不同的请求/状态：局部自由度高，但跨组消费与追踪复杂。
- 接受任意额外字段：扩展容易，但无法及时发现字段拼写错误。

## Consequences

E3 需要任务/幂等存储、查询与终态一致性处理。本地 E2 样例只证明结构与语义，无法证明运行中的幂等或状态迁移。协议额外字段不能随意添加。

## Evidence

contracts/API.md 第 1、2、4、6 节；四类请求、accepted 与结果样例；schema_version 和未知字段的拒绝检查。A14 的接受依据见 [协作记录](../collaboration/交接确认.md)；Backlog E2-08 已记录完成，B14 SHA 已记录，A14 指定交付 SHA 待其提供。
