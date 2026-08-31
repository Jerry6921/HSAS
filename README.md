# HKU Moodle Collector (MVP)

一个本地运行、配置驱动的 Moodle 数据采集器。它使用 Playwright 的持久化浏览器 profile 保留 HKU SSO/MFA 登录会话，优先调用 Moodle 课程状态 AJAX 方法，并通过 Pydantic 输出稳定 JSON；HTML parser 保留为 fallback。

> 仅采集你有权访问的课程，并遵守 HKU/Moodle 使用政策。`.moodle-profile/` 含登录 cookie，不能提交或分享。

## 目录

```text
hku-moodle-collector/
├── config/selectors.example.json       # 所有易变 CSS selector
├── src/hku_moodle_collector/
│   ├── acquisition/                    # 阶段 1：访问与下载
│   │   ├── browser.py                  # Playwright 会话/cookie
│   │   ├── discovery.py                # 仪表板课程发现
│   │   ├── moodle_api.py               # AJAX service 与 JSON 解码
│   │   └── downloader.py               # 同源课程文件下载与校验
│   ├── transformation/                 # 阶段 2：对象化与分析
│   │   ├── models.py                   # Pydantic domain schema
│   │   ├── archive_index.py            # 统一遍历 activity/file 与文档定位
│   │   ├── archive_stats.py            # 统一刷新归档统计
│   │   ├── state_mapper.py             # Moodle state -> CourseArchive
│   │   ├── html_parser.py              # HTML fallback
│   │   ├── pdf_analysis.py             # PDF 正文分析
│   │   └── assessment_parser.py        # 结构化 Assessment
│   ├── storage/                        # 阶段 3：持久化
│   │   └── json_store.py               # 安全文件名与 JSON 输出
│   ├── config.py                       # 跨阶段配置
│   └── cli.py                          # 流程编排
├── tests/                              # 离线解析测试
├── requirements.txt
└── pyproject.toml
```

代码依赖保持单向：`cli -> acquisition/transformation/storage`；domain models 不依赖浏览器或 CLI，storage 也不理解 Moodle 业务。Mapper、PDF Analyzer 和 Assessment Parser 是并列处理器，共享 `archive_index` 与 `archive_stats`，彼此没有直接依赖或循环导入。

### 加载和查询 course.json

`ArchiveIndex` 负责把磁盘 JSON 校验为强类型 `CourseArchive`，并一次性建立常用内存索引：

```python
from hku_moodle_collector.transformation.archive_index import ArchiveIndex

index = ArchiveIndex.from_json("output/courses/138907/course.json")
archive = index.archive

section = index.get_section("1594283")
activity = index.get_activity("4166630")
syllabus = index.find_document(role="syllabus")
assessment = index.get_assessment("final-essay")
```

公开只读映射包括 `sections_by_id`、`activities_by_id`、`files_by_path`、`files_by_sha256`、`assessments_by_id` 和 `groups_by_id`。如果其他服务增删了对象，调用 `index.rebuild()` 刷新索引；JSON 写回仍由 `storage/json_store.py` 负责。

## 安装

需要 Python 3.11+：

```bash
cd hku-moodle-collector
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m playwright install chromium
```

项目根目录的 `.env` 配置 `MOODLE_BASE_URL`、`MOODLE_LOGIN_URL` 和
`MOODLE_DASHBOARD_URL`。如需更新地址，打开当前 HKU Moodle 后，从浏览器复制
实际显示的 host、登录页和 dashboard URL；不要在 `.env` 中保存密码、cookie、
sesskey 或其他访问令牌。

若页面结构与示例不同，在浏览器开发者工具检查元素后，复制并修改 selector 文件：

```bash
cp config/selectors.example.json config/selectors.local.json
```

随后把 `.env` 中 `MOODLE_SELECTOR_CONFIG` 改为 `config/selectors.local.json`。每个字段接受多个候选 selector，程序使用第一个能匹配到节点的候选项。

## 运行

首次登录（会打开可见 Chromium）：

```bash
hku-moodle login
```

在浏览器中手动完成 HKU SSO/MFA，看到 Moodle dashboard 后回到终端按 Enter。之后 session cookie 保存在 `.moodle-profile/`。

发现课程：

```bash
hku-moodle discover
```

结果写入 `output/courses.json`。从中复制一门课的 URL，然后用 API 优先方式同步课程并下载资料：

```bash
hku-moodle sync-course --course-url 'https://YOUR-MOODLE-HOST.example.edu/course/view.php?id=123'
```

输出目录：

```text
output/courses/123/
├── course.json
├── raw/course-state.json
├── analysis/text/                       # 每份 PDF 的完整提取正文
└── files/
    ├── 00-General/
    └── 01-Week-1/
```

`course.json` 使用 v2 schema，按 section 保存 activity。每个已下载文件记录相对于 `output/` 的 `relative_path`，以及移除 sesskey/token 后的 `source_url`、MIME、字节数、SHA-256 和下载时间。

默认在下载后执行 PDF 正文分析，包括页数、可提取文字页数、字数、按 200 WPM 估算的阅读时间、关键词、明确标记为 `extractive` 的摘要、PDF metadata、正文 `.txt` 路径与正文 SHA-256。扫描型 PDF 不会伪造结果，而会设为 `partial` 和 `ocr_required=true`。

Syllabus 与 Moodle assessment sections 会组合成结构化 `assessments`：分组/项目权重、字数限制、开放期、截止时间、scheduled date、要求、来源页、确认状态和课程政策。用户学习档案不属于课程归档，应在后续独立文件中管理。

默认下载 Moodle 同源的 PDF、Office/OpenDocument、文本、压缩包和图片；外部 URL 只记录、不自动访问。单文件上限和并发数由 `.env` 的 `MOODLE_MAX_DOWNLOAD_BYTES` 与 `MOODLE_DOWNLOAD_CONCURRENCY` 控制。若只需要元数据：

```bash
hku-moodle sync-course --course-url '...' --no-download-files
```

只分析已经下载好的课程，不重新登录或下载：

```bash
hku-moodle analyze-course --course-id 123
```

旧版 HTML-only 采集仍可使用：

```bash
hku-moodle collect --course-url 'https://YOUR-MOODLE-HOST.example.edu/course/view.php?id=123'
```

输出包括：

- `output/123.json`：统一 schema 的课程、section、resource、assignment、announcement
- `output/raw/123.html`：原始 HTML，方便页面变更时调试 parser

运行离线测试：

```bash
pytest
```

## Schema 和分类边界

`CourseArchive` 当前 schema 为 `2.1`，含课程信息、sections、activities、文件及 PDF analysis、结构化 assessments、统计和原始状态路径。Moodle 的 course/section/course-module ID 会原样保留，便于增量同步。`CourseSnapshot` v1 继续服务于 HTML fallback。

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
