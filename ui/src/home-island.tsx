import { motion, useReducedMotion } from "motion/react";
import {
  AlertTriangle,
  ArrowRight,
  CalendarDays,
  Check,
  Copy,
  FileText,
  Inbox,
  RefreshCw,
  ScanText,
  Search,
  Sparkles,
} from "lucide-react";
import { Button } from "./components/ui/button";
import { Badge } from "./components/ui/badge";
import type {
  HomeInboxEntry,
  HomeListEntry,
  HomeUpdateChange,
  HomeUpdateCourse,
  ModernHomeOptions,
} from "./types";

const countKeys: Array<[string, string]> = [
  ["ai_review", "等待 AI 整理"],
  ["ocr", "等待 OCR"],
  ["google_authorization", "等待授权"],
  ["date_unknown", "日期待确认"],
  ["source_conflicts", "来源冲突"],
];

function previewValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text.length > 96 ? `${text.slice(0, 93)}…` : text;
}

function formatDateTime(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-HK", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function StatusList({ entries, empty, onOpen }: {
  entries: HomeListEntry[];
  empty: string;
  onOpen: (index: number) => void;
}) {
  if (!entries.length) return <p className="hiqs-home-empty">{empty}</p>;
  return (
    <div className="hiqs-home-compact-list">
      {entries.map((entry, index) => {
        const content = (
          <>
            <strong>{entry.title}</strong>
            <span>{entry.meta}</span>
            {entry.note && <small>{entry.note}</small>}
          </>
        );
        return entry.actionIndex === undefined
          ? <article key={`${entry.title}:${index}`}>{content}</article>
          : <button type="button" key={`${entry.title}:${index}`} onClick={() => onOpen(entry.actionIndex!)}>{content}</button>;
      })}
    </div>
  );
}

function InboxEntry({ entry, onApply }: { entry: HomeInboxEntry; onApply: (entryId: string) => void }) {
  return (
    <article className="hiqs-home-inbox-entry">
      <div className="hiqs-home-inbox-heading">
        <div>
          <h3>{entry.title}</h3>
          <p>{[entry.note, formatDateTime(entry.created_at)].filter(Boolean).join(" · ")}</p>
        </div>
        <Button size="sm" onClick={() => onApply(entry.entry_id)}>确认写入</Button>
      </div>
      {entry.changes.map((change, index) => (
        <section key={`${change.title}:${index}`} className="hiqs-home-inbox-change">
          <strong>{change.action === "create" ? "新增" : "更新"} {change.title}</strong>
          <div>
            {change.fields.slice(0, 12).map((field) => (
              <p key={field.field}><code>{field.field}</code><span>{previewValue(field.before)} → {previewValue(field.after)}</span></p>
            ))}
          </div>
        </section>
      ))}
    </article>
  );
}

function ChangeCard({ change, onOpenSource }: { change: HomeUpdateChange; onOpenSource: ModernHomeOptions["onOpenSource"] }) {
  const actionLabels: Record<string, string> = { added: "新增", modified: "修改", removed: "删除", baseline: "首次整理" };
  const kindLabels: Record<string, string> = { deadline: "日期", activity: "项目", material: "文件" };
  const canOpen = change.action !== "removed" && Boolean(change.relative_path || change.text_path || change.source_url);
  return (
    <div className="hiqs-home-change-card">
      <div className="hiqs-home-change-title">
        <Badge className={`is-${change.action}`}>{actionLabels[change.action] || change.action}</Badge>
        <span>{kindLabels[change.kind] || change.kind}</span>
        <strong>{change.title}</strong>
        {canOpen && <Button size="sm" variant="ghost" onClick={() => onOpenSource({ ...change, relative_path: change.relative_path || change.text_path })}>预览</Button>}
      </div>
      {change.field && <code className="hiqs-home-change-field">{change.field}</code>}
      {change.action === "modified" && (
        <div className="hiqs-home-diff">
          <div><span>更新前</span><pre>{previewValue(change.before)}</pre></div>
          <div><span>更新后</span><pre>{previewValue(change.after)}</pre></div>
        </div>
      )}
    </div>
  );
}

function UpdateCourse({ course, onOpenSource }: { course: HomeUpdateCourse; onOpenSource: ModernHomeOptions["onOpenSource"] }) {
  const files = (course.files || []).filter((file) => file.relative_path !== "course.json");
  return (
    <article className="hiqs-home-update-course">
      <header>
        <div><h3>{course.course_title}</h3><p>{course.course_id} · 检测至 {formatDateTime(course.acknowledge_through)}</p></div>
        <Badge>{course.mode === "full" ? "首次整理" : "增量更新"}</Badge>
      </header>
      {(course.changes || []).map((change, index) => <ChangeCard key={`${change.title}:${index}`} change={change} onOpenSource={onOpenSource} />)}
      {!(course.changes || []).length && (
        <div className="hiqs-home-baseline">
          <p>已建立课程基线，{files.length} 个文件等待首次整理。</p>
          <div>{files.slice(0, 12).map((file, index) => <Button key={`${file.title}:${index}`} size="sm" variant="ghost" onClick={() => onOpenSource({ ...file, title: file.filename || file.title })}>{file.filename || file.title}</Button>)}</div>
        </div>
      )}
    </article>
  );
}

export function HomeIsland({ options }: { options: ModernHomeOptions }) {
  const reduceMotion = useReducedMotion();
  const enter = reduceMotion ? false : { opacity: 0, y: 10 };
  const sync = options.syncJob;
  const syncing = sync?.state === "running";
  const syncTotal = Math.max(1, sync?.total || 1);
  const syncCompleted = Math.min(sync?.completed || 0, syncTotal);

  return (
    <motion.div className="hiqs-modern-home" initial={enter} animate={{ opacity: 1, y: 0 }} transition={{ duration: .24, ease: [.2, .75, .2, 1] }}>
      <motion.button
        type="button"
        className={`hiqs-home-next ${options.nextUp.empty ? "is-empty" : ""}`}
        disabled={options.nextUp.empty}
        whileHover={reduceMotion ? undefined : { y: -2 }}
        onClick={() => options.nextUp.itemId && options.onOpenNext(options.nextUp.itemId, options.nextUp.dateKey)}
      >
        <span className="hiqs-home-next-lines" aria-hidden="true" />
        <span className="hiqs-home-next-copy">
          <span>NEXT UP</span>
          <strong>{options.nextUp.course}</strong>
          <small>{options.nextUp.meta}</small>
        </span>
        <span className="hiqs-home-next-time"><strong>{options.nextUp.start}</strong><small>{options.nextUp.end}</small></span>
      </motion.button>

      <section className="hiqs-home-command">
        <header className="hiqs-home-section-heading">
          <div><p>COMMAND CENTER</p><h2>同步工作台</h2><span>连接课程来源、读取变更，再由你决定哪些信息进入本地资料库。</span></div>
          <div className="hiqs-home-actions"><Badge><Sparkles size={13} />本地工作区</Badge><Button variant="default" onClick={options.onStartWorkflow} disabled={syncing}>{syncing ? "同步中" : "开始同步"}</Button></div>
        </header>

        {syncing && (
          <div className="hiqs-home-sync" role="status">
            <div><span><RefreshCw className="hiqs-spin" size={15} />{sync?.cancel_requested ? "正在取消" : sync?.detail || "正在同步"}</span><strong>{syncCompleted} / {syncTotal}</strong></div>
            <progress value={syncCompleted} max={syncTotal} />
            <Button size="sm" onClick={options.onCancelSync} disabled={Boolean(sync?.cancel_requested)}>取消同步</Button>
          </div>
        )}

        <div className="hiqs-home-closure">
          <div className="hiqs-home-closure-heading">
            <div><p>INFORMATION CLOSURE</p><h3>资料闭环</h3></div>
            <div>
              {options.hasRetryTasks && <Button size="sm" onClick={options.onRetryFailures}><RefreshCw size={14} />只重试失败项</Button>}
              <Button size="sm" onClick={options.onCopyAgentPrompt} disabled={!options.hasAgentPrompt}><Copy size={14} />复制 Agent 整理指令</Button>
            </div>
          </div>
          <div className="hiqs-home-stages">
            {options.stages.map((stage, index) => (
              <motion.article key={stage.id} initial={reduceMotion ? false : { opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: index * .035 }} className={stage.state}>
                <i>{stage.state === "complete" ? <Check size={12} /> : <span />}</i>
                <strong>{stage.label}</strong>
                <small>{stage.state === "complete" ? "已完成" : stage.count ? `${stage.count} 项待处理` : "待处理"}</small>
              </motion.article>
            ))}
          </div>
          {options.retrySummary && <p className="hiqs-home-retry"><AlertTriangle size={14} />{options.retrySummary}</p>}
        </div>

        <div className="hiqs-home-metrics">
          {options.metrics.map((metric) => <article key={metric.label}><span>{metric.label}</span><strong>{metric.value}</strong><small>{metric.note}</small></article>)}
        </div>
      </section>

      <div className="hiqs-home-grid">
        <section className="hiqs-home-status">
          <header className="hiqs-home-section-heading compact"><div><p>MATERIAL STATUS</p><h2>资料状态</h2></div><Badge>{options.statusTotal} 项待处理</Badge></header>
          <div className="hiqs-home-counts">
            {countKeys.map(([key, label]) => <article key={key}><span>{label}</span><strong>{options.counts[key] || 0}</strong></article>)}
          </div>
          <div className="hiqs-home-status-columns">
            <section>
              <header><div><h3>OCR 队列</h3><p>{options.ocrCapability}</p></div><Button size="sm" onClick={options.onRunOcr} disabled={!options.canRunOcr}><ScanText size={14} />批量 OCR</Button></header>
              <StatusList entries={options.ocrQueue} empty="OCR 队列已清空。" onOpen={options.onOpenOcr} />
            </section>
            <section>
              <header><div><h3>需要处理</h3><p>授权、待确认日期与来源冲突</p></div></header>
              <StatusList entries={options.attention} empty="当前没有需要人工处理的资料状态。" onOpen={options.onOpenAttention} />
            </section>
          </div>
        </section>

        <div className="hiqs-home-side">
          <section className="hiqs-home-search">
            <header><p>LOCAL SEARCH</p><h2>本地问答式搜索</h2><span>在课程事项、课件和来源中查找匹配内容。</span></header>
            <label><Search size={17} /><input type="search" value={options.searchQuery} onChange={(event) => options.onSearch(event.target.value)} placeholder="例如：MATH1851 Part I test 占分多少？" /></label>
            <div className="hiqs-home-search-results">
              {!options.searchResults.length && <p>{options.searchHint}</p>}
              {options.searchResults.map((result) => <button type="button" key={`${result.title}:${result.resultIndex}`} onClick={() => options.onOpenSearchResult(result.resultIndex)}><span><strong>{result.title}</strong><small>{result.subtitle}</small></span><ArrowRight size={15} /></button>)}
            </div>
          </section>
          <section className="hiqs-home-inbox">
            <header className="hiqs-home-section-heading compact"><div><p>PERSONAL INBOX</p><h2>个人补充信息</h2></div><Badge><Inbox size={13} />{options.inboxCount} 条草稿</Badge></header>
            <span className="hiqs-home-note">AI 将 Tutorial group、临时教室和个人提醒放入这里；预览后再确认写入。</span>
            {!options.inboxEntries.length && <p className="hiqs-home-empty">个人补充信息 Inbox 当前为空。</p>}
            {options.inboxEntries.map((entry) => <InboxEntry key={entry.entry_id} entry={entry} onApply={options.onApplyInbox} />)}
          </section>
        </div>
      </div>

      <section className="hiqs-home-updates">
        <header className="hiqs-home-section-heading compact"><div><p>MOODLE CHANGES</p><h2>更新记录</h2></div><Badge><CalendarDays size={13} />{options.updateCount} 项</Badge></header>
        <span className="hiqs-home-note">逐项显示 Moodle 快照的新增、修改与删除，并标出需要 AI 整理的文件。</span>
        {!options.updates.length && <p className="hiqs-home-empty"><FileText size={15} />当前 Moodle 快照已完成整理。</p>}
        <div className="hiqs-home-update-list">{options.updates.map((course) => <UpdateCourse key={course.course_id} course={course} onOpenSource={options.onOpenSource} />)}</div>
      </section>
    </motion.div>
  );
}
