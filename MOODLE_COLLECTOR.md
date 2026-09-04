# HIQS Moodle Collector

Collector 使用 Playwright 的持久化浏览器 profile 读取 HKU Moodle，下载学生当前有权访问的
课程文件，并在事务目录中建立可供 AI 阅读的本地资料库。

> Collector 收集用户有权访问的课程。用户亲自完成 SSO/MFA；`browser-profile/` 与登录
> cookie 始终保存在私人运行目录。

## 运行

```bash
hsas login
hsas sync-courses                 # 所有可见课程
hsas sync-courses 123             # 单门课程
hsas materials list --course 123  # 原文件和文本副本的绝对路径
hsas changes show                 # 仅显示尚未由 AI 整理的范围
```

课程参数也可使用与配置 Moodle 完全同源的 course URL。

## 同步管线

```text
Moodle API / HTML fallback
        ↓
保存原始 course state
        ↓
下载所有可访问附件和非 HTML 文件
        ↓
PDF 文本提取
        ↓
DOCX / PPTX 文本与 speaker notes 提取
        ↓
比较活动及文件变化
        ↓
加入 AI pending review
        ↓
验证并原子发布课程快照
```

AI 在默认同步管线中承担课程事实归纳，并通过
`hsas information validate/apply` 写入课程事实。

## 文件覆盖

下载器处理 Moodle `pluginfile.php` 及页面内的文件链接，并保存常见文档、PDF、
Presentation、Spreadsheet、图片、音视频、压缩包、代码、Notebook 和其他非 HTML
文件响应。下载仍受配置的最大文件大小、超时和并发限制。

Google Workspace 是唯一默认允许尝试下载的外部来源：

- Docs 导出 DOCX；
- Slides 导出 PPTX；
- Sheets 导出 XLSX。

导出返回登录/权限 HTML 时，活动会标为 `external` 并记录真实响应；Office 文件只接受
有效导出内容，所有访问遵循当前用户权限。

## 文本副本

- PDF 使用 `--- Page N ---` 标记页码；
- DOCX 读取正文以及可用的页眉、页脚、脚注、尾注和批注；
- PPTX 按 slide 提取文字，并纳入 speaker notes；
- 扫描 PDF 或图片型 Office 文件会提示 OCR/视觉读取限制。

旧 `.doc`、`.ppt` 和其他格式会保留原文件；AI 可使用相应的文档工具读取。所有可提取
文本统一进入 `analysis/text/`，供 `hsas materials search` 查询。

## 输出

```text
<RESOURCES_DIR>/
├── courses.json
├── sync-report.json
└── courses/<course_id>/
    ├── course.json
    ├── raw/course-state.json
    ├── files/
    ├── analysis/text/
    └── changes/
```

`StoredFile` 保存本地路径、已清理 URL、MIME、大小、SHA-256、下载时间、ETag、
Last-Modified、最近校验时间及可选文本分析。

增量同步使用 HTTP validator 和 SHA-256 复用未变文件。每门课程在 staging 中构建；只有
下载、分析和模型校验完成后才通过目录交换发布。中断或失败会保留上一份有效快照。

变化历史位于 `changes/history/`。首次整理为全量 review；之后 AI 只需读取
`hsas changes show` 返回的文件。处理游标独立保存在 `ai-state/change-checkpoint.json`，
每次同步都会完整保留尚待处理的变化。

## 配置

公开默认配置位于 `config/defaults.toml` 和 `config/selectors.example.json`。本地覆盖
写入平台数据目录的 `config.toml` 或未跟踪的 `.env`。密码、MFA、cookie 和 sesskey
始终由浏览器认证会话管理。

主要下载参数：

- `MOODLE_MAX_DOWNLOAD_BYTES`：单文件大小上限；
- `MOODLE_DOWNLOAD_CONCURRENCY`：并行下载数；
- navigation timeout：请求超时。

## 故障判断

`course.json` 中的活动可能是：

- `downloaded`：至少一个文件已保存；
- `external`：外部链接或等待导出授权；
- `skipped`：响应提供元数据，文件存储已跳过；
- `failed`：请求或写入失败，见 `download_error`;
- `pending`：同步等待完成。

检查资料时必须包含 `unassigned_activities`。缺失文件、OCR 警告和 external 状态统一
表示仍需获取或读取的证据。

## 离线验证

```bash
python -m ruff check src tests
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
```
