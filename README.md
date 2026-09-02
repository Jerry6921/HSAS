# HSAS — HKU Study Assistance System

> 把 Moodle 中分散的课程信息，转化为有依据、可执行的跨课程学习优先级。

HSAS 是面向 HKU 学生的本地学习辅助系统。它同步 Moodle 课程，整理
Assessment、DDL、权重、要求和课件，通过确定性规则判断当前最重要的学习事项，并从
本地课件中检索相关内容，组成带课程、文件和页码来源的 RAG context，帮助 AI 给出有来源
的学习建议。

你可以在本地 Dashboard 中查看优先事项、同步状态和课程资料，并记录真实学习进度。
个人资料、课程文件、登录状态和计划默认保存在本地数据目录。

## 它解决什么问题

课程信息通常散落在 Moodle 页面、syllabus、公告、Label 和 PDF 中。多门课程同时进行时，
学生需要持续综合日期、工作量、重要程度和学习进度：

- 最近有哪些真正重要的 DDL 和考试？
- 权重、难度、剩余工作量和当前进度应该如何一起考虑？
- 一项大型作业应该从哪里开始，怎样拆成可完成的阶段？
- 当前任务对应哪些课件，应该怎样学习，怎样确认自己已经掌握？
- Moodle 更新后，旧计划是否仍然可信？

HSAS 将这些信息整理成带来源的课程数据库，再生成稳定、可验证的跨课程优先事项。
信息模型为未公布或证据不足的字段保留 unknown 状态和来源说明。

系统中的职责分为课程事实采集、确定性规划、本地 RAG 检索和 AI 学习解释。学生结合现实
安排选择具体学习日期和时间。

## 主要功能

### Moodle 登录与课程同步

- 使用 Playwright 保存本地浏览器会话，HKU SSO/MFA 交互在浏览器中完成；
- 检查当前 Moodle 登录状态，并区分已登录、已退出和状态未知；
- 从 Dashboard 发现当前课程；
- 支持同步全部课程，也支持通过课程 ID 或同源 Moodle URL 同步单门课程；
- 分别保留每门课程最近一次同步结果，部分失败状态与其他课程的成功状态并存；
- Moodle 页面或接口识别异常时记录错误并保留现有课程状态。

### 课程资料与 Assessment 整理

- 将 Moodle 原始 state、HTML、section、activity 和资源转换成统一的 CourseArchive；
- 从 Moodle Activity、syllabus 和 PDF 文本中提取 Assessment 候选；
- 整理 Assessment 类型、权重、开放时间、DDL、字数限制、评分组和来源；
- 合并多个来源，并保留原始课程、activity、section、文件和页码证据；
- 为未公布、互相冲突或证据不足的信息记录 unknown 状态和来源置信度；
- 比较新旧课程归档，识别 DDL、权重、Assessment、Activity 和课件变化。

### 课件下载与本地处理

- 下载课程文件，并校验来源、重定向和单文件大小；
- 使用缓存验证信息增量更新课件，未变化的文件可以复用；
- 同步异常或文件损坏时恢复上一份有效课程快照；
- 提取 PDF 正文、页码、元数据、关键词和抽取式摘要；
- 计算字数和预计阅读时间，为后续工作量估算提供可测量依据；
- 保留课件原始相对路径，方便从检索结果回到真实文件。

### 跨课程优先级计划

- 综合 DDL、Assessment 权重、课程目标、任务难度、准备状态、预计工作量和依赖关系；
- 将重要 Assessment 和当前课程 Activity 转换为统一的 PlanItem；
- 按 `critical`、`high`、`medium`、`planned` 生成稳定、可解释的跨课程排序；
- 为论文、考试、项目和演示生成不同的阶段里程碑；
- 计划刷新会继承旧计划中仍然有效的真实进度；
- 生成工作量、紧急事项、来源快照和警告汇总；
- 输出优先事项清单，学习日期和时段由学生结合现实安排选择。

### Student Profile 与执行反馈

- 使用 Student Profile 保存课程目标、能力、学习偏好、限制和已确认的个人事实；
- Profile patch 流程包含用户确认、深度合并和完整模型验证；
- 记录每个 PlanItem 的计划时长、实际时长、完成进度和用户备注；
- 使用稳定 `record_id` 支持幂等重试和内容冲突检测；
- 根据真实 Execution Log 校准剩余进度和后续工作量；
- Profile 或 Execution 更新后自动请求重新验证并生成 Integrated Plan。

### 本地 RAG 与 AI 协作

- 对 PDF 提取文本按页码和长度切分，构成本地轻量 RAG 的检索语料；
- 支持搜索概念、问题或关键词，并提供课程范围筛选；
- 可以从 PlanItem 自动组合课程、任务描述和完成标准形成检索问题；
- 返回正文片段、匹配分数、课程、Activity、文件名、相对路径和页码；
- 检索结果作为 RAG context 交给 AI，用于解释知识、设计学习动作和自测标准；
- 当前实现采用本地 BM25 风格词法检索，课程文本和检索过程位于本地数据目录。

### 本地 Dashboard 与 CLI

- Dashboard 展示关键事项、优先级理由、DDL、剩余工作量、课程资料和同步警告；
- 可按课程和 section 浏览、打开已下载课件，并查看完整课程信息；
- Dashboard 记录用户确认的实际学习情况并自动刷新计划；
- Dashboard 绑定 `127.0.0.1`，写请求包含本地请求标记，HTTP 配置采用同源访问；
- CLI 提供登录、同步、状态检查、计划生成、Profile、Execution、检索、迁移和更新命令；
- CLI 与 Dashboard 调用同一组 application 服务，因此业务验证规则保持一致。

### 数据可靠性与更新

- 所有核心 JSON 模型在读取和写入前使用 Pydantic 完整验证；
- JSON、文本和二进制文件通过临时文件和原子替换完成写入；
- 每门课程通过独立锁、staging、journal 和 backup 完成快照发布；
- 新快照验证异常或发布中断时恢复上一份有效数据；
- Integrated Plan 记录 Profile、Execution Log 和 CourseArchive 版本，可判断计划是否过期；
- Git 更新由 dry-run、完整 commit 固定、文件备份和事务恢复组成；
- 软件代码与 resources、课程资料、浏览器会话和个人计划采用分离目录。

## 工作方式

```text
HKU Moodle
    ↓
课程数据库：Assessment、DDL、课件与来源
    +
Student Profile + Execution Log
    ↓
Deterministic Planner
    ↓
Integrated Plan：关键事项、排序理由、工作量与完成标准
    ↓
本地轻量 RAG
    ↓
AI 学习建议：方法、预计投入、证据与自测标准
```

`Integrated Plan` 是持续更新的优先事项清单，记录当前关注事项、排序理由、预计投入和完成
标准；具体学习日期和时间由学生根据现实安排决定。

## 代码架构与工作流

HSAS 使用四层架构。依赖由外层指向业务核心：接口层接收请求，应用层编排用例，领域层保存
模型与确定性规则，基础设施层负责 Moodle、文件系统、PDF、运行时目录和 Git 更新。

```mermaid
flowchart TB
    User[用户或 AI Agent] --> Interfaces[interfaces<br/>CLI 与本地 Dashboard]
    Interfaces --> Application[application<br/>业务用例]
    Application --> Ports[application/ports<br/>外部能力契约]
    Application --> Domain[domain<br/>模型与确定性规则]
    Interfaces -. 创建并注入 .-> Infrastructure[infrastructure<br/>外部系统适配器]
    Infrastructure -. 实现 .-> Ports
    Infrastructure --> Domain
    Infrastructure --> Moodle[HKU Moodle / Playwright]
    Infrastructure --> Resources[resources / JSON / PDF]
```

层间依赖关系为：

```text
interfaces ───────> application ───────> domain
     │                   │
     │                   └──> application/ports
     │
     └──> infrastructure ───> application/ports + domain
```

`domain` 集中保存 Pydantic 模型和确定性规则；`application` 由领域模型、用例和端口组成；
`infrastructure` 实现 Moodle、存储、PDF、运行时和更新能力；`interfaces` 作为组合根创建
具体适配器并注入应用服务。项目使用 Python `Protocol` 描述端口，适配器以结构化类型实现
契约。`tests/test_enforce_architecture.py` 检查模块命名、层级结构和依赖图。

### 目录职责

```text
src/hsas/
├── interfaces/          # CLI、Dashboard、HTTP 请求与结果展示
├── application/         # 同步、规划、Profile、Execution、课件检索用例
│   └── ports/           # 应用拥有的 CourseGateway、PlanningRepository 契约
├── domain/
│   ├── courses/         # 课程、Assessment、课件模型与课程变化规则
│   └── planning/        # Profile、Execution、Plan 模型与规划算法
└── infrastructure/
    ├── moodle/          # Moodle 登录、发现、采集、下载、转换与同步事务
    ├── documents/       # PDF 文本提取、元数据与摘要分析
    ├── storage/         # 原子读写、仓储实现与课程快照发布
    ├── runtime/         # 用户数据目录、自动建目录与旧数据迁移
    └── updates/         # 固定 Git commit 的事务更新
```

### 主要文件与依赖关系

#### 接口层

| 文件 | 职责 | 调用关系 |
|---|---|---|
| `interfaces/run_cli.py` | 统一 `hsas` 命令入口、目录初始化、输出与退出码 | 创建仓储和 Moodle 适配器，调用 application 用例 |
| `interfaces/handle_commands.py` | Profile、Execution、Materials 子命令 | 调用 Profile、Execution、Plan 和检索服务 |
| `interfaces/run_dashboard.py` | 绑定 `127.0.0.1` 的 Dashboard API 与静态文件服务 | 使用与 CLI 相同的 application 服务和 infrastructure 适配器 |
| `interfaces/web/` | Dashboard 的 HTML、CSS 和 JavaScript | 调用本地 JSON API，由后端应用服务处理 resources 数据 |

#### 应用层与端口

| 文件 | 职责 | 主要依赖 |
|---|---|---|
| `application/ports/define_gateways.py` | 定义 `CourseGateway` 及同步、登录、课程列表返回类型 | 为 Moodle 适配器和测试替身提供统一契约 |
| `application/ports/define_repositories.py` | 定义 `PlanningRepository` | 依赖领域模型 |
| `application/synchronize_courses.py` | 通过 `CourseGateway` 表达登录、课程发现和同步用例 | `application/ports` |
| `application/generate_plans.py` | 加载规划输入、调用 Planner、验证并保存 Plan；检查 Plan 新鲜度 | `PlanningRepository`、planning domain |
| `application/orchestrate_plans.py` | 将 CLI 风格参数转换成 `PlanGenerationRequest` | `generate_plans.py` |
| `application/update_profile.py` | 确认、过滤、深度合并并验证 Profile patch | `PlanningRepository`、`StudentProfile` |
| `application/record_execution.py` | 幂等添加或纠正真实执行记录 | `PlanningRepository`、Plan/Execution 模型 |
| `application/retrieve_materials.py` | 对本地 PDF 提取文本进行分页、分块和 BM25 风格检索 | CourseArchive、PlanItem |

#### 课程领域

| 文件 | 职责 |
|---|---|
| `domain/courses/define_models.py` | 严格 Pydantic 模型基类 |
| `domain/courses/define_courses.py` | CourseArchive、Section、Activity、StoredFile 和统计模型 |
| `domain/courses/define_assessments.py` | Assessment、评分组、候选项与来源证据模型 |
| `domain/courses/define_documents.py` | PDF 元数据、正文分析与阅读时间模型 |
| `domain/courses/index_courses.py` | 为 CourseArchive 提供 section、activity 和 file 索引 |
| `domain/courses/calculate_statistics.py` | 重新计算课程、活动和下载统计 |
| `domain/courses/detect_changes.py` | 比较新旧课程归档中的 DDL、Assessment、Activity 和文件变化 |
| `domain/courses/expose_contracts.py` | 暴露稳定的课程数据契约 |

#### 规划领域

| 文件 | 职责 |
|---|---|
| `domain/planning/define_profile.py` | 学生目标、课程优先级、能力、偏好、限制和来源确认状态 |
| `domain/planning/define_execution.py` | 用户确认的真实学习记录与写入策略 |
| `domain/planning/define_plan.py` | IntegratedPlan、PlanItem、优先级、工作量、来源快照和里程碑 |
| `domain/planning/calculate_priority.py` | 根据 DDL、权重、难度、准备状态、工作量和 Profile 计算优先级 |
| `domain/planning/calculate_feedback.py` | 用 Execution Log 校准进度和预计工作量 |
| `domain/planning/generate_plan.py` | `PlannerEngine`：构造、筛选和排序关键事项，生成阶段里程碑 |
| `domain/planning/validate_plan.py` | 检查来源、引用、依赖、汇总、里程碑与 Execution 一致性 |

#### 基础设施层

| 文件 | 职责 | 主要协作对象 |
|---|---|---|
| `infrastructure/moodle/synchronize_courses.py` | `CourseGateway` 的 Moodle 实现；协调完整同步事务 | fetch、map、download、PDF、Assessment、change、snapshot |
| `infrastructure/moodle/fetch_moodle.py` | 持久化浏览器、登录检查、课程发现与 Moodle AJAX 获取 | Playwright、Settings |
| `infrastructure/moodle/map_courses.py` | 将 Moodle state 转换为 CourseArchive | courses domain |
| `infrastructure/moodle/download_files.py` | 同源校验、增量下载、大小限制、缓存验证和旧文件复用 | storage、CourseArchive |
| `infrastructure/moodle/parse_html.py` | 从 Moodle HTML 提取课程和活动信息 | courses domain |
| `infrastructure/moodle/display_progress.py` | 显示课程同步阶段与下载进度 | Rich |
| `infrastructure/moodle/record_sync.py` | 维护每门课程的同步结果和 Plan 警告 | `sync-report.json` |
| `infrastructure/moodle/assessments/` | 从 Moodle 和 syllabus 提取、清洗、合并并验证 Assessment | Assessment domain |
| `infrastructure/documents/analyze_pdfs.py` | 提取 PDF 正文、页码、关键词、摘要和阅读时间 | StoredFile、PdfAnalysis |
| `infrastructure/storage/persist_data.py` | 原子 JSON、文本和二进制读写 | 所有需要持久化的适配器 |
| `infrastructure/storage/implement_repositories.py` | `PlanningRepository` 的本地 JSON 实现 | application ports、planning models |
| `infrastructure/storage/publish_courses.py` | 带锁、staging、journal、backup 和恢复的课程快照事务 | CourseArchive 验证 |
| `infrastructure/runtime/resolve_paths.py` | 解析平台标准目录并自动建立 resources、state、cache 等目录 | CLI、Settings |
| `infrastructure/runtime/migrate_data.py` | 复制、校验并报告旧版仓库内数据迁移 | runtime paths |
| `infrastructure/updates/update_installation.py` | dry-run 后按完整 Git commit 更新，失败时恢复 | Git、runtime paths |

### 运行时目录如何自动生成

每次 CLI 启动时，`interfaces/run_cli.py` 会调用 `get_runtime_paths().create()`；传入
`--resources` 时调用 `ensure_resources_layout()`，两条路径都会建立核心目录。

```text
HSAS data directory/
├── config.toml
├── browser-profile/
├── resources/
│   └── courses/
├── state/
├── cache/
└── logs/
```

Profile、Execution Log 和 Integrated Plan 在对应操作首次成功执行时创建；课程目录及
`course.json` 由同步事务创建。

### 课程同步工作流

```mermaid
flowchart LR
    Command[CLI 或 Dashboard] --> Service[CourseSynchronizationService]
    Service --> Gateway[MoodleCourseGateway]
    Gateway --> Fetch[发现课程并获取 Moodle state]
    Fetch --> Stage[复制上一份有效快照到 staging]
    Stage --> Map[转换 CourseArchive]
    Map --> Download[下载或复用课件]
    Download --> PDF[分析 PDF 正文]
    PDF --> Assessment[构建 AssessmentOverview]
    Assessment --> Change[比较新旧变化]
    Change --> Validate[验证 staged course.json]
    Validate --> Publish[原子发布课程快照]
    Publish --> Report[更新 sync-report.json]
```

单门课程拥有独立写锁。同步期间所有操作发生在 staging 目录，完整 CourseArchive 验证
成功后替换 live 目录；中断或发布异常时恢复上一份有效快照。

### Integrated Plan 生成工作流

```mermaid
flowchart LR
    Repo[PlanningRepository] --> Inputs[Profile + Execution Log + CourseArchives + 旧 Plan]
    Inputs --> Planner[PlannerEngine]
    Planner --> Priority[优先级、工作量、反馈和里程碑]
    Priority --> Validation[validate_integrated_plan]
    Validation -->|有效| Save[原子保存 integrated_plan.json]
    Validation -->|无效| Keep[保留上一份有效 Plan]
```

Planner 会把 Assessment 与未被 Assessment 覆盖的课程 Activity 转换为 PlanItem，结合
Profile 和 Execution Log 估算剩余投入，保留仍有效的旧进度，筛选关键事项并生成论文、
考试、项目和演示等不同类型的阶段里程碑。`source_snapshot` 记录本次计划使用的 Profile、
Execution Log 和 CourseArchive 版本，用于判断计划是否过期。

### Profile 与 Execution 工作流

Profile patch 工作流记录用户确认状态，完成深度合并与完整模型验证后原子保存；规范资源
路径中的 Profile 更新会请求重新生成 Plan。

Execution 记录引用现有 PlanItem。相同 `record_id` 和相同内容形成幂等重试，不同内容形成
冲突结果。Execution Log 保存后重新生成 Plan，`FeedbackIndex` 据此更新完成进度、实际投入
和保守的工作量校准。

```text
用户输入与确认状态
    ↓
接口层解析和检查
    ↓
application 验证业务规则
    ↓
PlanningRepository 原子保存
    ↓
重新生成并验证 Integrated Plan
```

### 本地 RAG 工作流

```text
问题或 PlanItem
    ↓
ArchiveIndex 定位相关课程和课件
    ↓
读取 PDF 提取文本与页码标记
    ↓
分页、分块、英文词与中文二元词分词
    ↓
BM25 风格检索与排序
    ↓
组成带正文、课程、文件、相对路径和页码的 RAG context
```

检索结果保留来源信息，并作为上下文交给 AI 解释课程内容和设计学习动作。

更详细的事务、依赖和更新设计见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 快速开始

### 环境要求

- macOS 或 Linux；
- Python 3.11 或更高版本；
- 可正常访问 HKU Moodle 的账号；
- 首次登录时由用户本人完成 HKU SSO/MFA。

### 安装

```bash
git clone https://github.com/Jerry6921/HSAS.git
cd HSAS
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -c requirements.lock -e .
playwright install chromium
```

HKU Moodle 地址包含在默认配置中，其他运行参数可通过本地配置文件调整。

### 打开本地 Dashboard

```bash
hsas ui
```

浏览器会打开 `http://127.0.0.1:8765`。Dashboard 绑定本机地址，可以：

- 检查 Moodle 登录状态并打开登录窗口；
- 同步全部课程或指定课程；
- 查看优先事项、排序理由、DDL、工作量和警告；
- 按课程与 section 浏览并打开已下载课件；
- 查看完整课程信息；
- 记录带用户确认状态的实际学习时间和完成进度，并自动刷新计划。

首次使用时，在 Dashboard 中依次完成登录和课程同步。HKU SSO/MFA 交互发生在 Playwright
打开的 HKU 登录页面，HSAS 保存登录后的本地浏览器 profile。

### 命令行使用

偏好终端的用户可以运行：

```bash
hsas list-status       # 查看登录、同步和计划状态
hsas login             # 完成 Moodle 登录
hsas sync-courses      # 同步全部课程
hsas update-plan       # 重新生成优先事项
```

运行 `hsas --help` 或相应子命令的 `--help` 查看完整选项。

## 与 AI Agent 配合

HSAS 可以与能够读取项目文件和运行本地命令的 AI Agent 配合。Agent 会通过项目自带的
操作入口检查数据新鲜度、检索相关课件，并解释 Planner 的结果。

例如：

```text
检查当前状态，告诉我各课程的同步状态。
同步课程并更新计划，然后解释最高优先级的三项任务。
检索最高优先事项对应的课件，给出学习方法、预计投入和自测标准。
```

AI Agent 通过 HSAS 命令、应用服务和本地 RAG 读取课程依据。Profile 和学习进度写入流程
记录用户确认状态，并在写入后触发模型验证和计划刷新。

## 本地数据目录

HSAS 将软件代码与个人数据分开保存。macOS 默认数据目录为：

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

Linux 使用 platformdirs 提供的标准用户目录；macOS 和 Linux 都可以通过 `HSAS_DATA_DIR`
自定义数据位置。

Git 跟踪内容由软件代码、测试、文档和配置模板组成。课程资料、个人计划、执行记录和浏览器
profile 存放在本地数据目录。当前本地 RAG 使用 BM25 风格词法检索，提取文本、检索过程和
RAG context 位于该数据目录。

## 更多信息

- [代码架构与事务设计](ARCHITECTURE.md)
- [Moodle 采集与数据说明](MOODLE_COLLECTOR.md)
- [数据与更新设计](SECURITY.md)

## License

HSAS is released under the [MIT License](LICENSE).
