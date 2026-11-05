# chinese-teacher-brain

PSLE 普通华文作文评分与修改应用，面向小五、小六学生与家长。教学依据为根目录 `PSLE_Chinese_Project_Proposal.md` v1.0。当前支持文字正文、看图作文题目图片识别与人工确认；不支持学生手写正文 OCR。

默认采用**作文小老师参考评分 v1**：满分40，内容20、表达20，来源为用户报告的样本评分与批改，性质为教学参考、未提供经核实的官方评分细则。不显示整科AL等级，不声称采用MOE正式细则。旧无分项配置及历史报告保留；离线演示仍明确为固定样例。

## Windows PowerShell 运行

正常安装 Python 3.12 的机器：

```powershell
cd Chinese-teacher-brain
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m streamlit run app.py
```

本工作区系统登记的 Store Python 3.12 无法访问，已在忽略目录 `.runtime/` 准备独立 Python 3.12.16 及 `.venv312/`。**当前机器直接运行**：

```powershell
.\.venv312\Scripts\python -m streamlit run app.py
```

无需激活环境或修改 PowerShell 执行策略，打开终端给出的地址，通常为 http://localhost:8501 。没有密钥可通过侧栏“打开离线演示”查看报告。

## Streamlit Community Cloud 部署

部署入口为仓库根目录 `app.py`，分支建议 `main`；Advanced settings 选择 **Python 3.12**。平台安装根目录 `requirements.txt`，已固定经过本项目测试的5个运行时直接依赖。`requirements-dev.txt` 用于离线测试，`requirements-lock.txt` 是本地完整环境快照，不作为云端安装入口。不需要 `packages.txt` 或 Windows 系统依赖。

1. 将本项目推送到**独立的中文作文应用 GitHub 仓库**。提交 `app.py`、`teacher/`、`config/`、依赖文件、`.python-version`、`.streamlit/config.toml`、secrets示例及README；可一并提交合成测试和脚本。不要上传 `.env`、真实secrets、虚拟环境、`data/`、`uploads/`、`reports/`。
2. 在 Community Cloud 选择该仓库、`main` 和 `app.py`。华文使用独立网址，英文继续保留原有私有应用，不需要修改英文应用或仓库可见性。在 Advanced settings → Secrets 填写以下顶层TOML键（替换占位内容，不要加 `[openai]` 或 `[auth]` 分组）：

```toml
FAMILY_PASSWORD = "替换为家人共用的长随机密码"
OPENAI_API_KEY = "填入真实密钥"
OPENAI_MODEL = "gpt-4.1"
# 可选；省略时图片识别复用 OPENAI_MODEL。
# OPENAI_VISION_MODEL = "账户可用且支持图像和结构化输出的模型"
```

3. 发布后先用家庭密码登录，再打开离线演示检查页面；最后用匿名短文验证真实批改。模型需在账户中可用并支持 Responses 结构化输出；不要提交或截图展示真实密码及密钥。

官方说明：[部署入口与Python版本](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)、[云端Secrets配置](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)。`.python-version` 记录本地版本意图，不能代替部署界面选择Python版本。

部署准备验收：加入家庭登录后，138项离线测试通过（含登录阻断、尝试限制、退出清理、两个AppTest会话隔离、同图隔离、secrets读取）；离线Edge组件检查通过，确认图片解码与下载Blob的Unicode内容正确。此前本地依赖一致性及Python 3.12 / Linux x86_64依赖解析通过。尚未在真实Community Cloud创建应用，这些检查不替代部署后的验收。英文应用及仓库可见性保持不变；代码提交与推送只针对华文仓库。

**会话数据不是永久存储。** 应用每个浏览器会话使用独立、随机命名的系统临时目录，保存该会话的记录、图片、诊断和历史适配备份。不会扫描仓库的 `data/records` 或其他会话目录，不使用全局缓存保存学生资料。当前会话内可以保存、重新打开；新会话、断线重连或云端重启后不保证恢复。请及时下载JSON、Markdown并自行保留原图。JSON不包含图片；应用目前没有跨会话账户存储或上传JSON恢复入口。

本地网页也采用同样隔离方式；原有本地 `data/` 不删除、不自动导入网页。命令行工具无网页会话上下文时，仍可显式访问项目 `data/`，不要将该目录提交Git。临时目录不代表离开页面立即安全删除，实例回收前可能仍存在；没有将它作为永久云端档案。

## 家庭访问控制

公开的华文应用网址先显示家庭密码页。必须在 Streamlit Secrets 中设置顶层 `FAMILY_PASSWORD` 为非空字符串；缺失、空白或类型错误时阻止进入，离线演示也不能绕过。本地同样需要 `.streamlit/secrets.toml`；家庭密码不从 `.env` 或查询参数读取。示例文件故意留空，推荐自行生成至少16字符的独立随机密码，不复用API密钥。

密码使用 `hmac.compare_digest` 比较UTF-8字节；明文不保存在登录状态、记录或日志中。登录状态是服务端会话内的随机密钥HMAC标记，不放进网址或共享缓存；修改Secrets或服务重启后需重新登录。登录前不绑定业务目录、不加载评分配置或历史记录、不展示图片、下载或模型功能。

连续5次输错后，该会话暂停60秒；当前服务实例5分钟内累计20次失败时，所有未登录会话暂时限制尝试，直到失败计数滑出窗口。更换会话不会清除实例计数；实例重启会重置，多个实例之间不共享。这是家庭共用密码访问控制，不是独立账号、身份识别或完整的分布式防暴力系统。

侧栏“退出家庭登录”清空作文、图片关联、报告、待执行任务与登录状态，删除该会话创建的临时目录，清理该会话上传文件及旧媒体引用。其他会话不受影响。已经由家人下载或保存到浏览器外的文件无法收回；退出前需下载的资料请先备份。没有“记住登录”的长期cookie。

学生图片预览与下载使用随已登录页面传输的数据，在浏览器生成图片和Blob下载；不使用 `st.image` / `st.download_button` 为学生资料创建独立的公开 `/media` 地址。静态文件服务明确关闭。不存在将作文或报告放进跨会话缓存的逻辑。公开仓库只能包含代码、配置和合成测试；家庭密码不隐藏公开仓库代码，也不要把学生资料提交到Git。

## 配置

将 `.env.example` 复制为 `.env`，或将 `.streamlit/secrets.toml.example` 复制为 `.streamlit/secrets.toml`，填写：

- `FAMILY_PASSWORD`：必填家庭密码，只从 Streamlit Secrets 读取；空缺时锁定应用。
- `OPENAI_API_KEY`：有效密钥。
- `OPENAI_MODEL`：账户可用、支持 Responses 结构化输出的评分模型。
- `OPENAI_VISION_MODEL`：可选，支持图像输入及结构化输出的模型；未填写则复用评分模型。不要保留模型名称占位符。

API配置优先采用进程环境变量，其次 `.env`、Streamlit secrets。家庭密码例外，只读取Streamlit Secrets。更改后重启。真实评分发送作文及确认题目信息，图片识别发送当前题目图片给模型服务，通常产生费用；姓名可不填写。SDK 使用 `store=False`，这不等于对服务商数据处理政策作额外承诺。

报告请求使用Responses.create及strict JSON Schema，先取得JSON，再逐栏目、逐段运行Pydantic和业务校验；不再因一段自定义校验失败而丢弃整包候选。图像仍通过按顺序排列的多个input_image Base64数据URL传入模型。当前SDK路径和联调证据见 [FLOW_RECOVERY_NOTES.md](FLOW_RECOVERY_NOTES.md)。

## 作文使用流程

1. 填写题目、年级、题型、题目要求及稿次；姓名可选。正文每个真实段落换行，保留字词、标点，可用空行分隔。排版造成的硬换行需先人工整理。
2. 点击“确认原文”，检查独立保存的原文与段号，再点击“评分与批改”。
3. 查看评分、故事结构、逐段批改、语言修改、词句提升、综合意见及唯一二稿计划。
4. 需要时独立点击“生成示范二稿”；示范稿不代表学生独立完成，也不承诺考试分数。
5. 保存已确认记录，侧栏重新打开；可下载 Markdown 报告和 JSON 备份。

编辑题目、正文、元信息、题目图片或确认图意后，旧报告明确为旧版本，不会把旧分数视为新作文结果。重新确认会创建新记录；要保留旧报告请先保存旧记录。编辑未确认时保存／下载的是已确认旧版本，页面有明确提示。

评分与图片识别使用会话任务队列，执行前取出任务，期间禁用输入与提交按钮，rerun 不自行重复调用。评分完成后同版本评分按钮禁用。SDK不自动重试网络请求。新参考配置或设置修改目标时，先独立评分，再生成教学指导，基础操作最多3次请求（通常2次）；存在已确认同稿样例时，另作1次一致性检查，必要格式修复最多再1次。旧配置且不设目标、图片识别及二稿生成仍各最多2次请求。每次点击修复失败条目最多1次请求；重试一致性检查单独最多2次。请求与修复可能计费，网络、认证等失败不自动重试。

## 修改目标与教学指导

新建40分制作文默认可选36分修改目标，可调整或关闭。目标单独保存，仅用于修改计划，不改变原稿评分，不保证修改稿的考试分数。修改目标或评分配置后需重新确认；旧记录没有目标时保持未设置。没有正式评分表时明确标注教学参考及来源限制。

逐段点评保留本段作用、分类问题、意思重组、具体内容发展、词句融入、完整示范及修改理由。实际自然段用example_paragraphs数组保存，新拟细节明确标注。详细步骤与自查标准集中在对应段落；概览和可勾选执行清单只引用同一组短任务。好词好句区分原文已有和提升建议；已使用的表达引用逐段示范，不重复整段。

当前人工布局预览见 [reports/hierarchy_report_preview.md](reports/hierarchy_report_preview.md)，结构表见 [reports/story_structure_example.md](reports/story_structure_example.md)。原稿是合成文本，分数仅为界面测试占位，不是学生原稿评分或模型结果。组织与验证记录见 [REPORT_HIERARCHY_NOTES.md](REPORT_HIERARCHY_NOTES.md)。评分配置与样本核对历史见 [CALIBRATION_REVIEW_NOTES.md](CALIBRATION_REVIEW_NOTES.md)。

完整报告流程修复见 [FLOW_RECOVERY_NOTES.md](FLOW_RECOVERY_NOTES.md)：按paragraph_id保留有效指导，依据实际缺失段落显示0/6或5/6；取消的综合栏目不再参与请求和完成判断。当前schema为report-v7-flow-recovery，旧部分记录先备份、明确适配，不能直接混入新修复。精确引用校验继续保留。

页面和Markdown统一顺序：得分与整体评价、故事结构与详略建议、逐段修改指导、语言修改表、词句提升、二稿执行清单。评分技术说明只在“评分依据”展开区；不另设重复的重点段落栏目。P004在逐段指导中标重点，原段和完整示范各只展示一次。执行勾选可保存并导出。旧记录缺字段时适配已有内容，分段缺失则提示，不猜分段或改历史评分。

另生成的示范二稿若精确复用了已展示的整段，报告内引用对应原段或示范，完整稿可单独下载；JSON和原始二稿body保持完整。原文证据继续逐字校验，失败项仍标不完整，不用空值或删除引用关闭旧错误。

## 看图作文题目图片

1. 选择“看图作文”，选择 PNG、JPG、JPEG 或 WEBP，点击“添加已选题目图片”。最多8张，每张10 MB、2000万像素，每边至少32像素；验证真实解码格式与扩展名，不接受损坏文件、动画或多帧图片。
2. 预览后用“上移”“下移”“删除”安排顺序，不依赖文件名。支持一张包含多幅图，也支持多张图片。
3. 点击“识别题目与图意”，实际调用图像模型。原始文件原样保存；模型副本进行 EXIF 方向校正并缩至最长边2048像素，以 JPEG 发送，副本只在内存中生成。
4. 分开核对可辨认题目文字与要求、逐张图意、明确事实、不确定细节。看不清处标【字迹不清】；不能把推测的人物关系、动机或结局当作事实。无密钥时可手动填写，不会假装识别成功。
5. 点击“确认题目与图意”，再“确认原文”，最后评分。评分请求包含确认的要求、图意、事实、不确定项及图片顺序；图意评价必须引用确认文字，并分开评价合理补充和偏离图意。手动填写只按用户确认的文字核对，不能声称模型看过图片。不机械要求每图一段。
6. 添加、删除、替换、重排图片或编辑图意会使当前确认失效。编辑区可能保留旧顺序文字，须按当前顺序调整后重新确认。历史记录重新打开会恢复图像关联与顺序；原图缺失时提示，仍可阅读现有报告。

## 引文校验与局部修复

确认原文、评分请求、校验、渲染都共用 `Essay.paragraphs`：忽略空白行，保留非空段本身的首尾空白，CRLF、CR、LF 都作为换行边界，不修改保存的原文。旧版结构模型本来就支持多段证据，但缺少专用概述字段；现用 `summary` 写概述，每个 `evidence` 只逐字引用对应一段，跨段结构使用多个证据项，不能拼接或改写冒充原文。

原报错只能证明声称属于 P003 的引文不在 P003。旧实现未保留失败原始响应，不能确定该次具体是段号错误还是模型改写。现在若引文仅在另一段唯一逐字匹配，则修正定位并记录；多段匹配、改写句或跨段拼接不猜测，不删标点、不替换词语、不做模糊匹配。定位修正后取消原字符偏移，避免错误标红。

有界修复针对失败条目，保留同栏有效条目及原编号。请求包含错误字段路径、合法段落、确认原文、已有有效结果及当前会话可用的候选引文比对，不要求重新生成整份报告。仍失败时整份报告标记“不完整”，失败项注明未完成，不伪造分数。同栏提示合并，技术细节折叠展示。每条最多3次修复（初次生成后的自动修复占1次，之后每次点击最多1次请求），达到上限停止。可保存、下载不完整结果；关闭页面前需保存，否则未保存会话可能丢失。

完整与部分报告共用专用评分区、结构小节、逐段原文／点评双栏、四列语言表、具体词句与综合意见，不再使用递归字段展示。不显示空分项；没有图片或确认图意时不显示核图栏目。诊断说明和匿名复现方法见 [REPORT_REPAIR_NOTES.md](REPORT_REPAIR_NOTES.md)。

学生与模型文本安全转义，不直接渲染模型 HTML。明确错误仅在精确字符位置吻合时标红；无法可靠定位时放入语言修改表。可选优化与错误分开，重复短语不会批量替换。

## 评分设置

`config/scoring_reference_v1.json`是新默认配置，20+20来自用户参考样本，并非已经核实的官方权重；未提供正式分档，因此bands为空。`config/scoring.json`保留旧配置。程序校验分项名称、范围及总分一致。历史记录使用自己的配置快照，不因新默认而改分。

`config/calibration/user_reference_pending.json`登记用户报告的26分、13+13及判断理由；尚无对应完整原稿与批改，状态待核对，不能宣称精确校准。完整来源材料可通过 `teacher.calibration.save_case()`保存在Git忽略的 `data/calibration/`，同ID补全登记。题目、正文（含错字及换行）、段落和配置一致且有参考批改，才进入评分之后的一致性检查。参考数字与二稿目标都不进入初次独立评分；一致性检查给出分歧依据或人工复核提示，不覆盖分数。

好词好句的source说明词语是否原文已有，example_source另区分原文引用与教学新拟。教学例句不作为学生原文校验，原文Evidence仍需精确匹配。

原文不可变，版本基于完整元信息、正文、题目图片及确认图意计算。兼容原有纯文字记录的哈希。历史记录保留生成时评分配置、提示词版本及模型名称。

## 文件结构

```text
app.py                         # 实际 Streamlit 入口
teacher/
  __init__.py
  config.py                    # 评分配置读取
  models.py                    # 原文、图片、报告及记录模型
  client.py                    # 官方 SDK 与配置、中文错误
  prompts.py                   # 教学提示词及版本
  service.py                   # 评分、局部修复、二稿
  report_flow.py               # 条目保留、失败槽位修复与累计上限
  diagnostics.py               # 结构化诊断、提示合并、安全日志
  validation.py                # 引文、段落、分值、版本校验
  render.py                    # 安全渲染及完整／不完整导出
  report_view.py               # 统一顺序、段落/任务引用、精确改动去重
  storage.py                   # 原子 JSON 存储
  images.py                    # 原图校验存储与真实图像请求
  image_ui.py                  # 上传排序、预览、图意确认
  demo.py                      # 固定离线演示
config/scoring.json
tests/test_core.py
tests/test_ui.py
tests/test_repairs_images.py
tests/test_report_workflow.py
.streamlit/config.toml
.streamlit/secrets.toml.example
.env.example
.gitignore
.python-version
requirements.txt
requirements-dev.txt
requirements-lock.txt
pytest.ini
PSLE_Chinese_Project_Proposal.md
README.md
REPORT_REPAIR_NOTES.md
data/records/                  # 运行时创建，Git 忽略
data/images/                   # 原始图片，Git 忽略
```

## 验证

```powershell
.\.venv312\Scripts\python -m pytest -q
.\.venv312\Scripts\python -m compileall -q app.py teacher tests
```

其他机器先安装requirements-dev.txt，将.venv312换为.venv。本次验证结果见FLOW_RECOVERY_NOTES.md。包含真实SDK响应边界的固定JSON测试、完整/部分结果保留、修复合并、版本隔离、实际缺失统计、页面和Markdown一致性。测试诊断写入临时目录，不混入真实API日志。离线通过不等于评分或教学质量已准确。

本轮已完成一次真实API数据流程联调：使用本地现有gpt-4.1及人工匿名六段测试稿，一次请求即通过全部必需栏目，6/6段详细点评经AppTest确认实际显示。实际返回内容11、表达10、总分21；不是原27分作文的复评，也不代表已完成精确评分校准。记录位于data/integration/flow-recovery/result.json，完整报告为同目录report.md。没有用健康接口替代批改验证，未进行多设备浏览器视觉验收。

早期启动验收曾在Python 3.12.16下检查Streamlit健康接口和首页HTTP响应；本轮页面采用AppTest离线验证，未启动新服务。

## 保存、备份及部署

网页记录用 UUID 文件名，在当前会话临时目录的 `records/` 中原子写入（临时文件、flush/fsync、替换）；重复保存更新同一记录。损坏记录跳过并提示，不阻止启动。会话 `diagnostics/` 日志记录栏目、错误代码、字段路径、段落ID、累计修复次数、状态、本地请求标识和可用的 API 请求标识，不默认记录密钥、原文或引文正文。详细引文对比仅留在当前会话，旧日志缺失的细节不推测补齐。

原图保存为当前会话临时目录的 `images/<sha256>.<真实扩展名>`，不用用户文件名作为路径。图片副本仅在内存生成，上传与识别数据不进入 Git。替换或删除关联不会自动删除原图，避免损坏当前会话历史；暂不自动清理孤立图片。

**JSON 仅包含图片关联、顺序、确认图意和文字记录，不包含原始图片**。请自行保存上传的原图。新会话不会扫描其他会话或本地旧 `data/records` 来恢复记录；尚无图片打包备份、JSON上传导入或账户恢复功能。开发者离线工具仍可显式传入目录读取旧备份，原文件保留不变。

学生资料、图片、报告与真实密钥应放在 Git 忽略目录 `data/`、`uploads/`、`reports/` 或被忽略的配置文件，不要移入其他受版本管理目录。额外 `.env` 副本也已忽略，模板仅放占位符。

Streamlit Community Cloud 选 Python 3.12、入口 `app.py`，从 `requirements.txt` 安装依赖并配置 Secrets；`requirements-lock.txt` 是实测依赖快照。**云端本地文件不保证永久保存**，需下载记录并备份图片；后续再接持久化服务。推送代码与在Community Cloud新建应用是两个步骤，仍需在部署界面选择仓库、入口与填写Secrets。

网页采用家庭密码访问控制并按会话隔离档案与图片，但没有独立用户身份、跨设备账户档案或永久存储。正式评分表、校准样本与完整词句库仍未提供；范文分析、独立稿件比较、学习趋势、词句库检索及 PDF／Word 导出留作后续扩展。教学判断、图像事实与示范二稿的情节忠实性仍需人工审核。
