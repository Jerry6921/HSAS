import { useState, type FormEvent } from "react";
import { motion } from "motion/react";
import { flowEase, flowTransition, useWorkspaceMotion } from "./lib/motion";
import {
  AlertTriangle,
  ArrowRight,
  CalendarDays,
  Check,
  ChevronDown,
  Copy,
  FileText,
  Inbox,
  RefreshCw,
  Search,
} from "lucide-react";
import { Button } from "./components/ui/button";
import { Badge } from "./components/ui/badge";
import type {
  HomeAttentionItem,
  HomeAttentionSnapshot,
  AttentionActionKind,
  AttentionDraftField,
  HomeInboxEntry,
  HomeListEntry,
  HomeRecentUpdate,
  HomeUpdateChange,
  HomeUpdateCourse,
  HomeUpdateOutcome,
  ModernHomeOptions,
} from "./types";

const attentionReasonLabels = {
  DUE_DATE_TENTATIVE: "日期暂定",
  DUE_DATE_UNKNOWN: "日期未知",
  SUBMISSION_DETAILS_MISSING: "提交信息不全",
  WEIGHT_UNKNOWN: "占分未知",
  SOURCE_CONFLICT: "来源冲突",
  SOURCE_SYNC_FAILED: "来源同步失败",
  SOURCE_CHANGED_REVIEW_PENDING: "来源变化待整理",
  LOGIN_REQUIRED: "需要登录",
  OVERDUE_UNRESOLVED: "已逾期未解决",
} as const;

const attentionFieldLabels: Record<AttentionDraftField, string> = {
  due_at: "截止日期与时间",
  due_time: "截止时间",
  submission_method: "提交方式",
  submission_link: "提交链接",
  weight_percent: "成绩占比",
};

function editableAttentionFields(item: HomeAttentionItem): AttentionDraftField[] {
  if (!item.information_item_id) return [];
  const fields: AttentionDraftField[] = [];
  if (item.reason_codes.includes("DUE_DATE_UNKNOWN")) fields.push("due_at");
  if (!fields.includes("due_at") && item.missing_fields.includes("due_time")) fields.push("due_time");
  if (item.missing_fields.includes("submission_method")) fields.push("submission_method");
  if (item.missing_fields.includes("submission_link")) fields.push("submission_link");
  if (item.reason_codes.includes("WEIGHT_UNKNOWN")) fields.push("weight_percent");
  return fields;
}

const ATTENTION_DISMISS_KEY = "hiqs.attention.dismissed.v1";
const sourceWorkflowReasons = new Set(["SOURCE_SYNC_FAILED", "SOURCE_CHANGED_REVIEW_PENDING"]);

function readDismissedAttention(): Record<string, string> {
  try {
    const value = JSON.parse(window.localStorage.getItem(ATTENTION_DISMISS_KEY) || "{}");
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

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

function AttentionRow({ item, onAction, onReviewChanges, onCreateDraft, onDismiss }: {
  item: HomeAttentionItem;
  onAction: (item: HomeAttentionItem, action: AttentionActionKind) => void;
  onReviewChanges: () => void;
  onCreateDraft: ModernHomeOptions["onCreateAttentionDraft"];
  onDismiss: () => void;
}) {
  const [formOpen, setFormOpen] = useState(false);
  const [values, setValues] = useState<Partial<Record<AttentionDraftField, string>>>({});
  const [sourceNote, setSourceNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fields = editableAttentionFields(item);
  const supplementLabels = fields.map((field) => attentionFieldLabels[field]);
  const statusLabels = item.reason_codes
    .filter((reason) => !["DUE_DATE_UNKNOWN", "SUBMISSION_DETAILS_MISSING", "WEIGHT_UNKNOWN"].includes(reason))
    .map((reason) => attentionReasonLabels[reason]);
  const openItem = () => {
    const action = item.actions.find((candidate) => candidate.kind === "open_item") ?? item.actions[0];
    if (!action) return;
    if (action.kind === "review_changes") onReviewChanges();
    onAction(item, action.kind);
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const completed = Object.fromEntries(fields.filter((field) => values[field]?.trim()).map((field) => [field, field === "weight_percent" ? Number(values[field]) : values[field] ?? ""])) as Partial<Record<AttentionDraftField, string | number>>;
    if (!Object.keys(completed).length) { setError("请至少填写一项信息。"); return; }
    setBusy(true);
    setError("");
    const created = await onCreateDraft(item, completed, sourceNote.trim());
    setBusy(false);
    if (created) { setFormOpen(false); setValues({}); setSourceNote(""); }
    else setError("未能建立草稿，请查看页面提示并重试。");
  };

  return <article className={`hiqs-attention-row is-${item.severity}`} role="button" tabIndex={0} onClick={(event) => { if ((event.target as HTMLElement).closest("button, input, textarea, select, a")) return; openItem(); }} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openItem(); } }}>
    <div className="hiqs-attention-copy">
      <h3>{item.title}</h3>
    </div>
    <div className="hiqs-attention-right">
      {fields.length > 0 && <div className="hiqs-attention-facts" aria-label="待补充信息">
        {supplementLabels.map((label) => <span key={label} className={label === "成绩占比" ? "is-weight" : undefined}>{label}</span>)}
      </div>}
      {item.due_at && <time className="hiqs-attention-known-date" dateTime={item.due_at}>{formatDateTime(item.due_at)}</time>}
      {statusLabels.length > 0 && <span className="hiqs-attention-status">{statusLabels.join(" · ")}</span>}
      <div className="hiqs-attention-actions">
        {fields.length > 0 && <Button size="sm" variant={formOpen ? "default" : "ghost"} aria-expanded={formOpen} onClick={() => setFormOpen(!formOpen)}>{formOpen ? "收起表单" : "手动补充"}</Button>}
        <Button size="sm" variant="ghost" onClick={onDismiss}>暂时忽略</Button>
      </div>
    </div>
    {formOpen && <form className="hiqs-attention-form" onSubmit={submit}>
      <div className="hiqs-attention-form-fields">{fields.map((field) => <label key={field}>{attentionFieldLabels[field]}<input type={field === "due_at" ? "datetime-local" : field === "due_time" ? "time" : field === "submission_link" ? "url" : field === "weight_percent" ? "number" : "text"} min={field === "weight_percent" ? "0" : undefined} max={field === "weight_percent" ? "100" : undefined} step={field === "weight_percent" ? "0.1" : undefined} placeholder={field === "submission_method" ? "例如：Moodle 作业入口" : field === "submission_link" ? "https://…" : undefined} value={values[field] || ""} onChange={(event) => setValues((previous) => ({ ...previous, [field]: event.target.value }))} /></label>)}</div>
      <label className="hiqs-attention-source-note">信息来源或核对说明<textarea required minLength={3} maxLength={500} value={sourceNote} onChange={(event) => setSourceNote(event.target.value)} placeholder="例如：课程公告标题及日期；请勿填写密码或令牌。" /></label>
      <div className="hiqs-attention-form-footer"><small>先保存到个人补充信息草稿；预览并再次确认后才会写入课程资料。</small><Button type="submit" size="sm" disabled={busy}>{busy ? "正在建立草稿…" : "提交补充草稿"}</Button></div>
      {error && <p className="hiqs-attention-form-error" role="alert">{error}</p>}
    </form>}
  </article>;
}

export function AttentionRadar({ snapshot, onAction, onReviewChanges, onCreateDraft, onCopyPrompt, embedded = false }: {
  snapshot: HomeAttentionSnapshot;
  onAction: (item: HomeAttentionItem, action: AttentionActionKind) => void;
  onReviewChanges: () => void;
  onCreateDraft: ModernHomeOptions["onCreateAttentionDraft"];
  onCopyPrompt: ModernHomeOptions["onCopyAttentionPrompt"];
  embedded?: boolean;
}) {
  const [sectionOpen, setSectionOpen] = useState(false);
  const [dismissed, setDismissed] = useState<Record<string, string>>(readDismissedAttention);
  const [lastDismissed, setLastDismissed] = useState<HomeAttentionItem | null>(null);
  const visible = snapshot.items.filter((item) => (
    dismissed[item.attention_id] !== item.fingerprint
    && item.reason_codes.some((reason) => !sourceWorkflowReasons.has(reason))
  ));
  const groups = visible.reduce<Array<{ key: string; code: string; title: string; items: HomeAttentionItem[] }>>((result, item) => {
    const key = item.course_id || `${item.course_code || "source"}:${item.course_title || item.affected_source || "HIQS"}`;
    const existing = result.find((group) => group.key === key);
    if (existing) existing.items.push(item);
    else result.push({
      key,
      code: item.course_code || "SOURCE",
      title: item.course_title || item.affected_source || "系统来源",
      items: [item],
    });
    return result;
  }, []);

  const dismiss = (item: HomeAttentionItem) => {
    const next = { ...dismissed, [item.attention_id]: item.fingerprint };
    setDismissed(next);
    setLastDismissed(item);
    window.localStorage.setItem(ATTENTION_DISMISS_KEY, JSON.stringify(next));
  };
  const undo = () => {
    if (!lastDismissed) return;
    const next = { ...dismissed };
    delete next[lastDismissed.attention_id];
    setDismissed(next);
    setLastDismissed(null);
    window.localStorage.setItem(ATTENTION_DISMISS_KEY, JSON.stringify(next));
  };

  const countLabel = snapshot.state === "loading" ? "整理中" : snapshot.state === "error" ? "暂不可用" : `${visible.length} 项`;

  return (
    <motion.section className={`hiqs-attention ${embedded ? "is-embedded" : ""}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: .35 }} aria-labelledby="hiqs-attention-title">
      <details className="hiqs-attention-fold" open={sectionOpen} onToggle={(event) => setSectionOpen(event.currentTarget.open)}>
        <summary className="hiqs-attention-heading">
          <span className="hiqs-attention-index-label">01 / REVIEW</span>
          <span className="hiqs-attention-heading-copy"><strong id="hiqs-attention-title">待确认</strong><small>未来 14 天内，优先核实会影响安排或提交的事项。</small></span>
          <span className={`hiqs-attention-count ${snapshot.state !== "ready" ? "is-status" : ""}`} aria-label={countLabel}>{snapshot.state === "ready" ? <><strong>{visible.length}</strong><em>项</em></> : <strong>{countLabel}</strong>}</span>
          {snapshot.state === "ready" && visible.length > 0 && <button type="button" className="hiqs-attention-copy-prompt" title="复制一段让 AI 逐项询问并整理缺漏信息的提示词" onClick={(event) => { event.preventDefault(); event.stopPropagation(); onCopyPrompt(visible); }}><Copy size={14} />复制 AI 问答提示词</button>}
          <ChevronDown className="hiqs-attention-chevron" size={17} aria-hidden="true" />
        </summary>
        <div className="hiqs-attention-body">
      {snapshot.state === "loading" && <div className="hiqs-attention-loading" role="status"><i /><i /><i /><span>正在整理需要确认的事项…</span></div>}
      {snapshot.state === "error" && <div className="hiqs-attention-state is-error" role="status"><AlertTriangle size={16}/><span>风险摘要暂时无法读取；课程资料与日历仍可正常使用。</span></div>}
      {snapshot.state === "ready" && !visible.length && <div className="hiqs-attention-state"><Check size={16}/><span>未来两周没有需要优先核实的事项。</span>{lastDismissed && <Button size="sm" variant="ghost" onClick={undo}>撤销忽略</Button>}</div>}
      {snapshot.state === "ready" && visible.length > 0 && <div className="hiqs-attention-groups">
        {groups.map((group) => <section className="hiqs-attention-course-group" key={group.key}>
          <header><span>{group.code}</span><h3>{group.title}</h3><small>{group.items.length} 项待处理</small></header>
          <div className="hiqs-attention-list">
            {group.items.map((item) => <AttentionRow key={`${item.attention_id}:${item.fingerprint}`} item={item} onAction={onAction} onReviewChanges={onReviewChanges} onCreateDraft={onCreateDraft} onDismiss={() => dismiss(item)} />)}
          </div>
        </section>)}
      </div>}
      {snapshot.state === "ready" && visible.length > 0 && lastDismissed && <button type="button" className="hiqs-attention-undo" onClick={undo}>已暂时忽略一项 · 撤销</button>}
        </div>
      </details>
    </motion.section>
  );
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
  const kindLabels: Record<string, string> = { deadline: "日期", activity: "项目", material: "文件", course: "课程信息" };
  const fieldLabels: Record<string, string> = {
    title: "标题", semester: "学期", starts_on: "开课日期", ends_on: "结束日期",
    overview: "课程简介", objectives: "学习目标", instructors: "教师", links: "链接",
    policies: "课程政策", notes: "备注", category: "类型", date_status: "日期状态",
    opens_at: "开放时间", starts_at: "开始时间", ends_at: "结束时间", due_at: "截止时间",
    due_on: "截止日期", scheduled_on: "安排日期", recurrence: "重复安排", all_day: "全天",
    location: "地点", description: "说明", assessment_format: "考核形式",
    submission_method: "提交方式", weight_percent: "占分", word_limit: "字数限制",
    requirements: "要求", materials: "相关资料", warnings: "提示", material: "资料归类",
  };
  const canOpen = change.action !== "removed" && Boolean(change.relative_path || change.text_path || change.source_url);
  return (
    <div className="hiqs-home-change-card">
      <div className="hiqs-home-change-title">
        <Badge className={`is-${change.action}`}>{actionLabels[change.action] || change.action}</Badge>
        <span>{kindLabels[change.kind] || change.kind}</span>
        <strong>{change.title}</strong>
        {canOpen && <Button size="sm" variant="ghost" onClick={() => onOpenSource({ ...change, relative_path: change.relative_path || change.text_path })}>预览</Button>}
      </div>
      {change.field && change.field !== 'sha256' && <code className="hiqs-home-change-field">{fieldLabels[change.field] || change.field}</code>}
      {change.action === "modified" && <details className="hiqs-change-details"><summary>{change.field === 'sha256' ? '文件内容已更新 · 查看技术详情' : '查看变更详情'}</summary>
        <div className="hiqs-home-diff">
          <div><span>更新前</span><pre>{previewValue(change.before)}</pre></div>
          <div><span>更新后</span><pre>{previewValue(change.after)}</pre></div>
        </div>
      </details>}
    </div>
  );
}

function UpdateCourse({ course, onOpenSource }: { course: HomeUpdateCourse; onOpenSource: ModernHomeOptions["onOpenSource"] }) {
  const files = (course.files || []).filter((file) => file.relative_path !== "course.json");
  return (
    <article className="hiqs-home-update-course">
      <header>
        <div><h3>{course.course_title}</h3><p>{course.course_id} · 检测至 {formatDateTime(course.acknowledge_through)}</p></div>
        <Badge>{course.mode === "full" ? "首次整理" : course.mode === "completed" ? "已写入" : "增量更新"}</Badge>
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

type OutcomeEntry = HomeUpdateOutcome & { course_id: string; course_title: string; action?: string };

function OutcomeGroup({ title, description, tone, entries, onOpenSource }: {
  title: string;
  description: string;
  tone: string;
  entries: OutcomeEntry[];
  onOpenSource: ModernHomeOptions["onOpenSource"];
}) {
  if (!entries.length) return null;
  return (
    <section className={`hiqs-update-outcome-group is-${tone}`}>
      <header><div><h3>{title}</h3><p>{description}</p></div><strong>{entries.length}</strong></header>
      <div>
        {entries.map((entry) => {
          const canOpen = Boolean(entry.relative_path || entry.text_path || entry.source_url);
          return <article key={`${entry.course_id}:${entry.record_id}:${entry.action || tone}`}>
            <span>{entry.course_title}</span>
            <div><strong>{entry.title}</strong>{entry.details.length > 0 && <p>{entry.details.join(" · ")}</p>}</div>
            {entry.action && <Badge className={`is-${entry.action}`}>{entry.action === "added" ? "新增" : entry.action === "modified" ? "更新" : "移除"}</Badge>}
            {canOpen && <Button size="sm" variant="ghost" onClick={() => onOpenSource({ ...entry, relative_path: entry.relative_path || entry.text_path })}>查看来源</Button>}
          </article>;
        })}
      </div>
    </section>
  );
}

export function RecentUpdateVisual({ recent, pending, onOpenSource }: {
  recent?: HomeRecentUpdate | null;
  pending: HomeUpdateCourse[];
  onOpenSource: ModernHomeOptions["onOpenSource"];
}) {
  const [expanded, setExpanded] = useState(false);
  const completed = Boolean(recent?.courses?.length);
  const courses = completed ? recent!.courses : pending;
  const changes = courses.flatMap((course) => course.changes || []);
  const baselineCount = courses.reduce((sum, course) => sum + (!(course.changes || []).length ? (course.files || []).filter((file) => file.relative_path !== "course.json").length : 0), 0);
  const counts = {
    added: completed ? recent!.summary.added : changes.filter((change) => change.action === "added" || change.action === "baseline").length + baselineCount,
    modified: completed ? recent!.summary.modified : changes.filter((change) => change.action === "modified").length,
    removed: completed ? recent!.summary.removed : changes.filter((change) => change.action === "removed").length,
  };
  const total = counts.added + counts.modified + counts.removed;
  const maxCourseChanges = Math.max(1, ...courses.map((course) => (course.changes || []).length || (course.files || []).length));
  const title = completed ? "最近一次资料更新" : pending.length ? "本轮待写入内容" : "最近没有内容变化";
  const timestamp = completed ? formatDateTime(recent!.applied_at) : "等待下一次同步与 Agent 整理";
  const collect = (field: keyof Pick<HomeUpdateCourse,
    "activities_added" | "activities_updated" | "activities_confirmed" |
    "materials_added" | "materials_updated" | "materials_removed"
  >, action?: string): OutcomeEntry[] => courses.flatMap((course) =>
    (course[field] || []).map((entry) => ({
      ...entry,
      course_id: course.course_id,
      course_title: course.course_title,
      action,
    })),
  );
  const activitiesAdded = collect("activities_added");
  const activitiesConfirmed = collect("activities_confirmed");
  const activitiesUpdated = collect("activities_updated");
  const materialChanges = [
    ...collect("materials_added", "added"),
    ...collect("materials_updated", "modified"),
    ...collect("materials_removed", "removed"),
  ];
  const outcomeCount = activitiesAdded.length + activitiesConfirmed.length + activitiesUpdated.length + materialChanges.length;

  return (
    <section className={`hiqs-update-visual ${!total ? "is-empty" : ""}`} aria-labelledby="hiqs-update-visual-title">
      <header>
        <div><p>CHANGESET / LATEST</p><h2 id="hiqs-update-visual-title">{title}</h2><span>{completed ? `${timestamp} · 已通过校验写入资料库` : timestamp}</span></div>
        {total > 0 && <button type="button" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>{expanded ? "收起明细" : "查看全部明细"}<ChevronDown size={15} /></button>}
      </header>
      {!total ? <p className="hiqs-update-visual-empty"><Check size={16} />资料库与来源保持一致；下一次完成更新后，这里会保留新增与变更摘要。</p> : <>
        <div className="hiqs-update-overview">
          <div className="hiqs-update-total"><strong>{String(total).padStart(2, "0")}</strong><span>项内容变化</span><small>横跨 {courses.length} 门课程</small></div>
          <div className="hiqs-update-breakdown">
            <article className="is-added"><span>新增</span><strong>{counts.added}</strong><small>新课程、事项与资料</small></article>
            <article className="is-modified"><span>变更</span><strong>{counts.modified}</strong><small>日期、内容与归类调整</small></article>
            <article className="is-removed"><span>移除</span><strong>{counts.removed}</strong><small>已不在当前资料中</small></article>
            <div className="hiqs-update-composition" aria-label={`新增 ${counts.added}，变更 ${counts.modified}，移除 ${counts.removed}`}>
              {counts.added > 0 && <i className="is-added" style={{ flexGrow: counts.added }} />}
              {counts.modified > 0 && <i className="is-modified" style={{ flexGrow: counts.modified }} />}
              {counts.removed > 0 && <i className="is-removed" style={{ flexGrow: counts.removed }} />}
            </div>
          </div>
        </div>
        {outcomeCount > 0 && <section className="hiqs-update-outcomes" aria-label="本次整理结果">
          <header><span>本次整理结果</span><small>同一活动的多个字段变化已合并显示</small></header>
          <div>
            <OutcomeGroup title="新增活动" description="本次加入日历或课程记录" tone="activity-added" entries={activitiesAdded} onOpenSource={onOpenSource} />
            <OutcomeGroup title="信息已确认" description="日期由未知或暂定变为已确认" tone="confirmed" entries={activitiesConfirmed} onOpenSource={onOpenSource} />
            <OutcomeGroup title="活动信息变更" description="时间、地点、提交或要求发生变化" tone="activity-updated" entries={activitiesUpdated} onOpenSource={onOpenSource} />
            <OutcomeGroup title="资料变化" description="新增、更新或移除的课程资料" tone="materials" entries={materialChanges} onOpenSource={onOpenSource} />
          </div>
        </section>}
        <div className="hiqs-update-course-map">
          <div className="hiqs-update-course-map-heading"><span>按课程分布</span><small>条形长度代表本次变化数量</small></div>
          {courses.map((course, index) => {
            const courseChanges = (course.changes || []).length || (course.files || []).length;
            const added = (course.changes || []).filter((change) => change.action === "added" || change.action === "baseline").length;
            const modified = (course.changes || []).filter((change) => change.action === "modified").length;
            const removed = (course.changes || []).filter((change) => change.action === "removed").length;
            return <article key={course.course_id}>
              <em>{String(index + 1).padStart(2, "0")}</em>
              <div><strong>{course.course_title}</strong><small>{[added && `${added} 新增`, modified && `${modified} 变更`, removed && `${removed} 移除`].filter(Boolean).join(" · ") || `${courseChanges} 项首次整理`}</small></div>
              <span><i style={{ width: `${Math.max(8, courseChanges / maxCourseChanges * 100)}%` }} /></span>
              <b>{courseChanges}</b>
            </article>;
          })}
        </div>
      </>}
      {expanded && <div className="hiqs-update-visual-details">{courses.map((course) => <UpdateCourse key={course.course_id} course={course} onOpenSource={onOpenSource} />)}</div>}
    </section>
  );
}

export function HomeIsland({ options }: { options: ModernHomeOptions }) {
  const [workspace, setWorkspace] = useState(false);
  const today = new Date();
  const dateNumber = String(today.getDate()).padStart(2, '0');
  const dateMonth = new Intl.DateTimeFormat('zh-HK', {year: 'numeric', month: 'long'}).format(today);
  const weekday = new Intl.DateTimeFormat('zh-HK', {weekday: 'long'}).format(today);
  const animate = useWorkspaceMotion();
  const reveal = animate ? { opacity: 0, y: 16 } : false;
  const sync = options.syncJob;
  const syncing = sync?.state === "running";
  const syncTotal = Math.max(1, sync?.total || 1);
  const syncCompleted = Math.min(sync?.completed || 0, syncTotal);
  const syncPercent = Math.round((syncCompleted / syncTotal) * 100);

  return (
    <div className="hiqs-modern-home">
      <div className="hiqs-workspace-tabs" role="group" aria-label="首页视图"><Button aria-pressed={!workspace} variant={!workspace ? 'default' : 'ghost'} onClick={() => setWorkspace(false)}>今天{!workspace && <motion.span layoutId="hiqs-home-tab" className="hiqs-tab-indicator" transition={animate ? { type: 'spring', stiffness: 370, damping: 38 } : { duration: 0 }} />}</Button><Button aria-pressed={workspace} variant={workspace ? 'default' : 'ghost'} onClick={() => setWorkspace(true)}>资料中心 {options.statusTotal > 0 && <Badge>{options.statusTotal}</Badge>}{workspace && <motion.span layoutId="hiqs-home-tab" className="hiqs-tab-indicator" transition={animate ? { type: 'spring', stiffness: 370, damping: 38 } : { duration: 0 }} />}</Button></div>
      {!workspace && <>
      <motion.header className="hiqs-editorial-masthead" initial={reveal} animate={{ opacity: 1, y: 0 }} transition={flowTransition}>
        <div className="hiqs-masthead-date"><span>{dateMonth}</span><strong>{dateNumber}</strong><span>{weekday}</span></div>
        <div className="hiqs-masthead-copy"><span className="hiqs-kicker">HIQS / STUDY JOURNAL · 01</span><h2>今天，值得掌握的事。</h2><p>课程日程与资料变化，按你的学习节奏排列。</p></div>
        <div className="hiqs-masthead-facts"><span><strong>{options.today.length}</strong> 今天的安排</span><span><strong>{options.deadlines.length}</strong> 近期考核</span><span><strong>{options.statusTotal}</strong> 资料提醒</span></div>
      </motion.header>
      <motion.div className="hiqs-feature-layout" initial={reveal} animate={{ opacity: 1, y: 0 }} transition={{ duration: .5, delay: .07, ease: flowEase }}>
      <motion.button
        type="button"
        className={`hiqs-home-next ${options.nextUp.empty ? "is-empty" : ""}`}
        disabled={options.nextUp.empty}
        whileHover={animate ? { scale: 1.005 } : undefined}
        transition={{ duration: .32, ease: flowEase }}
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
      <aside className="hiqs-feature-note"><span className="hiqs-kicker">AT A GLANCE / 02</span><strong>先看下一项，再进入细节。</strong><p>点击事项可查看时间、地点及相关来源；待核实信息会单独标明。</p><button type="button" onClick={() => setWorkspace(true)}>查看资料状态 <ArrowRight size={16}/></button></aside>
      </motion.div>

      <motion.section className="hiqs-daily-grid" initial={reveal} animate={{ opacity: 1, y: 0 }} transition={{ duration: .48, delay: .13, ease: flowEase }}>{[["今天的安排", options.today], ["接下来 · 考核与截止", options.deadlines]].map(([title, entries], index) => <section key={String(title)}><header className="hiqs-editorial-section-title"><span>0{index + 3} / AGENDA</span><h2>{String(title)}</h2></header>{(entries as ModernHomeOptions['today']).length ? (entries as ModernHomeOptions['today']).map((entry, row) => <button className="hiqs-agenda-row" key={`${entry.itemId}:${entry.dateKey}`} onClick={() => options.onOpenNext(entry.itemId, entry.dateKey)}><em>{String(row + 1).padStart(2, '0')}</em><span><strong>{entry.title}</strong><small>{entry.meta}</small></span><ArrowRight size={16}/></button>) : <p className="hiqs-home-empty">暂无已排定事项。待确认日期可在日历中查看。</p>}</section>)}</motion.section>
      <motion.section className="hiqs-recent" initial={reveal} animate={{ opacity: 1, y: 0 }} transition={{ duration: .48, delay: .18, ease: flowEase }}><header className="hiqs-editorial-section-title"><span>05 / ARCHIVE</span><h2>课程资料更新</h2></header>{options.updates.length ? options.updates.slice(0, 5).map((course, index) => <article key={course.course_id}><em>{String(index + 1).padStart(2, '0')}</em><strong>{course.course_title}</strong><span>{course.changes?.length || course.files?.length || 0} 项变更</span><Button size="sm" onClick={() => setWorkspace(true)}>查看更新</Button></article>) : <p>当前没有待整理的资料更新。</p>}</motion.section>
      <motion.button className="hiqs-health" initial={reveal} animate={{ opacity: 1, y: 0 }} transition={{ duration: .48, delay: .22, ease: flowEase }} onClick={() => setWorkspace(true)}><span>{syncing ? "正在同步课程资料…" : options.statusTotal ? `${options.statusTotal} 项资料状态需要关注` : "本地资料状态正常"}</span><span>打开资料中心 →</span></motion.button>
      </>}

      {workspace && <motion.section className="hiqs-home-command" initial={reveal} animate={{ opacity: 1, y: 0 }} transition={flowTransition}>
        <div className="hiqs-home-closure">
          <div className="hiqs-home-closure-heading">
            <div><p>INFORMATION CLOSURE</p><h3>资料闭环</h3></div>
            <div>
              <Button className="hiqs-sync-action" variant="default" size="sm" onClick={options.onStartWorkflow} disabled={syncing}>{syncing ? "同步中" : "开始同步"}</Button>
              {options.hasRetryTasks && <Button size="sm" onClick={options.onRetryFailures}><RefreshCw size={14} />只重试失败项</Button>}
              <Button size="sm" onClick={options.onCopyAgentPrompt} disabled={!options.hasAgentPrompt}><Copy size={14} />复制 Agent 整理指令</Button>
            </div>
          </div>
          <div className="hiqs-home-stages">
            {options.stages.map((stage, index) => (
              <motion.article key={stage.id} initial={animate ? { opacity: 0, x: -8 } : false} animate={{ opacity: 1, x: 0 }} transition={{ duration: .35, delay: index * .035, ease: flowEase }} className={stage.state}>
                <i>{stage.state === "complete" ? <Check size={12} /> : <span />}</i>
                <strong>{stage.label}</strong>
                <small>{stage.state === "complete" ? "已完成" : stage.count ? `${stage.count} 项待处理` : "待处理"}</small>
              </motion.article>
            ))}
          </div>
          {syncing && (
            <div className="hiqs-home-sync" role="status">
              <div className="hiqs-home-sync-heading"><div><small>SYNC / LIVE STATUS</small><span><RefreshCw className="hiqs-spin" size={15} />{sync?.cancel_requested ? "正在取消同步" : sync?.detail || "正在同步课程资料"}</span></div><strong>{syncPercent}<em>%</em></strong></div>
              <div className="hiqs-home-sync-track"><progress value={syncCompleted} max={syncTotal} aria-label={`同步进度 ${syncPercent}%`} /><span style={{ width: `${syncPercent}%` }} /></div>
              <div className="hiqs-home-sync-meta"><span>{syncCompleted} / {syncTotal} 个同步项目</span><Button size="sm" variant="ghost" onClick={options.onCancelSync} disabled={Boolean(sync?.cancel_requested)}>{sync?.cancel_requested ? "等待取消" : "取消同步"}</Button></div>
            </div>
          )}
          {options.retrySummary && <p className="hiqs-home-retry"><AlertTriangle size={14} />{options.retrySummary}</p>}
          <section className="hiqs-home-review">
            <AttentionRadar embedded snapshot={options.attentionSnapshot} onAction={options.onAttentionAction} onCreateDraft={options.onCreateAttentionDraft} onCopyPrompt={options.onCopyAttentionPrompt} onReviewChanges={() => document.querySelector<HTMLElement>(".hiqs-home-updates")?.scrollIntoView({ behavior: animate ? "smooth" : "auto", block: "start" })} />
          </section>
          </div>

        <div className="hiqs-home-metrics">
          {options.metrics.map((metric) => <article key={metric.label}><span>{metric.label}</span><strong>{metric.value}</strong><small>{metric.note}</small></article>)}
        </div>
        <RecentUpdateVisual recent={options.recentUpdate} pending={options.updates} onOpenSource={options.onOpenSource} />
      </motion.section>}

      <div className={`hiqs-home-grid ${workspace ? 'is-workspace' : 'is-today'}`}>
        <div className="hiqs-home-side">
          <section className="hiqs-home-search">
            <header><p>LOCAL SEARCH</p><h2>本地问答式搜索</h2><span>在课程事项、课件和来源中查找匹配内容。</span></header>
            <label><Search size={17} /><input type="search" value={options.searchQuery} onChange={(event) => options.onSearch(event.target.value)} placeholder="例如：MATH1851 Part I test 占分多少？" /></label>
            <div className="hiqs-home-search-results">
              {!options.searchResults.length && <p>{options.searchHint}</p>}
              {options.searchResults.map((result) => <button type="button" key={`${result.title}:${result.resultIndex}`} onClick={() => options.onOpenSearchResult(result.resultIndex)}><span><strong>{result.title}</strong><small>{result.subtitle}</small></span><ArrowRight size={15} /></button>)}
            </div>
          </section>
          {workspace && <section className="hiqs-home-inbox">
            <header className="hiqs-home-section-heading compact"><div><p>PERSONAL INBOX</p><h2>个人补充信息</h2></div><Badge><Inbox size={13} />{options.inboxCount} 条草稿</Badge></header>
            <span className="hiqs-home-note">AI 将 Tutorial group、临时教室和个人提醒放入这里；预览后再确认写入。</span>
            {!options.inboxEntries.length && <p className="hiqs-home-empty">个人补充信息 Inbox 当前为空。</p>}
            {options.inboxEntries.map((entry) => <InboxEntry key={entry.entry_id} entry={entry} onApply={options.onApplyInbox} />)}
          </section>}
        </div>
      </div>

      {workspace && <section className="hiqs-home-updates">
        <header className="hiqs-home-section-heading compact"><div><p>MOODLE CHANGES</p><h2>更新记录</h2></div><Badge><CalendarDays size={13} />{options.updateCount} 项</Badge></header>
        <span className="hiqs-home-note">逐项显示 Moodle 快照的新增、修改与删除，并标出需要 AI 整理的文件。</span>
        {!options.updates.length && <p className="hiqs-home-empty"><FileText size={15} />当前 Moodle 快照已完成整理。</p>}
        <div className="hiqs-home-update-list">{options.updates.map((course) => <UpdateCourse key={course.course_id} course={course} onOpenSource={options.onOpenSource} />)}</div>
      </section>}
    </div>
  );
}
