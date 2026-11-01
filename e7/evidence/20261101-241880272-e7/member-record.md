# E7 个人复跑记录（241880272）

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 姓名 / 学号 | 杨王旭 / 241880272 |
| 小组 / 轨道 | B14 / B（DRAFT） |
| 服务器克隆目录 | `/root/241880272/draft` |
| 分支 / 运行时提交 | `e7-validation` / `3874f0f3825a59204182a4bcdafc9ad9660ae63c` |
| 候选来源 | E5 已保存的环境适配候选 `context-mirror`（回放，`model_call_in_e7: false`） |
| 候选 SHA256 | `e0a47332ae920e9372a583abd44a2d2841c9622e0ed736fbd98b79db6acdbd76` |
| 证据目录 | `e7/evidence/20261101-241880272-e7/` |

## 执行命令

```bash
python3 e7/scripts/run_e7.py quality-gate \
  --fixture fixtures/draft \
  --candidate e6/candidates/context-mirror/Dockerfile \
  --provenance e6/candidates/context-mirror/provenance.json \
  --out work/e7-20261101-224933-recheck --build-timeout 600
python3 e7/scripts/run_e7.py verify-gate --run-dir work/e7-20261101-224933-recheck
python3 -m unittest discover -s e7/tests -v
```

服务测试在 `b14-e7-service:17cb93b65bb04426a69470777fa97e05` 镜像内执行。

## 结果

| 场景 | 期望 | 实际 | 结论 |
| --- | --- | --- | --- |
| success | SUCCEEDED | SUCCEEDED | 通过 |
| wrong-output | FAILED | FAILED | 通过 |
| invalid-candidate | 构建前拒绝 | PREFLIGHT_REJECTED | 通过 |
| build-failed | FAILED | FAILED | 通过 |
| runtime-timeout | TIMED_OUT + 清理 | TIMED_OUT | 通过 |
| runtime-nonzero | FAILED | FAILED（退出 23） | 通过 |

| 检查项 | 实际结果 |
| --- | --- |
| 采集器单测 | 7 项通过 |
| 服务镜像测试 | 68 项通过 |
| 门禁总体 | `status=PASS`，`passed=true`，`complete=true`，6/6 |
| 证据自检 | `verify-gate` 退出 0，236 个文件 |
| 超时启动标记 | stdout 首行为 `E7_TIMEOUT_STARTED` |
| 超时容器清理 | `cleanup-inspect` 输出 `[]` |

## 证据清单

- `gate/`：本次六场景门禁的完整原始证据，含各场景输入副本、故障注入 diff、两轮 Dockerfile、构建与运行日志、镜像 ID、清理记录、`gate-result.json`、`results.csv` 与 `SHA256SUMS.json`。
- `verify-gate.json`：对归档副本执行只读校验的输出。
- `collector-tests.txt`、`service-tests.txt`：采集器单测与服务镜像测试输出。
- `source-revision.txt`、`git-identity.txt`：运行时提交与本地 Git 身份。
- `SHA256SUMS.txt`：本目录文件的 SHA-256 清单。

## 边界

- 本次六场景门禁在宿主机 Python 3.10 + Docker CLI 上直接运行（E7 README 允许的非容器入口）；服务测试在 E7 服务镜像内执行。
- 候选为 E5 已保存文件的回放，E7 未调用模型。
- 复跑耗时约 32 分钟，主要因每个场景 `--no-cache` 重建依赖且 apt 下载偏慢，不是代码缺陷。
- GitHub Actions 的运行链接、artifact、实际分支保护配置、合并拒绝与最终合并记录仍未取得，采集信息标记 `github_proof=false`。
- 未修改 E7 实现、候选或测试；实验报告与验收 CSV 待 E5–E7 全部完成后统一整理。
