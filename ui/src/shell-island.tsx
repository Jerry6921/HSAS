import { motion } from "motion/react";
import { flowTransition, useWorkspaceMotion } from "./lib/motion";
import { AlertTriangle, CalendarDays, Database, Home, RefreshCw, Settings2, Sparkles } from "lucide-react";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import type { ModernShellOptions } from "./types";

export function TopbarIsland({ options }: { options: ModernShellOptions }) {
  return <div className="hiqs-shell-topbar">
    <button type="button" className="hiqs-shell-brand" onClick={() => options.onNavigate("home")}><span>H</span><strong>HIQS<small>HKU INFORMATION QUERY SYSTEM</small></strong></button>
    <details className="hiqs-settings"><summary>设置与状态</summary><div className="hiqs-shell-top-actions">
      <Button size="sm" onClick={options.onUpdate} disabled={options.updateDisabled} title={options.updateTitle}><RefreshCw size={14} />{options.updateLabel}</Button>
      <Button size="sm" onClick={options.onToggleMotion} aria-pressed={options.motionEnabled}><Sparkles size={14} />动效 · {options.motionEnabled ? "开" : "关"}</Button>
      <Badge>仅限本机 · 数据由 AI 整理</Badge>
    </div></details>
  </div>;
}

const nav = [
  ["home", "今天", "日程与资料中心", Home],
  ["calendar", "日历", "全部课程事项", CalendarDays],
  ["reconciliation", "课程对账", "核对各来源覆盖情况", Database],
] as const;

export function SidebarIsland({ options }: { options: ModernShellOptions }) {
  return <div className="hiqs-shell-sidebar">
    <header><p>QUERY</p><h2>课程导航</h2></header>
    <nav>
      {nav.map(([view, label, note, Icon]) => <button type="button" key={view} className={options.view === view ? "is-active" : undefined} onClick={() => options.onNavigate(view)}><Icon size={16} /><span><strong>{label}</strong><small>{note}</small></span></button>)}
    </nav>
    <details className="hiqs-course-navigation" open={window.matchMedia('(min-width: 701px)').matches}><summary>我的课程</summary><div className="hiqs-shell-course-heading"><strong>本学期</strong><Button size="sm" variant="ghost" onClick={options.onManageCourses}><Settings2 size={14} />管理</Button></div>
    <div className="hiqs-shell-courses">
      {options.courses.map((course) => <button type="button" key={course.courseId} className={`${course.active ? "is-active" : ""} tone-${course.toneIndex}`} onClick={() => options.onOpenCourse(course.courseId)}><i /><span><strong>{course.code}</strong><small>{course.title}</small></span></button>)}
      {!options.courses.length && <p>暂无课程</p>}
    </div>
    </details><aside><strong>你的学习资料库</strong><p>课程、日程与来源，集中在这一个空间。</p></aside>
  </div>;
}

export function HeadingIsland({ options }: { options: ModernShellOptions }) {
  const animate = useWorkspaceMotion();
  return <motion.div className="hiqs-shell-heading" key={`${options.view}:${options.title}`} initial={animate ? { opacity: 0, x: -12 } : false} animate={{ opacity: 1, x: 0 }} transition={flowTransition}>
    <div><p>{options.view === 'home' ? `PERSONAL EDITION / ${new Date().getFullYear()}` : options.eyebrow}</p><h1>{options.view === 'home' ? '学习手记' : options.title}<span /></h1><small>{options.caption}</small></div>
    <Button onClick={options.onRefresh} disabled={options.operationRunning}><RefreshCw size={15} />刷新数据</Button>
  </motion.div>;
}

export function NoticesIsland({ options }: { options: ModernShellOptions }) {
  const animate = useWorkspaceMotion();
  return <div className="hiqs-shell-notices">
    {options.notices.map((notice, index) => <motion.div key={`${notice.kind}:${notice.message}:${index}`} initial={animate ? { opacity: 0, y: -6 } : false} animate={{ opacity: 1, y: 0 }} transition={flowTransition} className={notice.kind}><AlertTriangle size={15} /><span>{notice.message}</span></motion.div>)}
  </div>;
}
