# B14 E2 已发布版本记录

核对日期：2026-09-25。

## 字节一致性修复（后续基线）

**下面记录的 `689539119e60afd4b224d3163d1ba292992baa95` 为历史 E2 基线，已知其产物导出会受到 Git 换行配置影响，后续配对应改用包含本修复的新提交。** 接口版本仍为 1.0，Schema、样例字段、manifest 校验值及产物 Git 原始内容均未修改。

本修复添加根目录 `.gitattributes`：

```gitattributes
/contracts/artifacts/** -text
```

新增 `validator/verify_git_export.py`，分别在 `core.autocrlf=true/false/input` 下调用 `git archive`，核验全部 19 份产物，并在临时解压目录运行契约套件。验证记录见 [产物字节修复](validation-artifact-bytes.md)。

本节随修复提交一起发布。为避免在提交中循环引用自身 SHA，完整的新基线 SHA 通过本次 Git 记录和给 A14 的发布回复提供。任何“HEAD/origin/main 等于旧基线”的下文描述均为原发布时的历史核对结果。

## 历史 E2 首次发布

| 项目 | 已核实信息 |
| --- | --- |
| 仓库 | https://github.com/dInG-yAnWen/DevOPs |
| 分支 | main |
| 已发布 E2 契约基线 SHA | `689539119e60afd4b224d3163d1ba292992baa95` |
| 提交说明 | E2 finished |
| Git 作者 | DingYanwen |
| Git 作者时间 | 2026-09-25T16:48:26+08:00 |
| 契约版本 | schema_version 1.0 |
| 固定版本入口 | [该提交的仓库快照](https://github.com/dInG-yAnWen/DevOPs/tree/689539119e60afd4b224d3163d1ba292992baa95) |

## 核对依据

本地 HEAD、origin/main 与实际远程查询结果一致：

```text
git ls-remote origin refs/heads/main
689539119e60afd4b224d3163d1ba292992baa95    refs/heads/main
```

该提交已包含统一契约、样例、产物、校验器、设计记录与 A14 回复存档。A14 可以使用以上完整 SHA 固定引用版本，不必再用只有 README 的初始提交 `81ebd88445604956f045b0479054eb24bec72477` 作为契约基线。

## 本次补录与基线的区别

以上 SHA 标识已发布的 E2 内容快照。这份版本记录及本轮状态补录是其后的工作区修改，不能声称它们已包含在该 SHA 内。本轮未自动再次 commit/push。后续提交这些文档会产生新 SHA，但不要求为了让文档引用自身而反复提交；可以继续以以上版本作为双方约定的契约基线。

## A14 版本与剩余事项

A14 仓库地址为 `https://github.com/oVLVo11/DevOps_A14.git`。目前已接收其 ZIP 和接口确认，尚未收到其指定的正式交付 commit SHA；请 A14 提供并确认用于配对的版本，不以猜测填入。

本记录证明 B14 GitHub 契约基线已发布，不代表个人贡献审阅、课程平台提交或 E3 真实运行已经完成。原始 A14 回复和过去验证记录保留当时状态，不改写历史原文。
