# Apple Calendar / Reminders

`HIQSPort` 的 Apple delivery service 将现有已校验课程事实单向投影到 macOS
EventKit。iCloud 账户下建立专用 `HIQS` 日历和提醒事项列表，使用 namespace +
稳定 item/occurrence hash 对账。它不反写课程事实或 Notion 个人状态，不上传原文件。

`application/apple_projection.py` 复用日历展开与 actionable 判定；
`core/services/apple.py` 负责配置、互斥、检查点与完成回执；
`infrastructure/apple/EventKitBridge.swift` 负责原生账户、授权、持久化和读回；
`infrastructure/apple/worker.py` 安装并核验 LaunchAgent。MCP 与 CLI 只是同一 Port
的适配器。辅助程序 `.app`、配置、SHA-256 build cache、状态与日志在私有
`resources/apple/` 下；IPC 文件在 0700 临时目录，配置及请求文件权限为 0600。
源码安装使用本机 Swift toolchain，以明确的 macOS 14 部署目标构建并 ad-hoc 签名。
macOS 之外及没有 Swift compiler 的安装能保留预览/测试能力，无法建立原生连接；
独立冻结发行版需另行打包此辅助程序，不能声称当前实现已完成该发行路径。

首次 setup 仅保存账户与稳定 identity 并请求原生权限，正式 sync 才创建/更新
事件和任务。Calendar 需要 full access，Reminders 也需要授权。账户缺失、权限被拒、
同名多容器、重复 managed identity 或已管理记录被移到其他容器时返回阻塞/失败，
不会静默改成本地账户。显式保存的容器或账户 ID 失效时保留配置以便人工对账。

每次 sync 在进程文件锁下，先保存扫描时间窗，再调用原生桥。这样超时后即使正式
来源已改变，也能重新找到此前写入的事件。读取事件按一年分段，避免 EventKit
四年 predicate 截断；除了窗口，还按保存的 local ID 对账。写入前拒绝重复 identity。
写入后用新的 EventStore 逐项核对 title/date/location/source-note/URL、提醒事项完成
状态以及撤回/删除结果。只有完整 matched/expected 且无错误才报告 complete。
本地回执一直包含 `cloud_delivery_verified: false`，因为不能从 EventKit 证明另一设备
已收到 iCloud 推送。源数据读取、语义准确性、Apple 本地持久化与跨设备收到分别报告。

HIQS 更新源字段及 `[HIQS ...]` 标记范围；保留完成状态、priority、alarms 和标记外
个人文字。Apple 是精简日程，只展示标题、日期、地点及一个来源链接；课程要求、
占分、格式及长段出处留在 HIQS。投影使用 `confirmed_upcoming_brief_v1`，只接收
`date_status: confirmed` 且仍有效的记录。每轮使用 CORE 注入时钟重新检查：定时截止
过后即过期；纯日期事项保留到本地当天结束；已开始但尚未结束的活动保留到结束时。
重复规则先展开，再过滤已结束的单次活动。无日期/暂定/未知状态均不传到 Apple，
仍保留原始课程事实。只有日期时不填写时间；时点事件使用零时长。

新策略清理本 namespace 先前已同步但现在不符合条件的事件和提醒事项，不再在
Apple 列表保留 `[已撤回]` 卡片。删除提醒事项前，将完成状态、priority、alarms 及
个人文字原子存到私有 0600 `resources/apple/filtered-reminders.json`，以便未来同一
item 的日期更正并重新符合条件时恢复个人状态。删除后逐项读回确认记录已不存在。
旧版不带新策略的 plan 保留原 withdrawal 行为。全部筛选/精简/清理只作用于 Apple
投影，不更改 `information.json`、Notion 状态或其他个人日历。
全天事件使用本机浮动日期和 EventKit 当天 23:59:59 的结束表示；不把 ICS 的
次日零点排他边界直接用于 EventKit，避免单日事项多占一天。辅助程序内部也使用
独立进程锁，Python launcher 超时后不会让两个原生进程同时创建重复事件。

首轮 sync 完整核验后才可 enable worker。LaunchAgent 使用安全参数数组调用
`hsas --resources ... apple sync`，`WatchPaths` 监听正式 information 文件，
`StartInterval=300` 做补偿重试，`RunAtLoad=true`；只在登录会话下运行，不运行 Agent，
不采集 Moodle 或批准新事实。安装后 `launchctl print` 核验 loaded 状态；disable
停止并移除当前实例的 LaunchAgent，但保留 Apple 记录和本机配置。

用户/Agent 操作步骤位于产品 Skill 的
[Apple 同步协议](../skills/hiqs-course-information/references/apple-sync-protocol.md)。

依据：[Apple 授权与事件存储](https://developer.apple.com/documentation/eventkit/accessing-the-event-store)、
[事件与提醒事项创建](https://developer.apple.com/documentation/eventkit/creating-events-and-reminders)、
[local ID 在完整同步后可能失效](https://developer.apple.com/documentation/eventkit/ekcalendaritem/calendaritemidentifier)、
[四年 predicate 范围限制](https://developer.apple.com/documentation/eventkit/ekeventstore/predicateforevents(withstart:end:calendars:))。
