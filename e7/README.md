# E7 DRAFT 验证与 CI

本目录提供真实 Docker 场景门禁、离线证据校验和 GitHub Actions 工作流。候选均回放 E5 已保存的文件；测试中的源码变更是显式故障注入，不是模型生成结果。E5/E6 封存证据保持原始字节。

## 真实场景

|场景|受控输入与必要判断|
|---|---|
|success|原始 fixture；首轮缺 make，修复后同镜像运行输出精确 `hello E3\n`，退出0|
|wrong-output|将期望输出改错；正常程序输出须被判失败|
|invalid-candidate|改错候选 CMD；在构建前拒绝，不能产生构建证据|
|build-failed|只修改本场景 fixture 副本制造编译失败；候选构建失败后不运行程序|
|runtime-timeout|只修改 main.c 副本，输出启动标记后延迟10秒；5秒运行预算应超时，随后清理并确认容器不存在|
|runtime-nonzero|自主扩展：程序输出正确但退出23；仍必须失败，不能仅凭 stdout 判成功|

每个场景保留原始输入、实际副本、故障变更 diff、前后哈希、命令/退出码、完整 stdout/stderr 和 E6 工作流证据。负面场景的程序失败是预期行为；只有失败阶段和证据均正确，门禁才将该场景记为通过。基础镜像拉取或软件源故障不能代替目标故障。

运行预算包括 Docker 启动开销。超时场景必须先捕获程序启动标记；空输出的超时不能证明目标程序已经开始执行。新运行将5秒预算写入元数据，旧归档缺少该字段时仍按原1秒预算复验。

## 执行

在 Linux 云主机仓库根目录执行，输出目录必须尚不存在：

```bash
python3 e7/scripts/collect_e7.py --out work/e7-collection-01
python3 e7/scripts/run_e7.py verify-gate --run-dir work/e7-collection-01/gate
```

采集器构建独立服务镜像、验证镜像中的源码、运行服务测试和全部六个真实场景，保存环境、源码提交和哈希、服务镜像 ID 及原始日志。源码须已提交且工作区干净。默认回放 E6 的 Aliyun 软件源适配候选；CI 使用本目录 `candidates/debian/` 中的原始 Debian 源候选，两个来源各自留存，不把网络环境差异当成算法改进。

也可直接在已有 Python/Docker 环境运行服务 CLI：

```bash
python3 e7/scripts/run_e7.py quality-gate \
  --fixture fixtures/draft \
  --candidate e6/candidates/context-mirror/Dockerfile \
  --provenance e6/candidates/context-mirror/provenance.json \
  --out work/e7-gate-01 --build-timeout 600
```

`--case` 可重复指定场景用于排错。部分场景不构成完整 E7 门禁通过。`verify-gate` 只读核对封存文件、命令绑定、每个场景的实际行为和汇总结果，不重新执行 Docker。失败结果保留，重跑使用新目录。

## CI 与分支保护

`.github/workflows/e7-quality-gate.yml` 在 E7 分支及 main 的 push、main 的 PR 和手动触发时运行。必需检查名为 `e7-b-quality-gate`；Actions 依赖固定到经过核对的官方提交。失败时仍上传 `work/ci/`，保留14天，应及时下载备份。

完整 GitHub 验收还需正常、失败、修复通过三次运行链接及 artifact，main 的实际保护配置、失败合并请求的拒绝响应，以及最终成功合并记录。`ci/main-protection.template.json` 是配置模板；应用前须读取并保留仓库现有约束，并将必需检查绑定到实际 GitHub Actions App。模板文件和本地测试不能替代 GitHub 端验收。

失败演示只在独立分支增加错误的版本测试预期 `main(["version"]) == 1`；保存 CI 失败与合并拒绝后，将预期改回0。不要修改服务行为来迁就错误测试。合并尝试须绑定当前 PR head SHA，并先确认保护生效及该提交检查确实失败。

## 课程参考

流程参考附件 `DevOps_1020_Student_Cloud/labs/B-draft/scripts/run_e7_b_gate.py`、`.github/workflows/e7-quality-gate.yml`、`docs/03_B轨道操作指南.md` §5—6 和 `docs/04_GitHub_CI与合并门禁.md`。本仓使用更严格的 E6 Dockerfile 约束，因此通过各场景源码副本注入故障，保留固定构建与启动指令。
