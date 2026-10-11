# E4 提交记录（B 组）

## 1. 基本信息

| 项目 | 内容 |
| --- | --- |
| 学号 | 241880272 |
| 服务器上的克隆目录 | `/root/241880272/draft` |
| 本组远程仓库 | `https://github.com/dInG-yAnWen/DevOPs.git` |
| 运行那次的完整源码 SHA | `eb2c62c9a3222cbcb25a8bc204348ce91b3c9ba8` |
| 成功证据目录（绝对路径） | `/root/241880272/draft/work/20261007-193940/` |

## 2. make all 结果

| 检查项 | 结果 |
| --- | --- |
| 退出码 | **0** |
| 单测 | **4 passed**（`4 passed in 0.01s`） |
| 冒烟 | **passed = true** |
| 扫描 | **通过**（密钥检查：未发现问题） |

分步结论：

| 步骤 | 结论 |
| --- | --- |
| doctor 环境自检 | `problems: []`；Git 身份 `241880272` / `241880272@localhost` |
| build 构建 | 成功；镜像 `e4-draft:241880272`，ID `sha256:741b514dea8286af2bc6e5ae0ade2ce5ebc0f40ffb8cb6f7ee312b27f70b6759`，架构 `amd64` |
| test 单测 | `4 passed in 0.01s` |
| smoke 冒烟 | `docker_server: 29.1.3`；`build_exit_code: 1`（样例预期失败）；`make_error_line: "#8 0.127 /bin/sh: 1: make: not found"`；`make_not_found: true`；`passed: true` |
| scan 密钥检查 | 密钥检查：未发现问题（文件 138 个，含 Git 历史，含镜像 `e4-draft:241880272`） |

工具链版本（来自 `toolchain.lock`）：

```text
git=1:2.47.3-0+deb13u1
docker-cli=Docker version 28.5.1, build e180ab8
python3=3.13.14
arch=amd64
pip:iniconfig==2.3.0
pip:packaging==26.3
pip:pluggy==1.6.0
pip:Pygments==2.21.0
pip:pytest==8.4.2
```

完整输出日志另存于 `/root/241880272/make-all.log`。

## 3. 证据目录文件清单

目录：`/root/241880272/draft/work/20261007-193940/`

| 文件 | 大小 | 用途 |
| --- | --- | --- |
| `env.json` | 891 B | 环境自检结果 |
| `build.log` | 3.9 KB | 构建日志 |
| `image.json` | 173 B | 镜像 ID 与架构 |
| `toolchain.lock` | 196 B | 工具链版本锁定 |
| `test.log` | 98 B | 单测输出 |
| `smoke.json` | 665 B | 冒烟结论 |
| `secret-scan.txt` | 99 B | 密钥扫描结果 |

## 4. 假 Key 检查日志路径

- 路径：`/root/241880272/draft/work/20261007-194311/secret-scan.txt`
- 该目录与成功证据目录 `work/20261007-193940/` 相互独立，不可混淆。
- 说明：假 Key 检查共执行两次扫描（第一次应报错、第二次应通过），两次写入同一时间戳目录，因此该文件保存的是**第二次通过**的结果（`密钥检查：未发现问题`）。第一次在写入 `leak-demo.txt` 后报出 2 处疑似泄露、`make scan` 返回 `Error 1`，该次输出未另存为文件。

## 5. 附：与另一名组员的对照

对照对象：学号 241880273，克隆目录 `/root/241880273/draft`，成功证据目录 `work/20261007-175642/`。

| 对照项 | 241880272（本记录） | 241880273 | 结论 |
| --- | --- | --- | --- |
| 源码 SHA | `eb2c62c9a3222cbcb25a8bc204348ce91b3c9ba8` | 同左 | 一致 |
| `toolchain.lock` | 见上 | 逐字相同 | 一致 |
| `test.log` | `4 passed in 0.01s` | 同左 | 一致 |
| `smoke.json` 结论 | `docker_server 29.1.3` / `build_exit_code 1` / `make_not_found true` / `passed true` | 同左 | 一致 |
| `secret-scan.txt` | 未发现问题（138 个文件） | 同左 | 一致 |
| 镜像 ID | `sha256:741b514d…b6759` | `sha256:a3fa0790…0274` | 不同（预期） |
| `build.log` 体积 | 3.9 KB | 3.6 KB | 不同（预期） |
| 证据目录时间戳 | `20261007-193940` | `20261007-175642` | 不同（预期） |

两份克隆取自同一模板提交，工具版本与预期结果一致；镜像 ID、日志体量与运行时间因构建缓存和执行时刻不同而有差异，符合 E4 预期。
