# HSAS 架构、依赖关系与内部工作流

本文说明 HSAS 的代码分层、目录与文件职责、依赖方向、运行时目录，以及课程同步、规划、
学习反馈和本地 RAG 的内部运作过程。面向学生的产品介绍与安装方法见 [README](README.md)。

## 整体架构

HSAS 使用四层架构。接口层接收 CLI、Dashboard 和 Agent 请求；应用层编排完整用例；领域层
保存课程、规划模型和确定性规则；基础设施层连接 Moodle、PDF、文件系统和 Git。

~~~mermaid
flowchart TB
    User[用户或 AI Agent] --> Interfaces[interfaces<br/>CLI 与本地 Dashboard]
    Interfaces --> Application[application<br/>业务用例]
    Application --> Ports[application/ports<br/>外部能力契约]
    Application --> Domain[domain<br/>模型与确定性规则]
    Interfaces -. 创建并注入 .-> Infrastructure[infrastructure<br/>外部系统适配器]
    Infrastructure -. 实现 .-> Ports
    Infrastructure --> Domain
    Infrastructure --> Moodle[HKU Moodle / Playwright]
    Infrastructure --> Resources[本地 JSON / PDF / 运行状态]
~~~

层间主要依赖关系为：

~~~text
interfaces ───────> application ───────> domain
     │                   │
     │                   └──> application/ports
     │
     └──> infrastructure ───> application/ports + domain
~~~

应用层拥有外部能力的 Python Protocol 契约，基础设施适配器以结构化类型实现这些契约。
接口层作为组合根创建具体适配器并注入应用服务。领域层不依赖 Typer、Playwright、平台路径、
文件持久化或更新传输。

项目采用 Protocol 而非抽象基类，使测试替身和基础设施适配器可以通过行为结构满足契约，
无需继承共同父类。tests/test_enforce_architecture.py 检查模块命名、目录层级和依赖方向。

## 目录职责

文件夹使用名词表达架构归属，普通 Python 模块使用动词短语表达行为。Python 规定的
__init__.py 与 __main__.py 为模块命名例外。

~~~text
src/hsas/
├── interfaces/          # CLI、Dashboard、HTTP 请求与结果展示
├── application/         # 同步、规划、Profile、Execution、课件检索用例
│   └── ports/           # CourseGateway、PlanningRepository 等应用契约
├── domain/
│   ├── courses/         # 课程、Assessment、课件模型与课程变化规则
│   └── planning/        # Profile、Execution、Plan 模型与规划算法
└── infrastructure/
    ├── moodle/          # Moodle 登录、发现、采集、下载、转换与同步事务
    ├── documents/       # PDF 文本、元数据、摘要和阅读量分析
    ├── storage/         # 原子读写、仓储实现与课程快照发布
    ├── runtime/         # 用户数据目录、自动建目录与旧数据迁移
    └── updates/         # 固定 Git commit 的事务更新
~~~

## 主要文件与依赖关系

### 接口层

| 文件 | 职责 | 调用关系 |
|---|---|---|
| interfaces/run_cli.py | hsas 命令入口、目录初始化、参数解析、输出和退出码 | 创建仓储和 Moodle 适配器，调用应用用例 |
| interfaces/handle_commands.py | Profile、Execution 与 Materials 子命令 | 调用 Profile、Execution、Plan 和检索服务 |
| interfaces/run_dashboard.py | 本地 Dashboard API 与静态文件服务 | 使用与 CLI 相同的应用服务和基础设施适配器 |
| interfaces/web/ | Dashboard 的 HTML、CSS 和 JavaScript | 调用本地 JSON API，展示应用服务返回的数据 |

接口层负责输入输出和适配器装配。业务规则由应用层与领域层执行，因此 CLI 与 Dashboard
共享同一组验证和规划行为。

### 应用层与端口

| 文件 | 职责 | 主要依赖 |
|---|---|---|
| application/ports/define_gateways.py | 定义 CourseGateway 及同步、登录、课程列表返回类型 | 领域模型 |
| application/ports/define_repositories.py | 定义 PlanningRepository | 规划领域模型 |
| application/synchronize_courses.py | 表达登录、课程发现和同步用例 | CourseGateway |
| application/generate_plans.py | 加载规划输入、调用 Planner、验证并保存 Plan；检查 Plan 新鲜度 | PlanningRepository、planning domain |
| application/orchestrate_plans.py | 将接口参数转换成 PlanGenerationRequest | generate_plans.py |
| application/update_profile.py | 合并并验证 Profile 更新 | PlanningRepository、StudentProfile |
| application/record_execution.py | 幂等添加或纠正真实学习记录 | PlanningRepository、Plan 与 Execution 模型 |
| application/retrieve_materials.py | 对本地 PDF 提取文本进行分页、分块和 BM25 风格检索 | CourseArchive、PlanItem |

应用层描述“完成一次操作需要哪些步骤”，并通过端口访问外部系统。它返回结果或类型化错误，
由接口层决定如何展示。

### 课程领域

| 文件 | 职责 |
|---|---|
| domain/courses/define_models.py | 课程领域的严格 Pydantic 模型基类 |
| domain/courses/define_courses.py | CourseArchive、Section、Activity、StoredFile 和统计模型 |
| domain/courses/define_assessments.py | Assessment、评分组、候选项与来源证据模型 |
| domain/courses/define_documents.py | PDF 元数据、正文分析与阅读时间模型 |
| domain/courses/index_courses.py | 为 CourseArchive 建立 section、activity 和 file 索引 |
| domain/courses/calculate_statistics.py | 重新计算课程、活动和下载统计 |
| domain/courses/detect_changes.py | 比较新旧课程中的 DDL、Assessment、Activity 和文件变化 |
| domain/courses/expose_contracts.py | 暴露稳定的课程数据契约 |

### 规划领域

| 文件 | 职责 |
|---|---|
| domain/planning/define_profile.py | 学生目标、课程优先级、能力、偏好、限制和确认状态 |
| domain/planning/define_execution.py | 真实学习记录及其写入模型 |
| domain/planning/define_plan.py | IntegratedPlan、PlanItem、优先级、工作量、来源快照和里程碑 |
| domain/planning/calculate_priority.py | 根据 DDL、占分、难度、准备状态、工作量和 Profile 计算优先级 |
| domain/planning/calculate_feedback.py | 使用 Execution Log 校准进度和预计工作量 |
| domain/planning/generate_plan.py | 构造、筛选和排序关键事项，生成阶段里程碑 |
| domain/planning/validate_plan.py | 检查来源、引用、依赖、汇总、里程碑与 Execution 一致性 |

领域层保存可独立测试的模型和规则。优先级、工作量、反馈与里程碑由确定性函数计算，外部系统
的变化不会进入这些模块。

### 基础设施层

| 文件 | 职责 | 主要协作对象 |
|---|---|---|
| infrastructure/moodle/synchronize_courses.py | CourseGateway 的 Moodle 实现；协调完整同步事务 | fetch、map、download、PDF、Assessment、change、snapshot |
| infrastructure/moodle/fetch_moodle.py | 浏览器会话、登录检查、课程发现与 Moodle AJAX 获取 | Playwright、Settings |
| infrastructure/moodle/map_courses.py | 将 Moodle state 转换为 CourseArchive | courses domain |
| infrastructure/moodle/download_files.py | 同源校验、增量下载、大小限制、缓存验证和旧文件复用 | storage、CourseArchive |
| infrastructure/moodle/parse_html.py | 从 Moodle HTML 提取课程和活动信息 | courses domain |
| infrastructure/moodle/display_progress.py | 显示课程同步阶段与下载进度 | Rich |
| infrastructure/moodle/record_sync.py | 维护每门课程的同步结果和 Plan 警告 | sync-report.json |
| infrastructure/moodle/assessments/ | 从 Moodle 和 syllabus 提取、清洗、合并并验证 Assessment | Assessment domain |
| infrastructure/documents/analyze_pdfs.py | 提取 PDF 正文、页码、关键词、摘要和阅读时间 | StoredFile、PdfAnalysis |
| infrastructure/storage/persist_data.py | 原子 JSON、文本和二进制读写 | 所有持久化适配器 |
| infrastructure/storage/implement_repositories.py | PlanningRepository 的本地 JSON 实现 | application ports、planning models |
| infrastructure/storage/publish_courses.py | 带锁、staging、journal、backup 和恢复的课程快照事务 | CourseArchive 验证 |
| infrastructure/runtime/resolve_paths.py | 解析平台标准目录并建立 resources、state、cache 等目录 | CLI、Settings |
| infrastructure/runtime/migrate_data.py | 复制、校验并报告旧版数据迁移 | runtime paths |
| infrastructure/updates/update_installation.py | dry-run 后按完整 Git commit 更新，失败时恢复 | Git、runtime paths |

## 运行时目录

CLI 启动时，interfaces/run_cli.py 调用 get_runtime_paths().create()。显式传入 resources
路径时，ensure_resources_layout() 建立相同的核心业务目录。

~~~text
HSAS data directory/
├── config.toml
├── browser-profile/
├── resources/
│   └── courses/
├── state/
├── cache/
└── logs/
~~~

Profile、Execution Log 和 Integrated Plan 在对应操作首次成功执行时创建。课程目录及
course.json 由同步事务创建。程序代码与学生数据位于不同目录，软件更新不以仓库路径承载
个人课程资料。

## 课程同步工作流

~~~mermaid
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
~~~

每门课程拥有独立写锁。同步过程在 staging 目录构建完整快照，验证成功后通过带 journal
的目录交换发布。中断或交换异常时，恢复上一份有效课程目录。sync-report.json 保留每门
课程的最近结果，因此单门课程失败不会覆盖其他课程的成功状态。

## Integrated Plan 生成工作流

~~~mermaid
flowchart LR
    Repo[PlanningRepository] --> Inputs[Profile + Execution Log + CourseArchives + 旧 Plan]
    Inputs --> Planner[PlannerEngine]
    Planner --> Priority[优先级、工作量、反馈和里程碑]
    Priority --> Validation[validate_integrated_plan]
    Validation -->|有效| Save[原子保存 integrated_plan.json]
    Validation -->|无效| Keep[保留上一份有效 Plan]
~~~

Planner 把 Assessment 与当前课程 Activity 转换为 PlanItem，结合 Profile 和 Execution Log
估算剩余投入，继承仍然有效的旧进度，再生成论文、考试、项目和演示对应的阶段里程碑。

IntegratedPlan.source_snapshot 记录本次规划使用的 Profile、Execution Log 和 CourseArchive
版本。assess_plan_freshness 将这些版本与当前输入比较，判断计划是否已经落后于课程或学生
进度。规划失败时，已确认的输入和上一份有效计划继续保留。

## Profile 与 Execution 工作流

~~~text
用户输入
    ↓
接口层解析
    ↓
application 验证业务规则
    ↓
PlanningRepository 原子保存
    ↓
重新生成并验证 Integrated Plan
~~~

Profile 更新经过合并和完整模型验证后保存。Execution 记录引用现有 PlanItem；相同
record_id 与相同内容形成幂等重试，不同内容形成冲突结果。Execution Log 保存后，
FeedbackIndex 更新完成进度、实际投入和保守的工作量校准。

## 本地 RAG 工作流

~~~text
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
~~~

检索结果保留课程和文件来源，供 CLI、Dashboard 或 AI Agent 使用。课件文本、检索索引和
RAG context 位于本地数据目录。

## Dashboard 边界

hsas ui 绑定 127.0.0.1，提供打包的静态资源和本地 JSON API。读取操作使用与 CLI 相同的
领域模型验证数据；进度记录和课程同步调用既有应用服务。写请求使用 JSON 和本地请求标记，
服务端不启用跨域访问。

## 更新边界

内置更新器同步 Git 跟踪的软件文件，并保留个人数据目录。HTTPS 更新采用两步流程：dry-run
取得完整 commit，再由用户以该 commit 执行更新。更新事务不处理依赖变化；依赖变化通过
正常的包管理器升级完成。
