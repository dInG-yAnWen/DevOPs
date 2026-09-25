# B14 E2 Backlog

2026-09-25。DONE_LOCAL 表示本地材料与校验完成；A14_ACCEPTED 表示已收到 A14 对 E2 1.0 的接受回复，两者均不代表正式版本发布或课程平台提交。负责人使用责任角色，未冒填组员姓名；个人认领见贡献记录。

| ID | 需求 | 负责人/协作方 | 产物 | 验收条件 | 状态 |
| --- | --- | --- | --- | --- | --- |
| E2-01 | 统一四类请求和 Job | B14 接口负责人 / A14 接口负责人 | task.schema.json、API.md | 四类对象可表示，未知类型拒绝 | DONE_LOCAL / A14_ACCEPTED |
| E2-02 | DRAFT 输入输出与终态 | B14 DRAFT 负责人 | draft_* 样例 | 成功/失败/超时/取消及受控失败均表达 | DONE_LOCAL |
| E2-03 | baseline 约束 | B14 契约整理 / A14 EChecker 负责人 | incremental_*、图与报告 | 缺 baseline、SHA/配置不符被拒绝 | DONE_LOCAL / A14_ACCEPTED |
| E2-04 | REPAIR 消费 MD | B14 MDFixer 负责人 / A14 检测负责人 | repair_*、md.json、fix.patch | 仅接受同版本 MD，候选拒绝可解释 | DONE_LOCAL |
| E2-05 | 产物访问规范 | B14/A14 接口负责人 | manifest、ADR-002、resolver | 本地按 URI 读取，来源与 hash 一致 | DONE_LOCAL / A14_ACCEPTED；人工文件交接已复核，真实服务联调未执行 |
| E2-06 | 最小契约验证 | B14 验收负责人 | validate.py、validation.md | 正例通过、反例拒绝、复现命令可运行 | DONE_LOCAL |
| E2-07 | 设计与 AI 记录 | B14 文档负责人 | ADR、AI_USAGE、主交付说明 | 决策、替代方案、人工/AI 来源可追溯 | DONE_LOCAL；待人工审阅 |
| E2-08 | A14 接口确认与本地交接 | A14 接口负责人 / B14 联系人 | collaboration/ 回复原文、交接结果 | A14 接受 1.0，历史命令约定记录，样例兼容 | DONE_LOCAL / A14_ACCEPTED；正式 SHA 待发布 |
| E2-09 | 个人贡献认领 | B14 各成员 | contributions.md、实际 Git 记录 | 姓名、实际工作与证据对应 | OPEN，不代填 |
| E2-10 | 正式课程提交 | B14 提交负责人 | 课程仓库 URL 与新 SHA | 用户允许后 commit/push，记录真实 SHA | ON_HOLD_BY_USER，不 commit |
| E3-01 | 共同选定真实实验项目 | A14 项目联系人 / B14 DRAFT 负责人 | repo、SHA、命令、环境说明 | 固定提交可复现，不使用示例地址 | DEFERRED_TO_E3，A/B 共同选定 |
| E3-02 | 真实存储与访问 | A14/B14 部署负责人 | registry/下载映射 | A14 实际读取至少一份 B14 产物，记录证据 | OPEN |
| E3-03 | 真正的 Job 运行服务 | B14/A14 服务负责人 | HTTP API、存储、执行器 | 202/GET、24h 幂等、超时取消与终态锁定 | OPEN |
| E3-04 | DRAFT 生成策略 | B14 DRAFT 负责人 | 生成与迭代实现 | 按固定 commit 构建和验证，真实日志保留 | OPEN |
| E3-05 | MDFixer 与重检回路 | B14 MDFixer / A14 检测负责人 | 修复实现、重检接口 | patch 绑定正确基线与候选，三项通过才接受 | OPEN |
| E3-06 | 环境和报告语义核验 | B14/A14 | 仓库检出/镜像可达检查 | 验证真实路径、命令、image digest、配置重用条件 | OPEN |
| E3-07 | 历史构建命令快照 | A14 EChecker 负责人 / B14 接口负责人 | A14 内部存储与后续字段评审记录 | 按 repo/base_commit/configuration 保存；E2 不新增字段，后续公开须评审 | DEFERRED_TO_E3 |

## 协作状态与后续事项

A14 已接受统一 Job、错误类别、MD-only 交接和基线配置约束，见 [协作记录](collaboration/交接确认.md)。不再重复列为等待 A14 回复。

- E2 收尾：人工贡献审阅、双方正式发布并交换完整 SHA、课程平台提交。
- E3 共同决定：真实项目、registry/产物存储及读取授权。
- E3 历史命令：A14 按 repository_url + base_commit + configuration_id 内部保存快照；双方评审是否通过新版本公开 build_commands_uri，E2 1.0 不新增字段。

本文件只记录事项，不代替真实实现、提交或对外发送消息。
