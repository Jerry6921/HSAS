# HIQS — AI Skill Set for HKU

HIQS 是以 AI Skills 为主体的 HKU 学习工作流：Agent 阅读资料、理解问题、组织事实并
撰写笔记，Notion 提供课程、课程档案、资料与笔记的可视化工作台；Apple 管理待办与日历。Python 是 Skills 共用的
本地服务库，负责登录采集、OCR、检索、校验、保存与投影同步。

## 产品 Skills

| Skill | 负责的工作 |
| --- | --- |
| [hiqs-course-information](skills/hiqs-course-information/SKILL.md) | 审阅 Moodle／SIS／Class Planner 来源，回答带引用的问题，生成并提交校验过的课程事实。 |
| [hiqs-course-notes](skills/hiqs-course-notes/SKILL.md) | 完整阅读讲义与可用试题，一次完成分单元学习笔记、题目对应表和快速复习，并保存恢复点。 |
| [hiqs-course-planning](skills/hiqs-course-planning/SKILL.md) | 根据 syllabus／SIS 规划完整班别组合；在授权候选池内 enrol、对账和失败重排，固定已成功课程。 |
| [hiqs-notion-workspace](skills/hiqs-notion-workspace/SKILL.md) | 在对应 Notion 工作台展示课程档案、原文件与笔记，提供原生课程与笔记导航并核验交付结果。 |

例如：

> 整理本学期新增的课程资料，核对 Assignment 的日期、要求和占分，并同步到 Notion。

> 根据 ENGG1000 的 lecture 和可用 past papers／quizzes，生成一整套分段学习与复习笔记，保存到对应 Notion 课程下。

Skills 决定阅读范围、证据解释、教学组织和写作。Python 提供可复用的确定性能力，
不替 Agent 作事实判断或生成教学内容。后台只执行已配置的采集、上传和视图同步；
新增课程事实仍经过 Agent 审阅与 validate／apply／checkpoint。

## 项目结构

```text
HIQS/
├── skills/                     产品主体：可分发的 AI Skills 与随附资源
│   ├── hiqs-course-information/
│   ├── hiqs-course-notes/
│   ├── hiqs-course-planning/
│   └── hiqs-notion-workspace/
├── src/hsas/                   可复用 Python 服务及其适配器
│   ├── core/                   HIQSPort、服务装配与用例服务
│   ├── domain/                 数据合同与确定性规则
│   ├── application/            采集、检索、校验、笔记检查点及投影用例
│   ├── infrastructure/         HKU 来源、文件、存储与 Notion 适配器
│   ├── mcp/                    Skills 调用服务的正式接口
│   ├── cli/                    人工设置、恢复诊断与确定性 worker
│   └── codegen/                合同生成工具
├── contracts/                  服务的可检查数据合同
├── docs/                       架构、Notion 接入与实现边界
├── tests/                      复用服务与入口的行为验证
├── scripts/                    Skill 打包、合同生成与验证入口
└── .agents/skills/             产品 Skill 链接与仓库工程 Skill
```

`skills/` 是产品 Skill 的唯一维护位置；`.agents/skills/` 使用相对链接指向同一份内容。
旧 `src/AI_Skills` 也是兼容链接。工程开发 Skill 留在 `.agents/skills/hiqs-product-development`，
不进入面向学生的 Skill 分发包。Python 保留 `hsas` 包名和命令，继续访问既有私有资料。
详细职责和调用关系见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 开始使用

1. 在本地安装 Python 服务依赖，并将 Agent 的 MCP stdio 命令设为项目虚拟环境中的
   `hiqs-mcp`。仓库内从 `AGENTS.md` 定位 Skills；分发安装见下节。
2. 按 [Notion 整合说明](docs/notion-integration.md) 配置并验证工作台连接。
   Notion 是主要展示端；独立连接用于确定性同步，Agent 的 Notion 连接器用于页面编辑及笔记正文发布。
3. 让 Agent 调用相应 Skill，盘点资料、采集来源或处理已有资料。机构登录与 MFA
   由用户在官方页面完成。采集完成与 AI 整理完成分别显示。
4. 在 Notion 查看课程、档案、资料与笔记；在 Apple 查看已确认且未过期的待办与日历。笔记先保存本地检查点，再发布到已核对的
   课程父页并读回；连接未配置时仍保留本地成果并说明未完成的外部交付。

本地开发环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock -e '.[dev]'
.venv/bin/hiqs-mcp
```

`hiqs-mcp --profile <name>` 把工具面收窄到单个 Skill（`course-information`、
`course-notes`、`course-planning`、`notion-workspace`）；不指定时保持完整工具面。
登录、原生权限、取消和导出这类需要人在场的工具不属于任何 Skill profile，
只在完整面可见。分类记录在 `contracts/mcp-tool-profiles.json`，新增工具若未归类会
直接使检查失败。

MCP 客户端通常负责启动最后一条 stdio 命令。机构浏览器采集还需在同一环境安装
Playwright Chromium：`.venv/bin/python -m playwright install chromium`。
连接状态可用 `hsas notion status`、`hsas notion check` 诊断。
配置连接并不等于已同步；实际同步、文件上传和笔记发布结果须分别核验。

## Skill 分发与服务依赖

本机开发完成并通过检查后，Agent 会按仓库规则自动执行安装／更新：

```bash
.venv/bin/python scripts/install_agent_skills.py
```

默认安装到 `$CODEX_HOME/skills`（未设置则为 `~/.codex/skills`），校验安装内容并保留被
替换版本的备份；下一轮对话可用。安装 Skills 与连接 HIQS MCP 分开处理。

```bash
.venv/bin/python scripts/package_agent_skills.py --output work/hiqs-agent-skills.zip
```

ZIP 从 `skills/` 打包产品 Skills 的正文、references、scripts、assets 和元数据，
不打包工程 Skill、私有 resources 或认证配置。将解压后的 Skill 目录放入所用 Agent
的技能目录，并连接本地 HIQS MCP。Skill 包与 Python 服务分别交付；安装 Skill
不会自动安装服务、建立 Notion 连接或启动常驻 Agent。

课程笔记完整遵循 `english-course-notes` 的英文教材式教学、例题、解题阶段、单位、复习及
Notion 发布要求；完整规范随 Skill 分发。默认成果为对应 Notion 课程下经读回验证的页面，
整套请求仍连续完成所有单元，无需逐段回复“继续”。
可恢复检查点保存在私有 resources 的 `course-notes/<run_id>/`，每个 revision 导出
完整 Markdown bundle。`sync_notion` 同步事实和资料，笔记正文由 Agent 定向发布。
当前实现与验收边界见 [课程笔记实现说明](docs/course-notes-implementation.md)。

## 证据与事实验证

HIQS 将需要登录访问的课程信息、文件和日程保存为本地证据，并为 Agent 提供带来源的查询
结果。已经核对的信息与尚未确认的信息分别保存。

处理流程如下：

```text
Moodle / SIS / Class Planner
        ↓
发现、下载、递归解析
        ↓
EvidenceNode / EvidenceEdge
        ↓
FTS5 检索与按需读取
        ↓
Agent 提取学业事实
        ↓
校验、冲突处理、人工确认
        ↓
information.json → Notion 课程 / 档案 / 资料视图
information.json → Apple Calendar / Reminders（已确认、未过期）
```

#### 采集与验证机制

1. **多个课程来源的采集**

   HIQS 可以处理：

   - 登录状态和 HKU SSO
   - Moodle 活动正文、表格
   - 页面内嵌链接和递归链接
   - PDF、PPTX、DOCX、图片与 OCR
   - SIS、Class Planner 等不同来源

   采集分为发现、下载和解析三个阶段。文件无法解析时，原文件、来源地址和处理状态仍会
   保留，以便查看或重新处理。

2. **证据与来源关系**

   提取的内容会尽可能关联课程、活动、文件、页码、表格和来源节点。查询结果可以包含：

   - 信息来自哪里
   - 对应哪个文件或页面
   - 是否完整
   - 是否经过 OCR 或 fallback
   - 还能按 `evidence_id` 继续读取上下文

   [material_search.py](src/hsas/application/material_search.py) 负责从本地索引返回相关证据，
   统一证据模型负责保存内容与来源之间的关系。索引同时收录课件文本、Moodle 活动和
   `information.json` 中已经验证的课程记录；分块会保留标题层级、页码、slide 和表格行，
   以减少脱离结构的搜索片段。

3. **受控的正式数据写入**

   HIQS 的写入路径是：

   ```text
   Agent 提议 → Schema 验证 → Apply → 来源 checkpoint → 正式读取验证
   ```

   Agent 提交的更新只有通过数据格式、字段约束和来源批次检查后，才会写入正式课程数据库。
   验证失败时不更新正式数据；写入完成后会再次读取结果，并记录对应来源的处理进度。

4. **增量更新与来源对账**

   Moodle、SIS、Class Planner、个人输入之间可以分别保留状态。系统能区分：

   - 新发现的信息
   - 已处理的信息
   - 来源冲突
   - 日期未知
   - 采集失败
   - 需要用户确认的事项

   后续同步只处理新增、修改或删除的资料。某个来源缺少信息时不会自动判定为冲突；来源提供
   互相矛盾的内容，或关键信息没有足够证据时，相关事项会保留为未知或进入“需要确认”。

#### 信息边界

- 可采集范围取决于用户账号权限、来源页面是否可访问，以及同步是否成功。
- OCR、HTML fallback 和文件文本提取结果可能不完整；HIQS 会保留原文件和处理状态供用户
  回查。
- 未找到信息不等于该信息不存在。没有足够证据的日期、地点、占分和要求不会自动标为已确认。
- HIQS 用于整理和核对课程信息；涉及提交截止时间、考试安排和课程政策时，用户仍可打开所列
  官方来源进行最终确认。

## 交付边界

产品交付是 Skills + Notion + Python 服务，本地入口只有 MCP、CLI 与 Apple 交付。
曾作为兼容／恢复入口的本地 React Dashboard、`hsas ui`、macOS 应用和 DMG 打包已移除；
历史实现可从 git 历史取回，不重新引入，除非先记录一条架构决策。

## 隐私与信息可信度

- 本地课程原文件、证据和检查点保存在私有 resources；授权的 Notion 同步会将所选投影及原文件上传到对应工作区。
- 密码、MFA、Cookie 和访问令牌留在用户管理的认证范围，不进入课程信息库和 Skill 分发包。
- 日期、地点、占分、要求与政策保留可核对来源；未知或冲突信息明确显示。
- 同步或整理失败保留上一份有效资料；个人补充信息通过预览和确认进入正式事实。
- Notion 的用户正文、笔记与草稿由学生管理；Apple 提醒事项中的完成状态独立保留。

## License

HIQS 软件采用 [PolyForm Noncommercial License 1.0.0](LICENSE)。从课程平台下载的资料仍
适用其原有版权与使用条件。
