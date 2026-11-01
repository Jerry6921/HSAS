# HIQS Skills 与 Notion 工作台

Notion 是 HIQS Skill Set 的主要可视化与资料展示端，承载课程、课程档案、原始资料与学习笔记。Apple 日历与提醒事项负责日程和待办。
产品入口是 [hiqs-notion-workspace](../skills/hiqs-notion-workspace/SKILL.md)，
课程事实与笔记分别由对应 Skill 理解和编写。Python 复用服务负责机构登录、
资料采集、OCR、证据检索、验证保存与确定性投影。独立连接由本机后台进程使用，
不依赖 Codex 会话；Agent 的页面编辑／笔记正文发布另用 Notion 连接器并读回核验。

## 接口

所有入口通过 `HIQSPort`，业务投影位于 `application/notion_projection.py`。
MCP 提供 `get_notion_projection`、`get_notion_status`、`check_notion_connection`、
`sync_notion`、`export_notion` 与 `get_notion_controls`。CLI 提供对应恢复命令：

```sh
hsas notion plan
hsas notion status
hsas notion export ./private-notion-export
hsas notion configure ./private-connection-ids.json
hsas notion check
hsas notion sync
hsas notion watch --interval 300
hsas notion controls
hsas notion work --interval 300
hsas notion worker-plist ~/Library/LaunchAgents/io.github.hiqs.notion-sync.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.github.hiqs.notion-sync.plist
```

连接配置文件只有目标 ID，不需要把密钥写入该文件：

```json
{
  "parent_page_id": "YOUR_HIQS_HOME_PAGE_ID",
  "upload_limit_bytes": 5242880,
  "collect_interval_seconds": 3600,
  "data_sources": {
    "courses": "COURSES_DATA_SOURCE_ID",
    "materials": "MATERIALS_DATA_SOURCE_ID",
    "controls": "CONTROLS_DATA_SOURCE_ID"
  }
}
```

在 [Notion Connections](https://www.notion.so/profile/integrations) 创建内部
连接，只开启读取、插入和更新内容，并把 HIQS 工作台及子页面连接给它。
`configure` 使用隐藏输入收取密钥，验证所有数据库访问后才保存；本地
`resources/notion/connection.json` 权限为 0600。也可通过环境变量
`HIQS_NOTION_TOKEN` 提供凭据，状态与错误报告不返回凭据。

## 数据归属与可恢复同步

课程以 `HIQS Course ID`、资料以 `课程 ID:SHA256` 识别。每次写入前从 Notion
分页读取现状，发现重复 ID 时停止，避免选择错误记录。重复同步更新同一
页面。内容相同的课程文件只上传一次，所有原分类和来源路径保留在投影中。

HIQS 更新课程事实属性，保留 `Personal Status`、`Personal Notes`、笔记
正文、课程页布局与没有 HIQS ID 的用户草稿。文件上传只追加原文件；
正文更新不覆盖用户内容。来源删除后标记派生状态，不删除页面、附件或笔记。
同一机器同时只有一个同步进程，进度逐条保存到 `resources/notion/state.json`。
上传采用内容哈希标记，网络中断后先检查附件是否已经写入，再恢复。

Notion 中编辑课程事实不会直接修改 `information.json`。事实仍必须经过
已有的 validate/apply 与证据检查流程。后台同步只发布已经验证的快照；
它不调用外部 LLM、不自动认可新课程事实。`collect_interval_seconds`
设为 3600 时每小时采集；0 可关闭定时采集。手动请求也会重新计时，避免
刚刚采集结束又立即启动定时采集。

## Notion 同步控件

工作台原生按钮向“同步控制”数据库新增请求：名称“同步课程”、角色“请求”、
操作“同步课程”、状态“排队”。`work` 每五秒检查队列，调用既有 CORE
采集流程；“重试失败”请求只重试失败来源。请求页的“取消请求”复选框取消
正在执行的采集。只有明确排队的已知操作会执行，普通草稿不会触发采集。
本机检查点在派发前保存；重启后不自动重复执行结果不明的旧请求。

“HIQS 同步状态”记录显示当前阶段、已完成数、总数、进度和待整理数。
总数未知时只显示阶段，不能虚构百分比；采集完成后若有未审核事实，显示
“待 AI 整理”。首页折叠区和状态页使用原生代码块的 Copy 按钮复制现有
Agent 整理提示词。后台只更新这些明确归属的代码块，保留其他正文与布局。

生成的 launchd 配置使用 `work`，同时处理按钮请求并定期发布已验证事实。
定时采集的进度更新同一条状态记录，不新增重复的计划页或任务记录。
新增原文件即使还未由 AI 整理，也可先上传到课程资料的“待整理”分组；
这只是资料收件箱，不写入 `information.json`。AI 校验分类后沿用同一资料 ID
更新分类，保留已上传附件。新日期、分数和事项仍须走 validate/apply。
独立连接未配置时显示“等待连接”，按钮请求不能由本机执行；密钥只在本机
隐藏输入。原生按钮需在 Notion 界面配置，文件/API 不伪造按钮或剪贴板操作。

## 视图与文件

工作台以课程、档案、资料和笔记为主。默认投影 `scope: library` 仅产生
courses/materials 行；即使旧配置仍含 items/calendar ID，同步也不会访问或
重建它们。只有显式历史导出兼容模式才保留旧投影能力，正常服务不启用。
个人笔记、页面正文、附件与无 HIQS ID 的学生草稿继续保留。

导航使用 Notion 原生课程/笔记数据库、gallery/table 视图、callout、toggle
与页面链接。课程主页、课程档案、原始资料和笔记索引继续复用现有关系。
笔记正文中原有的私有 HTML 阅读页保留。原生导航中的 HTML 笔记标题使用
`Notion 页面 URL#HTML 区块 ID`，点击直接定位正文，避免把临时 S3 附件 URL
作为长期导航。原生子页面入口若无法指定区块锚点，用原生文字链接取代显示入口，
原页完整保留在同一索引下的私有存档；纯原生笔记保留原格式。

原同级 `sites/hiqs-course-library` 网站已按用户新要求退出工作台：首页
内嵌与链接移除，网站撤回公开访问。源码保留以便恢复，但默认不再部署、
内嵌或作为工作台入口；只有用户重新明确请求网站时才恢复该方向。

移除旧布局前保留私有结构/数据快照；仅回收明确授权的任务、日历视图和
数据库，保留课程、资料、笔记及其页面。后台发布按 library 投影运行，
避免旧重复功能恢复。评分与要求仍属课程档案，不创建个人完成状态。
每次同步末尾重新查询所有课程/资料行，核对属性、关系及移除状态，
在 `verification` 保存 expected/matched 和失败清单。附件和实际视图另行核验。

Notion 工作区上传上限独立于 API multipart 流程。默认 5 MiB；超过限制
显示“超过上传限制”，不能声明已上传。升级工作区后，调整配置中的实际
上限并重试即可。超过 20 MiB 的文件由 REST 适配器采用 multipart，保留
原文件字节。参考 [官方文件上传说明](https://developers.notion.com/reference/create-a-file-upload)。

默认课程库导出包含 courses/materials CSV、课程 Markdown、JSON 和原文件 ZIP，
不生成待办 CSV、calendar CSV 或 ICS。导出包含私人资料，不应提交到公开仓库。

## 独立 UI 迁移状态

连接验证并配置后，`hsas ui` 和 macOS 入口打开 Notion 工作台。
后台同步使用 launchd，与界面进程分离。未配置连接时仍保留旧本地界面
作为恢复入口；当前版本尚未物理删除 React/WebKit 资源。完全退役需要
先验证独立连接的真实同步、后台运行与机构资料更新/审核的完整替代路径。
这份实现不是已经发布的 HIQS 3.0。
