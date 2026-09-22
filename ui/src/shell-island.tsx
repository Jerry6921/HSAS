import { motion } from "motion/react";
import { AlertTriangle, CalendarDays, Database, Home, RefreshCw, Settings2, Sparkles } from "lucide-react";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import type { ModernShellOptions } from "./types";

export function TopbarIsland({ options }: { options: ModernShellOptions }) {
  return <div className="hiqs-shell-topbar">
    <button type="button" className="hiqs-shell-brand" onClick={() => options.onNavigate("home")}><span>H</span><strong>HIQS<small>HKU INFORMATION QUERY SYSTEM</small></strong></button>
    <div className="hiqs-shell-top-actions">
      <Button size="sm" onClick={options.onUpdate} disabled={options.updateDisabled} title={options.updateTitle}><RefreshCw size={14} />{options.updateLabel}</Button>
      <Button size="sm" onClick={options.onToggleMotion}><Sparkles size={14} />动态质感 · {options.motionEnabled ? "开" : "关"}</Button>
      <Badge>仅限本机 · 数据由 AI 整理</Badge>
    </div>
  </div>;
}

const nav = [
  ["home", "首页", "登录、同步与更新记录", Home],
  ["calendar", "日历", "全部课程事项", CalendarDays],
  ["reconciliation", "课程对账", "核对各来源覆盖情况", Database],
] as const;

export function SidebarIsland({ options }: { options: ModernShellOptions }) {
  return <div className="hiqs-shell-sidebar">
    <header><p>QUERY</p><h2>课程导航</h2></header>
    <nav>
      {nav.map(([view, label, note, Icon]) => <button type="button" key={view} className={options.view === view ? "is-active" : undefined} onClick={() => options.onNavigate(view)}><Icon size={16} /><span><strong>{label}</strong><small>{note}</small></span></button>)}
    </nav>
    <div className="hiqs-shell-course-heading"><strong>课程概览</strong><Button size="sm" variant="ghost" onClick={options.onManageCourses}><Settings2 size={14} />管理</Button></div>
    <div className="hiqs-shell-courses">
      {options.courses.map((course) => <button type="button" key={course.courseId} className={`${course.active ? "is-active" : ""} tone-${course.toneIndex}`} onClick={() => options.onOpenCourse(course.courseId)}><i /><span><strong>{course.code}</strong><small>{course.title}</small></span></button>)}
      {!options.courses.length && <p>暂无课程</p>}
    </div>
    <aside><strong>资料怎么进入这里？</strong><p>让 AI 阅读课程资料，按模板生成更新文件，再通过校验命令写入。</p><code>hsas information template</code></aside>
  </div>;
}

export function HeadingIsland({ options }: { options: ModernShellOptions }) {
  return <motion.div className="hiqs-shell-heading" key={`${options.view}:${options.title}`} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }}>
    <div><p>{options.eyebrow}</p><h1>{options.title}<span /></h1><small>{options.caption}</small></div>
    <Button onClick={options.onRefresh} disabled={options.operationRunning}><RefreshCw size={15} />刷新数据</Button>
  </motion.div>;
}

export function NoticesIsland({ options }: { options: ModernShellOptions }) {
  return <div className="hiqs-shell-notices">
    {options.notices.map((notice, index) => <motion.div key={`${notice.kind}:${notice.message}:${index}`} initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} className={notice.kind}><AlertTriangle size={15} /><span>{notice.message}</span></motion.div>)}
  </div>;
}
