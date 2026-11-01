# E6 个人复跑记录（徐梓航，241880273）

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 小组 / 轨道 | B14 / B（DRAFT） |
| 服务器个人克隆目录 | `/root/241880273/e6-241880273` |
| 运行分支 | `e6-241880273`，基于 `e6-mvp` |
| 运行源码提交 | `c47bcce4647bc450fc3a8832fab5ef3b03f93891` |
| Git 身份 | `241880273 <241880273@localhost>` |
| E6 采集运行目录 | `work/e6-20261101-184121-241880273` |
| 证据归档目录 | `e6/evidence/20261101-241880273-e6/collection/` |
| 候选来源 | 回放 E5 已保存的 `context-mirror` 候选；E6 未调用模型 |

## 执行与结果

执行命令：`python3 e6/scripts/collect_e6.py --out work/e6-20261101-184121-241880273 --service-build-timeout 1200 --build-timeout 600`

采集结果为 `SUCCEEDED`。服务镜像 ID：`sha256:d55bff3dd21ddbe0af364b915bc7bf8004d506b3a53325d91cddcf0ffb88e743`。

E6 工作流证据校验通过，`passed=true`、`verified=true`、`workflow_succeeded=true`。Trace ID：`e6-b-c80ce316bee04e6a96a64e62541a16e1`；校验文件数：32；工作流镜像 ID：`sha256:80c1236d0ab2e4d1cbe50b60ed7834b50ef2ecb0a7bdbcc024aa4a27c00515d3`；候选 SHA-256：`e0a47332ae920e9372a583abd44a2d2841c9622e0ed736fbd98b79db6acdbd76`。

服务测试通过 40 个测试。采集清单包含 99 个条目，归档校验结果为 99 项匹配、无缺失、无多余、无哈希不匹配。

## 验证范围说明

本次工作流使用 E5 保存的候选证据进行离线一致性校验，工作流构建没有重新执行；服务镜像由本次 E6 采集流程构建。上述范围以采集结果和归档日志为准。

## 证据校验命令

`python3 e6/scripts/run_e6.py verify-evidence --run-dir e6/evidence/20261101-241880273-e6/collection/run`
