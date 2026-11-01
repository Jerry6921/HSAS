# 课程规划与 enrolment 实现

对应需求：[HIQS-20261017-ENROL-02](hiqs-course-planning-enrolment-handoff.md)。
实现日期：2026-10-17（Asia/Hong_Kong）。

## 可观察的交付结果

Agent 能读取未选课程资料，将用户认可的课程池、目标和完整班别组合保存为任务；
通过同一 MCP／HIQSPort 求解整体课表，得到一次性 enrol 操作指令，保存真实页面读回后
锁定成功课程，在池内重新规划尚未完成的目标。中断后可以从检查点恢复。
每个状态都带原因，Pending、未知结果、无解和完成分开报告。

本实现采用 **Skill + 前台 Agent + 确定性服务**。官方页面的阅读、状态映射和点击由
Agent 使用其可用的浏览器工具执行，Python 不假设未经验证的 SIS 提交 URL 或选择器。
测试中的官方页面记录都是受控输入，不是当前账户的真实 enrol 验收。

## 边界与文件

| 层次 | 责任 |
| --- | --- |
| `skills/hiqs-course-planning/SKILL.md` | 解释 syllabus／programme 年份、推荐候选、读取官方班别／状态、执行已授权页面操作及恢复。 |
| `application/course_planning.py` | 严格输入模型、日期展开、完整组件验证、硬约束与软偏好排序、全组合搜索。 |
| `core/services/course_planning.py` | 授权、原子检查点、版本／进程锁、计划历史、提交尝试、成功锁定、失败分类及结果对账。 |
| `CoursePlanningPort` | MCP 与 CLI 共用的应用边界；不含页面选择器。 |
| SIS Course Information gateway | 按显式课程代码查询未选课程；定向查询保留其他已缓存课程。原有名单同步仍保持自己的范围语义。 |
| `hsas course-planning` | 人工恢复适配器；规则不在 CLI 重写。 |

任务位于私有 resources 的 `course-planning/<run_id>/state.json`，官方观察保存在
`observations/<sha256>.json`。计划与尝试引用输入快照哈希，可通过
`get_course_plan(run_id, observation_sha256=...)` 读回并验证。任务不写
`information.json`，不推进课程事实的审阅游标。

## 数据与求解

先调用 `get_course_planning_schema` 取得准确 schema。

- `request` 固定 account／term、goals、已认可 options、硬约束、偏好和 scope。
  一个 goal 可以允许 A 或 B；不要求把整个候选池都选上。授权绑定完整 request 的哈希。
- 一个 option 是一个合法完整组合，含所需 lecture／tutorial／lab 班别身份、学分、资格、
  全部实际日期及来源。异步组件显式声明；缺组件或未经核验的时间不能当作完整课表。
- `recurring_meetings` 可按起止日期、星期、排除日期和补课日期展开。已知考试用
  `component=exam`；未覆盖考试保留 warning。时间缓冲作用于课程会议之间。
- 已完成先修、学生类别限制、programme 年份等由 Agent 根据来源核验为 `eligible`；
  缺失保持 unknown。当前组合中的共修／互斥分别用 `corequisite_courses`／
  `excluded_courses` 表达；官方资格变化可在 observation 的 availability 中更新，
  不扩大候选池或改动目标。
- 求解固定所有已成功课程，包含用户此前手动 enrol 的其他课程及其学分；待批请求
  作为占位约束参与规划，单独列为 `pending_goals`，不计作已满足目标。
- 求解所有剩余目标，避免逐门贪心造成后续冲突；一个课程不能重复满足两个目标。
  先满足学分、日期、组件和课程关系，再依次优化集中上课、避早课及池内顺序。
  搜索预算耗尽返回“可行性未决”，不假称数学无解。

## 操作合同

| MCP 工具 | 结果 |
| --- | --- |
| `sync_sis_course_info(course_codes=[...])` | 查询显式候选，支持未 enrol 课程；不解释页面事实。 |
| `create_course_plan(request, confirmed)` | 创建本地任务，不授权实际 enrol。 |
| `get_course_plan` | 列出任务或读取完整状态、计划、尝试、实际读回及历史输入。 |
| `authorize_course_plan` | 授权精确 request 哈希；记录生效／到期时间、快照新鲜度、检查间隔及总尝试预算。 |
| `reconcile_course_plan` | 验证账户、学期、完整性、时间、来源及组件，更新实际状态并重排。 |
| `next_course_plan_action` | 至多预留一次提交；先持久化 unknown 尝试，再返回 submit 操作。 |
| `cancel_course_plan` | 终止后续动作，保留已选课程和未知提交，不自动 drop。 |

所有变更要求 `confirmed=true`，已有任务的变更还要求 `expected_revision`。
真实 enrol 任务授权必须来自用户的选课指令；开发请求本身不提供该授权。
授权过期／预算用尽保留未完成目标；再次授权可扩大总预算，旧尝试不被清零。

`submit` 包含 attempt ID、完整目标组合、账户／学期、计划版本、前置观察哈希和有效期。
Agent 操作前再次核对最新任务、账户、学期、实际课表及组件，之后只执行一次 add/enrol。
工具没有直接调用 SIS；返回 submit 也不是选课成功。

## 对账、重试与等待

完整观察必须覆盖当前账户的已选及待批状态，保存学校原始状态、读取时间、来源定位和
内容哈希。现有 Student Center 课程名单不能独自证明一次交易的全部组件。
服务校验结构、身份与约束，**不会独立证明 Agent 的页面解释或来源真实性**。

- 成功：正式 enrolled 且完整组合匹配；锁定课程和班别，不允许为了优化而 drop／swap。
- Pending／候补：保存请求，不标成功。可以继续兼容的其他目标；最终仍等待正式决定。
- 超时／中断：尝试维持 unknown。恢复先查询；即使一条课程行缺失，也不能直接重投。
  需要该组合明确 absent，及对应 attempt 的观察结果分类，才可结算失败。
- 满额／限制：池内整体重排；同一条件下不反复提交同一无效组合。
  `condition_key` 跟随实际条件变化，轮询时间变化本身不构成新条件。
- 临时故障／未提交：遵循配置间隔及官方 `retry_after` 退避，可在同池重试。
- 登录失效：等待用户认证，恢复后先对账。
- 外部修改成功课程：保留原锁定记录并请求用户决定，不能静默换班或改目标。
- 同账户／学期：本地任务在文件锁下互斥预留。取消或到期任务的 unknown 尝试仍须对账；
  本地锁不控制外部手动浏览器，也不能撤回学校已接收的提交。

返回的 `verified_as_of` 给出官方读回时间，`authorization_active` 表示权限有效期。
`executor=foreground-agent`、`background_running=false` 明确没有独立执行器。
等待保存 `next_check_at`，会话结束后可恢复；未实现常驻守护进程或默认定时监控。
当前无新增兼容 UI 页面，也未把选课执行状态发布到 Notion。

## 验收对应

以下是受控输入下的程序验证范围；真实官方页面流程全部仍待任务授权后的端到端验证。

| 需求场景 | 测试覆盖 |
| --- | --- |
| EN-AC-01／02 | 带来源的候选模型、完整组合求解、显式未选课程查询及缓存保留；推荐的学术判断由 Skill 执行。 |
| EN-AC-03／04 | 满额后自动换认可候选；固定成功课程；全组合、lab、考试、日期和缓冲冲突。 |
| EN-AC-05／06 | A 或 B 仅满足一次；重叠目标池全局匹配；不改变成功课程、不扩池。 |
| EN-AC-07／08 | Pending 不完成、不重投；超时先对账；逐项结果未知不重复提交。 |
| EN-AC-09 | 未知资格可见、限制条件不变时不重试、共修与互斥、官方资格变化。 |
| EN-AC-10／11 | 进程重建读回、陈旧 revision 拒绝、并行预留防重复、跨任务互斥、外部修改检测。 |
| EN-AC-12／13 | 全满等待、窗口关闭阻塞、预算／授权停止；全部正式状态满足后才完成。 |
| EN-AC-14 | 取消后不再预留，保留已成功及未知尝试，允许继续对账。 |

`tests/test_course_planning.py` 还验证完整 MCP 授权→预留→Pending→正式成功流程、
CLI 同 Port 读取、不可变历史输入回读、Skill 打包及不写 canonical facts。
使用 `PYTHONPATH=.:src .venv/bin/pytest -q`、Ruff、生成合同检查和 UI check 验证集成。

## 本轮验证记录

- 新增课程规划／enrol 流程行为测试：26 项通过。
- Python 全量：273 项通过（包含需要本地回环端口的 HTTP 测试）。
- UI：TypeScript 类型检查、11 项 Vitest 测试和 Vite 生产构建通过。
- Ruff、生成合同一致性及 `git diff --check` 通过。
- 本轮未操作真实 SIS 选课，未提交或推送 Git；现有课程笔记、Notion 和 Skill 目录迁移工作保留。
