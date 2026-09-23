import { motion } from "motion/react";
import { flowEase, useWorkspaceMotion } from "./lib/motion";
import { AlertTriangle, Check, CircleDashed, Database } from "lucide-react";
import { Badge } from "./components/ui/badge";
import type { ModernReconciliationOptions } from "./types";

export function ReconciliationIsland({ options }: { options: ModernReconciliationOptions }) {
  const animate = useWorkspaceMotion();
  return <div className="hiqs-modern-reconciliation">
    <header><div><p>SOURCE RECONCILIATION</p><h2>课程来源对账</h2><span>{options.authority}</span></div><Badge><Database size={14} />{options.countLabel}</Badge></header>
    <div className="hiqs-reconciliation-list">
      {options.courses.map((course, index) => <motion.article key={course.courseCode} className={course.state} initial={animate ? { opacity: 0, y: 10 } : false} animate={{ opacity: 1, y: 0 }} transition={{ duration: .4, delay: Math.min(index, 6) * .045, ease: flowEase }}>
        <div className="hiqs-reconciliation-course"><div><strong>{course.courseCode}</strong><span>{course.title}</span></div><Badge>{course.state === "complete" ? <Check size={13} /> : <AlertTriangle size={13} />}{course.stateLabel}</Badge></div>
        <div className="hiqs-reconciliation-sources">{course.sources.map((source) => <div key={source.key} className={source.present ? "is-present" : "is-missing"}>{source.present ? <Check size={13} /> : <CircleDashed size={13} />}<span>{source.label}</span><strong>{source.present ? "已有" : "缺失"}</strong></div>)}</div>
        <p>{course.note}</p>
      </motion.article>)}
      {!options.courses.length && <p className="hiqs-course-empty large">当前没有课程对账数据。</p>}
    </div>
  </div>;
}
