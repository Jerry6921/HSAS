export type CalendarMode = "month" | "week" | "day";

export interface ModernCalendarEvent {
  id: string;
  title: string;
  start: string;
  end?: string;
  allDay: boolean;
  itemId: string;
  dateKey: string;
  courseCode: string;
  category: string;
  categoryKey: string;
  dateStatus: string;
  agentPrompt?: string | null;
}

export interface CalendarFilterCourse {
  courseId: string;
  code: string;
  title: string;
  selected: boolean;
  toneIndex: number;
}

export interface CalendarUnscheduledItem {
  itemId: string;
  title: string;
  courseCode: string;
  category: string;
  categoryKey: string;
  dateLabel: string;
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
  query: string;
  filterCourses: CalendarFilterCourse[];
  unscheduled: CalendarUnscheduledItem[];
  onQueryChange: (query: string) => void;
  onToggleCourse: (courseId: string, selected: boolean) => void;
  onSelectAllCourses: () => void;
  onOpenUnscheduled: (itemId: string) => void;
}

export interface ModernCalendarBridge {
  mount: (element: HTMLElement, options: ModernCalendarOptions) => void;
  unmount: (element: HTMLElement) => void;
}

export interface HomeNextUp {
  empty: boolean;
  course: string;
  meta: string;
  start: string;
  end: string;
  itemId?: string;
  dateKey?: string;
}

export interface HomeMetric {
  label: string;
  value: number;
  note: string;
}

export interface HomeStage {
  id: string;
  label: string;
  state: string;
  count?: number;
}

export interface HomeListEntry {
  title: string;
  meta: string;
  note?: string | null;
  actionIndex?: number;
}

export interface HomeSearchResult {
  title: string;
  subtitle: string;
  resultIndex: number;
}

export interface HomeInboxField {
  field: string;
  before: unknown;
  after: unknown;
}

export interface HomeInboxChange {
  action: string;
  title: string;
  fields: HomeInboxField[];
}

export interface HomeInboxEntry {
  entry_id: string;
  title: string;
  note?: string | null;
  created_at?: string | null;
  changes: HomeInboxChange[];
}

export interface HomeUpdateSource {
  title: string;
  relative_path?: string | null;
  source_url?: string | null;
}

export interface HomeUpdateChange extends HomeUpdateSource {
  action: string;
  kind: string;
  field?: string | null;
  before?: unknown;
  after?: unknown;
  text_path?: string | null;
}

export interface HomeUpdateCourse {
  course_id: string;
  course_title: string;
  mode: string;
  acknowledge_through?: string | null;
  changes?: HomeUpdateChange[];
  files?: Array<HomeUpdateSource & { filename?: string }>;
}

export interface HomeSyncJob {
  state: string;
  detail?: string | null;
  completed?: number;
  total?: number;
  cancel_requested?: boolean;
}

export interface ModernHomeOptions {
  today: Array<{itemId: string; dateKey: string; title: string; meta: string}>;
  deadlines: Array<{itemId: string; dateKey: string; title: string; meta: string}>;
  nextUp: HomeNextUp;
  metrics: HomeMetric[];
  stages: HomeStage[];
  retrySummary: string;
  hasRetryTasks: boolean;
  hasAgentPrompt: boolean;
  counts: Record<string, number>;
  statusTotal: number;
  ocrCapability: string;
  canRunOcr: boolean;
  ocrQueue: HomeListEntry[];
  attention: HomeListEntry[];
  searchQuery: string;
  searchHint: string;
  searchResults: HomeSearchResult[];
  inboxCount: number;
  inboxEntries: HomeInboxEntry[];
  updateCount: number;
  updates: HomeUpdateCourse[];
  syncJob?: HomeSyncJob | null;
  onOpenNext: (itemId: string, dateKey?: string) => void;
  onStartWorkflow: () => void;
  onRetryFailures: () => void;
  onCopyAgentPrompt: () => void;
  onCancelSync: () => void;
  onRunOcr: () => void;
  onOpenOcr: (index: number) => void;
  onOpenAttention: (index: number) => void;
  onSearch: (query: string) => void;
  onOpenSearchResult: (index: number) => void;
  onApplyInbox: (entryId: string) => void;
  onOpenSource: (source: HomeUpdateSource) => void;
}

export interface ModernHomeBridge {
  mount: (element: HTMLElement, options: ModernHomeOptions) => void;
  unmount: (element: HTMLElement) => void;
}

export type CourseContentMode = "materials" | "activities";

export interface CourseSource {
  title?: string | null;
  label?: string | null;
  relative_path?: string | null;
  url?: string | null;
  source_url?: string | null;
  page_numbers?: number[];
}

export interface CourseGradeItem {
  title: string;
  weightPercent: number;
}

export interface CourseMaterialItem {
  id: string;
  title: string;
  code: string;
  tone: string;
  meta: string;
  error?: string | null;
  changeLabel?: string | null;
  canOpen: boolean;
  hasPrompt: boolean;
  source: CourseSource;
  prompt?: string | null;
}

export interface CourseMaterialSection {
  title: string;
  description?: string | null;
  toneIndex: number;
  unclassified?: boolean;
  materials: CourseMaterialItem[];
}

export interface CourseActivityItem {
  itemId: string;
  title: string;
  category: string;
  categoryKey: string;
  dateState: string;
  dateStateLabel: string;
  meta: string;
  description?: string | null;
  hasPrompt: boolean;
  prompt?: string | null;
}

export interface CourseActivityGroup {
  category: string;
  categoryKey: string;
  items: CourseActivityItem[];
}

export interface ModernCourseOptions {
  courseId: string;
  code: string;
  title: string;
  facts: string;
  moodleUrl?: string | null;
  overview?: string | null;
  objectives: string[];
  sources: CourseSource[];
  grades: CourseGradeItem[];
  mode: CourseContentMode;
  archiveSummary: string;
  hasRecentPrompt: boolean;
  materialSections: CourseMaterialSection[];
  activities: CourseActivityGroup[];
  onModeChange: (mode: CourseContentMode) => void;
  onOpenSource: (source: CourseSource) => void;
  onCopyPrompt: (prompt: string, message: string) => void;
  onOpenItem: (itemId: string) => void;
  onCopyRecentPrompt: () => void;
}

export interface ModernCourseBridge {
  mount: (element: HTMLElement, options: ModernCourseOptions) => void;
  unmount: (element: HTMLElement) => void;
}

export type AppView = "home" | "calendar" | "course" | "reconciliation";

export interface ShellCourse {
  courseId: string;
  code: string;
  title: string;
  toneIndex: number;
  active: boolean;
}

export interface ShellNotice {
  kind: "error" | "warning" | "success";
  message: string;
}

export interface ModernShellOptions {
  view: AppView;
  eyebrow: string;
  title: string;
  caption: string;
  courses: ShellCourse[];
  notices: ShellNotice[];
  updateLabel: string;
  updateStatus: string;
  updateDisabled: boolean;
  updateTitle?: string;
  motionEnabled: boolean;
  operationRunning: boolean;
  onNavigate: (view: "home" | "calendar" | "reconciliation") => void;
  onOpenCourse: (courseId: string) => void;
  onManageCourses: () => void;
  onRefresh: () => void;
  onUpdate: () => void;
  onToggleMotion: () => void;
}

export interface ModernShellBridge {
  mount: (topbar: HTMLElement, sidebar: HTMLElement, heading: HTMLElement, notices: HTMLElement, options: ModernShellOptions) => void;
  unmount: (topbar: HTMLElement, sidebar: HTMLElement, heading: HTMLElement, notices: HTMLElement) => void;
}

export interface ReconciliationSource {
  key: string;
  label: string;
  present: boolean;
}

export interface ReconciliationCourse {
  courseCode: string;
  title: string;
  state: string;
  stateLabel: string;
  note: string;
  sources: ReconciliationSource[];
}

export interface ModernReconciliationOptions {
  authority: string;
  countLabel: string;
  courses: ReconciliationCourse[];
}

export interface ModernReconciliationBridge {
  mount: (element: HTMLElement, options: ModernReconciliationOptions) => void;
  unmount: (element: HTMLElement) => void;
}

export interface DetailFact { label: string; value: string; }
export interface DetailBlock { title: string; values: string[]; warning?: boolean; }
export interface DetailLink { label: string; url: string; }

export interface ModernDetailOptions {
  itemId: string;
  courseLabel: string;
  title: string;
  category: string;
  categoryKey: string;
  dateStateLabel: string;
  weightLabel?: string | null;
  warningCount: number;
  description?: string | null;
  facts: DetailFact[];
  blocks: DetailBlock[];
  materials: CourseSource[];
  links: DetailLink[];
  sources: CourseSource[];
  exceptionSources: CourseSource[];
  hasPrompt: boolean;
  prompt?: string | null;
  userCreated: boolean;
}

export interface EventEditorCourse { courseId: string; label: string; }
export interface EventEditorDefaults { date: string; startTime: string; endTime: string; courseId?: string | null; }
export interface EventEditorValue {
  course_id: string;
  title: string;
  category: string;
  all_day: boolean;
  date: string;
  start_time: string;
  end_time: string;
  location: string;
  description: string;
}

export interface ManagerCourse {
  courseId: string;
  code: string;
  title: string;
  semester?: string | null;
  toneIndex: number;
}

export interface NewCourseValue { course_id: string; code: string; title: string; semester: string; }

export interface ModernOverlayOptions {
  courses: EventEditorCourse[];
  managerCourses: ManagerCourse[];
  operationRunning: boolean;
  onCloseDetail: () => void;
  onOpenSource: (source: CourseSource) => void;
  onCopyPrompt: (prompt: string, message: string) => void;
  onDeleteEvent: (itemId: string) => void;
  onSubmitEvent: (value: EventEditorValue) => void;
  onAddCourse: (value: NewCourseValue) => void;
  onDeleteCourse: (courseId: string) => void;
  onDeleteCourses: (courseIds: string[]) => void;
}

export interface ModernOverlayBridge {
  mount: (element: HTMLElement, options: ModernOverlayOptions) => void;
  update: (options: ModernOverlayOptions) => void;
  openDetail: (options: ModernDetailOptions) => void;
  closeDetail: () => void;
  openSource: (source: CourseSource) => void;
  closeSource: () => void;
  openEventEditor: (defaults: EventEditorDefaults) => void;
  closeEventEditor: () => void;
  openCourseManager: () => void;
  closeCourseManager: () => void;
}

declare global {
  interface Window {
    HIQSModernCalendar?: ModernCalendarBridge;
    HIQSModernHome?: ModernHomeBridge;
    HIQSModernCourse?: ModernCourseBridge;
    HIQSModernShell?: ModernShellBridge;
    HIQSModernReconciliation?: ModernReconciliationBridge;
    HIQSModernOverlay?: ModernOverlayBridge;
  }
}
