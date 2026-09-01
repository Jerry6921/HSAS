# HKU Moodle Collector (MVP)

一个本地运行、配置驱动的 Moodle 数据采集器。它使用 Playwright 的持久化浏览器 profile 保留 HKU SSO/MFA 登录会话，优先调用 Moodle 课程状态 AJAX 方法，并通过 Pydantic 输出稳定 JSON；HTML parser 保留为 fallback。

> 仅采集你有权访问的课程，并遵守 HKU/Moodle 使用政策。用户数据目录中的 `browser-profile/` 含登录 cookie，不能提交或分享。

## 目录

```text
HSAS/
├── config/defaults.toml                # HKU Moodle 公开默认配置
├── config/selectors.example.json       # 所有易变 CSS selector
├── src/hsas/
│   ├── interfaces/                     # CLI 与 Agent 适配器
│   │   ├── run_cli.py
│   │   └── handle_commands.py
│   ├── application/                    # 用例编排
│   │   ├── synchronize_courses.py
│   │   ├── generate_plans.py
│   │   ├── retrieve_materials.py
│   │   ├── update_profile.py
│   │   └── record_execution.py
│   ├── domain/                         # 无外部 I/O 的领域规则
│   │   ├── courses/
│   │   │   ├── define_courses.py
│   │   │   ├── define_assessments.py
│   │   │   ├── index_courses.py
│   │   │   └── detect_changes.py
│   │   └── planning/
│   │       ├── define_profile.py
│   │       ├── define_execution.py
│   │       ├── define_plan.py
│   │       ├── calculate_priority.py
│   │       ├── generate_plan.py
│   │       └── validate_plan.py
│   └── infrastructure/                 # 外部系统与持久化
│       ├── moodle/                     # Moodle 获取、映射与 Assessment 解析
│       ├── documents/analyze_pdfs.py
│       ├── storage/                    # 原子写入与课程快照发布
│       ├── runtime/                    # platformdirs 路径与旧数据迁移
│       └── updates/                    # 受信任 Git 更新与失败回滚
├── src/AI_Skills/                      # AI 操作与规划规范
├── tests/                              # 离线解析测试
└── pyproject.toml
```

`interfaces/run_cli.py` 只负责组合命令；`interfaces/handle_commands.py` 是薄适配层。
`application/` 编排同步、规划、检索和用户确认写入，`domain/` 保存纯领域模型与确定性
规则，`infrastructure/` 承担 Moodle、PDF、磁盘和 Git 等外部副作用。所有普通 Python
模块采用动词职责名称；文件夹采用名词。磁盘写入统一经过
`infrastructure/storage/persist_data.py`，以同目录临时文件、刷新和原子替换避免截断已有 JSON。

### 加载和查询 course.json

`ArchiveIndex` 负责把磁盘 JSON 校验为强类型 `CourseArchive`，并一次性建立常用内存索引：

```python
from hsas.infrastructure.runtime import get_runtime_paths
from hsas.domain.courses.index_courses import ArchiveIndex

resources = get_runtime_paths().resources_dir
index = ArchiveIndex.from_json(resources / "courses/138907/course.json")
archive = index.archive

section = index.get_section("1594283")
activity = index.get_activity("4166630")
syllabus = index.find_document(role="syllabus")
assessment = index.get_assessment("final-essay")
```

公开只读映射包括 `sections_by_id`、`activities_by_id`、`files_by_path`、`files_by_sha256`、`assessments_by_id` 和 `groups_by_id`。如果其他服务增删了对象，调用 `index.rebuild()` 刷新索引；JSON 写回由 `infrastructure/storage/persist_data.py` 负责。

`domain/courses/calculate_statistics.py` 统计整个 `CourseArchive`，并不专属于 PDF。它在初始映射、文件下载、跳过下载和 PDF 分析后都会被调用。统计只需共享的 `iter_activities()` 轻量遍历，因此不会为了计数额外构建完整 `ArchiveIndex`。

## 安装

需要 Python 3.11+：

```bash
cd "/path/to/HSAS"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m playwright install chromium
```

HKU Moodle 的公开 URL 默认保存在 `config/defaults.toml`。如需本地覆盖，可在平台数据目录创建 `config.toml`，或使用已被 Git 忽略的 `.env`；不得在其中保存密码、cookie、MFA 或 sesskey。

若页面结构与示例不同，在浏览器开发者工具检查元素后，复制并修改 selector 文件：

```bash
mkdir -p "$HOME/Library/Application Support/HSAS"
cp config/selectors.example.json \
  "$HOME/Library/Application Support/HSAS/selectors.json"
```

随后在用户 `config.toml` 的 `[moodle]` 中设置 `selector_config`，或通过 `MOODLE_SELECTOR_CONFIG` 环境变量覆盖。每个字段接受多个候选 selector，程序使用第一个能匹配到节点的候选项。

```toml
[moodle]
selector_config = "selectors.json"
```

旧版项目内数据可一次性复制到平台目录：

```bash
hsas migrate-data
```

迁移会先检查目标冲突，再原子复制并逐文件验证 SHA-256；旧的 `src/resources/`、`.moodle-profile/` 和 `.env` 不会被自动删除。迁移报告保存在用户数据目录的 `state/migration-report.json`。

代码更新固定使用 `https://github.com/Jerry6921/HSAS` 的 `main` 分支：

```bash
hsas update-hsas --dry-run
hsas update-hsas --commit FULL_40_CHARACTER_COMMIT
```

更新器验证项目名称、Python 语法和 updater 兼容性，只同步 Git 跟踪的代码文件，跳过个人数据路径，并在代码复制失败时回滚。HTTPS 更新必须先 dry-run，再以完整 commit 精确授权；依赖变化交给包管理器处理。

## 运行

首次登录（会打开可见 Chromium）：

```bash
hsas login
```

在浏览器中手动完成 HKU SSO/MFA，看到 Moodle dashboard 后回到终端按 Enter。之后 session cookie 保存在平台数据目录的 `browser-profile/`。

检查登录状态、Moodle 可用课程和本地已下载课程：

```bash
hsas list-status
```

下载并完整处理一门课程。参数可以是 `list` 显示的数字 ID：

```bash
hsas sync-courses 123
```

也可以传入完整课程 URL：

```bash
hsas sync-courses 'https://YOUR-MOODLE-HOST.example.edu/course/view.php?id=123'
```

下载并完整处理 dashboard 上的全部课程：

```bash
hsas sync-courses
```

`sync-courses` 带 ID/URL 时处理单课，不带参数时遍历全部课程；两种模式使用相同管线：获取 AJAX state、在隔离目录对象化、复用或下载文件、PDF 正文分析、运行 Assessment Parser、生成 ChangeSet、验证完整快照，最后通过带恢复日志的目录切换发布整门课程。批量模式中一门课程失败不会中断其余课程，单课和批量结果都会合并进 `sync-report.json` 的逐课程状态。

增量同步会按 Moodle activity ID 和清理后的文件 URL 匹配旧文件。`StoredFile` 会持久化服务端返回的 `etag`、`last_modified` 和 `validated_at`；后续同步发送 `If-None-Match`/`If-Modified-Since`，收到 `304` 时直接复用本地文件与 PDF analysis。服务端不支持 validator 时仍以 SHA-256 判断正文是否变化；内容变化时更新原路径并重新分析。字段级变化保存在 `changes/latest.json`，实际有变化的同步还会写入 `changes/history/`，覆盖 Assessment DDL、项目/分组权重、activity 状态以及课件新增、删除和内容变化。

根据全部已同步课程和 Student Profile 自动生成或更新综合计划：

```bash
hsas update-plan
```

`hsas update-plan` 默认更新平台 resources 目录中的 `integrated_plan.json`。它会保留进度和实际耗时，重算课程引用、重要程度、难度、剩余耗时、优先级、排序理由和里程碑。论文/报告使用“要求与论点→研究提纲→初稿→修订→提交检查”，考试使用“诊断→知识覆盖→针对练习→模考→最终复习”，项目和演示也分别使用构建/整合与幻灯片/彩排阶段；普通 assessment 保留简洁的 ready 节点。所有内部节点均早于官方 DDL buffer。

新版 Integrated Plan 是 priority backlog，不是日历：JSON 不保存 timetable、具体可用时段或容量分配。Python 只负责稳定地回答“哪些要务更优先、为什么、预计还需多少投入、怎样算完成”。学生或 AI 可使用可选的每周学习预算判断总体负担，但实际何时学习由学生决定。

生成 Plan 后，AI 可按某个高优先级事项检索课件正文：

```bash
hsas materials for-item PLAN_ITEM_ID
hsas materials search "topic or concept" --course COURSE_ID --limit 5
```

检索结果保留 course、activity、文件路径和 PDF 页码。AI 应依据这些证据给出合适的学习方法、大致耗时和可自测成果，而不是把学习动作安排到具体日期或时间。当前实现是无需外部 API 的本地关键词 RAG；扫描型 PDF 在完成 OCR 前不会被当作已读正文。

同步时终端会显示阶段进度和当前负责组件，例如：

```text
138907 MoodleAPI         ━━━━━━  14% Fetching core_courseformat_get_state
138907 StateMapper       ━━━━━━  29% Mapping Moodle state
138907 FileStore         ━━━━━━  43% Saving raw course state
138907 Downloader        ━━━━━━  57% 3/12 downloading: Week 2 lecture slides
138907 PdfAnalyzer       ━━━━━━  71% Extracting PDF text
138907 AssessmentParser  ━━━━━━  86% Structuring assessments
138907 ChangeDetector    ━━━━━━  93% Comparing plan-relevant changes
138907 FileStore         ━━━━━━ 100% Saving course.json
```

不带参数的 `sync-courses` 还会额外显示 Moodle API 遍历进度和 `All courses` 总进度。组件名表示当前执行职责；这些处理器目前大多是函数式模块，并不一定是 Python class。

macOS 默认输出目录：

```text
~/Library/Application Support/HSAS/resources/courses/123/
├── course.json
├── raw/course-state.json
├── analysis/text/                       # 每份 PDF 的完整提取正文
└── files/
    ├── 00-General/
    └── 01-Week-1/
```

`course.json` 使用 v2 schema，按 section 保存 activity。每个已下载文件记录相对于当前 resources 根目录的 `relative_path`，以及移除 sesskey/token 后的 `source_url`、MIME、字节数、SHA-256、下载时间、HTTP validator 和最近校验时间。

默认在下载后执行 PDF 正文分析，包括页数、可提取文字页数、字数、按 200 WPM 估算的阅读时间、关键词、明确标记为 `extractive` 的摘要、PDF metadata、正文 `.txt` 路径与正文 SHA-256。扫描型 PDF 不会伪造结果，而会设为 `partial` 和 `ocr_required=true`。

通用 Assessment Parser v1 会让 Moodle section/activity、渲染页面补全的 Label 文本和 syllabus extractor 分别产生带置信度的候选项，再按规范化标题合并证据、报告字段冲突并校验总权重。它能识别 Label 中的评分比例、month-first/day-first 日期、TBD 和独立 bonus，也能识别 syllabus 中“总权重 + 多个子权重”的组合评分项。整个流程不匹配课程 ID、课程代码或课程名，也不存在单独课程插件。输出包含分组/项目权重、bonus、字数限制、开放期、截止时间、scheduled date、来源页或 activity ID、确认状态、提取方法和课程政策。即使 syllabus PDF 不可用，Parser 仍会保留 Moodle 结果，并把低置信度 section 项目标记为 tentative。用户学习档案独立保存在平台 resources 目录的 `student_profile.json`，不会写入课程归档。

同步命令下载 Moodle 同源的 PDF、Office/OpenDocument、文本、压缩包和图片；外部 URL 只记录、不自动访问。单文件上限和并发数由 `.env` 的 `MOODLE_MAX_DOWNLOAD_BYTES` 与 `MOODLE_DOWNLOAD_CONCURRENCY` 控制。

运行离线测试：

```bash
pytest
```

## Schema 和分类边界

`CourseArchive` 当前 schema 为 `2.2`，含课程信息、sections、activities、文件及 PDF analysis、结构化 assessments、统计和原始状态路径；读取端仍兼容 `2.0` 与 `2.1`。Moodle 的 course/section/course-module ID 会原样保留，便于增量同步。`CourseSnapshot` v1 继续服务于 HTML fallback。

API state 直接提供 `module` 与 `plugin`，主要分类如下：

- `assign`：assignment
- `forum` 且标题包含 announcement/公告/通知：announcement
- `forum`：普通论坛
- `quiz`：测验
- `resource/folder/page/book`：课程资源
- `url`：外部链接，只保存地址

当前课程状态方法仍不包含 assignment deadline 和 announcement 帖子正文；这些需要后续调用对应 activity API。HTML fallback 仍采用旧版 URL 规则。

## 技术栈

- **Playwright**：执行 JavaScript、处理 SSO 跳转，并通过 persistent context 保持会话。
- **BeautifulSoup**：离线解析已渲染 HTML，使解析逻辑易测试、无需每次启动浏览器。
- **Pydantic v2**：校验运行配置、URL 与输出 schema。
- **platformdirs**：在 macOS、Linux 和 Windows 上解析标准个人数据、缓存与日志目录。
- **Typer**：提供简洁的命令行入口。
- **pytest**：用固定 HTML fixture 防止解析规则回归。
