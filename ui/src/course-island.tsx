import { AnimatePresence, motion } from "motion/react";
import { flowEase, flowTransition, useWorkspaceMotion } from "./lib/motion";
import { useState } from "react";
import { ArrowUpRight, BookOpen, Copy, Diamond, ExternalLink, ListChecks, RefreshCw } from "lucide-react";
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

function SourceButton({ source, index, onOpen }: { source: CourseSource; index: number; onOpen: (source: CourseSource) => void }) {
  const title = source.title || source.label || source.relative_path || source.url || source.source_url || "课程来源";
  return <button type="button" onClick={() => onOpen(source)}><em>{String(index + 1).padStart(2, '0')}</em><span>{title}</span><ArrowUpRight size={14} /></button>;
}

export function CourseIsland({ options }: { options: ModernCourseOptions }) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => { try { return JSON.parse(localStorage.getItem('hiqs-material-sections') || '{}'); } catch { return {}; } });
  const [query, setQuery] = useState('');
  const toggleSection = (key: string, closed: boolean) => setCollapsed(previous => { const next = {...previous, [key]: closed}; try { localStorage.setItem('hiqs-material-sections', JSON.stringify(next)); } catch {} return next; });
  const animate = useWorkspaceMotion();
  const showingMaterials = options.mode === "materials";
  const materialCount = options.materialSections.reduce((total, section) => total + section.materials.length, 0);
  const activityCount = options.activities.reduce((total, group) => total + group.items.length, 0);
  const displayTitle = options.title.startsWith(`${options.code} `) ? options.title.slice(options.code.length + 1) : options.title;
  const titleInitial = /^[A-Za-z]/.test(displayTitle) ? displayTitle.charAt(0) : null;
  return (
    <motion.div className="hiqs-modern-course" initial={animate ? { opacity: 0, y: 14 } : false} animate={{ opacity: 1, y: 0 }} transition={flowTransition}>
      <section className="hiqs-course-hero" key={options.courseId}>
        <div className="hiqs-course-hero-copy">
          <p>COURSE FILE <span>/</span> {options.code}</p>
          <h1 aria-label={displayTitle}>{titleInitial ? <><span className="hiqs-course-title-initial" aria-hidden="true">{titleInitial}</span><span aria-hidden="true">{displayTitle.slice(1)}</span></> : displayTitle}</h1>
          <span>{options.facts}</span>
        </div>
        <aside className="hiqs-course-hero-index">
          <p>IN THIS DOSSIER</p>
          <dl>
            <div><dt>课程资料</dt><dd>{materialCount}</dd></div>
            <div><dt>结构化活动</dt><dd>{activityCount}</dd></div>
            <div><dt>资料栏目</dt><dd>{options.materialSections.length}</dd></div>
          </dl>
          <div className="hiqs-course-hero-actions"><Button size="icon" variant="ghost" title="刷新数据" aria-label="刷新数据" onClick={options.onRefresh} disabled={options.operationRunning}><RefreshCw size={16} /></Button>{options.moodleUrl && <Button asChild><a href={options.moodleUrl} target="_blank" rel="noopener noreferrer"><ExternalLink size={15} />打开 Moodle</a></Button>}</div>
        </aside>
      </section>

      <div className="hiqs-course-upper">
        <section className="hiqs-course-summary">
          <header><p>01 / FIELD NOTES</p><h2>课程综合信息</h2><span className="hiqs-course-provenance">由 AI 根据已下载课程资料归纳；事实仍以所列来源为准。</span></header>
          <div className="hiqs-course-field"><h3>课程概述</h3><div className={options.overview ? "hiqs-course-copy" : "hiqs-course-empty"}>{options.overview || "尚未从官方资料录入课程概述。"}</div></div>
          <div className="hiqs-course-field"><h3>课程目的</h3>{options.objectives.length ? <ul>{options.objectives.map((objective, index) => <li key={`${objective}:${index}`}>{objective}</li>)}</ul> : <div className="hiqs-course-empty">尚未从官方资料录入课程目的。</div>}</div>
          {!!options.sources.length && <div className="hiqs-course-field"><h3>信息来源</h3><div className="hiqs-course-sources">{options.sources.map((source, index) => <SourceButton key={`${source.title || source.relative_path}:${index}`} source={source} index={index} onOpen={options.onOpenSource} />)}</div></div>}
        </section>

        <section className="hiqs-course-grades" key={options.courseId}>
          <p>02 / ASSESSMENT</p><h2>成绩构成</h2>
          {options.grades.length ? (
            <div className="hiqs-course-grade-list">
              {options.grades.map((grade, index) => <div key={`${grade.title}:${index}`}><span><strong>{grade.title}</strong><b>{grade.weightPercent}%</b></span><div className="hiqs-grade-bar"><progress value={grade.weightPercent} max="100" aria-label={`${grade.title} 占比`} /><motion.span className="hiqs-grade-fill" aria-hidden="true" style={{ width: `${Math.max(0, Math.min(100, grade.weightPercent))}%`, transformOrigin: 'left center' }} initial={animate ? { scaleX: 0 } : false} animate={{ scaleX: 1 }} transition={{ duration: .8, delay: .12 + Math.min(index, 7) * .055, ease: flowEase }} /></div></div>)}
            </div>
          ) : <div className="hiqs-course-empty">尚未从官方资料确认成绩构成。</div>}
          {!!options.grades.length && <small className="hiqs-course-grade-note">仅列出已确认占分；父项与子项不会自动相加。</small>}
        </section>
      </div>

      <section className="hiqs-course-content">
        <header>
          <div><p>03 / ARCHIVE</p><h2>{showingMaterials ? "全部课件" : "课程活动"}</h2></div>
          <div className="hiqs-course-content-actions">
            <span>{options.archiveSummary}</span>
            {showingMaterials && <Button size="sm" onClick={options.onCopyRecentPrompt} disabled={!options.hasRecentPrompt}><Copy size={14} />复制最近 Lecture 提示词</Button>}
            <div className="hiqs-course-mode" aria-label="课程内容类型">
              {modes.map(([mode, label]) => <Button key={mode} type="button" variant="ghost" size="sm" className={options.mode === mode ? "is-active" : undefined} aria-pressed={options.mode === mode} onClick={() => options.onModeChange(mode)}>{options.mode === mode && <motion.span layoutId="hiqs-course-mode" className="hiqs-course-mode-active" transition={animate ? { type: 'spring', stiffness: 370, damping: 38 } : { duration: 0 }} />}<span>{label}</span></Button>)}
            </div>
          </div>
        </header>

        {showingMaterials && <label className="hiqs-material-search">查找资料<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="输入文件名或关键词" /></label>}
        <AnimatePresence mode="wait" initial={false}>
          <motion.div key={options.mode} initial={animate ? { opacity: 0, x: 12 } : false} animate={{ opacity: 1, x: 0 }} exit={animate ? { opacity: 0, x: -8 } : undefined} transition={{ duration: .25, ease: flowEase }}>
            {showingMaterials ? (
              options.materialSections.length ? options.materialSections.map((section, index) => (
                <details key={`${options.courseId}:${section.title}`} open={query ? true : !collapsed[`${options.courseId}:${section.title}`]} onToggle={event => { if (!query) toggleSection(`${options.courseId}:${section.title}`, !event.currentTarget.open); }} className={`hiqs-course-material-section tone-${section.toneIndex}${section.unclassified ? " is-unclassified" : ""}`}>
                  <summary><span className="hiqs-course-section-index">{String(index + 1).padStart(2, '0')}</span><span className="hiqs-course-section-title">{section.title}</span><Badge>{section.materials.length} 项</Badge></summary>
                  {section.description && <p className="hiqs-section-description">{section.description}</p>}
                  <div className="hiqs-course-material-list">{section.materials.filter(material => `${material.title} ${material.meta}`.toLowerCase().includes(query.toLowerCase())).map((material) => <MaterialCard key={material.id} material={material} options={options} />)}</div>
                </details>
              )) : <div className="hiqs-course-empty large"><BookOpen size={18} />当前 Moodle 快照中没有课程资料。</div>
            ) : (
              options.activities.length ? options.activities.map((group, index) => (
                <section key={group.categoryKey} className={`hiqs-course-activity-section category-${group.categoryKey}`}>
                  <header><span className="hiqs-course-section-index">{String(index + 1).padStart(2, '0')}</span><h3>{group.category}</h3><Badge>{group.items.length} 项</Badge></header>
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
