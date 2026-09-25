# DRAFT 样本：TinyGreeting（B14 E3）

课程 E3 B 组 DRAFT 样本，对应课件《E3 并行测试基线》第 30、31、32 页。
这是一个最小的 C/GNU Make 项目，用来验证 DRAFT 的两层成功判据：
编译通过（构建命令退出码 0、可执行文件生成）与功能验证（约定输出）。

## 源码快照

| 文件 | 作用 |
| --- | --- |
| `main.c` | 打印固定字符串 `hello E3` |
| `Makefile` | 目标 `hello`；`make test` 运行程序 |
| `Dockerfile.broken` | 故意缺少工具链的失败候选 |
| `Dockerfile.reference` | 人工参考修复，安装工具链后构建 |
| `docker_status.json` | Docker 未执行的原因、等价证据与补齐命令（本机无 Docker） |

## 构建与验证命令

```sh
make            # 构建；预期退出码 0，生成 ./hello
make test       # 或 ./hello；预期标准输出 "hello E3"，退出码 0
make clean      # 清理 main.o 与 hello
```

## 成功判据（两层）

1. 编译通过：`make` 退出码 0，且 `hello` 可执行文件确实生成，保留构建日志。
2. 功能验证：`./hello` 退出码 0，标准输出恰为 `hello E3`。

## 容器复现（需要 Docker，见交付说明的运行限制）

```sh
docker build -f Dockerfile.broken    -t b14-e3-draft-broken:20260925    .   # 预期失败，退出码非 0
docker build -f Dockerfile.reference -t b14-e3-draft-reference:20260925 .   # 预期成功，退出码 0
docker run --rm b14-e3-draft-reference:20260925                              # 预期输出 hello E3
docker images --no-trunc --format '{{.ID}}' b14-e3-draft-reference:20260925  # 记录镜像 ID
```

`docker build` 需要网络拉取 `python:3.13-slim` 并安装 `gcc/make/libc6-dev`。
