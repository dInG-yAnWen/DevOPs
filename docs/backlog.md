# B14 Backlog（E2 契约 + E3 基线）

2026-09-25。DONE_LOCAL 表示本地材料与校验完成；A14_ACCEPTED 表示已收到 A14 对 E2 1.0 的接受回复；B14_E3_LOCAL 表示 B14 已本地完成 E3 自备基线（真实执行，见 `e3/`）。以上均不代表正式版本发布或课程平台提交。负责人使用责任角色，未冒填组员姓名；个人认领见贡献记录。

| ID | 需求 | 负责人/协作方 | 产物 | 验收条件 | 状态 |
| --- | --- | --- | --- | --- | --- |
| E2-01 | 统一四类请求和 Job | B14 接口负责人 / A14 接口负责人 | task.schema.json、API.md | 四类对象可表示，未知类型拒绝 | DONE_LOCAL / A14_ACCEPTED |
| E2-02 | DRAFT 输入输出与终态 | B14 DRAFT 负责人 | draft_* 样例 | 成功/失败/超时/取消及受控失败均表达 | DONE_LOCAL |
| E2-03 | baseline 约束 | B14 契约整理 / A14 EChecker 负责人 | incremental_*、图与报告 | 缺 baseline、SHA/配置不符被拒绝 | DONE_LOCAL / A14_ACCEPTED |
| E2-04 | REPAIR 消费 MD | B14 MDFixer 负责人 / A14 检测负责人 | repair_*、md.json、fix.patch | 仅接受同版本 MD，候选拒绝可解释 | DONE_LOCAL |
| E2-05 | 产物访问规范 | B14/A14 接口负责人 | manifest、ADR-002、resolver | 本地按 URI 读取，来源与 hash 一致 | DONE_LOCAL / A14_ACCEPTED；人工文件交接已复核，真实服务联调未执行 |
| E2-06 | 最小契约验证 | B14 验收负责人 | validate.py、validation.md | 正例通过、反例拒绝、复现命令可运行 | DONE_LOCAL |
| E2-07 | 设计与 AI 记录 | B14 文档负责人 | ADR、AI_USAGE、主交付说明 | 决策、替代方案、人工/AI 来源可追溯 | DONE_LOCAL；待人工审阅 |
| E2-08 | A14 接口确认与本地交接 | A14 接口负责人 / B14 联系人 | collaboration/ 回复原文、交接结果 | A14 接受 1.0，历史命令约定记录，样例兼容 | DONE_LOCAL / A14_ACCEPTED；B14 SHA 已补录，待 A14 指定交付 SHA |
| E2-09 | 个人贡献认领 | B14 各成员 | contributions.md、实际 Git 记录 | 姓名、实际工作与证据对应 | OPEN，不代填 |
| E2-10 | 正式课程提交 | B14 提交负责人 | 仓库 URL 与已发布契约 SHA | 版本可核验，并完成课程平台最终提交 | B14 基线已发布；课程平台提交待完成 |
| E3-01 | 共同选定真实实验项目 | A14 项目联系人 / B14 DRAFT 负责人 | repo、SHA、命令、环境说明 | 固定提交可复现，不使用示例地址 | B14_E3_LOCAL（B14 自备小项目 TinyGreeting）；与 A14 共同选定仍 OPEN |
| E3-02 | 真实存储与访问 | A14/B14 部署负责人 | registry/下载映射 | A14 实际读取至少一份 B14 产物，记录证据 | OPEN |
| E3-03 | 真正的 Job 运行服务 | B14/A14 服务负责人 | HTTP API、存储、执行器 | 202/GET、24h 幂等、超时取消与终态锁定 | OPEN |
| E3-04 | DRAFT 生成策略 | B14 DRAFT 负责人 | 生成与迭代实现 | 按固定 commit 构建和验证，真实日志保留 | B14_E3_LOCAL 基线（真实构建/验证、失败候选、参考 Dockerfile）；自动生成器实现仍 OPEN |
| E3-05 | MDFixer 与重检回路 | B14 MDFixer / A14 检测负责人 | 修复实现、重检接口 | patch 绑定正确基线与候选，三项通过才接受 | B14_E3_LOCAL 样本（MD 报告、参考补丁、行为证据、无效候选恢复）；重检接口与 A14 联调仍 OPEN |
| E3-06 | 环境和报告语义核验 | B14/A14 | 仓库检出/镜像可达检查 | 验证真实路径、命令、image digest、配置重用条件 | PARTIAL：本地路径/命令/工具链已核；image digest 未核（本机无 docker） |
| E3-07 | 历史构建命令快照 | A14 EChecker 负责人 / B14 接口负责人 | A14 内部存储与后续字段评审记录 | 按 repo/base_commit/configuration 保存；E2 不新增字段，后续公开须评审 | DEFERRED_TO_E3 |

## 协作状态与后续事项

A14 已接受统一 Job、错误类别、MD-only 交接和基线配置约束，见 [协作记录](collaboration/交接确认.md)。不再重复列为等待 A14 回复。

- E2 收尾：人工贡献审阅、向 A14 提供 B14 已发布 SHA 并取得其指定版本、课程平台提交。B14 基线为 `689539119e60afd4b224d3163d1ba292992baa95`，见 [版本记录](release.md)。
- E3 共同决定：真实项目、registry/产物存储及读取授权。
- E3 历史命令：A14 按 repository_url + base_commit + configuration_id 内部保存快照；双方评审是否通过新版本公开 build_commands_uri，E2 1.0 不新增字段。

## E3 B14 自我准备（2026-09-25）

按课件第 6 页 B 组清单，B14 已在 `e3/` 完成 DRAFT 与 MDFixer 两类自备基线，真实执行证据在
`e3/evidence/20260925-b14-e3/`，主交付说明见 `e3/B14_E3交付说明.md`。

| ID | 事项 | 产物 | 状态 |
| --- | --- | --- | --- |
| E3-B14-01 | DRAFT 样本：源码、Makefile、README、命令 | `e3/fixtures/draft/` | B14_E3_LOCAL |
| E3-B14-02 | DRAFT 失败候选与参考修复 | `Dockerfile.broken`、`Dockerfile.reference` | 文件就绪；Docker 构建待有环境执行 |
| E3-B14-03 | DRAFT 真实构建/验证日志 | `draft_build.log`、`draft_verify.log` | B14_E3_LOCAL（退出码 0，输出 `hello E3`） |
| E3-B14-04 | 固定 MD 报告与对应 Makefile | `md_report.json`、`Makefile.before` | B14_E3_LOCAL |
| E3-B14-05 | 参考补丁与行为验证 | `reference.patch`、`mdfixer_07..10` 日志 | B14_E3_LOCAL（改头文件旧值→clean 新值） |
| E3-B14-06 | 无效候选与恢复 | `mdfixer_11..13` 日志 | B14_E3_LOCAL |
| E3-B14-07 | Docker 镜像 ID / 容器结果 | `observations.json` 的 `docker` 字段 | OPEN（本机无 docker/网络，未伪造） |
| E3-B14-08 | 一键复现脚本 | `e3/scripts/run_b14_e3.py` | B14_E3_LOCAL |

本文件只记录事项，不代替真实实现、提交或对外发送消息。
