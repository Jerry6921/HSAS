# HSAS — HKU Study Assistance System

> 把 Moodle 中分散的课程信息，转化为有依据、可执行的跨课程学习优先级。

HSAS 是面向 HKU 学生的本地学习辅助系统。它同步用户有权访问的 Moodle 课程，整理
Assessment、DDL、权重、要求和课件，通过确定性规则判断当前最重要的学习事项，并从
本地课件中检索相关内容，帮助 AI 给出有来源的学习建议。

你可以在本地 Dashboard 中查看优先事项、同步状态和课程资料，并记录真实学习进度。
个人资料、课程文件、登录状态和计划默认只保存在自己的电脑上。

## 它解决什么问题

课程信息通常散落在 Moodle 页面、syllabus、公告、Label 和 PDF 中。多门课程同时进行时，
学生不仅要记住日期，还需要不断判断：

- 最近有哪些真正重要的 DDL 和考试？
- 权重、难度、剩余工作量和当前进度应该如何一起考虑？
- 一项大型作业应该从哪里开始，怎样拆成可完成的阶段？
- 当前任务对应哪些课件，应该怎样学习，怎样确认自己已经掌握？
- Moodle 更新后，旧计划是否仍然可信？

HSAS 将这些信息整理成带来源的课程数据库，再生成稳定、可验证的跨课程优先事项。
未知或证据不足的信息会保持未知，不会被自动当成零，也不会由 AI 猜测补全。

## 与相关产品的区别

| 能力 | Moodle | 待办/日历工具 | 通用 AI 助手 | HSAS |
|---|---|---|---|---|
| 课程信息 | 信息完整但分散 | 依赖手动录入 | 依赖用户粘贴上下文 | 自动整理课程、Assessment、DDL、课件和来源 |
| 跨课程优先级 | 不负责综合判断 | 主要按日期或手动排序 | 可能随对话变化 | 按 DDL、权重、难度、状态、工作量和依赖稳定计算 |
| 学习建议 | 提供资料，不设计学习路径 | 不理解课程内容 | 容易依赖模型记忆 | 先检索本地课件，再给方法、预计投入和自测标准 |
| 更新与可信度 | 展示当前页面 | 需要人工维护 | 容易遗漏变化 | 检测课程变化、验证数据并保留上一份有效结果 |
| 个人数据 | 存于学校平台 | 通常存于服务商云端 | 取决于所用服务 | Profile、计划、进度和下载资料默认留在本机 |

HSAS 不是另一个待办清单，也不是让大模型自由生成日程。它把职责拆开：Collector 负责
课程事实，Planner 负责确定性排序，本地检索负责找到课件依据，AI 负责解释和设计灵活的
学习动作，学生自己决定何时学习。

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
本地课件检索
    ↓
AI 学习建议：方法、预计投入、证据与自测标准
```

`Integrated Plan` 是持续更新的优先事项清单，不是固定日历。它回答“现在应该关注什么、
为什么重要、需要多少投入、怎样算完成”；具体学习日期和时间由学生根据现实安排决定。

## 主要功能

- 同步全部课程或指定课程，并保存本地登录会话；
- 提取 Assessment、权重、开放时间、DDL、政策和来源；
- 下载并增量校验课件，提取可搜索的 PDF 正文；
- 检测课程变化，避免失败同步覆盖上一份有效数据；
- 生成跨课程优先级和论文、考试、项目等大型任务的阶段里程碑；
- 根据实际耗时与完成进度重新估算后续工作量；
- 从本地课件中检索与当前任务相关的文件和页码；
- 通过本地 Dashboard 浏览计划、课程资料、同步状态并记录进度。

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

HKU Moodle 地址已经包含在默认配置中，通常不需要创建 `.env`。

### 打开本地 Dashboard

```bash
hsas ui
```

浏览器会打开 `http://127.0.0.1:8765`。Dashboard 只监听本机地址，可以：

- 检查 Moodle 登录状态并打开登录窗口；
- 同步全部课程或指定课程；
- 查看优先事项、排序理由、DDL、工作量和警告；
- 按课程与 section 浏览并打开已下载课件；
- 查看完整课程信息；
- 经确认后记录实际学习时间和完成进度，并自动刷新计划。

首次使用时，在 Dashboard 中依次完成登录和课程同步。HKU SSO/MFA 始终由用户本人在
Playwright 打开的浏览器中完成，HSAS 不读取或保存密码和 MFA 验证码。

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
操作规范检查数据新鲜度、请求必要授权、检索相关课件，并解释 Planner 的结果。

例如：

```text
检查当前状态，告诉我哪些课程需要同步；先不要执行同步。
同步课程并更新计划，然后解释最高优先级的三项任务。
检索最高优先事项对应的课件，给出学习方法、预计投入和自测标准。
```

AI 不应直接改写课程归档或计划，也不能自行推断个人事实。Profile 和学习进度只会在用户
确认后通过受控接口写入。

## 数据与隐私

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

其他系统使用各自的标准用户目录，也可以通过 `HSAS_DATA_DIR` 自定义。浏览器 profile、
课程资料、个人计划和执行记录不会进入 Git。当前课件检索在本地完成，不需要外部 embedding
服务，也不会为了检索而上传课程文件。

请勿把密码、MFA、cookie、sesskey、token、Student Profile、课程资料或个人计划粘贴到
公开 Issue 或诊断信息中。

## 当前边界

- HSAS 是本地 MVP，不是 HKU 官方产品；
- 它只访问当前账号原本有权查看的内容，不绕过 Moodle 权限；
- Moodle 页面或接口变化时，可能需要更新适配逻辑；
- 扫描型 PDF 在加入 OCR 前无法提供可靠的正文检索；
- 未公布或证据不足的信息保持未知，课程要求仍以 Moodle 官方页面为准；
- AI 建议不替代学生自己的判断、时间安排或学术诚信责任。

## 更多信息

- [Moodle 采集与数据说明](MOODLE_COLLECTOR.md)
- [安全政策](SECURITY.md)

## License

HSAS is released under the [MIT License](LICENSE).
