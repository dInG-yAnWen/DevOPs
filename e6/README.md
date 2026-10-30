# E6 DRAFT 两轮构建 CLI

`auto-build` 自动执行初始构建、已保存候选构建、按本次镜像 ID 运行验证。使用 Python 标准库；真实构建需要 Linux、Docker CLI 和可用的 Docker daemon。候选是 E5 已保存的环境适配版本，本命令不调用模型 API。

## 使用

在仓库根目录执行，输出目录必须尚不存在：

```bash
python3 e6/scripts/run_e6.py auto-build \
  --fixture fixtures/draft \
  --candidate e6/candidates/context-mirror/Dockerfile \
  --provenance e6/candidates/context-mirror/provenance.json \
  --out work/e6-run-01 --timeout 600 --verify-timeout 30
python3 e6/scripts/run_e6.py verify-evidence --run-dir work/e6-run-01
```

服务包入口等价于 `PYTHONPATH=services/draft python3 -m draft auto-build ...`。`version` 和 E4 `smoke` 入口继续保留。

两轮构建均使用 `--no-cache`；基础镜像摘要不变，仍可能需要访问镜像仓库及 apt 软件源。初始构建必须实际到达 `RUN make`，出现缺 make 与命令退出127，不能用网络失败替代。候选仅允许增加指定构建依赖及既有的软件源适配；工作目录、源码复制、编译和启动命令保持一致。

候选构建成功后由 `--iidfile` 取得 image ID，再检查并运行同一 ID。程序容器禁网、限制1核/256 MiB/64进程；stdout 须精确为 `hello E3\n` 且退出0。运行完成或超时均清理本轮命名容器并检查其已不存在。

## 在服务容器内执行

完整采集入口会构建独立服务镜像、运行服务测试、执行一次真实工作流并保存环境、源码哈希及全部原始日志：

```bash
python3 e6/scripts/collect_e6.py --out work/e6-collection-01
python3 e6/scripts/run_e6.py verify-evidence --run-dir work/e6-collection-01/run
```

采集入口要求源代码已提交且 Git 工作区干净。结果保存在 Git 忽略的 `work/` 下；失败目录同样保留。`COLLECTION_SHA256SUMS.json` 覆盖采集目录内的实际文件，内层 `run/SHA256SUMS.json` 单独覆盖两轮构建证据。

下列命令使用独立 E6 镜像名称；仓库只读挂载，结果写入独立目录。命令在本组 Linux 云主机的本人目录执行：

```bash
mkdir -p work/e6-service-01
docker build --progress=plain -f services/draft/Dockerfile \
  -t b14-e6-241880284:local --iidfile work/e6-service-01/service-image-id.txt .
service_id=$(cat work/e6-service-01/service-image-id.txt)
docker run --rm --user "$(id -u):$(id -g)" \
  --env HOME=/tmp \
  --group-add "$(stat -c %g /var/run/docker.sock)" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD:/workspace:ro" -v "$PWD/work/e6-service-01:/evidence" \
  "$service_id" python3 -m draft auto-build \
  --fixture /workspace/fixtures/draft \
  --candidate /workspace/e6/candidates/context-mirror/Dockerfile \
  --provenance /workspace/e6/candidates/context-mirror/provenance.json \
  --out /evidence/run --timeout 600 --verify-timeout 30
python3 e6/scripts/run_e6.py verify-evidence --run-dir work/e6-service-01/run
```

## 产物和离线校验

每轮保存输入快照、两份 Dockerfile、修复 diff、候选来源、完整命令及原始 stdout/stderr、退出码/超时、镜像 ID/inspect、运行与清理证据、`result.json` 和 `SHA256SUMS.json`。目录封存后不修改；继续试验使用新目录。

`verify-evidence` 核对完整文件集合及哈希，并检查原始日志、命令与 image ID 的对应关系。它不重新构建，故不要求原镜像仍存在。CLI 仅在成功工作流且证据一致时退出0；完整保存的失败结果仍返回非零。

单元测试：

```bash
PYTHONPATH=services/draft python3 -m pytest services/draft/tests
python3 validator/validate.py --suite
```

本阶段是教学小样例的已保存候选回放，没有实现模型自动生成循环或完整论文项目基准。E7 的真实故障场景矩阵、CI 和合并门禁另行开展。E6 独立运行不依赖 A14 接口；组员的 E5 记录可在其分支继续完成。

## 参考范围

流程和验收字段参考课程附件 `DevOps_1020_Student_Cloud/labs/B-draft/services/draft/draft/autobuild.py`、`scripts/verify_e6_b_evidence.py` 与 `docs/03_B轨道操作指南.md` §4。当前实现独立适配本仓已固定摘要的初始文件，并采用严格的候选约束、同镜像运行、原始字节留存和清理核验。候选来源保存在 `candidates/context-mirror/provenance.json`。
