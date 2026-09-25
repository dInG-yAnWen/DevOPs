# DevOPs · B14（E2 + E3）

B14 负责 DRAFT 环境生成与 MDFixer（REPAIR），配对组为 A14。

主交付文件：[B14 E2 交付说明](docs/B14_E2交付说明.md)。包括需求、接口、验收结果和未决事项索引。

当前版本为 **A14 已接受的 E2 1.0 契约交付包**。2026-09-25 已收到回复并完成 B14 本地交接校验，详见 [协作确认与交接记录](docs/collaboration/交接确认.md)。示例仍为人工协议数据，不代表真实构建、算法复现或真实服务联调结果。B14 已 commit/push，已发布契约基线为 `689539119e60afd4b224d3163d1ba292992baa95`，详见 [版本记录](docs/release.md)。个人贡献审阅和课程平台提交仍待完成；本轮版本信息补录留在工作区。

E3 自备基线见 [B14 E3 交付说明](e3/B14_E3交付说明.md) 与 [E3 真实运行记录](e3/验证记录_20260925.md)：DRAFT 样本（TinyGreeting，真实构建/验证 + 失败候选 + 参考 Dockerfile）与 MDFixer 样本（缺 `config.h` 的固定 MD 报告 + 参考补丁 + 修复前行为证据），可一键复现。本机无 Docker/网络，未产生真实镜像 ID，已如实记录。

## 文件入口

- [统一 JSON Schema](contracts/task.schema.json)：四类请求、Job、受理响应、错误响应及产物内容定义。
- [接口契约](contracts/API.md)：端点、字段、状态、错误、默认值、幂等与跨服务检查。
- [请求和响应样例](contracts/examples/valid/) 与 [非法样例](contracts/examples/invalid/)。
- [产物索引](contracts/artifact-manifest.json) 与 [人工产物样例](contracts/artifacts/)。
- [E3 测试基线](e3/README.md)：DRAFT / MDFixer 样本、执行脚本与真实证据。
- [Backlog](docs/backlog.md)、[ADR](docs/adr/)、[AI 使用记录](docs/AI_USAGE.md)、[验证记录](docs/validation.md)。

## 复现契约验收

需要 Python 3.10+，无需网络即可校验。在仓库根目录运行：

```sh
python validator/validate.py --suite
python validator/validate.py contracts/examples/valid/draft_request.json
python validator/validate.py --read-artifact artifact://b14-draft/job-draft01/Dockerfile
```

Windows 可将 `python` 替换为可用的 Python 解释器路径或 `py -3`。默认离线后端支持本契约实际使用的 Schema 关键字，遇到未知关键字直接报错。可选执行 `python -m pip install -r validator/requirements.txt` 使用完整 `jsonschema` 后端；如果将依赖安装到 `.deps`，校验器会自动加载该目录。

校验器仅解析 JSON 和读取本地产物，不执行 JSON 中的 shell 命令、不下载镜像、不调用 LLM。默认 `--suite` 验证 Schema、正反样例、跨字段语义和本地产物完整性。URI 读取方式详见接口契约。
