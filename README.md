# HSAS — HKU Study Assistance System

License status: no open-source license is currently granted; see `LICENSE`.

> 把分散在 Moodle、syllabus 和课件里的课程信息，变成真正适合个人执行的跨课程学习计划。

HSAS 是一个面向 HKU 学生的本地 AI 学习辅助系统。它会采集学生有权访问的 Moodle 课程，理解 Assessment、DDL、权重、要求和课件内容，再结合学生的目标与真实学习进度，生成一份统一的跨课程优先级清单。AI 随后检索相关课件，为优先事项设计学习方法、预计投入时间和可自我检验的学习成果；具体何时学习由学生自行选择。

## 它解决什么问题

大学学习真正困难的地方，往往不是资料不足，而是信息没有形成一个可靠的决策系统：

- DDL、考试日期和作业要求分散在不同课程页面；
- syllabus、公告、Moodle Label 和 PDF 中可能各自包含一部分关键信息；
- 多门课程同时进行时，很难综合比较权重、紧迫度、难度和耗时；
- 普通 AI 对话容易遗漏来源、混淆事实与建议，计划也可能每次回答都不一样；
- 普通待办工具能记录任务，却不了解课程内容和真实工作量。

HSAS 将这些信息汇总成统一课程数据库，再通过可验证的规划规则生成跨课程计划。

## 为什么它比普通方案更适合学习规划

| 对比维度 | 普通 AI 学习助手 | 待办/日历工具 | HSAS |
|---|---|---|---|
| 信息深度 | 依赖用户复制的上下文 | 只保存手动输入的任务 | 课程结构、Assessment、syllabus、Label、PDF 正文和来源统一采集 |
| 数据可信度 | 可能混淆事实与建议 | 通常没有课程证据 | 保存 activity ID、页码、置信度、冲突和 warning |
| 个性化 | 依赖当次提示词 | 主要依赖手动设置 | 独立 Student Profile 描述目标、能力、偏好和限制 |
| 计划生成 | 大模型自由生成，结果可能漂移 | 规则较浅，不理解课程 | 确定性 Planner 综合 DDL、权重、难度、耗时、状态和依赖 |
| 学习指导 | 容易依赖模型记忆或用户粘贴 | 通常不理解课件 | AI 先通过本地 RAG 检索已下载课件，再给方法、耗时与自测标准 |
| 更新成本 | 需要重新对话和调用模型 | 需要人工维护 | 增量同步并自动重算，纯逻辑生成成本低 |
| AI 的角色 | 同时猜数据、做决定和解释 | 通常没有课程 AI | AI 只记录用户确认的数据、解释计划和提供顾问服务 |
| 数据控制 | 取决于服务商 | 通常存于云端 | 课程数据库、Profile 和 Plan 默认保存在本地 |

HSAS 最重要的区别，是没有把整个系统交给 AI 自由发挥：

- Collector 负责可靠地取得课程事实；
- Pydantic Schema 负责约束数据；
- Planner 负责稳定地排序关键要务并给出理由；
- Validator 负责发现引用、DDL、工作量和里程碑问题；
- RAG 负责从本地课件中检索与当前要务相关的证据；
- AI 负责与学生沟通、记录确认信息，并把要务转化为灵活的学习建议。

这种边界让系统既能利用 AI 的交互能力，又尽量避免幻觉、计划漂移和重复调用成本。

## 核心产品：Integrated Plan

`integrated_plan.json` 不是日历，也不是简单的 DDL 列表，而是一份可追踪、可更新的关键要务清单。它包含：

- 所有课程的标准化任务；
- 官方开放时间、考试日期和 DDL；
- Assessment 权重与成绩影响；
- 学习难度、任务状态和学生薄弱主题；
- 预计总耗时、已完成时间和剩余时间；
- `critical / high / medium / planned` 综合优先级；
- 论文、考试、项目和演示的阶段性里程碑；
- 每项任务的排序理由、完成标准、来源和 warning；
- 全局工作量摘要、资料缺失和不确定信息警告。

它不会保存学生的具体可用时段，也不会替学生把任务锁定到某天几点。Profile 可以保留可选的每周工作量预算和学习偏好，用于判断负担、改善建议，但不会据此生成固定日历。

```text
HKU Moodle
    ↓
课程数据库：课程结构、Assessment、DDL、课件与来源
    +
Student Profile：目标、学习特点、偏好与限制
    +
Execution Log：完成进度与实际耗时
    ↓
Deterministic Planner Engine
    ↓
Integrated Plan：排序后的关键要务、理由与完成标准
    ↓
本地 RAG 检索对应课程、activity、文件和 PDF 页码
    ↓
AI 生成学习方法、预计投入与可自测成果
    ↓
学生自行选择实际学习时段，并反馈真实耗时
```

## 核心功能

### 1. 深度课程采集

用户不需要逐门课程手动下载或整理资料。首次运行只需在 Playwright 打开的浏览器中亲自完成 HKU SSO/MFA 登录；之后 Moodle 数据抓取、文件下载、数据结构化与 Schema 校验均由 Python 自动完成。

HSAS 不只抓取课程名称和 DDL，还会尽可能保存：

- section、每周主题和 activity 结构；
- assignment、quiz、exam、project、presentation 等 Assessment；
- 权重、bonus、字数、开放时间、DDL、考试日期和具体要求；
- Moodle Label、syllabus 与课程政策；
- PDF 原文件、逐页正文、页数、字数和预计阅读时间；
- Moodle activity ID、syllabus 页码、来源链接和采集时间；
- 数据置信度、冲突、缺失字段和 OCR 警告。

同步支持 SHA-256 变化检测以及 ETag/Last-Modified 条件请求。未变化的课件可以直接复用，减少重复下载和 PDF 分析。

### 2. 统一、可验证的数据模型

课程、Student Profile、执行记录和综合计划都使用 Pydantic Schema 校验，并以本地 JSON 保存。

系统会明确区分：

- **课程事实**：来自 Moodle、syllabus 和课件；
- **学生事实**：由用户确认的目标、时间、能力与进度；
- **规划结果**：由 Planner 根据前两者计算；
- **AI 解释**：帮助用户理解结果，不覆盖官方事实。

每个重要结论尽量保留来源、置信度和 warning，未知信息不会被自动当成零或被 AI 猜测补全。

### 3. 纯逻辑优先级排序

Integrated Plan 由确定性的 Python Planner 生成，不依赖大模型临场“想一个顺序”。Planner 会综合考虑：

- DDL 和考试日期；
- Assessment 权重和课程目标；
- 学习难度与薄弱主题；
- 剩余工作量、完成进度与估算误差；
- 任务是否开放、材料是否齐全；
- 前置依赖、风险和来源可信度。

大型 Assessment 会自动拆分：

- 论文/报告：要求与论点 → 研究提纲 → 初稿 → 修订 → 提交检查；
- 考试：诊断 → 知识覆盖 → 针对练习 → 模考 → 最终复习；
- 项目：范围确认 → 原型 → 核心实现 → 整合测试 → 最终交付；
- 演示：信息与提纲 → 初版材料 → 彩排 → 最终检查。

这些阶段是早于官方 DDL 的任务里程碑，不是具体学习时段。相同输入会产生稳定、可复现的排序；更新 Integrated Plan 不需要调用 AI API，因此成本更低，也更适合频繁运行。

### 4. 本地课件 RAG 与灵活学习设计

AI 不应只根据任务标题猜测应该怎样学习。它会先读取 Integrated Plan 的高优先级事项，再用本地 RAG 检索对应课程的 PDF 正文，保留课程、activity、文件和页码来源，最后提出：

- 适合该内容的学习方法，例如预习、主动回忆、刷题、论证提纲或模拟考试；
- 每个学习动作大致需要多少分钟，而不是安排到具体日期和时间；
- 完成后应能回答、解释、推导、实现或产出什么，以便学生自我检验；
- 资料缺失、OCR 不可用或证据不足时的明确提示。

当前 RAG v1 使用本地、确定性的关键词相关度检索，不需要 embedding 服务或外部 API，因此便宜、可复现且不会上传课件。它擅长检索已提取的文本；扫描型 PDF 仍需要后续 OCR 才能纳入正文检索。

### 5. 学习反馈闭环

系统可以记录计划耗时、实际耗时、完成进度和结果，并据此校准未来估算：

```text
计划 → 执行 → 记录实际耗时 → 校准估算 → 更新计划
```

已经开始或完成的内容会被保留，其余事项则根据新 DDL、课件变化、学生进度和实际耗时重新排序、重新估算。

### 6. AI 课程顾问

在结构化课程数据库之上，AI 可以回答：

- 本周应该学什么？需要阅读哪些课件？
- 最近有哪些 DDL？哪些日期仍是 TBD？
- 某项 Assessment 的权重、要求和来源是什么？
- syllabus 如何规定迟交、参与和 AI 使用？
- 为什么某项任务优先级更高？
- 针对当前优先事项，应该怎样学习、预计多久、如何确认自己真的掌握？

## 快速开始

### 环境要求

- Python 3.11 或更高版本；
- 可正常访问 HKU Moodle 的账号；
- Chromium，由 Playwright 安装；
- 首次登录时需要用户本人完成 HKU SSO/MFA。

### 安装

```bash
cd "/path/to/HSAS"
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -c requirements.lock -e .
playwright install chromium
```

HKU Moodle URL 已作为公开默认值保存在 `config/defaults.toml`，通常无需配置。个人配置、课程数据和浏览器登录状态不放在 Git 仓库中；macOS 默认使用：

```text
~/Library/Application Support/HSAS/
├── config.toml
├── browser-profile/
├── resources/
│   ├── courses/
│   ├── student_profile.json
│   ├── execution_log.json
│   └── integrated_plan.json
└── state/
```

缓存与日志分别位于 `~/Library/Caches/HSAS/` 和 `~/Library/Logs/HSAS/`。这些路径由 `platformdirs` 自动选择；其他系统会使用各自的标准用户目录。可通过 `HSAS_DATA_DIR=/custom/path` 覆盖整个数据根目录，或通过全局 `hsas --resources /custom/path/resources COMMAND` 只覆盖本次命令的资源目录。

`.env` 仅作为可选的本地 Moodle 配置覆盖，已被 `.gitignore` 排除。密码、MFA、cookie 和 sesskey 不应写入任何配置文件。

### 从旧版目录迁移

如果旧版数据仍在项目中的 `src/resources/`、`.moodle-profile/` 和 `.env`，运行：

```bash
hsas migrate-data
```

命令会复制文件、逐文件校验 SHA-256，并把非敏感设置转换为用户目录中的 `config.toml`。它不会删除旧文件；验证成功后请先检查 `state/migration-report.json`，再自行处理项目中的旧副本。

### 使用

课程资料无需用户手动逐个下载：完成一次交互式登录后，运行同步命令即可让 Python 自动发现可用课程、抓取 Moodle 数据、下载可访问文件，并完成结构化与校验。

```bash
# 1. 打开浏览器并由用户完成登录
hsas login

# 2. 同步全部可用课程
hsas sync-courses

# 也可以只同步一门课程
hsas sync-courses 146267

# 3. 验证 Student Profile；确认写入和后续同步会自动尝试刷新计划
hsas profile validate
hsas update-plan

# 4. 查看登录、课程、Profile、执行记录和计划状态
hsas list-status
```

更新软件代码：

```bash
# 只克隆、验证和比较
hsas update-hsas --dry-run

# 使用 dry-run 输出的完整 commit 精确授权本次代码更新
hsas update-hsas --commit FULL_40_CHARACTER_COMMIT
```

更新器只管理仓库代码。个人 resources、浏览器 profile、`.env`、虚拟环境和本地 selector 均不会被 Git 内容覆盖；代码复制失败时会回滚。依赖变化必须通过普通包管理器升级，不在原地更新事务中执行。

### 搭配 AI Agent 使用

在 Codex 或其他能够读取项目文件与运行终端命令的 Agent 中，直接打开 **HSAS 项目根目录**。根目录的 `AGENTS.md` 会引导 Agent 加载 `src/AI_Skills/SKILL.md`，再按任务读取 Collector Handbook、Study Assistant Task Guide 和相关安全协议。

推荐流程：

1. 让 Agent 运行 `hsas list-status`，检查登录、课程数据、Student Profile 和 Integrated Plan 状态。
2. 如果尚未登录，让 Agent 运行 `hsas login`；浏览器打开后，由用户本人完成 HKU SSO/MFA。
3. 明确授权 Agent 运行 `hsas sync-courses`。Python 会自动发现课程、抓取 Moodle 数据、下载课件、解析 Assessment，并完成结构化与校验。
4. 告诉 Agent 你的目标、薄弱主题、学习偏好、限制，以及可选的每周学习预算。确认变更后，Agent 通过 `hsas profile apply` 安全更新 Profile，而不是直接编辑 JSON。
5. CLI 自动尝试重新规划；Agent 再检查 Planner 与 Validator 是否成功。必要时显式运行 `hsas update-plan`。
6. Agent 读取排序后的关键要务，并先运行 `hsas materials for-item PLAN_ITEM_ID` 检索相关课件；必要时再用 `hsas materials search` 精细检索。
7. Agent 根据检索证据给出学习方法、大致耗时和可自测成果。学生自行选择实际学习时段；AI 不把具体时段写回 Integrated Plan。
8. 学习后通过 `hsas execution add` 记录实际耗时与进度；CLI 自动重新估算并保留失败前的有效 Plan。

可以直接这样提问：

```text
检查 HSAS 当前状态，并告诉我哪些课程需要同步；先不要执行同步。

同步全部可用课程，然后更新综合计划。

我每周大约能投入 12 小时，偏好每次专注 60 分钟。
请先向我确认准备写入的 Profile 变更，再更新计划。

根据 Integrated Plan 告诉我这周最优先的三项任务，
并解释每项任务受到哪些 DDL、权重、难度、耗时和状态因素影响。

先检索最高优先级事项对应的课件，再给我三个灵活学习动作。
每项都说明大致耗时、采用这种方法的理由、课件来源和自测标准，
不要替我指定周几几点学习。

我刚完成了计划项 plan-item-123 的一个预计 60 分钟学习动作，实际用了 90 分钟，
完成了相当于 60 分钟的计划工作。记录这次执行结果并重新估算后续计划。
```

Agent 与 HSAS 的职责边界是：

- **用户**：完成登录并确认个人资料、实际耗时和进度；
- **Python Collector**：抓取、下载、解析、结构化和校验 Moodle 数据；
- **Planner Engine**：根据课程事实、Student Profile 和 Execution Log 排序关键要务；
- **本地 RAG**：从已下载课件正文中检索与某项要务相关的内容并返回来源；
- **AI Agent**：理解用户意图、记录已确认信息，并据检索证据设计灵活学习建议；
- **学生**：根据现实安排自行选择学习时段，并反馈真实耗时。

Agent 不应直接编辑 `student_profile.json`、`execution_log.json`、`course.json` 或 `integrated_plan.json`。Profile 与执行记录必须通过受控 CLI 校验并原子写入。当同步失败或数据过期时，应保留上一份有效数据并明确提示，而不是猜测最新 DDL 或伪造更新成功。

### 安全更新 Profile 与执行记录

Profile 采用最小 JSON 补丁，避免重写或覆盖未涉及的数据：

```json
{
  "profile_status": "active",
  "study_capacity": {
    "weekly_study_budget_minutes": 720,
    "preferred_session_minutes": 60
  }
}
```

用户确认补丁内容后执行：

```bash
hsas profile apply profile-patch.json --confirmed
```

记录学习反馈时，实际耗时和完成的计划工作量必须分开提供：

```bash
hsas execution add PLAN_ITEM_ID \
  --planned-minutes 60 \
  --actual-minutes 90 \
  --progress-minutes 60 \
  --completed

```

`--planned-minutes` 是 AI 此前为该学习动作提出的大致投入，不代表固定日历时段。重复提交可传入相同的 `--record-id`；完全相同的重试不会产生重复记录。如果报告有误，使用 `hsas execution correct RECORD_ID` 更正原记录。成功写入后 CLI 会自动运行 Planner；如果失败，已确认事实与上一份有效 Plan 都会保留，`hsas list-status` 会显示 Plan 已过期。

也可以直接从命令行检索课件：

```bash
# 根据一个 Plan Item 自动组合查询，并限制到对应课程
hsas materials for-item PLAN_ITEM_ID

# 自定义检索；--course 可重复提供
hsas materials search "eigenvalue diagonalization" --course 138907 --limit 5
```

macOS 上主要数据默认保存在：

```text
~/Library/Application Support/HSAS/resources/
├── courses/<course-id>/course.json   # 结构化课程数据库
├── courses/<course-id>/files/        # 下载的课程文件
├── student_profile.json              # 学生目标、时间与学习特点
├── execution_log.json                # 真实执行与耗时反馈
└── integrated_plan.json              # 排序后的跨课程关键要务
```

## 当前边界

HSAS 目前是一个可运行的本地 MVP，而不是 HKU 官方产品。

- 它不会绕过 Moodle 权限，只读取当前账号本来可以访问的内容；
- Moodle 页面或接口变化时，可能需要调整 selector 或适配逻辑；
- 扫描型 PDF 会标记 OCR 缺失，目前不会假装已经理解正文；
- 未公布的 DDL、成绩和课程政策会保持未知，仍应以 Moodle 官方页面为准；
- Student Profile 和执行反馈需要学生本人确认，AI 不应推断敏感信息。

更详细的采集与数据结构说明见 [MOODLE_COLLECTOR.md](MOODLE_COLLECTOR.md)。AI 应从 [SKILL.md](src/AI_Skills/SKILL.md) 进入，再按需读取 [Handbook.md](src/AI_Skills/Handbook.md) 与 [Task.md](src/AI_Skills/Task.md)。
