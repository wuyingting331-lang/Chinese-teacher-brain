# 完整批改报告数据流程修复

本轮暂停教学功能扩展，没有调整评分配置、分项尺度、目标分数规则或模型。仅修复响应接收、逐项验证、状态保留、版本隔离、统计、页面和导出。

## 已确认的根因及证据边界

本地真实API日志 `data/diagnostics/validation.jsonl` 的请求 `13d04a1922ff4aa98c42b6c5df256cd0` 显示：

- 2026-11-05 11:15:04（新加坡时间），评分概览有4个引文错误。
- 11:15:12，评分修复通过，overview为VALIDATED。
- 11:15:45，指导批次出现paragraphs[3]的SCHEMA_VALUE_ERROR；同时结构、布局、逐段、语言、词句、清单以及两个已取消综合栏目被整体标为SCHEMA_PARSE_ERROR。

**确认的问题一：SDK整包解析导致有效候选丢失。** 原ModelClient使用responses.parse，SDK在返回之前对整个响应运行Pydantic及自定义验证。一个P004对象的自定义验证失败，generate()就没有返回原JSON。外层捕获异常后把该批所有目标标失败，其他候选根本没有进入逐项校验。固定JSON测试已复现：同样的单段格式错误能让旧整包模型验证抛异常，而新流程保留其余5段、结构表及所有其他有效栏目。

**不能确认的细节：** 旧响应正文没有保存，日志只有SCHEMA_VALUE_ERROR及对象路径，没有验证消息。不能断定过去那次一定是拆段数量、内嵌换行、空示范或其他哪一条对象验证规则，也不能断言其他候选的引文和教学判断均有效。本轮的固定响应是独立复现，不冒充旧响应。

**确认的问题二：统计数的是错误路径，不是实际缺失段落。** 旧grouped_messages按paragraphs和paragraphs[3]两条路径显示“两处”，但实际没有任何已验证的逐段对象，页面因此六段都缺。现在统计来自真实有效paragraph_id与确认原文ID的差集，分别显示0/6、5/6等，不靠错误列表推算完成。

**确认的问题三：已取消栏目仍在必需字段集合。** 原FIELDS/SECTIONS直接从历史Report全部字段生成，content_summary/expression_summary虽然页面已经取消，仍参与请求、失败统计、修复及完整性判断。现已从当前响应契约及必需条件移除；历史内容保留读取，不要求模型补这些字段。

**确认的问题四：请求ID更新晚于SDK解析。** 旧代码只有responses.parse成功后才写last_request_id，解析异常可能沿用前次评分请求ID。现在接收HTTP响应后立即保存当前ID，再做JSON解码和业务验证；新日志同时记录返回状态、解析状态、有效数与最终完整性。

另外已通过测试复现并修复了列表位置关联、有效槽位被重复摄入覆盖、缺少状态清单的旧投影直接进入新修复等风险；不声称旧的那次响应一定也包含这些问题。

## 当前一致的数据契约

版本：`report-v7-flow-recovery`。版本写入Record.report_schema_version、partial_state.format_version及请求元数据。没有新增教学字段。

| 用户栏目 | 生成字段 | 校验要点 | 存储与渲染 |
|---|---|---|---|
| 得分与整体评价 | overview | 分项、总和、范围不变；Evidence精确逐字对应 | slots.overview → Report.overview → overview/评分依据 |
| 结构与详略建议 | structure_overview、structure | 布局文字非空；有效结构条目、真实段落ID、动作和安排完整 | 对应标量/条目槽位 → structure表 |
| 逐段修改指导 | paragraphs | 按paragraph_id关联；覆盖全部原段；实际示范数组及既有字段规则 | 每个槽位绑定item_id=P001等 → 按原文顺序渲染 |
| 语言修改表 | language | 条目结构、类型、引用精确匹配 | language条目槽位 → 语言表 |
| 词句提升 | expressions | 词语来源、引用/新拟分类、段落引用 | expressions条目槽位 → 词句区 |
| 二稿执行清单 | tasks | 3—5项，标题和实际段落引用 | tasks条目槽位 → 概览引用及清单 |
| 图意核对（适用时） | picture_alignment | 有确认图意才要求对应评价与精确确认文字 | 单独槽位 → 评分依据 |

language/expressions只有模型明确返回且通过验证的空列表，才表示该栏没有额外条目；缺字段不会自动补[]。结构、布局、逐段和清单缺失不能靠默认文字、空数组或错误列表为空判完成。

当前请求不再包含两个已取消综合栏目。历史JSON仍可保留原字段和旧诊断，但这些不阻止当前报告完整，也不会作为新修复目标。

## 响应、保留与修复

1. 沿用同一配置模型，以responses.create取得响应；JSON Schema仍启用strict，store=False、SDK网络自动重试仍为0。
2. 分别识别completed、incomplete、refusal、无效JSON及请求失败。记录当前API请求ID，不把这些统一伪装成普通字段错误。
3. 完整JSON解码后逐栏目、逐条目验证，不先对整包运行会丢掉其他候选的模型验证。
4. paragraphs先按paragraph_id建立对应，不以返回列表的位置猜测。乱序可正确对应；缺失或重复ID定位到具体段落。
5. 每个错误保留section_id、path、item_id、paragraph_id和code。有效条目保留；失败更新不得覆盖已验证槽位。
6. 只修复失败目标。当前严格修复响应必须返回目标键，不能拿旧schema整段数组按位置混入。
7. 显式换行可以无损转换成真实段落数组；没有换行时不猜分段。不会修改学生原文或模糊匹配引文。
8. 完成状态由所有当前必需槽位及实际段落覆盖计算，不仅检查错误列表。失败时partial_sections也保留同栏已验证条目，partial_state为修复的权威状态。

旧版部分记录仅可兼容阅读。进入新生成时先在 `data/legacy_snapshots/`独立备份，只允许重新核验通过的原评分作为新流程起点；其余旧指导不直接混入新修复。已验证评分不改写，原记录不覆盖。只有裸partial_sections投影、没有schema和条目状态的结果，不能直接当作当前可修复状态。

## 离线复现与界面验证

新增测试走实际SDK适配器边界：模拟responses.create返回JSON，而不是仅返回已经构造成功的模型对象。

- 完整当前契约固定响应：全篇布局、6项结构建议、P001—P006、语言、词句和清单均显示。
- P004单段格式失败：保留5段及其他栏目，页面/导出显示5/6及P004。
- P004的一条语言引用失败：仅该条失败，其他语言条目与6段指导保留；精确修复后合并。
- 局部修复失败或试图额外改分：有效内容与原评分不变。
- 0段有效时显示0/6，不能再显示仅“两处”代替六段缺失。
- 乱序按ID对应；输入版本改变时请求前拒绝混入。
- 旧记录可读、明确适配；取消栏目的失败槽位不触发API请求、不阻止完成。
- 页面与Markdown同目录、同数据、同缺失统计；历史部分记录可保存再打开。
- 返回拒绝、截断/未完成、无效JSON、网络失败分别记录；不输出密钥、异常正文或原文到诊断日志。

最终离线验证：Python 3.12.16，**118项测试通过**。覆盖实际SDK响应边界、所要求的完整/单项失败/修复成功/修复失败/历史记录/输入更改/页面导出一致性，并保留既有评分及引用校验测试。`python -m compileall -q app.py teacher tests scripts`通过。

## 有界真实联调结果

已经完成，使用本地原配置模型 **gpt-4.1**，没有更换模型。材料是人工匿名六段测试作文，不是用户原27分作文。固定响应和28分测试占位值没有发送给模型，也没有作为评分起点；请求不带36分目标或参考样本数值。

实际调用 **1次完整生成、0次修复**，没有使用剩余预算。返回状态completed，JSON解码json_decoded，业务验证complete。

| 项目 | 实际有效数 |
|---|---:|
| 内容/表达/总分 | 11/20、10/20、21/40 |
| 全篇布局判断 | 有 |
| 结构建议 | 6项 |
| 逐段指导 | 6/6段 |
| 语言修改 | 5项 |
| 词句提升 | 3项 |
| 执行清单 | 4项 |

真实返回已重新载入AppTest，确认六段详细点评实际显示、没有缺失点评占位，所有必需栏目完整。该21分是测试稿真实返回，不是对原27分稿的重新评分；缺少原稿与旧响应，不能作同稿评分比较或声称已重放原请求。

联调材料与记录：

- `data/integration/flow-recovery/result.json`：请求数、状态、分项、计数、最终完整性及UI检查。
- `data/integration/flow-recovery/record.json`：真实返回的已验证记录。
- `data/integration/flow-recovery/report.md`：真实返回的报告导出。
- `data/diagnostics/generation.jsonl`：仅状态和计数元数据，不含密钥、提示词或响应正文。

## 修改文件

核心：`teacher/client.py`、`teacher/report_flow.py`、`teacher/service.py`、`teacher/render.py`、`teacher/diagnostics.py`、`teacher/storage.py`、`teacher/validation.py`、`teacher/models.py`、`app.py`。提示词只同步版本、ID关联和取消栏目的契约，没有改变评分尺度。

新增：`teacher/report_contract.py`、`teacher/report_migration.py`、`tests/test_flow_recovery.py`、`scripts/verify_live_recovery.py`、本说明。原有测试按当前取消栏目和部分有效内容保留的要求同步调整；测试元数据仍隔离在临时目录。
