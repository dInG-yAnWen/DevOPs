# E6 个人复跑记录（241880272）

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 姓名 / 学号 | 杨王旭 / 241880272 |
| 小组 / 轨道 | B14 / B（DRAFT） |
| 服务器克隆目录 | `/root/241880272/draft` |
| 分支 | `e6-mvp` |
| 运行时提交 | `d7154b374c9b422c99226f937701f576fb6b1532` |
| 候选来源 | E5 已保存的环境适配候选 `context-mirror`（`REPLAY_EXISTING_ENVIRONMENT_ADAPTATION`） |
| 候选 SHA256 | `e0a47332ae920e9372a583abd44a2d2841c9622e0ed736fbd98b79db6acdbd76` |
| 证据目录 | `e6/evidence/20261030-241880272-e6/` |

## 执行命令

```bash
python3 e6/scripts/run_e6.py auto-build \
  --fixture fixtures/draft \
  --candidate e6/candidates/context-mirror/Dockerfile \
  --provenance e6/candidates/context-mirror/provenance.json \
  --out work/e6-20261030-212703-recheck --timeout 600 --verify-timeout 30
python3 e6/scripts/run_e6.py verify-evidence --run-dir work/e6-20261030-212703-recheck
```

## 结果

| 检查项 | 实际结果 |
| --- | --- |
| 第一轮基线构建 | 退出 1，`EXPECTED_MISSING_MAKE` |
| 第二轮候选构建 | 退出 0，`NONE` |
| 镜像 ID | `sha256:d3c741d7a7bd09db82690321c7d860c0be68686bbb8349ba4301dbf6701bc463` |
| 同镜像离线运行 | 退出 0，stdout 精确为 `hello E3\n`，`output_matches=true` |
| 容器清理 | `removal_confirmed` 与 `absence_confirmed` 均为 true |
| 证据自检 | `verified: true`，32 个文件 |
| 单元测试 | 服务镜像内 40 项通过 |

## 证据清单

- `run/`：本次 auto-build 的完整原始证据，含两轮 Dockerfile、构建日志、镜像 ID 与 inspect、同镜像运行输出、清理记录、`result.json`、`run.json` 与 `SHA256SUMS.json`。
- `verify-evidence.json`：对 `run/` 执行只读自检的输出。
- `unit-tests.txt`：服务镜像内 pytest 输出（40 项通过）。
- `source-revision.txt`、`git-identity.txt`：运行时提交与本地 Git 身份。
- `SHA256SUMS.txt`：本目录文件的 SHA-256 清单。

## 边界

- 本次为 E5 已保存候选回放，E6 未调用模型；不把回放写成新生成的候选。
- 镜像 ID 跨运行不可复现（apt 安装包未锁版本）；同一次运行内“构建→按该 ID 运行”成立。
- 候选的固定 FROM digest、`WORKDIR`、`COPY`、`RUN make`、`CMD` 均保持原样，仅增加构建依赖与软件源适配。
- 实验报告按安排留待 E5–E7 全部完成后统一整理。
