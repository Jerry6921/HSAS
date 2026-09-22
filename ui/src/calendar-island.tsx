import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import zhCnLocale from "@fullcalendar/core/locales/zh-cn";
import type { DateClickArg } from "@fullcalendar/interaction";
import type { DateSelectArg, EventClickArg, EventContentArg } from "@fullcalendar/core";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ChevronLeft, ChevronRight, Copy, Plus } from "lucide-react";
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
      <span className="hiqs-fc-course">{details.courseCode}</span>
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
  const reduceMotion = useReducedMotion();
  const calendarEvents = options.events.map((event) => ({
    id: event.id,
    title: event.title,
    start: event.start,
    end: event.end,
    allDay: event.allDay,
    backgroundColor: event.color,
    borderColor: event.color,
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
    options.onSelectTime(start.toISOString().slice(0, 10), timeValue(start), timeValue(end));
  };

  return (
    <section className="hiqs-modern-calendar" aria-label="课程日历">
      <div className="hiqs-modern-toolbar">
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
              {options.mode === mode && <motion.span layoutId="hiqs-calendar-mode" className="hiqs-view-active" />}
              <span>{label}</span>
            </Button>
          ))}
        </div>
        <Button type="button" variant="default" size="sm" onClick={options.onAdd}><Plus size={15} />添加事件</Button>
        <Button type="button" size="sm" onClick={options.onToday}>今天</Button>
        <Button type="button" size="icon" aria-label="上一时间段" onClick={options.onPrevious}><ChevronLeft size={17} /></Button>
        <Button type="button" size="icon" aria-label="下一时间段" onClick={options.onNext}><ChevronRight size={17} /></Button>
        <strong className="hiqs-modern-label">{options.label}</strong>
        <Button asChild size="sm"><a href="/api/calendar.ics" download="HIQS-calendar.ics">导出 ICS</a></Button>
      </div>
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={`${options.mode}:${options.date}`}
          initial={reduceMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reduceMotion ? undefined : { opacity: 0, y: -6 }}
          transition={{ duration: 0.18, ease: [0.2, 0.75, 0.2, 1] }}
        >
          <FullCalendar
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
            events={calendarEvents}
            dayMaxEvents={4}
            slotMinTime="07:00:00"
            slotMaxTime="24:00:00"
            slotDuration="00:30:00"
            slotLabelInterval="01:00:00"
            allDayText="全天"
            eventTimeFormat={{ hour: "2-digit", minute: "2-digit", hour12: false }}
          />
        </motion.div>
      </AnimatePresence>
    </section>
  );
}
