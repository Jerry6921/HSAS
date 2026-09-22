export type CalendarMode = "month" | "week" | "day";

export interface ModernCalendarEvent {
  id: string;
  title: string;
  start: string;
  end?: string;
  allDay: boolean;
  color: string;
  itemId: string;
  dateKey: string;
  courseCode: string;
  category: string;
  categoryKey: string;
  dateStatus: string;
  agentPrompt?: string | null;
}

export interface ModernCalendarOptions {
  mode: CalendarMode;
  date: string;
  label: string;
  events: ModernCalendarEvent[];
  onViewChange: (mode: CalendarMode) => void;
  onPrevious: () => void;
  onNext: () => void;
  onToday: () => void;
  onAdd: () => void;
  onOpenEvent: (itemId: string, dateKey: string) => void;
  onOpenDay: (dateKey: string) => void;
  onSelectTime: (dateKey: string, startTime: string, endTime: string) => void;
  onCopyPrompt: (prompt: string, title: string) => void;
}

export interface ModernCalendarBridge {
  mount: (element: HTMLElement, options: ModernCalendarOptions) => void;
  unmount: (element: HTMLElement) => void;
}

declare global {
  interface Window {
    HIQSModernCalendar?: ModernCalendarBridge;
  }
}
