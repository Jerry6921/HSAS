# HKU Moodle Collector (MVP)

一个本地运行、配置驱动的 Moodle 数据采集器。它使用 Playwright 的持久化浏览器 profile 保留 HKU SSO/MFA 登录会话，优先调用 Moodle 课程状态 AJAX 方法，并通过 Pydantic 输出稳定 JSON；HTML parser 保留为 fallback。

> 仅采集你有权访问的课程，并遵守 HKU/Moodle 使用政策。`.moodle-profile/` 含登录 cookie，不能提交或分享。

## 目录

```text
HSAS/
├── config/selectors.example.json       # 所有易变 CSS selector
├── src/command.py                       # 唯一 CLI：四个统一命令
├── src/moodle_collector/
│   ├── acquisition/                    # 阶段 1：访问与下载
│   │   ├── moodle_client.py            # 浏览器会话、课程发现与 AJAX service
│   │   └── file_downloader.py          # 同源课程文件下载与校验
│   ├── transformation/                 # 阶段 2：对象化与分析
│   │   ├── common/                     # 跨业务共享的通用结构和转换
│   │   │   ├── base_schema.py          # 严格 Pydantic 基类
│   │   │   ├── course_schema.py        # 通用课程归档 schema
│   │   │   ├── course_mapper.py        # Moodle state -> CourseArchive
│   │   │   ├── course_index.py         # activity/file/assessment 索引
│   │   │   ├── course_stats.py         # 归档统计
│   │   │   └── html_fallback.py        # HTML fallback
│   │   ├── course_materials/           # 课件处理
│   │   │   ├── pdf_schema.py           # PDF 分析 schema
│   │   │   └── pdf_analyzer.py         # PDF 正文提取与分析
│   │   └── assessment/                 # 通用 Assessment Parser v1
│   │       ├── extractors/
│   │       │   ├── moodle_extractor.py # Moodle 候选提取
│   │       │   └── syllabus_extractor.py # syllabus 候选提取
│   │       ├── schema.py               # 输出 schema 与候选模型
│   │       ├── parse_rules.py          # 标题、类型和日期规则
│   │       └── builder.py              # 合并、校验与最终构建
│   ├── storage/                        # 阶段 3：持久化
│   │   └── local_store.py              # JSON/文本/二进制原子写入
│   ├── settings.py                     # 配置与 selector schema
│   ├── sync_progress.py                # 同步进度显示
│   └── workflow.py                     # 登录、状态和同步内部流程
├── src/integrated_planner/             # 独立跨课程规划包
│   ├── profile_schema.py               # Student Profile Pydantic schema
│   ├── plan_schema.py                  # Integrated Plan Pydantic schema
│   ├── plan_validator.py               # 引用、时间与容量校验
│   ├── plan_rules.py                   # 重要度、难度、耗时与优先级规则
│   ├── plan_scheduler.py               # 可用时间与时间块分配
│   ├── planner_engine.py               # 课程任务对象化和增量更新
│   └── workflow.py                     # 计划生成和校验内部流程
├── src/AI_Skills/                      # AI 操作与规划规范
├── src/resources/                      # 课程、Profile 与 Plan 共享数据
├── tests/                              # 离线解析测试
└── pyproject.toml
```

根级 `command.py` 只负责四个命令的薄编排；两个模块的 `workflow.py` 分别管理课程同步与计划更新。acquisition 负责获取数据；transformation 下的 `common` 生成和查询通用课程对象，`course_materials` 处理课件，`assessment` 生成结构化考核。所有磁盘写入最终统一经过无 Moodle 业务知识的 `storage/local_store.py`。写入先落到同目录临时文件，完成并刷新后再原子替换目标文件，避免程序中断时截断已有 `course.json`。

### 加载和查询 course.json

`ArchiveIndex` 负责把磁盘 JSON 校验为强类型 `CourseArchive`，并一次性建立常用内存索引：

```python
from moodle_collector.transformation.common.course_index import ArchiveIndex

index = ArchiveIndex.from_json("src/resources/courses/138907/course.json")
archive = index.archive

section = index.get_section("1594283")
activity = index.get_activity("4166630")
syllabus = index.find_document(role="syllabus")
assessment = index.get_assessment("final-essay")
```

公开只读映射包括 `sections_by_id`、`activities_by_id`、`files_by_path`、`files_by_sha256`、`assessments_by_id` 和 `groups_by_id`。如果其他服务增删了对象，调用 `index.rebuild()` 刷新索引；JSON 写回由 `storage/local_store.py` 负责。

`course_stats.py` 统计整个 `CourseArchive`，并不专属于 PDF。它在初始映射、文件下载、跳过下载和 PDF 分析后都会被调用。统计只需共享的 `iter_activities()` 轻量遍历，因此不会为了计数额外构建完整 `ArchiveIndex`。

## 安装

需要 Python 3.11+：

```bash
cd "/path/to/HSAS"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m playwright install chromium
```

仓库中的 `.env` 已配置当前 Moodle 地址。如需更新，打开当前 HKU Moodle，复制浏览器实际显示的 host、登录页和 dashboard URL 到 `.env`。不要在其中保存密码、cookie、sesskey 或其他访问令牌。

若页面结构与示例不同，在浏览器开发者工具检查元素后，复制并修改 selector 文件：

```bash
cp config/selectors.example.json config/selectors.local.json
```

随后把 `.env` 中 `MOODLE_SELECTOR_CONFIG` 改为 `config/selectors.local.json`。每个字段接受多个候选 selector，程序使用第一个能匹配到节点的候选项。

## 运行

首次登录（会打开可见 Chromium）：

```bash
hsas login
```

在浏览器中手动完成 HKU SSO/MFA，看到 Moodle dashboard 后回到终端按 Enter。之后 session cookie 保存在 `.moodle-profile/`。

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

`sync-courses` 带 ID/URL 时处理单课，不带参数时遍历全部课程；两种模式使用相同管线：获取 AJAX state、对象化、复用或下载文件、PDF 正文分析、运行 Assessment Parser、生成 ChangeSet，最后原子写入 `course.json`。批量模式中一门课程失败不会中断其余课程。

增量同步会按 Moodle activity ID 和清理后的文件 URL 匹配旧文件。`StoredFile` 会持久化服务端返回的 `etag`、`last_modified` 和 `validated_at`；后续同步发送 `If-None-Match`/`If-Modified-Since`，收到 `304` 时直接复用本地文件与 PDF analysis。服务端不支持 validator 时仍以 SHA-256 判断正文是否变化；内容变化时更新原路径并重新分析。字段级变化保存在 `changes/latest.json`，实际有变化的同步还会写入 `changes/history/`，覆盖 Assessment DDL、项目/分组权重、activity 状态以及课件新增、删除和内容变化。

根据全部已同步课程和 Student Profile 自动生成或更新综合计划：

```bash
hsas update-plan
```

`hsas update-plan` 默认更新 `src/resources/integrated_plan.json`。它会保留进度、实际耗时和已开始/完成的时间块，重算课程引用、重要程度、难度、剩余耗时、优先级、里程碑和未来时间表。论文/报告使用“要求与论点→研究提纲→初稿→修订→提交检查”，考试使用“诊断→知识覆盖→针对练习→模考→最终复习”，项目和演示也分别使用构建/整合与幻灯片/彩排阶段；普通 assessment 保留简洁的 ready 节点。所有内部节点均早于官方 DDL buffer。Profile 未提供可用时间时仍会生成统一任务，但不会虚构时间块。

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

输出目录：

```text
src/resources/courses/123/
├── course.json
├── raw/course-state.json
├── analysis/text/                       # 每份 PDF 的完整提取正文
└── files/
    ├── 00-General/
    └── 01-Week-1/
```

`course.json` 使用 v2 schema，按 section 保存 activity。每个已下载文件记录相对于 `src/resources/` 的 `relative_path`，以及移除 sesskey/token 后的 `source_url`、MIME、字节数、SHA-256、下载时间、HTTP validator 和最近校验时间。

默认在下载后执行 PDF 正文分析，包括页数、可提取文字页数、字数、按 200 WPM 估算的阅读时间、关键词、明确标记为 `extractive` 的摘要、PDF metadata、正文 `.txt` 路径与正文 SHA-256。扫描型 PDF 不会伪造结果，而会设为 `partial` 和 `ocr_required=true`。

通用 Assessment Parser v1 会让 Moodle section/activity、渲染页面补全的 Label 文本和 syllabus extractor 分别产生带置信度的候选项，再按规范化标题合并证据、报告字段冲突并校验总权重。它能识别 Label 中的评分比例、month-first/day-first 日期、TBD 和独立 bonus，也能识别 syllabus 中“总权重 + 多个子权重”的组合评分项。整个流程不匹配课程 ID、课程代码或课程名，也不存在单独课程插件。输出包含分组/项目权重、bonus、字数限制、开放期、截止时间、scheduled date、来源页或 activity ID、确认状态、提取方法和课程政策。即使 syllabus PDF 不可用，Parser 仍会保留 Moodle 结果，并把低置信度 section 项目标记为 tentative。用户学习档案独立保存在 `src/resources/student_profile.json`，不会写入课程归档。

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
- **Pydantic v2 / pydantic-settings**：校验环境配置、URL 与输出 schema。
- **Typer**：提供简洁的命令行入口。
- **pytest**：用固定 HTML fixture 防止解析规则回归。
