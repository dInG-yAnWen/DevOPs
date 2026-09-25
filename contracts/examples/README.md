# E2 人工契约样例

这里的 JSON 用于说明与校验协议，不代表已经执行的服务。

- `valid/`：20 份合法协议对象，覆盖四类创建请求、202 受理、成功结果，DRAFT 全部状态与受控失败、REPAIR 候选全失败、HTTP 输入错误。
- `invalid/`：7 份应被拒绝的完整 JSON，覆盖未知类型、缺 baseline、短 SHA、配置不符、RD 混入修复报告、修复版本不符、成功结果矛盾。
- `../artifacts/`：可真实读取的人工文件样例；日志是模拟文本，JSON 报告含 MANUAL_FIXTURE 标识，镜像元数据为 available=false。
- `../artifact-manifest.json`：URI 与文件路径、内容校验值和来源的映射。

同一 job_id 在不同终态文件中代表**互斥的场景样例**，例如 draft_result 与 draft_goal_unmet 不能视为同一个 Job 曾经同时拥有的历史。QUEUED/RUNNING/SUCCEEDED 是可选成功路径，FAILED/TIMED_OUT/CANCELLED 是替代终态。

所有 example.invalid URL、40 位重复数字提交、重复字母镜像 digest 都是占位数据，不可直接用于真实构建或联调。C0/C1 分别用 40 个 1/2，目的是让版本匹配/不匹配规则可以验证。

读取、Schema 与语义校验示例：

```sh
python validator/validate.py --suite
python validator/validate.py contracts/examples/valid/full_result.json
python validator/validate.py contracts/examples/invalid/repair_contains_rd.json
```

第三条预期失败并退出 1，不表示校验器出错。若需修改契约与固定样例，同时修改 `validator/build_fixtures.py` 后重新生成、验收；修改生成脚本会覆盖受其管理的 Schema/样例文件，真实实验数据应另存目录。
