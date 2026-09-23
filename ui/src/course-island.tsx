import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useState } from "react";
import { ArrowUpRight, BookOpen, Copy, Diamond, ExternalLink, FileText, ListChecks } from "lucide-react";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import type {
  CourseActivityItem,
  CourseContentMode,
  CourseMaterialItem,
  CourseSource,
  ModernCourseOptions,
} from "./types";

const modes: Array<[CourseContentMode, string]> = [["materials", "课件"], ["activities", "活动"]];

function MaterialCard({ material, options }: { material: CourseMaterialItem; options: ModernCourseOptions }) {
  return (
    <motion.article className={`hiqs-course-material tone-${material.tone}`}>
      <button type="button" className="hiqs-course-material-main" disabled={!material.canOpen} onClick={() => options.onOpenSource(material.source)}>
        <span className="hiqs-course-material-icon">{material.code}</span>
        <span className="hiqs-course-material-copy">
          <span className="hiqs-course-material-title">
            <strong>{material.title}</strong>
            {material.changeLabel && <Badge>{material.changeLabel}</Badge>}
          </span>
          <small>{material.meta}</small>
          {material.error && <small className="is-error">{material.error}</small>}
        </span>
        <span className="hiqs-course-open">{material.canOpen ? <><span>预览</span><ArrowUpRight size={15} /></> : "—"}</span>
      </button>
      <Button
        type="button"
        variant="ghost"
        className="hiqs-course-prompt"
        title="复制 AI 提示词"
        aria-label={`复制 ${material.title} 的 AI 提示词`}
        disabled={!material.hasPrompt || !material.prompt}
        onClick={() => material.prompt && options.onCopyPrompt(material.prompt, `“${material.title}”定位与总结提示词已复制。`)}
      ><Copy size={16} /></Button>
    </motion.article>
  );
}

function ActivityCard({ item, options }: { item: CourseActivityItem; options: ModernCourseOptions }) {
  return (
    <motion.article className={`hiqs-course-activity category-${item.categoryKey}`}>
      <button type="button" className="hiqs-course-activity-main" onClick={() => options.onOpenItem(item.itemId)}>
        <span className="hiqs-course-activity-icon"><Diamond size={17} fill="currentColor" /></span>
        <span className="hiqs-course-activity-copy">
          <span><strong>{item.title}</strong><Badge className={`date-${item.dateState}`}>{item.dateStateLabel}</Badge></span>
          <small>{item.meta}</small>
          {item.description && <small className="description">{item.description}</small>}
        </span>
        <span className="hiqs-course-open"><span>详情</span><ArrowUpRight size={15} /></span>
      </button>
      <Button
        type="button"
        variant="ghost"
        className="hiqs-course-prompt"
        title="复制 AI 提示词"
        aria-label={`复制 ${item.title} 的 AI 提示词`}
        disabled={!item.hasPrompt || !item.prompt}
        onClick={() => item.prompt && options.onCopyPrompt(item.prompt, `“${item.title}”活动查询提示词已复制。`)}
      ><Copy size={16} /></Button>
    </motion.article>
  );
}

function SourceButton({ source, onOpen }: { source: CourseSource; onOpen: (source: CourseSource) => void }) {
  const title = source.title || source.label || source.relative_path || source.url || source.source_url || "课程来源";
  return <button type="button" onClick={() => onOpen(source)}><FileText size={14} /><span>{title}</span><ArrowUpRight size={14} /></button>;
}

export function CourseIsland({ options }: { options: ModernCourseOptions }) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => { try { return JSON.parse(localStorage.getItem('hiqs-material-sections') || '{}'); } catch { return {}; } });
  const [query, setQuery] = useState('');
  const toggleSection = (key: string, closed: boolean) => setCollapsed(previous => { const next = {...previous, [key]: closed}; try { localStorage.setItem('hiqs-material-sections', JSON.stringify(next)); } catch {} return next; });
  const reduceMotion = useReducedMotion();
  const showingMaterials = options.mode === "materials";
  return (
    <motion.div className="hiqs-modern-course" initial={reduceMotion ? false : { opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .24, ease: [.2, .75, .2, 1] }}>
      <section className="hiqs-course-hero">
        <div>
          <p>COURSE FILE / {options.code}</p>
          <h2>{options.title}</h2>
          <span>{options.facts}</span>
        </div>
        {options.moodleUrl && <Button asChild><a href={options.moodleUrl} target="_blank" rel="noopener noreferrer"><ExternalLink size={15} />打开 Moodle</a></Button>}
      </section>

      <div className="hiqs-course-upper">
        <section className="hiqs-course-summary">
          <p>AI SUMMARY</p><h3>课程综合信息</h3>
          <span className="hiqs-course-provenance">由 AI 根据已下载课程资料归纳；事实仍以所列来源为准。</span>
          <h4>课程概述</h4>
          <div className={options.overview ? "hiqs-course-copy" : "hiqs-course-empty"}>{options.overview || "尚未从官方资料录入课程概述。"}</div>
          <h4>课程目的</h4>
          {options.objectives.length ? <ul>{options.objectives.map((objective, index) => <li key={`${objective}:${index}`}>{objective}</li>)}</ul> : <div className="hiqs-course-empty">尚未从官方资料录入课程目的。</div>}
          {!!options.sources.length && <><h4>信息来源</h4><div className="hiqs-course-sources">{options.sources.map((source, index) => <SourceButton key={`${source.title || source.relative_path}:${index}`} source={source} onOpen={options.onOpenSource} />)}</div></>}
        </section>

        <section className="hiqs-course-grades">
          <p>ASSESSMENT</p><h3>成绩构成</h3>
          {options.grades.length ? (
            <div className="hiqs-course-grade-list">
              {options.grades.map((grade, index) => <div key={`${grade.title}:${index}`}><span><strong>{grade.title}</strong><b>{grade.weightPercent}%</b></span><progress value={grade.weightPercent} max="100" /></div>)}
            </div>
          ) : <div className="hiqs-course-empty">尚未从官方资料确认成绩构成。</div>}
          {!!options.grades.length && <small className="hiqs-course-grade-note">仅列出已确认占分；父项与子项不会自动相加。</small>}
        </section>
      </div>

      <section className="hiqs-course-content">
        <header>
          <div><p>COURSE CONTENT</p><h2>{showingMaterials ? "全部课件" : "课程活动"}</h2></div>
          <div className="hiqs-course-content-actions">
            <span>{options.archiveSummary}</span>
            {showingMaterials && <Button size="sm" onClick={options.onCopyRecentPrompt} disabled={!options.hasRecentPrompt}><Copy size={14} />复制最近 Lecture 提示词</Button>}
            <div className="hiqs-course-mode" aria-label="课程内容类型">
              {modes.map(([mode, label]) => <Button key={mode} type="button" variant="ghost" size="sm" className={options.mode === mode ? "is-active" : undefined} aria-pressed={options.mode === mode} onClick={() => options.onModeChange(mode)}>{options.mode === mode && <motion.span layoutId="hiqs-course-mode" className="hiqs-course-mode-active" />}<span>{label}</span></Button>)}
            </div>
          </div>
        </header>

        {showingMaterials && <label className="hiqs-material-search">查找资料<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="输入文件名或关键词" /></label>}
        <AnimatePresence mode="wait" initial={false}>
          <motion.div key={options.mode} initial={reduceMotion ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={reduceMotion ? undefined : { opacity: 0, y: -6 }} transition={{ duration: .18 }}>
            {showingMaterials ? (
              options.materialSections.length ? options.materialSections.map((section) => (
                <details key={`${options.courseId}:${section.title}`} open={query ? true : !collapsed[`${options.courseId}:${section.title}`]} onToggle={event => { if (!query) toggleSection(`${options.courseId}:${section.title}`, !event.currentTarget.open); }} className={`hiqs-course-material-section tone-${section.toneIndex}${section.unclassified ? " is-unclassified" : ""}`}>
                  <summary>{section.title}<Badge>{section.materials.length} 项</Badge></summary>
                  {section.description && <p className="hiqs-section-description">{section.description}</p>}
                  <div className="hiqs-course-material-list">{section.materials.filter(material => `${material.title} ${material.meta}`.toLowerCase().includes(query.toLowerCase())).map((material) => <MaterialCard key={material.id} material={material} options={options} />)}</div>
                </details>
              )) : <div className="hiqs-course-empty large"><BookOpen size={18} />当前 Moodle 快照中没有课程资料。</div>
            ) : (
              options.activities.length ? options.activities.map((group) => (
                <section key={group.categoryKey} className={`hiqs-course-activity-section category-${group.categoryKey}`}>
                  <header><h3>{group.category}</h3><Badge>{group.items.length} 项</Badge></header>
                  <div className="hiqs-course-activity-list">{group.items.map((item) => <ActivityCard key={item.itemId} item={item} options={options} />)}</div>
                </section>
              )) : <div className="hiqs-course-empty large"><ListChecks size={18} />当前课程还没有结构化活动。</div>
            )}
          </motion.div>
        </AnimatePresence>
      </section>
    </motion.div>
  );
}
