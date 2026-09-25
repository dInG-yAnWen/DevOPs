# ADR-003：区分检测发现、目标未达成与系统异常

- 日期：2026-09-25
- 状态：A14 已接受 E2 1.0，回复已记录；B14 契约基线已发布，见 [版本记录](../release.md)
- 责任：B14 DRAFT/MDFixer 负责人、A14 检测负责人

## Context

原讨论曾把正常业务结果与正常失败合并，用户明确纠正：FULL_CHECK 发现 MD/RD 是正常产出；DRAFT 达到迭代上限仍无法生成环境是任务自身目标未达成；工具崩溃又是另一回事。课件明确第一类应 SUCCEEDED，但未唯一规定搜索不到解时的编码。

## Decision

- 正常检测完成：SUCCEEDED，error=null，MD/RD 在 ERROR_REPORT.findings。
- 目标未达成：FAILED + error.category=GOAL_UNMET。DRAFT 保留逐轮记录；REPAIR 保留拒绝候选与原因。
- 系统异常：FAILED + SYSTEM；总超时使用 TIMED_OUT/EXEC_4002。
- 主动取消：CANCELLED/EXEC_4004 + CONTROL。
- 输入不合法：HTTP 4xx / INPUT 类，不创建 Job。

沿用原消息中 ENV_3002/EXEC_4003 等错误码，使用 category 区分受控失败与设施/执行异常；新增 REPAIR_6001 表示所有候选失败。没有采用对话中出现过的另一套描述性错误码。

REPAIR 只消费非空 MD-only 报告，A14 负责过滤并保留来源。候选 patch 先在隔离工作树应用，然后构建、测试、重检。所有目标 MD 消失且三项验证通过才 ACCEPTED；单个候选拒绝是正常过程，不直接等于系统异常。B14 汇总候选决策，A14 提供重检能力。

## Alternatives

- 搜索结束即 SUCCEEDED + NO_SOLUTION：能表达算法执行完整，但调用方更容易误当成可用环境/修复已产生。
- 所有失败共用 SYSTEM：无法区分继续调整策略还是修复执行设施。
- 检测 MD 即 FAILED：违背课件与用户明确语义。
- 生成 patch 即接受：缺少构建与重检依据，不能证明修复有效。

## Consequences

HTTP 200 的查询可能返回 FAILED Job，调用方必须检查 status 和 category。受控失败保留可诊断证据；暂不实现自动重复提交。REPAIR 成功示例包含模拟验证数据，真正的三项检查仍由 E3 实现。

## Evidence

full_result、draft_goal_unmet、draft_failed、draft_timed_out、draft_cancelled、repair_goal_unmet 样例；false_success、repair_contains_rd 和候选接受条件反例。

2026-09-25 A14 回复明确接受正常 MD/RD 与 GOAL_UNMET/SYSTEM/INPUT/CONTROL 分类，并承诺提供 MD-only 报告和 E3 候选重检结果。回复原文及交接检查见 [协作记录](../collaboration/交接确认.md)。
