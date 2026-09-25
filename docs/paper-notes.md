# B14 E2 论文与接口依据

本说明依据用户提供的四篇本地 PDF 及 E2 课件，聚焦接口所需的语义。未用论文中的性能指标宣称本仓库实现效果。页码按 PDF 页序；本仓库未复制论文全文。

| 来源 | 已核对内容 | 对本包的影响 |
| --- | --- | --- |
| `_ICSE_2026__Dockerfile_auto_generation.pdf`，§3、§3.1–3.2，PDF 3–5 页，Figure 4 | DRAFT 使用项目上下文生成初始 Dockerfile，执行后定位构建错误，按错误/上下文产生候选并迭代；项目在镜像中成功构建是成功判据 | DRAFT 输入固定源码与要求，保留逐轮修改、选择理由及日志；课件进一步要求 verify_command |
| `_TSE__BuildChecker.pdf`，摘要、§4，PDF 1、4–7 页 | 构建执行与声明模型用于发现 Make 依赖错误 | 全量服务输出实际/声明图、MD/RD 与定位证据；B14 不实现 A14 算法 |
| `_ISSTA_2024__Detecting_Build_Dependency_Error.pdf`，摘要，PDF 1 页 | EChecker 根据新提交中预处理指令和 Makefile 的变化更新实际依赖，尽可能避免 clean build | baseline 必须绑定旧提交和配置，结果返回当前图和发现变化 |
| `_ASE_2025__Auto_fix_missing_dependency_errors.pdf`，§II–III，PDF 3–5 页 | MDFixer 根据声明图识别依赖声明风格并生成相同风格的修复；风格包括原子依赖、宏、混合 | REPAIR 保留风格解释；只处理 MD；patch 接受还需课件要求的 build/test/recheck |

## 论文、课程与本组契约设计的区别

- 论文给出算法和概念，并未定义本仓库 HTTP 端点、Job JSON 或 artifact:// 协议。
- 课件第 19–24 页给出课程接口的主要输入输出、状态和来源约束。
- 3 次/1800 秒、端点与部分错误码来自已发给 A14 的协作消息。
- error.category、24 小时幂等保留、MD-only URI、manifest、严格额外字段策略等属于 B14 起草的契约设计；A14 已在 2026-09-25 回复接受 E2 1.0，依据见 [协作记录](collaboration/交接确认.md)。这些约定不是论文定义。

E2 只完成契约与样例。DRAFT 的真实生成策略、模型选择及调用费用不在本次实现范围；MDFixer 的声明图分析和真实候选选择也尚未实现。
