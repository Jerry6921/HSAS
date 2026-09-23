import FullCalendar from "@fullcalendar/react";
import { useEffect, useRef, useState } from "react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import zhCnLocale from "@fullcalendar/core/locales/zh-cn";
import type { DateClickArg } from "@fullcalendar/interaction";
import type { DateSelectArg, EventClickArg, EventContentArg } from "@fullcalendar/core";
import { AnimatePresence, motion } from "motion/react";
import { flowEase, useWorkspaceMotion } from "./lib/motion";
import { CalendarX2, ChevronLeft, ChevronRight, Copy, Plus, Search } from "lucide-react";
import { Button } from "./components/ui/button";
import { Badge } from "./components/ui/badge";
import type { CalendarMode, ModernCalendarEvent, ModernCalendarOptions } from "./types";

const views: Array<[CalendarMode, string]> = [["month", "月"], ["week", "周"], ["day", "日"]];
const viewNames: Record<CalendarMode, string> = {
  month: "dayGridMonth",
  week: "timeGridWeek",
  day: "timeGridDay",
};

function timeValue(date: Date) {
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function CalendarEventContent({ arg, options }: { arg: EventContentArg; options: ModernCalendarOptions }) {
  const details = arg.event.extendedProps as ModernCalendarEvent;
  const copyPrompt = (event: React.MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    if (details.agentPrompt) options.onCopyPrompt(details.agentPrompt, arg.event.title);
  };
  return (
    <div className="hiqs-fc-event-content">
      <div className="hiqs-fc-event-heading">
        <strong>{arg.event.title}</strong>
        {!details.allDay && <time>{arg.timeText}</time>}
      </div>
      <span className="hiqs-fc-course">{details.courseCode}{details.dateStatus !== 'confirmed' && ' · 待核实'}</span>
      <div className="hiqs-fc-event-footer">
        <Badge>{details.category}</Badge>
        {details.agentPrompt && (
          <Button type="button" variant="ghost" size="icon" className="hiqs-fc-copy" title="复制 AI 提示词" onClick={copyPrompt}>
            <Copy aria-hidden="true" size={13} />
            <span className="sr-only">复制 AI 提示词</span>
          </Button>
        )}
      </div>
    </div>
  );
}

export function CalendarIsland({ options }: { options: ModernCalendarOptions }) {
  const calendarRef = useRef<FullCalendar>(null);
  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width: 700px)').matches);
  useEffect(() => { const query = window.matchMedia('(max-width: 700px)'); const change = () => setMobile(query.matches); query.addEventListener('change', change); return () => query.removeEventListener('change', change); }, []);
  useEffect(() => { calendarRef.current?.getApi().gotoDate(options.date); }, [options.date, mobile]);
  useEffect(() => { calendarRef.current?.getApi().changeView(viewNames[options.mode], options.date); }, [options.mode, mobile]);
  const palette = ['#397566', '#76639b', '#ad6545', '#447b9b', '#887337', '#995f73'];
  const colorFor = (event: ModernCalendarEvent) => palette[(options.filterCourses.find(course => course.code === event.courseCode)?.toneIndex || 0) % palette.length];
  const animate = useWorkspaceMotion();
  const calendarEvents = options.events.map((event) => ({
    id: event.id,
    title: event.title,
    start: event.start,
    end: event.end,
    allDay: event.allDay,
    borderColor: colorFor(event),
    classNames: [`hiqs-category-${event.categoryKey.replaceAll("_", "-")}`],
    extendedProps: event,
  }));
  const handleEventClick = ({ event }: EventClickArg) => {
    const details = event.extendedProps as ModernCalendarEvent;
    options.onOpenEvent(details.itemId, details.dateKey);
  };
  const handleDateClick = ({ dateStr }: DateClickArg) => {
    if (options.mode === "month") options.onOpenDay(dateStr.slice(0, 10));
  };
  const handleSelect = ({ start, end, allDay }: DateSelectArg) => {
    if (allDay) return;
    const localDate = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}-${String(start.getDate()).padStart(2, '0')}`;
    options.onSelectTime(localDate, timeValue(start), timeValue(end));
  };

  return (
    <section className="hiqs-modern-calendar" aria-label="课程日历">
      <div className="hiqs-calendar-query">
        <label><Search size={16} /><input type="search" value={options.query} onChange={(event) => options.onQueryChange(event.target.value)} placeholder="作业、地点、要求…" aria-label="筛选日历事项" /></label>
        <details className="hiqs-filter-disclosure"><summary>筛选课程 · {options.filterCourses.filter(course => course.selected).length} 门</summary><div className="hiqs-calendar-course-filters">
          <span>课程</span>
          {options.filterCourses.map((course) => <button key={course.courseId} type="button" className={`tone-${course.toneIndex} ${course.selected ? "is-selected" : ""}`} title={course.title} onClick={() => options.onToggleCourse(course.courseId, !course.selected)}><i />{course.code}</button>)}
          <Button type="button" size="sm" variant="ghost" onClick={options.onSelectAllCourses}>全部</Button>
        </div></details>
      </div>
      <div className="hiqs-modern-toolbar">
        <Button type="button" variant="default" size="sm" onClick={options.onAdd}><Plus size={15} />添加事件</Button>
        <Button type="button" size="sm" onClick={options.onToday}>今天</Button>
        <Button type="button" size="icon" aria-label="上一时间段" onClick={options.onPrevious}><ChevronLeft size={17} /></Button>
        <Button type="button" size="icon" aria-label="下一时间段" onClick={options.onNext}><ChevronRight size={17} /></Button>
        <AnimatePresence mode="wait" initial={false}><motion.strong key={options.label} className="hiqs-modern-label" initial={animate ? { opacity: 0, x: 9 } : false} animate={{ opacity: 1, x: 0 }} exit={animate ? { opacity: 0, x: -9 } : undefined} transition={{ duration: .2, ease: flowEase }}>{options.label}</motion.strong></AnimatePresence>
        <Button asChild size="sm"><a href="/api/calendar.ics" download="HIQS-calendar.ics">导出 ICS</a></Button>
        <div className="hiqs-view-switch" aria-label="日历视图">
          {views.map(([mode, label]) => (
            <Button
              key={mode}
              type="button"
              variant="ghost"
              size="sm"
              className={options.mode === mode ? "is-active" : undefined}
              aria-pressed={options.mode === mode}
              onClick={() => options.onViewChange(mode)}
            >
              {options.mode === mode && <motion.span layoutId="hiqs-calendar-mode" className="hiqs-view-active" transition={animate ? { type: 'spring', stiffness: 370, damping: 38 } : { duration: 0 }} />}
              <span>{label}</span>
            </Button>
          ))}
        </div>
      </div>
      {mobile ? <section className="hiqs-mobile-agenda" aria-label="日程列表">{options.events.filter(event => options.mode === 'month' ? event.dateKey.startsWith(options.date.slice(0, 7)) : options.mode === 'day' ? event.dateKey === options.date.slice(0, 10) : (() => { const start = new Date(`${options.date.slice(0,10)}T00:00:00`); start.setDate(start.getDate() - start.getDay()); const end = new Date(start); end.setDate(end.getDate() + 7); const date = new Date(`${event.dateKey}T00:00:00`); return date >= start && date < end; })()).sort((a,b) => a.start.localeCompare(b.start)).map(event => <button className="hiqs-agenda-row" key={event.id} style={{borderLeft: `3px solid ${colorFor(event)}`}} onClick={() => options.onOpenEvent(event.itemId, event.dateKey)}><span><small>{event.dateKey} · {event.allDay ? '全天' : event.start.slice(11,16)}</small><strong>{event.title}</strong><small>{event.courseCode} · {event.category}{event.dateStatus !== 'confirmed' ? ' · 日期待核实' : ''}</small></span></button>)}{!options.events.length && <p>当前范围没有已排定事项。</p>}</section> :
        <div className="hiqs-calendar-stage">
          <FullCalendar
            ref={calendarRef}
            plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
            locale={zhCnLocale}
            initialView={viewNames[options.mode]}
            initialDate={options.date}
            headerToolbar={false}
            firstDay={0}
            height="auto"
            expandRows
            nowIndicator
            selectable
            selectMirror
            select={handleSelect}
            dateClick={handleDateClick}
            eventClick={handleEventClick}
            eventContent={(arg) => <CalendarEventContent arg={arg} options={options} />}
            eventDidMount={({el, event}) => el.style.setProperty('--hiqs-event-color', colorFor(event.extendedProps as ModernCalendarEvent))}
            events={calendarEvents}
            dayMaxEvents={4}
            slotMinTime="07:00:00"
            slotMaxTime="24:00:00"
            slotDuration="00:30:00"
            slotLabelInterval="01:00:00"
            allDayText="全天"
            eventTimeFormat={{ hour: "2-digit", minute: "2-digit", hour12: false }}
          />
        </div>}
      <details className="hiqs-modern-unscheduled"><summary>日期待确认 · {options.unscheduled.length} 项</summary>
        <header><div><p>TO VERIFY</p><h2>日期待确认</h2><span>这些事项仍保留在查询结果中；日期缺失不等于没有截止时间。</span></div><Badge>{options.unscheduled.length} 项</Badge></header>
        <div>{options.unscheduled.map((item) => <motion.button type="button" key={item.itemId} className={`hiqs-unscheduled-item hiqs-category-${item.categoryKey.replaceAll("_", "-")}`} onClick={() => options.onOpenUnscheduled(item.itemId)} whileHover={animate ? { x: 3 } : undefined} transition={{ duration: .25, ease: flowEase }}><i /><span><Badge>{item.category}</Badge><strong>{item.title}</strong><small>{item.courseCode} · {item.dateLabel}</small></span></motion.button>)}{!options.unscheduled.length && <p className="hiqs-calendar-empty"><CalendarX2 size={18} />当前筛选范围没有日期待确认事项。</p>}</div>
      </details>
    </section>
  );
}
