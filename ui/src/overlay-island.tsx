import { forwardRef, useEffect, useImperativeHandle, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { flowEase, useWorkspaceMotion } from "./lib/motion";
import { ArrowUpRight, Copy, ExternalLink, FileText, Plus, Trash2, X } from "lucide-react";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import type {
  CourseSource,
  EventEditorDefaults,
  EventEditorValue,
  ModernDetailOptions,
  ModernOverlayOptions,
  NewCourseValue,
} from "./types";

export interface OverlayHandle {
  update: (options: ModernOverlayOptions) => void;
  openDetail: (value: ModernDetailOptions) => void;
  closeDetail: () => void;
  openSource: (value: CourseSource) => void;
  closeSource: () => void;
  openEventEditor: (value: EventEditorDefaults) => void;
  closeEventEditor: () => void;
  openCourseManager: () => void;
  closeCourseManager: () => void;
}

interface SourcePayload {
  title: string;
  preview_kind: string;
  original_relative_path: string;
  page_numbers: number[];
  text?: string | null;
  final_url?: string | null;
  screenshot_data_url?: string | null;
}

function isMoodleUrl(value: string | null): value is string {
  if (!value) return false;
  try {
    const host = new URL(value).hostname.toLowerCase();
    return host === "moodle.hku.hk" || host.endsWith(".moodle.hku.hk");
  } catch { return false; }
}

function Modal({ children, onClose, wide = false }: { children: ReactNode; onClose: () => void; wide?: boolean }) {
  const animate = useWorkspaceMotion();
  const dialog = useRef<HTMLElement>(null);
  const close = useRef(onClose); close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.current?.focus();
    const key = (event: KeyboardEvent) => {
      const dialogs = document.querySelectorAll('[role="dialog"]');
      if (dialogs[dialogs.length - 1] !== dialog.current) return;
      if (event.key === 'Escape') { event.preventDefault(); close.current(); }
      if (event.key === 'Tab') {
        const nodes = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), summary, [tabindex="0"]') || []).filter(node => node.getClientRects().length);
        if (!nodes.length) { event.preventDefault(); return; }
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog.current)) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('keydown', key); document.body.style.overflow = oldOverflow; previous?.focus(); };
  }, []);
  return <motion.div className="hiqs-modal-backdrop" initial={animate ? { opacity: 0 } : false} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: animate ? .22 : 0 }} onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <motion.section ref={dialog} role="dialog" aria-modal="true" aria-label="详情与操作" tabIndex={-1} className={`hiqs-modal ${wide ? "is-wide" : ""}`} initial={animate ? { opacity: 0, y: 22, scale: .985 } : false} animate={{ opacity: 1, y: 0, scale: 1 }} exit={animate ? { opacity: 0, y: 8, scale: .99 } : { opacity: 0 }} transition={{ duration: animate ? .34 : 0, ease: flowEase }}>{children}</motion.section>
  </motion.div>;
}

function ModalHeader({ eyebrow, title, onClose }: { eyebrow: string; title: string; onClose: () => void }) {
  return <header className="hiqs-modal-header"><div><p>{eyebrow}</p><h2>{title}</h2></div><Button size="icon" aria-label="关闭" onClick={onClose}><X size={18} /></Button></header>;
}

function SourceCards({ title, values, onOpen }: { title: string; values: CourseSource[]; onOpen: (source: CourseSource) => void }) {
  if (!values.length) return null;
  return <section className="hiqs-detail-block"><h3>{title}</h3><div className="hiqs-detail-sources">{values.map((source, index) => <button type="button" key={`${source.title || source.relative_path}:${index}`} onClick={() => onOpen(source)}><FileText size={14} /><span>{source.title || source.label || source.relative_path || "来源"}</span><ArrowUpRight size={14} /></button>)}</div></section>;
}

function DetailModal({ detail, options, onClose, onOpenSource }: { detail: ModernDetailOptions; options: ModernOverlayOptions; onClose: () => void; onOpenSource: (source: CourseSource) => void }) {
  return <Modal onClose={onClose} wide><ModalHeader eyebrow="CALENDAR ITEM" title={detail.title} onClose={onClose} /><div className={`hiqs-detail-body category-${detail.categoryKey}`}>
    <div className="hiqs-detail-course">{detail.courseLabel}</div>
    <div className="hiqs-detail-pills"><Badge>{detail.category}</Badge><Badge>{detail.dateStateLabel}</Badge>{detail.weightLabel && <Badge>{detail.weightLabel}</Badge>}{detail.warningCount > 0 && <Badge>{detail.warningCount} 项提醒</Badge>}</div>
    {detail.description && <p className="hiqs-detail-description">{detail.description}</p>}
    <dl className="hiqs-detail-facts">{detail.facts.map((fact) => <div key={fact.label}><dt>{fact.label}</dt><dd>{fact.value}</dd></div>)}</dl>
    {detail.blocks.map((block) => <section key={block.title} className={`hiqs-detail-block ${block.warning ? "is-warning" : ""}`}><h3>{block.title}</h3><ul>{block.values.map((value, index) => <li key={`${value}:${index}`}>{value}</li>)}</ul></section>)}
    <SourceCards title="相关学习材料" values={detail.materials} onOpen={onOpenSource} />
    {!!detail.links.length && <section className="hiqs-detail-block"><h3>相关链接</h3><div className="hiqs-detail-sources">{detail.links.map((link) => <a key={link.url} href={link.url} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} /><span>{link.label}</span><ArrowUpRight size={14} /></a>)}</div></section>}
    <SourceCards title="证据来源" values={detail.sources} onOpen={onOpenSource} />
    <SourceCards title="本次变更来源" values={detail.exceptionSources} onOpen={onOpenSource} />
    <div className="hiqs-modal-actions"><Button onClick={() => detail.prompt && options.onCopyPrompt(detail.prompt, `“${detail.title}”活动查询提示词已复制。`)} disabled={!detail.hasPrompt}><Copy size={14} />复制 AI 提示词</Button>{detail.userCreated && <Button className="hiqs-danger" onClick={() => options.onDeleteEvent(detail.itemId)}><Trash2 size={14} />删除事件</Button>}</div>
  </div></Modal>;
}

function SourceModal({ source, onClose }: { source: CourseSource; onClose: () => void }) {
  const [payload, setPayload] = useState<SourcePayload | null>(null);
  const [error, setError] = useState("");
  const remoteValue = source.url || source.source_url;
  const remote = remoteValue && /^https?:\/\//i.test(remoteValue) ? remoteValue : null;
  const moodleRemote = isMoodleUrl(remote);
  const [loading, setLoading] = useState(Boolean(source.relative_path || moodleRemote));
  useEffect(() => {
    let active = true;
    setPayload(null); setError(""); setLoading(Boolean(source.relative_path || moodleRemote));
    if (!source.relative_path && !moodleRemote) return () => { active = false; };
    let request: Promise<Response>;
    if (source.relative_path) {
      const params = new URLSearchParams({ path: source.relative_path });
      for (const page of source.page_numbers || []) params.append("page", String(page));
      request = fetch(`/api/source-preview?${params}`, { cache: "no-store" });
    } else {
      request = fetch("/api/moodle/preview", { method: "POST", headers: { "Content-Type": "application/json", "X-HIQS-Request": "1" }, body: JSON.stringify({ url: remote }) });
    }
    request.then(async (response) => {
      const value = await response.json();
      if (!response.ok) throw new Error(value.error || "无法预览来源");
      if (active) setPayload(value);
    }).catch((reason) => { if (active) setError(reason.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [source, moodleRemote, remote]);
  const localUrl = payload ? `/api/material?path=${encodeURIComponent(payload.original_relative_path)}` : "";
  const pageHash = payload?.page_numbers?.length ? `#page=${payload.page_numbers[0]}` : "";
  return <Modal onClose={onClose} wide><ModalHeader eyebrow="SOURCE PREVIEW" title={source.title || source.label || "来源预览"} onClose={onClose} /><p className="hiqs-source-path">{source.relative_path || remote || ""}</p><div className="hiqs-source-body">
    {loading && <p>{moodleRemote ? "正在通过共享 Moodle 会话打开页面…" : "正在读取本地来源…"}</p>}
    {error && <p className="is-error">{error}</p>}
    {!source.relative_path && !moodleRemote && <p>该来源保留了外部链接，可通过下方按钮查看。</p>}
    {payload?.preview_kind === "pdf" && <><iframe src={`${localUrl}${pageHash}`} title={payload.title} />{payload.text && <details><summary>PDF 预览为空？查看已提取文本</summary><pre>{payload.text}</pre></details>}</>}
    {payload?.preview_kind === "image" && <img src={localUrl} alt={payload.title} />}
    {payload?.preview_kind === "web" && payload.screenshot_data_url && <><img className="hiqs-source-web-preview" src={payload.screenshot_data_url} alt={`${payload.title} 页面预览`} />{payload.text && <details><summary>查看页面可读文本</summary><pre>{payload.text}</pre></details>}</>}
    {payload && !["pdf", "image", "web"].includes(payload.preview_kind) && (payload.text ? <pre>{payload.text}</pre> : <p>该文件可打开原文；当前没有可显示的文本副本。</p>)}
  </div><div className="hiqs-modal-actions">{payload && payload.preview_kind !== "web" && <Button asChild variant="default"><a href={localUrl}><FileText size={14} />打开原文</a></Button>}{remote && <Button asChild><a href={remote} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} />在系统浏览器打开</a></Button>}</div></Modal>;
}

const categoryOptions = [["class","课程"],["tutorial","Tutorial"],["lab","实验"],["office_hour","Office hour"],["assignment","Assignment"],["quiz","Quiz"],["exam","考试"],["presentation","汇报"],["project","项目"],["report","报告"],["reading","阅读"],["deadline","截止时间"],["other","其他"]];

function EventEditorModal({ defaults, options, onClose }: { defaults: EventEditorDefaults; options: ModernOverlayOptions; onClose: () => void }) {
  const [value, setValue] = useState<EventEditorValue>({ course_id: defaults.courseId || options.courses[0]?.courseId || "", title: "", category: "other", all_day: false, date: defaults.date, start_time: defaults.startTime, end_time: defaults.endTime, location: "", description: "" });
  const set = <K extends keyof EventEditorValue>(key: K, next: EventEditorValue[K]) => setValue((current) => ({ ...current, [key]: next }));
  return <Modal onClose={onClose}><ModalHeader eyebrow="PERSONAL EVENT" title="添加事件" onClose={onClose} /><form className="hiqs-modern-form" onSubmit={(event) => { event.preventDefault(); if (!value.all_day && value.end_time <= value.start_time) { window.alert("结束时间必须晚于开始时间。"); return; } options.onSubmitEvent(value); }}>
    <label>课程<select value={value.course_id} onChange={(event) => set("course_id", event.target.value)} required>{options.courses.map((course) => <option key={course.courseId} value={course.courseId}>{course.label}</option>)}</select></label>
    <div><label>标题<input value={value.title} onChange={(event) => set("title", event.target.value)} maxLength={160} required placeholder="例如 小组讨论" /></label><label>分类<select value={value.category} onChange={(event) => set("category", event.target.value)}>{categoryOptions.map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
    <label className="hiqs-check"><input type="checkbox" checked={value.all_day} onChange={(event) => set("all_day", event.target.checked)} /><span>全天事件</span></label>
    <div><label>日期<input type="date" value={value.date} onChange={(event) => set("date", event.target.value)} required /></label><label>开始<input type="time" value={value.start_time} disabled={value.all_day} onChange={(event) => set("start_time", event.target.value)} required /></label><label>结束<input type="time" value={value.end_time} disabled={value.all_day} onChange={(event) => set("end_time", event.target.value)} required /></label></div>
    <div><label>地点<input value={value.location} onChange={(event) => set("location", event.target.value)} maxLength={160} placeholder="可选" /></label><label>说明<input value={value.description} onChange={(event) => set("description", event.target.value)} maxLength={500} placeholder="可选" /></label></div>
    <p>新增事件会写入本地 information.json；只有这里创建的个人事件可以删除。</p><div className="hiqs-modal-actions"><Button type="button" onClick={onClose}>取消</Button><Button type="submit" variant="default" disabled={options.operationRunning}>确认添加</Button></div>
  </form></Modal>;
}

function CourseManagerModal({ options, onClose }: { options: ModernOverlayOptions; onClose: () => void }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [course, setCourse] = useState<NewCourseValue>({ course_id: "", code: "", title: "", semester: "" });
  const allSelected = options.managerCourses.length > 0 && selected.length === options.managerCourses.length;
  return <Modal onClose={onClose} wide><ModalHeader eyebrow="COURSE DATABASE" title="管理课程" onClose={onClose} /><form className="hiqs-modern-form hiqs-add-course" onSubmit={(event) => { event.preventDefault(); options.onAddCourse(course); }}><div><label>课程 ID<input required pattern="[A-Za-z0-9][A-Za-z0-9._:-]*" value={course.course_id} onChange={(event) => setCourse({ ...course, course_id: event.target.value })} /></label><label>课程代码<input required value={course.code} onChange={(event) => setCourse({ ...course, code: event.target.value })} /></label></div><label>课程名称<input required value={course.title} onChange={(event) => setCourse({ ...course, title: event.target.value })} /></label><label>学期<input value={course.semester} onChange={(event) => setCourse({ ...course, semester: event.target.value })} /></label><Button type="submit" variant="default" disabled={options.operationRunning}><Plus size={14} />添加课程</Button></form>
    <p className="hiqs-manager-note">删除会移除课程、关联事项和本地课程文件；文件会转移到本机回收目录。</p><div className="hiqs-manager-toolbar"><label className="hiqs-check"><input type="checkbox" checked={allSelected} onChange={() => setSelected(allSelected ? [] : options.managerCourses.map((item) => item.courseId))} /><span>全选</span></label><span>已选择 {selected.length} 门</span><Button className="hiqs-danger" size="sm" disabled={!selected.length || options.operationRunning} onClick={() => options.onDeleteCourses(selected)}><Trash2 size={14} />删除所选</Button></div>
    <div className="hiqs-manager-list">{options.managerCourses.map((item) => <article key={item.courseId} className={`tone-${item.toneIndex} ${selected.includes(item.courseId) ? "is-selected" : ""}`}><label className="hiqs-check"><input type="checkbox" checked={selected.includes(item.courseId)} onChange={() => setSelected((current) => current.includes(item.courseId) ? current.filter((id) => id !== item.courseId) : [...current, item.courseId])} /><span /></label><i /><div><strong>{item.code}</strong><small>{item.title}{item.semester ? ` · ${item.semester}` : ""}</small></div><Button className="hiqs-danger" size="sm" onClick={() => options.onDeleteCourse(item.courseId)} disabled={options.operationRunning}><Trash2 size={14} />删除</Button></article>)}</div>
  </Modal>;
}

export const OverlayIsland = forwardRef<OverlayHandle, { initialOptions: ModernOverlayOptions }>(({ initialOptions }, ref) => {
  const [options, setOptions] = useState(initialOptions);
  const [detail, setDetail] = useState<ModernDetailOptions | null>(null);
  const [source, setSource] = useState<CourseSource | null>(null);
  const [editor, setEditor] = useState<EventEditorDefaults | null>(null);
  const [manager, setManager] = useState(false);
  useImperativeHandle(ref, () => ({ update: setOptions, openDetail: setDetail, closeDetail: () => setDetail(null), openSource: setSource, closeSource: () => setSource(null), openEventEditor: setEditor, closeEventEditor: () => setEditor(null), openCourseManager: () => setManager(true), closeCourseManager: () => setManager(false) }), []);
  return <AnimatePresence>{detail && <DetailModal key="detail" detail={detail} options={options} onClose={() => { setDetail(null); options.onCloseDetail(); }} onOpenSource={setSource} />}{source && <SourceModal key="source" source={source} onClose={() => setSource(null)} />}{editor && <EventEditorModal key="editor" defaults={editor} options={options} onClose={() => setEditor(null)} />}{manager && <CourseManagerModal key="manager" options={options} onClose={() => setManager(false)} />}</AnimatePresence>;
});
