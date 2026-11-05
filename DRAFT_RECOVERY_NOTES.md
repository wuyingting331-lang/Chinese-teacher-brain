# 二稿流程修复记录

本轮只修改二稿流程；评分配置、模型及批改报告结构未变。

## 已确认的问题与证据

旧 `teacher/service.py::generate_draft` 把 SecondDraft 正文和 implementation 一起解析；任何一个字段失败都会丢弃整个对象。第二次调用仍请求完整 SecondDraft，而且没有把第一次正文发给修复请求。两次失败只抛出 `GenerationFailure(errors,{})`，没有保留有效正文。

旧 `app.py::run_operation` 在已有 report 时用同一条通用提示覆盖真实原因。旧流程没有二稿专属状态或响应诊断。工作区没有用户那次失败的原始二稿响应，因此不能确认过去那次的具体字段或错误类别。

没有发现旧代码要求 implementation 的引文各不相同，也没有发现字数、成语数量、目标分数门槛。旧 draft_errors 已将 draft_quote 与 draft.body 比较，并非与学生原文比较；此规则继续保留。

## 当前数据与校验流程

- ModelClient 保留响应状态、JSON解析状态；二稿通过 generate_raw 取得候选，再分开解析正文与说明。
- DraftBody 校验字段、非空正文、essay_version。人物、核心事件及结局保留要求由二稿专用提示明确约束，仍需人工核对，不用关键词规则假装完成语义验证。
- DraftNotes 校验任务号、主要内容任务说明覆盖、实际二稿精确连续引文。共用同一引文合法；不替模型修剪、拼接或填补引文。
- 失败项有 code/path/reason；例如 `DRAFT_QUOTE_MISMATCH` / `implementation[0].draft_quote`。
- Record.draft_state 与 report 分开保存；正文有效时只请求 DraftNotes。重试失败不改正文，不改 report；成功清除旧错误和失败候选。
- 二稿专用 DRAFT_SYSTEM 区分原文 Evidence、改写正文和二稿证据，不复用整份报告生成系统指令。说明修复只发送已验证正文、同一组任务和错误，不发送原文片段及旧示范，避免证据来源混淆。
- 新拟细节、可选新增情节保留在正文对象中；不以新细节为原文证据。
- 页面区分正文有效但说明未完成、未验证草稿和完整二稿；显示具体原因、技术路径与对应重试按钮。失败候选明确标为未通过，不作为落实证据。有效正文可以单独下载；Markdown批改报告同步标注说明未完成。
- data/diagnostics/draft.jsonl 只保存错误类别/路径/原因及响应元数据，不记录密钥、提示词、正文。正文和候选只在用户记录/备份中保存。

## 修改文件

`teacher/draft_flow.py`（新增）、`teacher/service.py`、`teacher/models.py`、`teacher/prompts.py`、`teacher/render.py`、`app.py`、`tests/test_draft_recovery.py`（新增）、`scripts/verify_live_draft.py`（新增）。

## 离线验证

Python 3.12 环境：125项测试通过；compileall通过。新增7项覆盖正常二稿、同段共用证据、证据不存在、正文/说明分离、缺失说明字段、仅说明修复与清错、未完成响应分类、真实ModelClient的模拟SDK边界及AppTest实际显示。

还将真实联调保存记录离线送入AppTest：异常0、说明失败提示4条、有效正文实际显示，未将其冒充完整二稿。

## 真实联调结果及限制

2026-11-05，使用原配置 gpt-4.1；材料为上轮已保存的匿名合成六段作文及真实生成的报告，不是用户原来27分作文。

严格执行1次完整二稿生成和1次说明修复，合计2次；没有第三次请求。两次响应均 completed、JSON均 json_decoded。正文通过结构和版本校验并保留，报告内容未变。说明修复后仍有4条 DRAFT_QUOTE_MISMATCH，路径为 implementation[0..3].draft_quote，因此最终完整二稿状态为 false，未宣称成功。

这证明了说明证据与正文不一致的实际失败类别；当时未保存候选引文，不能进一步声称属于标点差异、省略号或误引原文中的某一种。之后增加了失败候选保存及来源收窄；最新提示词/收窄请求仅经过离线验证，未突破预算再次调用API。

结果：`data/integration/draft-recovery/result.json`；保留正文与错误：`data/integration/draft-recovery/record.json`。
