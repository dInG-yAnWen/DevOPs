# B14 E2 本地验证记录

日期：2026-09-25。环境：Windows，Codex 提供的 Python 3.12 运行时。工作目录：D:/Devops/DevOPs。

## 验证对象

统一 Schema、四类请求与响应、产物实际文件与 manifest、跨服务语义，以及本次 `.gitignore` 和 Git 未提交状态。

## 执行命令与结果

本机使用的解释器：

```powershell
& 'C:\Users\dingy\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' validator/build_fixtures.py
& 'C:\Users\dingy\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' validator/validate.py --suite
```

套件结果：

```text
Schema backend: offline subset (only keywords used by this contract)
PASS: 69 checks (schema=1, artifacts=19, valid=20, invalid=7, mutations=20, resolver=2)
```

| 验证层 | 检查数 | 结果与含义 |
| --- | --- | --- |
| Schema 已用规则检查 | 1 | 所有使用的关键字均受离线后端支持，引用存在，正则可编译 |
| 产物 | 19 | 文件可读、sha256 正确、元数据结构与 JSON 来源信息一致 |
| 正例 | 20 | 四类任务、各状态与错误响应通过 |
| 独立反例 JSON | 7 | 所有指定非法请求/结果被拒绝 |
| 运行时变异反例 | 20 | 覆盖默认限制、版本、越界目录、未知字段、baseline、报告、产物、超时/取消、候选接受与 delta |
| 解析器拒绝 | 2 | 未注册 URI 与路径穿越 URI 被拒绝 |

关键验收点：`job_type=ABC` 拒绝；删除 baseline 拒绝；REPAIR 报告混入 REDUNDANT 拒绝；baseline 配置和 MD 报告 commit 不匹配拒绝；检测正常发现 MD/RD 的 FULL_CHECK 仍通过 SUCCEEDED 校验；构建/验证非零退出码不能冒充 PASSED；修复重检未清除 MD 不能冒充接受。

## 校验实现与限制

优先使用可选依赖 jsonschema 4.26.0。当前环境原本未安装该库；经网络授权后官方源与 HTTPS 镜像下载仍出现 TLS 中断，因此本次使用仓库内 `schema_subset.py` 离线后端。

离线后端覆盖此 Schema 使用的 `$defs/$ref`、对象/数组/基础类型、required、additionalProperties、oneOf/anyOf/allOf、if/then、enum/const、pattern、字符串/数组长度与数值边界。遇到未支持关键字会直接失败。**它不是通用 Draft 2020-12 实现，也未替代官方 JSON Schema 一致性测试。** Schema 文件仍采用 Draft 2020-12 格式，其他环境安装 jsonschema 后可运行同一套件复核。

`validate.py` 另行验证跨字段与跨文件绑定。它不会执行命令、检出仓库、下载镜像、证明 patch 正确或访问真实 HTTP 服务；端点分派、幂等存储、状态迁移并发和真实超时取消目前是 E3 实现要求。

## Git 与交付检查

- `git diff --check`：通过；存在正常的 Git LF/CRLF 提示，无空白错误。
- `git check-ignore -v -- A14_预设决定说明.md`：命中根 `.gitignore` 中的精确规则。
- `git diff --cached --name-only`：空，未暂存。
- HEAD 保持 `81ebd88445604956f045b0479054eb24bec72477`。
- 仅保留工作区文件改动，未 commit、未 push。

A14 已提供接口接受回复和其本地验证记录，B14 已完成交付包兼容性复核，详见下节。真实服务联调、个人审阅和正式版本发布仍保留在 Backlog。

## 2026-09-25 A14 交付包复核

输入为用户提供的 `A14_E2_仓库交付包.zip`，来源校验值、回复原文与结果见 [协作记录](collaboration/交接确认.md) 和 [交接校验结果](collaboration/交接校验结果.json)。

本次直接读取 ZIP 内 JSON/产物，用 B14 本地校验器检查 A14 样例，并比较 JSON Schema 与文件原始字节；没有执行 A14 包内脚本。

- Schema：排除描述性 title 后，双方规则完全一致；B14 本次仅同步 Schema 和生成脚本中的标题状态。
- 产物：19 份 SHA-256 均正确，且与 B14 本地文件逐字节一致。
- 合法样例：20 份通过 B14 校验器。
- 非法样例：7 份被 B14 校验器拒绝。
- A14 自带验证记录中的 69 项通过属于 A14 提供的执行记录，已原文存档；与上述 B14 本次检查分开记录。

本次文档收尾未增加字段、修改错误码或样例。E2 1.0 不新增 baseline.build_commands_uri；历史命令内部存储属 A14 的 E3 待实现事项。E2 离线校验网络与 DRAFT 目标构建网络需求分开说明。

文档更新后使用 `python -B validator/validate.py --suite` 复核，仍为 69 项通过。另行检查全部本地 Markdown 链接、存档原文 hash、Schema 与生成脚本标题一致性，以及原样例/产物字节未变，均通过；Git HEAD 与暂存区保持不变。
