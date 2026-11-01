# HIQS course notes：最小实现与验收

需求依据：[HIQS-20261016-SKILLS-01](hiqs-agent-skills-handoff.md)。本实现覆盖第一个
完整用例，不预设校园事务、研究、预约或多用户平台。ENGG1000 是实际使用目标，核心代码
没有课程代码或个人身份条件。

结构调整后，产品 Skill 源统一为 `skills/hiqs-course-notes`、
`skills/hiqs-course-information` 和 `skills/hiqs-notion-workspace`，打包器直接读取
顶层 `skills/`；`.agents/skills` 保留相对链接。Notion 是默认笔记交付目标，
本地检查点与 Markdown 用于恢复、保存读回及发布受阻时保留成果。

2026-10-17 用户后续明确：notes 的要求与 `english-course-notes` 一致。该要求取代此前
“精简教学摘要”和“Notion 可选发布”的首版选择。`references/teaching.md` 随包携带源
Skill 正文的完整副本（不含技能发现 frontmatter），包含全部九节要求；不是摘要或个人
Skill 的隐式依赖。文件注释记录同步日期和源 SHA-256。以后同步源规范时保留完整正文，
同步检查入口和发布说明，避免维护一份逐渐偏离的简化版本。

## 架构核验与选择

| 需求性质 | 核验结果与实现选择 |
| --- | --- |
| U-01／U-02：Skill Set，先个人后分发 | 新增一个可独立分发的 `hiqs-course-notes`；保留 `hiqs-course-information` 的事实职责。AGENTS 负责仓库发现，不增加尚无真实用例的总路由框架。 |
| U-03／U-04：讲义＋题目，学习与复习 | Agent 编排资料阅读、知识结构、题目映射与教学写作；确定性工具验证引用身份、单元关系、完成状态与保存。 |
| U-05：一次整套 | Skill 运行所有单元的内部批次；不是逐段询问，也不是常驻后台服务。 |
| D／F-01–02：全量盘点和阅读 | 复用 `MaterialQueryService.manifest`；新增有 offset/eof 的全文读取，保存实际输入哈希、重复来源与提取警告。表格型活动即使无正文也进入 manifest。 |
| D／F-03–08：结构、题目、覆盖 | 单元计划、前置关系、来源审阅、题目位置和答案来源纳入检查点。每个 lecture/syllabus 必须进入单元计划，不能因试题缺席删除讲义覆盖。具体概念是否讲全仍需 Agent 核对。 |
| D／F-04、F-10：批次恢复与保存核验 | CORE 原子 JSON＋revision 比较＋文件锁；按 revision 导出 Markdown，逐文件读回；校验失败不替换上次有效检查点，导出失败保留已存正文。 |
| P-02：交付组织 | 采纳 overview、unit、question-map、review、coverage 五类成果，自动 index；内部以稳定 `<artifact_id>.md` 互链。 |
| P-03：Skill／工具边界 | 采纳 Skill 编排、确定性 CORE 执行。MCP 只通过 `HIQSPort` 委派，无第二套 CLI 业务逻辑。 |
| P／F-09：增量修订 | 首版支持单个成果修订、用户编辑合并及无关正文保留；新来源或哈希变化需新 run。跨 run 自动依赖失效和合并暂缓。 |

教学要求以完整的 `english-course-notes` 正文为准：跨课程状态隔离、课程阶段与解题
概念阶段、教材式推导、多结构例子及共同机制、模型条件下的依赖与独立性、深层误区、
单位换算推理、章节整合、独立快速复习、Notion 发布与最终核验。英语用于所有笔记组成，
用户可明确指定其他语言。整套请求覆盖默认单单元节奏，保持内部批次连续完成。
这些属于用户指定要求，非可选的教学建议；产品不依赖本机个人 Skill 的绝对路径。

## 接口和状态归属

调用链：`Skill → MCP → CourseNotesPort → CourseNotesService → private resources/course-notes`。

| MCP 工具 | 合同 |
| --- | --- |
| `get_course_notes_schema` | 返回 checkpoint 的精确 JSON Schema。生成快照为 `contracts/course-notes.schema.json`。 |
| `create_course_notes` | 精确 course_id、scope、language；捕获本地课程清单与实际文件哈希。需要 `confirmed=true`。不启动后台生成。 |
| `read_course_note_source` | run 内来源白名单，offset/limit、next_offset/eof、总字符数与提取警告；最大 30,000 字符，检查文件变化和路径越界。 |
| `save_course_notes` | revision 防覆盖；upsert reviews/artifacts，显式替换 units/questions；complete 必须通过覆盖结构检查；需要 `confirmed=true`。 |
| `get_course_notes` | 列出任务或读取 checkpoint／指定正文；复查来源状态，重建并读回本地交付，暴露失败与恢复位置。 |

输入来源元数据创建后保持不变；Agent 审阅状态、计划、正文、问题映射和外部发布回执属于
笔记 run。`state.json` 是带用户内容的权威检查点，不能像搜索缓存一样删除重建。
Markdown 是可重建投影，但用户编辑过的文件会保留，保存后续批次前必须读回并合并，
在 `reconciled_exports` 提交已读文件哈希。旧 revision 始终保留；工具不自动删除任务。

每次保存的完整 bundle 在 `exports/revision-NNNNNN/`，包含自动 `index.md` 和各成果。
失败若发生在 checkpoint 替换前，则旧状态不变；若发生在导出阶段，则新正文已保存而
`local_delivery.status=failed`。读取可重试导出。旧 revision 请求报冲突，调用者先取最新
checkpoint，不能盲目覆盖。来源变化后 `content_status=stale`，旧成果仍保留。

`source_reviews.reading=read` 是 Agent 完整阅读与视觉检查的声明；服务不能证明 Agent
理解过全文。完成检查验证来源覆盖关系、已规划单元、必需成果、引用 ID 和未解决限制；
无法机械证明教学完整性、引用文字准确性或答案推导正确性。`mastery=not_assessed` 不因
笔记完成改变。missing/unreadable required inputs 记录为 limitation，阻止 `complete`。

## 发布和权限

本地写入是笔记请求的必要可逆操作。canonical facts、来源审阅 checkpoint 和个人状态
不受影响。来源内容只作为数据，文件路径必须属于 resources；资料中的指令不会提升权限。

Notion 是默认 Agent 连接器工作流：定位并 fetch 对应课程父页 → 定向保存 → fetch 每个结果
核验 → 记录链接与 readback evidence。外部 `verified` 是 Agent 回执，CORE 不声称自己调用
了 Notion 验证 API。`sync_notion` 仍只负责原有事实投影，不发布学习笔记正文。外部服务失败
可与本地内容 `complete` 并存，报告时必须区分。

唯一对应课程父页已验证时，生成笔记的请求足以授权按该默认流程发布，无需再次例行确认。
存在目标歧义时先备稿并询问目标，连接不可用时保留本地成果并报告发布未完成。课程切换
重新解析父页；新课新增子页，更正定向修改原课，保留编号和用户正文。读取当前 Notion
enhanced-Markdown 规范后编写支持的目录、公式、表格和 toggle；本地文件互链在发布时
转换为真实页面链接／mentions。最终交付以验证过的 Notion 链接为主，本地 complete 状态
不能替代默认发布完成。只有用户明确指定其他目的地时才按该目的地交付。

## 实现计划及验收对应

| 已实现工作 | 关联要求 | 场景与证据边界 |
| --- | --- | --- |
| Skill＋teaching reference＋入口＋分发 ZIP | F-03–08 | AC-01–04、08–09 的执行规范；教学效果需真实用户阅读验收。 |
| 来源快照、哈希重复关系、全文分页 | F-01–02、08 | 自动测试验证读到尾、重复来源、变化检测、路径越界；原始图示/OCR 判断仍由 Agent 执行。 |
| 检查点、题目与引用模型、完成检查 | F-04、06、08 | 自动测试验证缺失单元/来源/成果、无官方答案引用、跨课程 ID 和题目关系拒绝；真实学期解析仍需实际课程执行。 |
| 原子存储、并发版本、revision 导出与读回 | F-04、10 | AC-02、07：重建 service 后续写、双写冲突、导出失败后恢复、本地与外部状态分离。 |
| 编辑检测、合并收据、稳定链接 | F-09（部分）、10 | AC-10 的本地正文修订通过测试；新增 quiz 的自动跨 run 增量更新未纳入。 |

自动集成用例使用仓库真实格式 `CourseArchive` fixture，经完整 MCP→CORE→manifest→保存→
Markdown 读回，无 stubbed Port/存储；验证另一课程 ID 复用。此用例不等于真实 ENGG1000
全课程任务，也不能证明大型课程的后半部分教学质量或 Notion 发布成功。

真实 ENGG1000 整套笔记、在线资料完整性、实际 Notion 保存读回与学生教学效果尚未验收。
本次没有生成用户课程笔记、提交 commit、推送、发布 GitHub issue 或覆盖既有 Notion 开发。

## 可重复检查

2026-10-17 本次结果：Python 全库 **243 passed**；UI typecheck 通过，Vitest
**11 passed**；Ruff、现有生成合同检查、笔记合同快照测试、两个 Skill 的官方
quick validator 及 `git diff --check` 通过。完整 MCP 资料到 bundle 的集成用例包含在
Python suite 中。首次沙箱运行有三项 Dashboard socket 测试被拒绝绑定，获得本地端口
执行权限后全库通过。UI 未改源码或生成资产；分发 ZIP 已在 `work/hiqs-agent-skills.zip`
生成并检查，不含个人 resources 或认证配置。

```bash
PYTHONPATH=.:src .venv/bin/pytest -q
.venv/bin/ruff check .
PYTHONPATH=.:src .venv/bin/python scripts/check_generated.py
.venv/bin/python scripts/generate_notes_contracts.py
.venv/bin/python scripts/package_agent_skills.py --output work/hiqs-agent-skills.zip
git diff --check
```

Skill 验证使用 `skill-creator/scripts/quick_validate.py`，需要 PyYAML；该依赖属于开发
校验环境。课程笔记不改变前端源码，但按跨层仓库要求运行 UI typecheck 与 Vitest 回归。
