# HSAS — HKU Study Assistance System

> 把 Moodle 中分散的课程事实，转化为有依据、可验证、能执行的跨课程学习优先级。

HSAS 是面向 HKU 学生的本地优先学习辅助系统。它采集用户有权访问的 Moodle
课程，结构化 Assessment、DDL、权重、要求与课件，通过确定性 Planner 生成跨课程
优先事项，再从本地课件检索证据，帮助 AI 给出学习方法、预计投入与自测标准。

HSAS 不替学生编造课程事实，也不把学习任务强制安排到具体时间。学生保留最终决策权，
个人资料、课程文件、登录状态和计划默认只保存在本机。

## 为什么使用 HSAS

- **课程事实有来源**：保留 Moodle activity、syllabus 页码、文件与采集时间等依据。
- **优先级可复现**：DDL、权重、难度、状态、工作量和依赖由确定性规则计算，而非让 AI 临场猜测。
- **学习建议基于课件**：本地 RAG 先检索已下载材料，再由 AI 设计学习动作和自测成果。
- **个人数据留在本机**：Student Profile、Execution Log、课程归档和浏览器 profile 不进入 Git。
- **失败时保留有效数据**：同步和规划采用验证、快照与回滚机制，不用失败结果覆盖上一份有效版本。

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
Integrated Plan：排序后的关键事项、理由、工作量与完成标准
    ↓
本地课件检索
    ↓
AI 学习建议：方法、预计投入、证据与自测标准
```

`Integrated Plan` 是可持续更新的优先事项清单，不是固定日历。它说明现在应该关注什么、
为什么重要、预计需要多少投入以及怎样算完成；具体学习时段由学生根据现实安排决定。

## 核心能力

- 通过 Playwright 保存本地登录会话并同步可访问的 Moodle 课程；
- 结构化课程、section、activity、Assessment、权重、日期与政策；
- 下载并增量校验课件，提取可搜索的 PDF 正文；
- 检测课程变化并保留 last-known-good 快照；
- 生成可验证的跨课程优先级与大型任务里程碑；
- 记录学生明确确认的 Profile 和实际执行反馈；
- 从本地材料检索与某项计划任务相关的课程证据；
- 支持安全的数据迁移和固定 Git commit 的代码更新。

## 快速开始

### 环境要求

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

HKU Moodle URL 已包含在公开默认配置中，通常不需要创建 `.env`。

### 首次使用

```bash
# 查看本地状态
hsas list-status

# 打开浏览器，由用户完成 HKU SSO/MFA
hsas login

# 同步全部课程；也可在命令后提供单个课程 ID 或 URL
hsas sync-courses

# 验证 Profile 并生成优先事项
hsas profile validate
hsas update-plan
```

常用的后续操作：

```bash
hsas materials for-item PLAN_ITEM_ID
hsas execution add PLAN_ITEM_ID \
  --planned-minutes 60 \
  --actual-minutes 75 \
  --progress-minutes 60
```

运行 `hsas --help` 或相应子命令的 `--help` 查看完整参数。

## 与 AI Agent 配合

在支持读取项目文件和运行终端命令的 Agent 中打开 HSAS 根目录。`AGENTS.md` 会引导
Agent 加载 `src/AI_Skills/SKILL.md`，遵守同步权限、个人数据写入、课程证据和计划解释规则。

适合直接提出的请求包括：

```text
检查当前状态，告诉我哪些课程需要同步；先不要执行同步。
同步全部课程并更新计划，然后解释最高优先级的三项任务。
检索最高优先事项对应的课件，给出学习方法、预计投入和自测标准。
```

AI 不应直接编辑 Profile、Execution Log、CourseArchive 或 Integrated Plan。确认后的个人事实
必须通过受控 CLI 写入；课程事实和计划输出必须由 Collector 与 Planner 生成。

## 数据与隐私

代码与个人数据相互隔离。macOS 默认数据目录为：

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

其他系统使用 `platformdirs` 对应的标准目录，也可通过 `HSAS_DATA_DIR` 覆盖。`.env`、
浏览器 profile、课程资料、个人计划和执行记录均被 Git 忽略。密码、MFA、cookie、sesskey
和 token 不应写入配置、日志、Issue 或公开诊断。当前 RAG 在本地运行，不需要上传课件或调用
外部 embedding 服务。

## 项目结构

```text
src/hsas/
├── interfaces/       # CLI 与 Agent 适配器
├── application/      # 同步、规划、检索和个人数据用例
├── domain/           # 课程与规划模型、规则和验证
└── infrastructure/   # Moodle、PDF、存储、运行目录与更新
```

依赖必须指向内层；详细规则见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 开发

```bash
python -m pip install -c requirements.lock -e '.[dev]'
python -m ruff check src tests
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
```

贡献前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题和公开诊断要求见
[SECURITY.md](SECURITY.md)。

## 当前边界

- HSAS 是本地 MVP，不是 HKU 官方产品；
- 它只读取当前账号本来有权访问的内容，不绕过 Moodle 权限；
- Moodle 页面或接口变化时可能需要更新适配逻辑；
- 扫描型 PDF 在加入 OCR 前无法提供可靠正文检索；
- 未公布或证据不足的信息保持未知，最终要求仍以 Moodle 官方页面为准；
- AI 建议不替代学生对时间安排、学习判断和学术诚信的责任。

## 进一步阅读

- [Moodle Collector 与数据结构](MOODLE_COLLECTOR.md)
- [系统架构](ARCHITECTURE.md)
- [AI 操作入口](src/AI_Skills/SKILL.md)
- [贡献指南](CONTRIBUTING.md)
- [安全政策](SECURITY.md)

## License

HSAS is released under the [MIT License](LICENSE).
