# E2 产物 Git 导出字节一致性修复

日期：2026-09-25。问题来源：A14 核验原 E2 基线时发现产物摘要不一致。

## 复现与原因

在原提交 `689539119e60afd4b224d3163d1ba292992baa95` 和修复前 HEAD `09fb3ec31fca5dd537398ec502833c6ee34eb381` 上，当前 Windows Git 的 `core.autocrlf=true` 会使 ZIP 导出后的 19 份产物与 manifest 均不匹配。

本机进一步按原始字节检查 Dockerfile：

| 来源 | 字节数 | SHA-256 |
| --- | --- | --- |
| Git blob / 本地工作区，LF | 138 | `1f8fa15049a61fe49dfd5befeb980dc4c749da88906ae558150156acd5b52ba5` |
| 修复前 `git archive`，CRLF | 144 | `333674d0286d38d31fb6f002ba3d29099637ebec3b93d5771512311b6bb4952f` |

manifest 对应第一行。字节差异由导出端的换行转换造成，Git blob 内容完整。修复保留原 manifest 摘要与协议字段。

## 修复

根 `.gitattributes` 增加 `/contracts/artifacts/** -text`。Git 对这些摘要敏感文件保持原字节，生成器仍以 `write_bytes` 写入产物。添加独立 Git 导出回归检查，不改动原 69 项契约套件。

## 复核方式

```sh
python validator/verify_git_export.py --ref HEAD
```

脚本依次设置 core.autocrlf=true、false、input，导出指定 Git 提交/树，逐份核对 manifest 的 SHA-256，再在新的临时目录执行 `validator/validate.py --suite`。解压后校验独立读取导出包中的 manifest 和文件，不依赖开发者工作区。

旧提交回归检查预期失败，且实际首先报告 19 份不匹配。

提交前对原 HEAD 使用 `git archive --worktree-attributes` 读取新工作区字节保护规则，在 true/false/input 三种配置下均得到 19/19 摘要一致；每个临时解压目录中的 69 项契约检查也全部通过。该结果对应工作区属性规则的预验证。修复已包含在 `ef50c0f6a64ce74d6f2cca5a9b968aedbb0b5856`；普通导出的复核入口为上面的 `verify_git_export.py --ref HEAD`。

## 范围

本项修复范围为 E2 产物传递的字节稳定性。E3 构建结果另见 E3 运行记录；A14 确认与版本见 [E2 交接记录](collaboration/交接确认.md) 及 [E3/E4 交接记录](collaboration/E3E4_交接记录_20261008.md)。
