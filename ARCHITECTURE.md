# HIQS 架构与数据流

HIQS 把课程资料收集、AI 理解和日历展示分开。程序负责完整保存资料、提供可读副本、验证
AI 写入的事实，并把事实确定性映射到日历；完整 Assessment 由 AI 依据来源归纳。

## 主链路

```mermaid
flowchart LR
    StudentCenter[HKU SIS Student Center] --> Roster[当前学期课程名单]
    Roster --> Collector
    Roster --> SIS[HKU SIS Course Information]
    Moodle[HKU Moodle 与授权外部文件] --> Collector[Collector]
    Collector --> Files[本地原文件]
    Collector --> Text[PDF DOCX PPTX 文本副本]
    Collector --> OCR[OCR Queue]
    OCR --> Text
    Collector --> Queue[待处理变化队列]
    SIS --> SisText[清洗后的官方课程正文]
    SIS --> SisQueue[独立内容哈希与差异队列]
    Files --> AI[AI 阅读]
    Text --> AI
    Queue --> AI
    SisText --> AI
    SisQueue --> AI
    Roster --> AI
    User[用户在 AI 对话中补充] --> AI
    AI --> Inbox[Personal Inbox 草稿与差异预览]
    Inbox --> Validator
    AI --> Update[information update JSON]
    Update --> Validator[Schema 校验与原子 upsert]
    Validator --> Store[information.json]
    Validator --> Checkpoint[成功后推进 AI 处理游标]
    Store --> Calendar[本地查询日历]
```

职责边界：

- Student Center Collector：读取当前学期注册课程名单，保存原始可读文本、课程代码和独立审阅 checkpoint；
- Collector：按注册课程发现 Moodle 活动、下载文件、记录来源与失败；
- SIS Course Information Collector：从 Student Center 课程代码查询官方课程页，清洗页面并保存可读副本、来源和内容哈希；
- AI：阅读原文件或文本副本，识别课程、tutorial、DDL、课业要求、形式和占分；
- Information Service：检查类型、范围、唯一 ID、课程引用与时间关系，原子写入；
- Change Queue：区分首次全量与后续增量，提供精确文件路径并记录处理游标；
- OCR Queue：识别扫描 PDF 与图片型 PPT，调用本地 OCR 并更新可搜索 sidecar；
- Personal Inbox：暂存用户通过 AI 补充的课程信息，并在逐字段预览与确认后进入统一校验；
- Calendar：只读投影，展开重复时间并显示具体项目；
- 用户：授权资料范围，并可通过 AI 对话确认额外事实或更正。

## 四层代码结构

```text
src/hsas/
├── interfaces/       CLI、本地 HTTP API、HTML/CSS/JavaScript
├── application/      信息 upsert、资料检索与课程同步用例
├── domain/
│   ├── information/  information.json 与 update 的严格模型
│   └── courses/      Moodle 归档、文件与文本分析模型
└── infrastructure/
    ├── moodle/       登录、发现、下载和快照事务
    ├── sis_course_info/ HKU SIS 登录、课程页面采集与独立 checkpoint
    ├── documents/    PDF、DOCX、PPTX 文本提取与本地 OCR
    ├── storage/      原子 JSON/文件持久化
    └── runtime/      本地数据目录
```

依赖方向保持：

```text
interfaces ──> application ──> domain
     │
     └───────> infrastructure ──> application ports + domain
```

领域层保持纯模型与规则。应用层通过
`InformationRepository` 端口保存信息库，基础设施层提供 JSON 实现。

## Moodle Collector

一次同步在 staging 目录内完成，成功后才替换上一份课程快照：

```mermaid
flowchart LR
    Discover[发现课程活动] --> Map[保存 Moodle state]
    Map --> Download[下载所有可访问文件]
    Download --> PDF[提取 PDF 文本]
    PDF --> Office[提取 DOCX PPTX 文本与备注]
    Office --> Changes[比较文件和活动变化]
    Changes --> Validate[验证 CourseArchive]
    Validate --> Publish[原子发布]
```

下载器接受 Moodle `pluginfile.php` 附件及各类文件响应，并通过响应类型与来源规则确认
文件。文件受最大大小、超时和并发配置约束。原始字节仅写入本地存储。

Google Workspace 链接是受控例外：`docs.google.com/document`、`presentation` 和
`spreadsheets` 链接分别尝试导出 DOCX、PPTX、XLSX。若导出返回登录页或权限页，活动
标为 external，并记录原因。

条件请求使用 ETag 和 Last-Modified；内容一致时复用原路径。失败同步期间继续使用上一份
有效课程目录。

## AI 可读资料

每个 `StoredFile` 保存：

- 原文件名、本地相对路径与已清理的来源 URL；
- MIME type、字节数、SHA-256、下载和校验时间；
- 若可提取，保存 extraction method、状态、文字量、警告和文本副本路径。

文本副本位于课程目录的 `analysis/text/`：

- PDF 使用 `--- Page N ---`；
- PPTX 使用 `--- Slide N ---` 并附 speaker notes；
- DOCX 包含正文及可见的页眉、页脚、脚注、尾注和批注文本。

`hsas materials list` 输出所有原文件和文本副本的绝对路径，方便 AI 直接读取；
`hsas materials search` 对已有文本副本作本地检索。原文件始终保留，AI 可按格式使用相应
文档工具读取各类资料。

HKU SIS 课程页面保存在 `sis-course-info/courses/<COURSE_CODE>/latest.txt` 与
`latest.html`。采集器只截取可见课程正文、移除 PeopleSoft 导航和会话状态，并记录安全的
Subject/Catalogue URL 与 SHA-256。课程事实保持由 AI 阅读，页面结构差异不会进入固定事实
parser。当前学期课程名单保存在 `sis-enrollment/latest.json`，Student Center 可见正文
保存在 `sis-enrollment/latest.txt`；课程名单的变化使用独立 batch 与 checkpoint 交给 AI
审阅。相同课程的多个 Moodle section 共用一份 SIS 来源。Class Planner 与 SIS 访问器
共享持久化 HKU Portal browser profile；SIS 登录从 `z_signon.jsp` 开始，并由用户在可见
窗口完成可能出现的图形验证码。统一同步先完成登录与 Student Center 课程名单采集，随后由
application 层的 `UnifiedCourseSyncService` 编排来源任务。infrastructure 层的
`BrowserSessionBroker` 在整个采集阶段只打开一个 headless Chromium context，Moodle、SIS
Course Information 和 Class Planner 各自使用独立 page 并通过 `asyncio.gather` 并发运行。
来源分别写入自己的目录，聚合状态只在锁内更新。

提取器会把文字覆盖不足的扫描 PDF 和图片型 PPT 标为 `ocr_required`。`hsas ocr status`
读取这些分析记录生成队列，`hsas ocr run --confirmed` 使用本地 Apple Vision 或
Tesseract/Poppler 批量识别。识别结果追加到文本副本并重新计算哈希、摘要、关键词和阅读
时间，随后原子更新对应 `course.json`。

## Incremental AI Review

每次成功同步都会比较上一份快照，并把活动、Moodle 日期和课件的新增、修改或删除写入
`courses/<course_id>/changes/history/`。课件变化携带原文件、文本副本和来源 URL；历史记录
随课程快照事务保留。

`ai-state/change-checkpoint.json` 为每门课程保存 AI 已处理到的 `collected_at`。课程等待
首个游标时，`changes show` 生成 `full` review；已有游标时则汇总之后的 change sets。输出批次
携带 `acknowledge_through`，因此生成批次后发生的新同步会使旧批次失效。

```text
changes show → AI 阅读列出的 files → information apply --changes → checkpoint
```

checkpoint 在信息写入成功后推进。信息已保存而游标确认失败时，变化保持 pending 以支持
安全重试。审查确认课程事实保持一致时，使用带双重确认的独立 acknowledge。

HKU SIS 页面使用 `sis-course-info/history/` 和 `review-checkpoint.json` 维护独立增量队列。
AI 先阅读变更记录指向的 `text_relative_path`，并以 `source_type: sis_course_info` 引用来源。
Moodle 当前页面、活动元数据、公告与课程资料拥有最高优先级；SIS 和 Class Planner 补充
Moodle 未陈述的事实。来源冲突时采用 Moodle 支持的值，同时保留双方证据与警告。

## Information Store

`information.json` 是日历的唯一事实输入：

```text
InformationStore
├── schema_version
├── timezone
├── updated_at / updated_by
├── courses[]
│   ├── course_id / moodle_course_id / code / title / color
│   ├── semester / starts_on / ends_on / overview / objectives
│   ├── instructors / links
│   └── policies / notes / sources
└── items[]
    ├── item_id / course_id / title / category
    ├── date_status
    ├── opens_at / starts_at / ends_at / due_at / due_on / scheduled_on
    ├── recurrence
    ├── location / description
    ├── assessment_format / submission_method
    ├── weight_percent / word_limit
    └── requirements / policies / warnings / links / materials / sources
```

类别覆盖课程、tutorial、lab、office hour、assignment、quiz、exam、presentation、
project、report、reading、deadline 和 other。

重复规则使用 Monday=0 到 Sunday=6，并带有效起止日期、开始/结束时间、排除日期和补课
日期。确认状态的事项必须有日期或重复规则；结束时间必须晚于开始时间；占分必须在 0–100。

## Upsert 事务

`InformationUpdate` 是 AI 写入格式。应用服务执行：

1. 要求显式 `--confirmed`；
2. 验证 update；
3. 读取并验证当前 store；
4. 按稳定 `course_id` 和 `item_id` 合并完整记录；
5. 验证合并结果中所有 item 都指向已存在课程；
6. fsync 临时文件后用 `os.replace` 原子替换。

省略记录会保留，删除使用显式流程。任何失败都发生在替换前。

## Personal Inbox

`ai-state/personal-inbox.json` 保存 AI 根据用户明确陈述准备的 `InformationUpdate` 草稿。
每条草稿拥有稳定 ID、创建时间、备注和 pending/applied 状态。Dashboard 与
`hsas inbox list` 将草稿同当前 `information.json` 比较，呈现 create/update 动作以及
逐字段 before/after。用户确认单条草稿后，应用服务调用现有 Information upsert，再把
Inbox 条目标为 applied。

## Dashboard

本地 HTTP 服务只绑定 `127.0.0.1`。浏览器通过 `GET /api/information` 获取已经验证的
store。首页以一个入口先建立共享 HKU Portal 会话并运行 Student Center，再并发采集 Moodle、
SIS Course Information 与 Class Planner；单一进度条显示阶段、当前课程和完成数量。同时
集中本地刷新、资料状态、OCR 队列、Personal Inbox、资料搜索和 pending review 差异。日历作为
独立侧栏页面。JavaScript 在当前 42 天月历网格内展开 weekly recurrence，并提供按日排列
开始与结束时间的议程视图。两种视图共享课程与全文筛选，日期待确认事项单独列出。

课程概览也由同一个端点返回。课程概述与目的由 AI 根据官方资料归纳后写入已校验的
`information.json`；成绩构成由带 `weight_percent` 的事项汇总；全部课件和新增/修改标记
来自最新 Moodle archive 与 pending review。程序综合 activity 类型、标题、section 与
文件名，在学习材料/课程信息两大区内继续标记 Lecture、Tutorial、Notes、Exercises、
Reading、Assessment 等类型。课件内容由 AI 阅读，页面呈现经过验证的课程事实。

日历详情显示 DDL、时间、地点、形式、提交方式、占分、字数、要求、政策、警告、链接、
AI 关联的学习材料和来源。`GET /api/source-preview` 只接受当前课程快照中的白名单路径；PDF 与图片使用同源原文
预览，DOCX/PPTX 使用已提取文本预览，并保留打开原文件的入口。首页问答式搜索只匹配本地
结构化事项和课件目录。AI 写入的字符串使用 DOM `textContent` 作为纯文本呈现。

## macOS App 与发布包

`HIQS.app` 使用 Swift/AppKit 创建原生窗口，并以 WKWebView 承载 Dashboard。App 启动时从
Bundle Resources 运行 PyInstaller 冻结的 `hiqs-backend`，令其绑定随机回环端口；从后端
启动输出取得地址后加载页面。窗口不提供地址栏，HTTP 服务继续限制在 `127.0.0.1`。

WKNavigationDelegate 允许回环页面导航，并把 Moodle 等外部 HTTP(S) 链接交给系统浏览器。
App 退出时终止后端子进程。DMG 构建脚本同时打包匹配的 Playwright Chromium，并通过
`PLAYWRIGHT_BROWSERS_PATH` 指向 Bundle 内浏览器，因此登录和同步不依赖额外安装步骤。

`scripts/build_macos_dmg.sh` 固定执行 Python 冻结、Swift 编译、Bundle 组装、ad-hoc 签名、
DMG 压缩与 SHA-256 输出。版本来自 `src/hsas/__init__.py`，并同步写入 Info.plist。

## 有限兼容

旧 CLI 名称 `hsas` 和默认数据目录 `HSAS` 保留，以继续访问用户已经下载的资料。
读取旧 `course.json` 时会忽略历史 `assessments` 字段；Planner、Student Profile、
Execution Log、Assessment Parser 及其命令均已从代码库移除。
