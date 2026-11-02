# E7 个人复跑记录（徐梓航，241880273）

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 小组 / 轨道 | B14 / B（DRAFT） |
| 服务器个人克隆目录 | `/root/241880273/e7-241880273` |
| 分支 | `e7-241880273` |
| 运行源码提交 | `7dac529416696cbe25cbb735439c92008b6d062c` |
| E7 运行目录 | `work/e7-20261102-145703-241880273` |
| 候选来源 | E5 已保存的 `context-mirror` 候选回放；E7 未调用模型 |
| 候选 Dockerfile SHA-256 | `e0a47332ae920e9372a583abd44a2d2841c9622e0ed736fbd98b79db6acdbd76` |
| E7 服务镜像 ID | `sha256:9c87b8586d3d968aa8090e4033779caa8569ac594b254bf14c75902463b56fe7` |
| 门禁 Trace ID | `e7-g-7f23f435bcf64ee3a298bf1c6456f0d4` |
| 证据归档目录 | `e7/evidence/20261102-241880273-e7/` |

## 执行结果

采集器状态为 `SUCCEEDED`。服务测试 68 项通过，E7 采集器测试 7 项通过。

六个质量门禁场景全部通过：success、wrong-output、invalid-candidate、build-failed、runtime-timeout、runtime-nonzero。门禁状态为 `PASS`，`complete=true`；`verify-gate` 校验 236 个文件通过，清理检查确认采集器容器不存在。

## 结果边界

候选来自 E5 已保存文件的回放，不是 E7 新生成的模型候选；E7 流程未调用模型或 API。个人本地复跑不代替 GitHub 端 artifact、实际分支保护及失败合并拒绝等团队级验收证据。
