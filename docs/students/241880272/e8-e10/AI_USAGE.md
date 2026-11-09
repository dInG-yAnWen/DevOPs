# AI 使用记录

工具/模型/日期：

- 工具：Codex（命令行代理，SSH 操作 B14 云服务器）。
- 模型与平台：会话内未提供可核验的具体模型版本，不猜测型号。
- 日期：2026-11-09。

输入上下文与问题：

- 课程材料 `DevOps_E8_E10`（2026-10-31 版）：公共准备、B 轨道 E8/E9/E10 手册、个人测试示例、提交与归档要求。
- 本地 `可选的实现改动.md`：要求在 E8 报告失效判断中引入实际扫描输入的内容指纹。
- 仓库现状：`labs/e8e10/lab.py` 的 `scan()` 与 `patch()`，`labs/e8e10/test_profile.py` 的 7 项测试。

模型建议：

- 在 `scan()` 中记录 `.c`、`.h`、`Makefile` 的 SHA-256 到报告。
- 在 `patch()` 生成补丁前重新计算并比较，不一致返回 `STALE_REPORT`。
- 增加“同一 HEAD、内容变化”的独立测试，断言拒绝且源文件字节不变。

采纳/拒绝及理由：

- 采纳内容指纹方案：最小改动、无需额外 GCC 调用、能覆盖未提交的内容变化。
- 未采用“重新扫描并比较 findings”：会额外引入一次扫描副作用，且错误分类更复杂。
- 未采用“要求工作区干净”：会阻止课堂实验中的合法中间状态，覆盖范围也不足。

人工修改：

- 报告、ADR 与 AI 记录由用户在服务器上核对后保留；代码与测试改动全部体现在提交 `b0af06746eced5642e8cd2f93bbf59218eb16f58` 中，无其他手工改写。

实际验证命令/输入/结果：

```bash
python3 run_lab.py build
python3 run_lab.py e8 --track B --out work/e8-B-final-20261109-205844
python3 run_lab.py e9 --track B --out work/e9-B-final-20261109-205845
python3 run_lab.py e10 --track B --out work/e10-B-final-20261109-205845
docker run --rm --network none ... python3 -m unittest discover -s labs/e8e10 -p test_profile.py -v
```

- 环境镜像构建退出 0，镜像 ID `sha256:adf4237b8e2af5d10a338f64cb13560bc3781205eb8c2202771e8c1301e242c0`。
- E8/E9/E10 三阶段退出 0，证据在 `work/` 对应目录。
- 单元测试修改前 7 项、修改后 8 项，均 OK、退出 0。
- 内容指纹专项验证 `passed=true`（`work/e8-B-input-fingerprint-20261109-205832/verification.json`）。

未调用模型的部分：

- 三个实验的构建、扫描、补丁生成与验证全部由本地 Python/GCC/Make/Docker 实际执行，未调用模型 API。
- 课程参考实现来自材料；本人贡献为上述输入指纹校验、对应测试、三阶段实跑与报告整理。
