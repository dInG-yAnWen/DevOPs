# E2 产物 Git 导出字节一致性修复

日期：2026-09-25。来源：A14 核验原 E2 基线后，经用户转达发现产物摘要不一致。

## 复现与原因

在原提交 `689539119e60afd4b224d3163d1ba292992baa95` 和修复前 HEAD `09fb3ec31fca5dd537398ec502833c6ee34eb381` 上，当前 Windows Git 的 `core.autocrlf=true` 会使 ZIP 导出后的 19 份产物与 manifest 均不匹配。

本机进一步按原始字节检查 Dockerfile：

| 来源 | 字节数 | SHA-256 |
| --- | --- | --- |
| Git blob / 本地工作区，LF | 138 | `1f8fa15049a61fe49dfd5befeb980dc4c749da88906ae558150156acd5b52ba5` |
| 修复前 `git archive`，CRLF | 144 | `333674d0286d38d31fb6f002ba3d29099637ebec3b93d5771512311b6bb4952f` |

manifest 对应第一行。因此确认是换行转换造成的字节差异；在本次复现中转换发生于导出端，并非 Git blob 本身已损坏。无需重算 manifest 或改变协议字段。

## 修复

根 `.gitattributes` 增加 `/contracts/artifacts/** -text`。Git 对这些摘要敏感文件保持原字节，生成器仍以 `write_bytes` 写入产物。添加独立 Git 导出回归检查，不改动原 69 项契约套件。

## 复核方式

```sh
python validator/verify_git_export.py --ref HEAD
```

脚本依次设置 core.autocrlf=true、false、input，导出指定 Git 提交/树，逐份核对 manifest 的 SHA-256，再在新的临时目录执行 `validator/validate.py --suite`。解压后校验独立读取导出包中的 manifest 和文件，不依赖开发者工作区。

旧提交回归检查预期失败，且实际首先报告 19 份不匹配。

提交前先对原 HEAD 使用 `git archive --worktree-attributes` 读取新工作区字节保护规则，在 true/false/input 三种配置下均得到 19/19 摘要一致；每个临时解压目录中的 69 项契约检查也全部通过。这是新属性规则的预验证，不冒充已发布提交的验证。提交后还需用上面的普通导出命令确认新基线。

## 范围

本次只修复 E2 产物传递的字节稳定性，不重新运行 E3 构建、不修改 A14 原回复、不代替 A14 对新基线的独立核验。A14 新的正式交付 SHA 仍待其回复。
