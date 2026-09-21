const categoryLabels = {
  class: "课程",
  tutorial: "Tutorial",
  lab: "实验",
  office_hour: "Office hour",
  assignment: "Assignment",
  quiz: "Quiz",
  exam: "考试",
  presentation: "汇报",
  project: "项目",
  report: "报告",
  reading: "阅读",
  deadline: "截止时间",
  other: "其他",
};

const categoryColors = {
  class: "#a45e48",
  tutorial: "#8e6857",
  lab: "#7e7661",
  office_hour: "#7d7069",
  assignment: "#b06c3f",
  quiz: "#b88a32",
  exam: "#9e443d",
  presentation: "#9a5960",
  project: "#9a6c3a",
  report: "#a75d3e",
  reading: "#7b6d61",
  deadline: "#963f36",
  other: "#83756d",
};

const categoryOrder = [
  "assignment", "quiz", "exam", "project", "report", "presentation",
  "class", "tutorial", "lab", "office_hour", "reading", "deadline", "other",
];

const materialPalettes = [
  { match: /ppt|powerpoint|slide|lecture|课件/i, code: "SLD", color: "#b85f3f" },
  { match: /pdf/i, code: "PDF", color: "#994b3d" },
  { match: /doc|word|note|reading|handout|讲义/i, code: "DOC", color: "#876252" },
  { match: /xls|sheet|csv|table|data/i, code: "DAT", color: "#69775d" },
  { match: /image|png|jpe?g|gif|figure/i, code: "IMG", color: "#a66b70" },
  { match: /video|mp4|mov|recording|录影|录像/i, code: "VID", color: "#765d72" },
  { match: /zip|archive|package/i, code: "ZIP", color: "#6d7071" },
  { match: /link|url|web/i, code: "URL", color: "#a57a43" },
];

const materialSectionColors = ["#994b3d", "#b85f3f", "#876252", "#69775d", "#a66b70", "#765d72"];

function materialVisual(material) {
  const value = [
    material.material_type,
    material.relative_path,
    material.source_url,
    material.title,
  ].filter(Boolean).join(" ");
  return materialPalettes.find((entry) => entry.match.test(value))
    || { code: material.relative_path ? "FILE" : "LINK", color: "#83756d" };
}

function materialSectionColor(title) {
  const checksum = [...String(title || "")].reduce((total, character) => total + character.codePointAt(0), 0);
  return materialSectionColors[checksum % materialSectionColors.length];
}

const timeGridStartHour = 7;
const timeGridHourHeight = 34;

function timeGridOffset(minutes) {
  return Math.max(0, minutes - timeGridStartHour * 60) / 60 * timeGridHourHeight;
}

function timeGridEventHeight(startMinutes, endMinutes) {
  const visibleStart = Math.max(startMinutes, timeGridStartHour * 60);
  const visibleEnd = Math.max(visibleStart, endMinutes);
  return Math.max(20, (visibleEnd - visibleStart) / 60 * timeGridHourHeight);
}

function clockValue(minutes) {
  const safeMinutes = Math.max(0, Math.min(23 * 60 + 59, minutes));
  const hours = Math.floor(safeMinutes / 60);
  const remainder = safeMinutes % 60;
  return `${String(hours).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function timeFromGridPointer(event, timeline) {
  const rect = timeline.getBoundingClientRect();
  const offset = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
  const rawMinutes = timeGridStartHour * 60 + offset / timeGridHourHeight * 60;
  return Math.max(timeGridStartHour * 60, Math.min(23 * 60, Math.round(rawMinutes / 30) * 30));
}

function openEventEditorFromGrid(event, timeline, date) {
  if (event.target.closest(".agenda-item, .week-event, .week-now-line, .agenda-now-line")) return;
  const startMinutes = timeFromGridPointer(event, timeline);
  const endMinutes = Math.min(23 * 60 + 59, startMinutes + 60);
  openEventEditor(date, clockValue(startMinutes), clockValue(endMinutes));
}

const state = {
  data: null,
  currentMonth: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
  selectedDay: new Date(),
  calendarMode: "month",
  selectedCourses: new Set(),
  selectedItemId: null,
  selectedDateKey: null,
  selectedOverviewCourseId: null,
  courseContentMode: "materials",
  managerSelectedCourseIds: new Set(),
  view: "home",
  query: "",
  homeQuery: "",
  applicationUpdate: null,
};

function categoryColor(item) {
  return categoryColors[item.category] || categoryColors.other;
}

const byId = (id) => document.getElementById(id);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function parseDateOnly(value) {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function dateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isoDateKey(value) {
  return typeof value === "string" && value.length >= 10 ? value.slice(0, 10) : null;
}

function addDays(date, amount) {
  const result = new Date(date);
  result.setDate(result.getDate() + amount);
  return result;
}

function mondayIndex(date) {
  return (date.getDay() + 6) % 7;
}

function visibleRange() {
  if (state.calendarMode === "week") {
    const start = addDays(state.selectedDay, -state.selectedDay.getDay());
    return { start, end: addDays(start, 6) };
  }
  const first = new Date(state.currentMonth.getFullYear(), state.currentMonth.getMonth(), 1);
  const start = addDays(first, -first.getDay());
  return { start, end: addDays(start, 41) };
}

function courseFor(item) {
  return state.data.courses.find((course) => course.course_id === item.course_id) || {
    code: item.course_id,
    title: item.course_id,
    color: "#64748b",
  };
}

function itemMatches(item) {
  if (!state.selectedCourses.has(item.course_id)) return false;
  if (!state.query) return true;
  const course = courseFor(item);
  const haystack = [
    item.title,
    item.description,
    item.location,
    item.assessment_format,
    item.submission_method,
    course.code,
    course.title,
    ...(item.requirements || []),
    ...(item.policies || []),
    ...(item.warnings || []),
    ...(item.materials || []).flatMap((material) => [material.title, material.note, material.relative_path]),
  ].filter(Boolean).join(" ").toLocaleLowerCase();
  return haystack.includes(state.query);
}

function primaryDateKey(item) {
  return isoDateKey(item.due_at) || item.due_on || item.scheduled_on || isoDateKey(item.starts_at) || isoDateKey(item.opens_at);
}

function occurrenceTime(item) {
  if (item.recurrence) return item.recurrence.start_time.slice(0, 5);
  const value = item.due_at || item.starts_at || item.opens_at;
  return value && value.includes("T") ? value.slice(11, 16) : "";
}

function occurrenceEndTime(item) {
  if (item.recurrence) return item.recurrence.end_time.slice(0, 5);
  const value = item.ends_at;
  return value && value.includes("T") ? value.slice(11, 16) : "";
}

function recurrenceException(recurrence, key) {
  return (recurrence.exceptions || []).find((value) => value.date === key) || null;
}

function recurringOccurrence(item, key) {
  const recurrence = item.recurrence;
  const exception = recurrenceException(recurrence, key);
  if ((recurrence.excluded_dates || []).includes(key) || exception?.status === "cancelled") return null;
  return {
    item,
    key,
    time: (exception?.start_time || recurrence.start_time).slice(0, 5),
    endTime: (exception?.end_time || recurrence.end_time).slice(0, 5),
    title: exception?.title || item.title,
    location: exception?.location || item.location,
    exception,
  };
}

function buildOccurrences() {
  if (!state.data) return [];
  const { start, end } = visibleRange();
  const startKey = dateKey(start);
  const endKey = dateKey(end);
  const occurrences = [];

  for (const item of state.data.items.filter(itemMatches)) {
    if (item.recurrence) {
      const recurrence = item.recurrence;
      const dates = new Set();
      let cursor = parseDateOnly(recurrence.valid_from > startKey ? recurrence.valid_from : startKey);
      const last = parseDateOnly(recurrence.valid_until < endKey ? recurrence.valid_until : endKey);
      while (cursor <= last) {
        const key = dateKey(cursor);
        if (recurrence.weekdays.includes(mondayIndex(cursor))) dates.add(key);
        cursor = addDays(cursor, 1);
      }
      for (const key of recurrence.additional_dates || []) {
        if (key >= startKey && key <= endKey) dates.add(key);
      }
      for (const exception of recurrence.exceptions || []) {
        if (exception.status === "changed" && exception.date >= startKey && exception.date <= endKey) dates.add(exception.date);
      }
      for (const key of dates) {
        const occurrence = recurringOccurrence(item, key);
        if (occurrence) occurrences.push(occurrence);
      }
      continue;
    }
    const key = primaryDateKey(item);
    if (key && key >= startKey && key <= endKey) {
      occurrences.push({ item, key, time: occurrenceTime(item) });
    }
  }
  return occurrences.sort((left, right) =>
    left.key.localeCompare(right.key) || left.time.localeCompare(right.time) || left.item.title.localeCompare(right.item.title)
  );
}

function renderCourseFilters() {
  const container = byId("course-filters");
  container.replaceChildren();
  if (!state.data.courses.length) {
    container.append(element("p", "empty-list", "暂无课程"));
    return;
  }
  for (const course of state.data.courses) {
    const label = element("label", "course-filter");
    label.style.setProperty("--course-color", course.color);
    const input = element("input");
    input.type = "checkbox";
    input.checked = state.selectedCourses.has(course.course_id);
    input.addEventListener("change", () => {
      if (input.checked) state.selectedCourses.add(course.course_id);
      else state.selectedCourses.delete(course.course_id);
      renderDataViews();
    });
    label.append(input, element("span", "check"), element("span", "course-name", course.code || course.title));
    label.title = course.title;
    container.append(label);
  }
}

function renderCourseNavigation() {
  const container = byId("course-navigation");
  container.replaceChildren();
  if (!state.data.courses.length) {
    container.append(element("p", "nav-empty", "暂无课程"));
    return;
  }
  for (const course of state.data.courses) {
    const button = element("button", "course-nav-item");
    button.type = "button";
    button.style.setProperty("--course-color", course.color);
    if (state.view === "course" && state.selectedOverviewCourseId === course.course_id) {
      button.classList.add("active");
    }
    button.append(
      element("span", "course-nav-dot"),
      element("strong", "", course.code || course.title),
      element("small", "", course.title),
    );
    button.addEventListener("click", () => showCourseOverview(course.course_id));
    container.append(button);
  }
}

function renderCourseManager() {
  const container = byId("course-manager-list");
  container.replaceChildren();
  const availableIds = new Set((state.data?.courses || []).map((course) => course.course_id));
  state.managerSelectedCourseIds = new Set(
    [...state.managerSelectedCourseIds].filter((courseId) => availableIds.has(courseId)),
  );
  if (!state.data?.courses.length) {
    container.append(element("p", "empty-list", "本地信息库中暂无课程。"));
    updateCourseManagerSelection();
    return;
  }
  for (const course of state.data.courses) {
    const row = element("article", "course-manager-row");
    row.style.setProperty("--course-color", course.color);
    const selection = element("label", "course-manager-check");
    const checkbox = element("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.managerSelectedCourseIds.has(course.course_id);
    checkbox.setAttribute("aria-label", `选择 ${course.code || course.title}`);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.managerSelectedCourseIds.add(course.course_id);
      else state.managerSelectedCourseIds.delete(course.course_id);
      row.classList.toggle("selected", checkbox.checked);
      updateCourseManagerSelection();
    });
    selection.append(checkbox, element("span", "check"));
    const copy = element("div", "course-manager-name");
    copy.append(
      element("span", "course-nav-dot"),
      element("strong", "", course.code || course.title),
      element("small", "", course.title),
    );
    const remove = element("button", "button compact danger", "删除");
    remove.type = "button";
    remove.addEventListener("click", () => deleteCourse(course));
    row.classList.toggle("selected", checkbox.checked);
    row.append(selection, copy, remove);
    container.append(row);
  }
  updateCourseManagerSelection();
}

function updateCourseManagerSelection() {
  const courses = state.data?.courses || [];
  const selectedCount = state.managerSelectedCourseIds.size;
  const selectAll = byId("course-manager-select-all");
  selectAll.checked = courses.length > 0 && selectedCount === courses.length;
  selectAll.indeterminate = selectedCount > 0 && selectedCount < courses.length;
  selectAll.disabled = courses.length === 0;
  byId("course-manager-selection").textContent = `已选择 ${selectedCount} 门`;
  byId("delete-selected-courses").disabled = selectedCount === 0;
}

function openCourseManager() {
  state.managerSelectedCourseIds.clear();
  renderCourseManager();
  const dialog = byId("course-manager-dialog");
  if (!dialog.open) dialog.showModal();
}

function closeCourseManager() {
  const dialog = byId("course-manager-dialog");
  if (dialog.open) dialog.close();
}

function setView(view) {
  state.view = view;
  byId("home-view").classList.toggle("hidden", view !== "home");
  byId("calendar-view").classList.toggle("hidden", view !== "calendar");
  byId("course-overview-view").classList.toggle("hidden", view !== "course");
  byId("reconciliation-view").classList.toggle("hidden", view !== "reconciliation");
  byId("show-home").classList.toggle("active", view === "home");
  byId("show-calendar").classList.toggle("active", view === "calendar");
  byId("show-reconciliation").classList.toggle("active", view === "reconciliation");
  byId("query-controls").classList.toggle("hidden", view !== "calendar");
  renderCourseNavigation();
}

function showReconciliation() {
  setView("reconciliation");
  byId("page-eyebrow").textContent = "SOURCE RECONCILIATION";
  byId("page-title").textContent = "课程来源对账";
  byId("data-caption").textContent = "以当前注册课程为基准，查看每个来源与本地信息库的覆盖情况。";
  renderReconciliation();
}

function showHome() {
  setView("home");
  renderHomeFocus();
}

function showCalendar() {
  setView("calendar");
  byId("page-eyebrow").textContent = "CALENDAR";
  byId("page-title").textContent = "课程日历";
  byId("data-caption").textContent = dataCaption();
}

function showCourseOverview(courseId) {
  state.selectedOverviewCourseId = courseId;
  setView("course");
  renderCourseOverview();
}

function dataCaption() {
  return state.data && state.data.updated_at
    ? `最近更新：${formatDateTime(state.data.updated_at)} · 时区 ${state.data.timezone}`
    : "尚未写入课程资料；AI 整理后会补充综合信息，Moodle 课件仍可浏览。";
}

function localDateTime(key, time = "23:59") {
  return new Date(`${key}T${time.slice(0, 5)}:00`);
}

function upcomingOccurrences(now = new Date()) {
  if (!state.data) return [];
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const horizon = addDays(today, 120);
  const startKey = dateKey(today);
  const endKey = dateKey(horizon);
  const candidates = [];

  function addCandidate(item, key, startTime, endTime = "") {
    const startsAt = startTime ? localDateTime(key, startTime) : localDateTime(key);
    const endsAt = endTime ? localDateTime(key, endTime) : startsAt;
    if (endsAt < now || startsAt > horizon) return;
    candidates.push({ item, key, time: startTime, endTime, startsAt, endsAt });
  }

  for (const item of state.data.items) {
    if (item.recurrence) {
      const recurrence = item.recurrence;
      const recurringKeys = new Set();
      const firstKey = recurrence.valid_from > startKey ? recurrence.valid_from : startKey;
      const lastKey = recurrence.valid_until < endKey ? recurrence.valid_until : endKey;
      let cursor = parseDateOnly(firstKey);
      const last = parseDateOnly(lastKey);
      while (cursor <= last) {
        const key = dateKey(cursor);
        if (recurrence.weekdays.includes(mondayIndex(cursor))) {
          const occurrence = recurringOccurrence(item, key);
          if (occurrence) {
            addCandidate(item, key, occurrence.time, occurrence.endTime);
            recurringKeys.add(key);
          }
        }
        cursor = addDays(cursor, 1);
      }
      for (const key of recurrence.additional_dates || []) {
        if (key >= startKey && key <= endKey) {
          const occurrence = recurringOccurrence(item, key);
          if (occurrence && !recurringKeys.has(key)) {
            addCandidate(item, key, occurrence.time, occurrence.endTime);
            recurringKeys.add(key);
          }
        }
      }
      for (const exception of recurrence.exceptions || []) {
        if (exception.status !== "changed" || exception.date < startKey || exception.date > endKey || recurringKeys.has(exception.date)) continue;
        const occurrence = recurringOccurrence(item, exception.date);
        if (occurrence) addCandidate(item, exception.date, occurrence.time, occurrence.endTime);
      }
      continue;
    }

    const key = primaryDateKey(item);
    if (!key || key < startKey || key > endKey) continue;
    const sourceValue = item.due_at || item.starts_at || item.opens_at;
    const startsAt = sourceValue?.includes("T") ? new Date(sourceValue) : null;
    const endValue = item.ends_at;
    const endsAt = endValue?.includes("T") ? new Date(endValue) : startsAt;
    if (startsAt && !Number.isNaN(startsAt.valueOf())) {
      if ((endsAt || startsAt) >= now) {
        candidates.push({
          item,
          key,
          time: occurrenceTime(item),
          endTime: occurrenceEndTime(item),
          startsAt,
          endsAt: endsAt || startsAt,
        });
      }
    } else {
      addCandidate(item, key, occurrenceTime(item), occurrenceEndTime(item));
    }
  }

  return candidates.sort((left, right) => left.startsAt - right.startsAt);
}

function greetingFor(date) {
  const hour = date.getHours();
  if (hour < 5) return "夜深了";
  if (hour < 12) return "早上好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

function homeDateCaption(date) {
  const weekday = new Intl.DateTimeFormat("zh-HK", { weekday: "long" }).format(date);
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日 · ${weekday}`;
}

function relativeStartLabel(startsAt, endsAt, now) {
  if (startsAt <= now && endsAt >= now) return "正在进行";
  const minutes = Math.max(1, Math.round((startsAt - now) / 60000));
  if (minutes < 60) return `还有 ${minutes} 分钟`;
  if (minutes < 24 * 60) return `还有 ${Math.round(minutes / 60)} 小时`;
  const days = Math.ceil(minutes / (24 * 60));
  return days === 1 ? "明天" : `${days} 天后`;
}

function renderHomeFocus() {
  const now = new Date();
  if (state.view === "home") {
    byId("page-eyebrow").textContent = "TODAY";
    byId("page-title").textContent = `${greetingFor(now)}，Jerry`;
    byId("data-caption").textContent = homeDateCaption(now);
  }
  if (!state.data) return;

  const card = byId("next-up-card");
  const next = upcomingOccurrences(now)[0];
  if (!next) {
    card.disabled = true;
    card.classList.add("empty");
    delete card.dataset.itemId;
    delete card.dataset.dateKey;
    byId("next-up-course").textContent = "近期没有已排定事项";
    byId("next-up-meta").textContent = "待确认日期仍保留在课程日历中";
    byId("next-up-start").textContent = "CLEAR";
    byId("next-up-end").textContent = "";
    return;
  }

  const course = courseFor(next.item);
  const dateLabel = `${next.startsAt.getMonth() + 1} 月 ${next.startsAt.getDate()} 日`;
  const relative = relativeStartLabel(next.startsAt, next.endsAt, now);
  const verification = next.item.date_status === "confirmed" ? "" : " · 待核实";
  card.disabled = false;
  card.classList.remove("empty");
  card.dataset.itemId = next.item.item_id;
  card.dataset.dateKey = next.key;
  byId("next-up-course").textContent = `${course.code || course.title} · ${course.title}`;
  byId("next-up-meta").textContent = [next.item.title, next.item.location, `${dateLabel} · ${relative}${verification}`].filter(Boolean).join("　·　");
  byId("next-up-start").textContent = next.time || dateLabel;
  byId("next-up-end").textContent = next.endTime ? `— ${next.endTime.slice(0, 5)}` : categoryLabels[next.item.category] || "查看详情";
}

function renderReviewClosure() {
  const closure = state.data?.review_closure;
  if (!closure) return;
  const stages = byId("closure-stages");
  stages.replaceChildren();
  for (const stage of closure.stages || []) {
    const row = element("div", `closure-stage ${stage.state}`);
    row.append(
      element("i", "closure-dot"),
      element("strong", "", stage.label),
      element("span", "", stage.state === "complete" ? "已完成" : stage.count ? `${stage.count} 项待处理` : "待处理"),
    );
    stages.append(row);
  }
  const retryTasks = closure.retry_tasks || [];
  const retryButton = byId("retry-failures");
  retryButton.classList.toggle("hidden", retryTasks.length === 0);
  retryButton.disabled = retryTasks.length === 0;
  const summary = byId("retry-summary");
  summary.classList.toggle("hidden", retryTasks.length === 0);
  summary.textContent = retryTasks.length
    ? `${retryTasks.length} 个失败项目可精确重试：${retryTasks.map((task) => `${task.source}${task.course_code ? ` · ${task.course_code}` : ""}`).join("、")}`
    : "";
}

function renderReconciliation() {
  const reconciliation = state.data?.course_reconciliation;
  const container = byId("reconciliation-list");
  container.replaceChildren();
  if (!reconciliation) return;
  const labels = reconciliation.source_labels || {};
  const sourceOrder = reconciliation.source_order || Object.keys(labels);
  byId("reconciliation-authority").textContent = reconciliation.authority_note
    || "课程事实以 Moodle 为最高优先级；SIS 与官方课表补充 Moodle 未说明的字段。";
  const attention = reconciliation.counts?.attention || 0;
  byId("reconciliation-count").textContent = attention ? `${attention} 门待处理` : "来源已对齐";
  for (const course of reconciliation.rows || []) {
    const card = element("article", `reconciliation-card ${course.state}`);
    const heading = element("div", "reconciliation-course");
    const copy = element("div");
    copy.append(element("strong", "", course.course_code), element("span", "", course.title));
    const stateLabel = course.state === "complete" ? "已对齐" : course.state === "legacy" ? "历史资料" : "需要处理";
    heading.append(copy, element("span", `reconciliation-state ${course.state}`, stateLabel));
    const sources = element("div", "reconciliation-sources");
    for (const key of sourceOrder) {
      const label = labels[key] || key;
      const present = Boolean(course.sources?.[key]);
      const source = element("div", `source-check ${present ? "present" : "missing"}`);
      source.append(element("i", ""), element("span", "", label), element("strong", "", present ? "已有" : "缺失"));
      sources.append(source);
    }
    const note = course.state === "legacy"
      ? "当前注册课程中已不存在；保留为历史资料。"
      : course.pending_information_write
        ? "来源已采集，等待 Agent 整理并写入本地信息库。"
        : course.missing_sources?.length
          ? `待补来源：${course.missing_sources.map((key) => labels[key] || key).join("、")}`
          : "各课程来源与本地信息库均有记录。";
    card.append(heading, sources, element("p", "reconciliation-note", note));
    container.append(card);
  }
}

function appendOverviewList(parent, values, emptyText) {
  if (!values || !values.length) {
    parent.append(element("p", "overview-empty", emptyText));
    return;
  }
  const list = element("ul", "overview-list");
  for (const value of values) list.append(element("li", "", value));
  parent.append(list);
}

function renderGradeDistribution(parent, course) {
  const values = course.grade_distribution || [];
  if (!values.length) {
    parent.append(element("p", "overview-empty", "尚未从官方资料确认成绩构成。"));
    return;
  }
  const list = element("div", "grade-list");
  for (const item of values) {
    const row = element("div", "grade-row");
    const label = element("div", "grade-label");
    label.append(element("strong", "", item.title), element("span", "", `${item.weight_percent}%`));
    const track = element("div", "grade-track");
    const bar = element("span", "grade-bar");
    bar.style.width = `${Math.min(item.weight_percent, 100)}%`;
    track.append(bar);
    row.append(label, track);
    list.append(row);
  }
  parent.append(list);
  parent.append(element("p", "grade-total", "仅列出已确认占分；父项与子项不会自动相加。"));
}

function formatBytes(value) {
  if (value === null || value === undefined) return null;
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function renderMaterialSection(parent, title, description, materials, className = "") {
  const section = element("section", `material-subgroup ${className}`.trim());
  section.style.setProperty("--section-color", materialSectionColor(title));
  const heading = element("div", "material-subgroup-heading");
  const copy = element("div");
  copy.append(element("h3", "", title));
  if (description) copy.append(element("p", "", description));
  heading.append(copy, element("span", "", `${materials.length} 项`));
  section.append(heading);
  const list = element("div", "materials-list");
  for (const material of materials) renderMaterialCard(list, material);
  section.append(list);
  parent.append(section);
}

function allCourseMaterials(course) {
  const materials = course.materials || {};
  const classified = (materials.sections || []).flatMap((section) => section.materials || []);
  return [...classified, ...(materials.unclassified || [])];
}

function renderMaterialCard(list, material) {
    const hasLocal = Boolean(material.relative_path && material.exists);
    const remoteUrl = safeHttpUrl(material.source_url);
    const canOpen = Boolean(hasLocal || remoteUrl);
    const card = element("article", "material-card");
    const visual = materialVisual(material);
    card.style.setProperty("--material-color", visual.color);
    const main = element(hasLocal ? "button" : remoteUrl ? "a" : "div", "material-card-main");
    if (hasLocal) {
      main.type = "button";
      main.addEventListener("click", () => openSourcePreview(material));
    } else if (remoteUrl) {
      main.href = remoteUrl;
      main.target = "_blank";
      main.rel = "noopener noreferrer";
    }
    const icon = element("span", "material-icon", visual.code);
    const copy = element("div", "material-copy");
    const titleLine = element("div", "material-title-line");
    titleLine.append(element("strong", "", material.title));
    if (material.change_action) {
      const labels = { baseline: "首次待整理", added: "新增", modified: "已更新", removed: "已删除" };
      titleLine.append(element("span", "update-badge", labels[material.change_action] || "有变化"));
    }
    const meta = [
      material.material_type,
      material.section_title,
      material.activity_name !== material.title ? material.activity_name : null,
      formatBytes(material.size_bytes),
      material.text_available ? "已有文本副本" : null,
    ].filter(Boolean).join(" · ");
    copy.append(titleLine, element("small", "", meta || categoryLabels[material.category] || material.category));
    if (material.download_error) copy.append(element("small", "material-error", material.download_error));
    main.append(icon, copy, element("span", "material-open", canOpen ? "预览" : "—"));
    const promptButton = element("button", "material-prompt-copy", "复制 AI 提示词");
    promptButton.type = "button";
    promptButton.disabled = !material.agent_prompt;
    promptButton.addEventListener("click", () => copyText(material.agent_prompt, `“${material.title}”定位与总结提示词已复制。`));
    card.append(main, promptButton);
    list.append(card);
}

function safeHttpUrl(value) {
  return typeof value === "string" && /^https?:\/\//i.test(value) ? value : null;
}

function openExternalTab(value) {
  const url = safeHttpUrl(value);
  if (url) window.open(url, "_blank", "noopener,noreferrer");
}

function closeSourcePreview() {
  const dialog = byId("source-preview");
  if (dialog.open) dialog.close();
}

async function openSourcePreview(source) {
  const dialog = byId("source-preview");
  const body = byId("preview-body");
  const original = byId("open-original");
  const remote = byId("open-source-url");
  byId("preview-title").textContent = source.title || "来源预览";
  byId("preview-path").textContent = source.relative_path || source.url || source.source_url || "";
  body.replaceChildren(element("p", "preview-loading", "正在读取本地来源…"));
  original.classList.add("hidden");
  remote.classList.add("hidden");
  const sourceUrl = safeHttpUrl(source.url || source.source_url);
  if (sourceUrl) {
    remote.href = sourceUrl;
    remote.classList.remove("hidden");
  }
  if (!dialog.open) dialog.showModal();
  if (!source.relative_path) {
    body.replaceChildren(element("p", "preview-empty", "该来源保留了 Moodle 链接，可通过下方按钮查看。"));
    return;
  }
  try {
    const params = new URLSearchParams({ path: source.relative_path });
    for (const page of source.page_numbers || []) params.append("page", page);
    const response = await fetch(`/api/source-preview?${params}`, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "无法预览来源");
    const localUrl = `/api/material?path=${encodeURIComponent(payload.original_relative_path)}`;
    original.href = localUrl;
    original.classList.remove("hidden");
    body.replaceChildren();
    if (payload.preview_kind === "pdf") {
      if (payload.text) {
        const fallback = element("details", "preview-text-fallback");
        fallback.append(
          element("summary", "", "PDF 预览为空？查看已提取文本"),
          element("pre", "preview-text", payload.text),
        );
        body.append(fallback);
      } else {
        body.append(element("p", "preview-pdf-help", "若 PDF 未显示，请使用下方的“打开原文”。"));
      }
      const page = payload.page_numbers.length ? `#page=${payload.page_numbers[0]}` : "";
      const frame = element("iframe", "preview-frame");
      frame.src = `${localUrl}${page}`;
      frame.title = payload.title;
      body.append(frame);
    } else if (payload.preview_kind === "image") {
      const image = element("img", "preview-image");
      image.src = localUrl;
      image.alt = payload.title;
      body.append(image);
    } else if (payload.text) {
      body.append(element("pre", "preview-text", payload.text));
    } else {
      body.append(element("p", "preview-empty", "该文件可打开原文；当前没有可显示的文本副本。"));
    }
  } catch (error) {
    body.replaceChildren(element("p", "preview-error", error.message));
  }
}

function courseItemsFor(course) {
  return state.data.items
    .filter((item) => item.course_id === course.course_id)
    .sort((left, right) => {
      const leftDate = primaryDateKey(left) || left.recurrence?.valid_from || "9999-12-31";
      const rightDate = primaryDateKey(right) || right.recurrence?.valid_from || "9999-12-31";
      return leftDate.localeCompare(rightDate)
        || categoryOrder.indexOf(left.category) - categoryOrder.indexOf(right.category)
        || left.title.localeCompare(right.title);
    });
}

function courseItemDateLabel(item) {
  const due = formatDateTime(item.due_at) || item.due_on;
  if (due) return `截止 ${due}`;
  const scheduled = formatDateTime(item.starts_at) || item.scheduled_on;
  if (scheduled) return `安排 ${scheduled}`;
  if (item.recurrence) {
    const weekdays = ["一", "二", "三", "四", "五", "六", "日"];
    const days = item.recurrence.weekdays.map((value) => `周${weekdays[value]}`).join("、");
    return `${days} ${item.recurrence.start_time.slice(0, 5)}–${item.recurrence.end_time.slice(0, 5)}`;
  }
  const opens = formatDateTime(item.opens_at);
  return opens ? `开放 ${opens}` : "日期待确认";
}

function renderCourseItemCard(list, item) {
  const card = element("article", "material-card course-item-row");
  card.style.setProperty("--item-color", categoryColor(item));
  const main = element("button", "material-card-main course-item-main");
  main.type = "button";
  const icon = element("span", "material-icon course-item-icon", "◆");
  const copy = element("div", "material-copy course-item-copy");
  const titleLine = element("div", "material-title-line course-item-title-line");
  titleLine.append(
    element("h4", "", item.title),
    element(
      "span",
      `date-state ${item.date_status}`,
      item.date_status === "confirmed" ? "已确认" : item.date_status === "tentative" ? "待核实" : "日期未知",
    ),
  );
  const meta = [
    categoryLabels[item.category] || item.category,
    courseItemDateLabel(item),
    item.location,
    item.weight_percent === null || item.weight_percent === undefined ? null : `占分 ${item.weight_percent}%`,
    (item.materials || []).length ? `${item.materials.length} 份相关资料` : null,
  ].filter(Boolean).join(" · ");
  copy.append(titleLine, element("small", "course-item-meta", meta));
  if (item.description) copy.append(element("small", "course-item-description", item.description));
  main.append(icon, copy, element("span", "material-open", "详情"));
  main.addEventListener("click", () => {
    state.selectedItemId = item.item_id;
    state.selectedDateKey = primaryDateKey(item);
    renderDetail(item, state.selectedDateKey);
  });
  const promptButton = element("button", "material-prompt-copy course-item-prompt-copy", "复制 AI 提示词");
  promptButton.type = "button";
  promptButton.disabled = !item.agent_prompt;
  promptButton.addEventListener("click", () => copyText(
    item.agent_prompt,
    `“${item.title}”活动查询提示词已复制。`,
  ));
  card.append(main, promptButton);
  list.append(card);
}

function renderCourseItems(parent, course) {
  const items = courseItemsFor(course);
  if (!items.length) {
    parent.append(element("p", "overview-empty", "当前课程还没有结构化活动。"));
    return;
  }
  for (const category of categoryOrder) {
    const values = items.filter((item) => item.category === category);
    if (!values.length) continue;
    const group = element("section", "course-item-group");
    group.style.setProperty("--item-color", categoryColors[category] || categoryColors.other);
    const heading = element("div", "course-item-group-heading");
    heading.append(
      element("h3", "", categoryLabels[category] || category),
      element("span", "", `${values.length} 项`),
    );
    const list = element("div", "course-item-list");
    for (const item of values) renderCourseItemCard(list, item);
    group.append(heading, list);
    parent.append(group);
  }
}

function renderCourseOverview() {
  const course = state.data.courses.find((value) => value.course_id === state.selectedOverviewCourseId);
  const container = byId("course-overview");
  container.replaceChildren();
  if (!course) {
    container.append(element("p", "overview-empty", "找不到这门课程。"));
    return;
  }
  byId("page-eyebrow").textContent = "COURSE OVERVIEW";
  byId("page-title").textContent = course.code || course.title;
  byId("data-caption").textContent = [course.title, course.semester].filter(Boolean).join(" · ");

  const hero = element("section", "course-hero");
  hero.style.setProperty("--course-color", course.color);
  const heroCopy = element("div");
  heroCopy.append(element("p", "eyebrow", "COURSE"), element("h2", "", course.title));
  const teachingPeriod = course.starts_on || course.ends_on
    ? `${course.starts_on || "起始日期待确认"} 至 ${course.ends_on || "结束日期待确认"}`
    : null;
  const facts = [course.semester, teachingPeriod, ...(course.instructors || [])].filter(Boolean).join(" · ");
  heroCopy.append(element("p", "", facts || "课程身份已建立，其他资料待 AI 整理。"));
  hero.append(heroCopy);
  if (course.moodle && /^https?:\/\//i.test(course.moodle.url)) {
    const link = element("a", "button", "打开 Moodle");
    link.href = course.moodle.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    hero.append(link);
  }
  container.append(hero);

  const upper = element("div", "overview-upper");
  const summary = element("section", "overview-card");
  summary.append(element("p", "eyebrow", "AI SUMMARY"), element("h3", "", "课程综合信息"));
  summary.append(element("p", "summary-provenance", "由 AI 根据已下载课程资料归纳；事实仍以所列来源为准。"));
  summary.append(element("h4", "", "课程概述"));
  summary.append(element("p", course.overview ? "overview-copy" : "overview-empty", course.overview || "尚未从官方资料录入课程概述。"));
  summary.append(element("h4", "", "课程目的"));
  appendOverviewList(summary, course.objectives, "尚未从官方资料录入课程目的。");
  if (course.sources && course.sources.length) {
    summary.append(element("h4", "", "信息来源"));
    const sources = element("div", "overview-sources");
    for (const source of course.sources) sources.append(sourcePreviewButton(source));
    summary.append(sources);
  }
  const grades = element("section", "overview-card");
  grades.append(element("p", "eyebrow", "ASSESSMENT"), element("h3", "", "成绩构成"));
  renderGradeDistribution(grades, course);
  upper.append(summary, grades);
  container.append(upper);

  const materials = element("section", "course-materials-card course-content-card");
  const materialHeading = element("div", "course-materials-title");
  materialHeading.append(element("div", "", null));
  const showingMaterials = state.courseContentMode === "materials";
  materialHeading.firstChild.append(
    element("p", "eyebrow", "COURSE CONTENT"),
    element("h2", "", showingMaterials ? "全部课件" : "课程活动"),
  );
  const counts = course.moodle
    ? `${course.moodle.downloaded_file_count} 个本地文件 · ${course.moodle.activity_count} 个 Moodle 项目`
    : "尚未同步 Moodle 快照";
  const materialActions = element("div", "course-material-actions");
  const switcher = element("div", "course-content-switch");
  switcher.setAttribute("role", "group");
  switcher.setAttribute("aria-label", "课程内容类型");
  for (const [mode, label] of [["materials", "课件"], ["activities", "活动"]]) {
    const button = element("button", `course-content-option ${state.courseContentMode === mode ? "active" : ""}`, label);
    button.type = "button";
    button.setAttribute("aria-pressed", String(state.courseContentMode === mode));
    button.addEventListener("click", () => {
      state.courseContentMode = mode;
      renderCourseOverview();
    });
    switcher.append(button);
  }
  materialActions.append(switcher);
  materialActions.append(element("span", "archive-summary", showingMaterials ? counts : `${courseItemsFor(course).length} 项结构化活动`));
  const recentPrompt = element("button", "button compact", "复制最近 Lecture 提示词");
  recentPrompt.type = "button";
  recentPrompt.disabled = !course.agent_prompts?.recent_lecture_materials;
  recentPrompt.addEventListener("click", () => copyText(
    course.agent_prompts?.recent_lecture_materials,
    `${course.code || course.title} 最近 Lecture 课件提示词已复制。`,
  ));
  if (showingMaterials) materialActions.append(recentPrompt);
  materialHeading.append(materialActions);
  materials.append(materialHeading);
  if (showingMaterials) {
    for (const section of course.materials?.sections || []) {
      renderMaterialSection(materials, section.title, section.description, section.materials || []);
    }
    const unclassified = course.materials?.unclassified || [];
    if (unclassified.length) {
      renderMaterialSection(
        materials,
        "待 AI 分类",
        "这些资料尚未写入 AI 自由命名的课程栏位。",
        unclassified,
        "material-unclassified",
      );
    }
    if (!allCourseMaterials(course).length) {
      materials.append(element("p", "overview-empty", "当前 Moodle 快照中没有课程资料。"));
    }
  } else {
    renderCourseItems(materials, course);
  }
  container.append(materials);
}

function renderMetrics(occurrences) {
  const filteredItems = state.data.items.filter(itemMatches);
  const monthPrefix = dateKey(state.currentMonth).slice(0, 7);
  byId("metric-courses").textContent = state.selectedCourses.size;
  byId("metric-items").textContent = filteredItems.length;
  byId("metric-month").textContent = occurrences.filter((value) => value.key.startsWith(monthPrefix)).length;
  byId("metric-unknown").textContent = filteredItems.filter((item) => item.date_status === "unknown").length;
  byId("metric-pending").textContent = state.data.material_status?.counts?.ai_review || 0;
}

function appendCompactStatus(container, title, meta, note = null, action = null) {
  const card = element(action ? "button" : "article", "compact-status");
  if (action) {
    card.type = "button";
    card.addEventListener("click", action);
  }
  card.append(element("strong", "", title), element("span", "", meta));
  if (note) card.append(element("small", "", note));
  container.append(card);
}

function renderMaterialStatus() {
  const status = state.data.material_status || {};
  const counts = status.counts || {};
  byId("status-ai").textContent = counts.ai_review || 0;
  byId("status-ocr").textContent = counts.ocr || 0;
  byId("status-google").textContent = counts.google_authorization || 0;
  byId("status-date").textContent = counts.date_unknown || 0;
  byId("status-conflict").textContent = counts.source_conflicts || 0;
  const total = Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0);
  byId("status-total").textContent = `${total} 项待处理`;

  const ocr = status.ocr || { capabilities: {}, queue: [] };
  const engine = ocr.capabilities?.engine;
  byId("ocr-capability").textContent = engine
    ? `${engine} · 全程本地处理`
    : "本机需要 Apple Vision 或 Tesseract";
  const runButton = byId("run-ocr");
  runButton.disabled = !(ocr.capabilities?.available && ocr.queue?.length);
  const queue = byId("ocr-queue-list");
  queue.replaceChildren();
  if (!ocr.queue?.length) {
    queue.append(element("p", "search-hint", "OCR 队列已清空。"));
  } else {
    for (const item of ocr.queue.slice(0, 8)) {
      appendCompactStatus(
        queue,
        item.title,
        `${item.course_id} · ${item.document_kind.toUpperCase()}`,
        item.activity_name,
        () => openSourcePreview(item),
      );
    }
  }

  const attention = byId("attention-list");
  attention.replaceChildren();
  const entries = [
    ...(status.google_authorization || []).map((item) => ({ ...item, kind: "Google 授权" })),
    ...(status.source_conflicts || []).map((item) => ({ ...item, kind: "来源冲突" })),
    ...(status.date_unknown || []).map((item) => ({ ...item, kind: "日期待确认" })),
  ];
  if (!entries.length) {
    attention.append(element("p", "search-hint", "当前没有需要人工处理的资料状态。"));
  } else {
    for (const item of entries.slice(0, 10)) {
      const informationItem = item.item_id
        ? state.data.items.find((value) => value.item_id === item.item_id)
        : null;
      appendCompactStatus(
        attention,
        item.title,
        `${item.course_id} · ${item.kind}`,
        item.message || (item.warnings || []).join("；") || null,
        informationItem ? () => {
          showCalendar();
          state.selectedItemId = informationItem.item_id;
          state.selectedDateKey = primaryDateKey(informationItem);
          renderDetail(informationItem, state.selectedDateKey);
        } : item.url ? () => openExternalTab(item.url) : null,
      );
    }
  }
}

function formatPreviewValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  return text.length > 90 ? `${text.slice(0, 87)}…` : text;
}

function renderPersonalInbox() {
  const inbox = state.data.personal_inbox || { pending_count: 0, entries: [] };
  byId("inbox-count").textContent = `${inbox.pending_count || 0} 条草稿`;
  const container = byId("inbox-list");
  container.replaceChildren();
  if (!inbox.entries?.length) {
    container.append(element("p", "search-hint", "个人补充信息 Inbox 当前为空。"));
    return;
  }
  for (const entry of inbox.entries) {
    const card = element("article", "inbox-entry");
    const heading = element("div", "inbox-entry-heading");
    const copy = element("div");
    copy.append(element("h3", "", entry.title));
    copy.append(element("p", "", [entry.note, formatDateTime(entry.created_at)].filter(Boolean).join(" · ")));
    const apply = element("button", "button compact", "确认写入");
    apply.type = "button";
    apply.addEventListener("click", () => applyInboxEntry(entry));
    heading.append(copy, apply);
    card.append(heading);
    for (const change of entry.changes || []) {
      const section = element("section", "inbox-change");
      section.append(element("strong", "", `${change.action === "create" ? "新增" : "更新"} ${change.title}`));
      const fields = element("div", "inbox-fields");
      for (const field of (change.fields || []).slice(0, 12)) {
        const row = element("div", "inbox-field");
        row.append(
          element("code", "", field.field),
          element("span", "", `${formatPreviewValue(field.before)} → ${formatPreviewValue(field.after)}`),
        );
        fields.append(row);
      }
      section.append(fields);
      card.append(section);
    }
    container.append(card);
  }
}

function renderCalendar(occurrences) {
  const grid = byId("calendar-grid");
  grid.replaceChildren();
  const isMonth = state.calendarMode === "month";
  const isWeek = state.calendarMode === "week";
  byId("weekday-row").classList.toggle("hidden", !isMonth);
  grid.classList.toggle("hidden", !isMonth);
  byId("weekly-agenda").classList.toggle("hidden", !isWeek);
  byId("daily-agenda").classList.toggle("hidden", state.calendarMode !== "day");
  byId("month-view-button").classList.toggle("active", isMonth);
  byId("week-view-button").classList.toggle("active", isWeek);
  byId("day-view-button").classList.toggle("active", state.calendarMode === "day");
  byId("calendar-title").textContent = isMonth ? "课程日历" : isWeek ? "每周日历" : "每日议程";
  const label = new Intl.DateTimeFormat("zh-HK", { year: "numeric", month: "long" }).format(state.currentMonth);
  if (isWeek) {
    const { start, end } = visibleRange();
    byId("calendar-label").textContent = `${new Intl.DateTimeFormat("zh-HK", { month: "short", day: "numeric" }).format(start)} – ${new Intl.DateTimeFormat("zh-HK", { month: "short", day: "numeric", year: "numeric" }).format(end)}`;
    renderWeeklyAgenda(occurrences);
    return;
  }
  byId("calendar-label").textContent = isMonth ? label : new Intl.DateTimeFormat("zh-HK", { year: "numeric", month: "long", day: "numeric", weekday: "short" }).format(state.selectedDay);
  if (state.calendarMode === "day") {
    renderDailyAgenda(occurrences);
    return;
  }
  const grouped = new Map();
  for (const occurrence of occurrences) {
    if (!grouped.has(occurrence.key)) grouped.set(occurrence.key, []);
    grouped.get(occurrence.key).push(occurrence);
  }
  const { start } = visibleRange();
  const today = dateKey(new Date());
  for (let index = 0; index < 42; index += 1) {
    const day = addDays(start, index);
    const key = dateKey(day);
    const cell = element("div", "calendar-day");
    if (day.getMonth() !== state.currentMonth.getMonth()) cell.classList.add("outside");
    if (key === today) cell.classList.add("today");
    const dayButton = element("button", "day-number", day.getDate());
    dayButton.type = "button";
    dayButton.setAttribute("aria-label", `查看 ${key} 的每日议程`);
    dayButton.addEventListener("click", () => {
      state.selectedDay = day;
      state.currentMonth = new Date(day.getFullYear(), day.getMonth(), 1);
      state.calendarMode = "day";
      renderDataViews();
    });
    cell.append(dayButton);
    const list = element("div", "day-events");
    const values = grouped.get(key) || [];
    for (const occurrence of values.slice(0, 3)) {
      const course = courseFor(occurrence.item);
      const chip = element("article", "event-chip");
      chip.style.setProperty("--course-color", course.color);
      chip.style.setProperty("--item-color", categoryColor(occurrence.item));
      if (occurrence.item.date_status !== "confirmed") chip.classList.add("tentative");
      if (state.selectedItemId === occurrence.item.item_id && state.selectedDateKey === key) chip.classList.add("selected");
      const main = element("button", "event-chip-main");
      main.type = "button";
      const heading = element("span", "event-card-heading");
      heading.append(
        element("strong", "event-card-title", occurrence.title || occurrence.item.title),
        element("time", "", occurrence.time || ""),
      );
      const courseLine = element("span", "event-course", `🎓 ${course.code || course.title}`);
      const tags = element("span", "event-tags");
      tags.append(
        element("span", "event-category", categoryLabels[occurrence.item.category] || occurrence.item.category),
        element(
          "span",
          `event-date-status ${occurrence.item.date_status}`,
          occurrence.item.date_status === "confirmed" ? "confirmed" : occurrence.item.date_status === "tentative" ? "tentative" : "unknown",
        ),
      );
      main.append(heading, courseLine, tags);
      main.title = `${course.code} · ${occurrence.title || occurrence.item.title}`;
      main.addEventListener("click", () => {
        state.selectedItemId = occurrence.item.item_id;
        state.selectedDateKey = key;
        renderDetail(occurrence.item, key);
        renderCalendar(occurrences);
      });
      const prompt = element("button", "event-prompt-copy", "复制 AI 提示词");
      prompt.type = "button";
      prompt.disabled = !occurrence.item.agent_prompt;
      prompt.addEventListener("click", () => copyText(
        occurrence.item.agent_prompt,
        `“${occurrence.item.title}”活动查询提示词已复制。`,
      ));
      chip.append(main, prompt);
      list.append(chip);
    }
    if (values.length > 3) list.append(element("span", "more-count", `另有 ${values.length - 3} 项`));
    cell.append(list);
    grid.append(cell);
  }
}

function renderDailyAgenda(occurrences) {
  const container = byId("daily-agenda");
  container.replaceChildren();
  const key = dateKey(state.selectedDay);
  const values = occurrences.filter((occurrence) => occurrence.key === key);
  const heading = element("div", "agenda-heading");
  heading.append(
    element("p", "eyebrow", "DAY VIEW"),
    element("h3", "", new Intl.DateTimeFormat("zh-HK", { month: "long", day: "numeric", weekday: "long" }).format(state.selectedDay)),
    element("span", "", `${values.length} 项活动`),
  );
  container.append(heading);
  if (!values.length) {
    container.append(element("p", "agenda-empty", "这一天没有已记录的课程活动。"));
    return;
  }

  const allDay = values.filter((occurrence) => !occurrence.time || occurrence.item.all_day);
  const timed = values.filter((occurrence) => occurrence.time && !occurrence.item.all_day);
  if (allDay.length) {
    const allDayRow = element("section", "agenda-all-day");
    allDayRow.append(element("span", "agenda-all-day-label", "全天"));
    const allDayEvents = element("div", "agenda-all-day-events");
    for (const occurrence of allDay) {
      allDayEvents.append(buildAgendaEvent(occurrence, key, values, true));
    }
    allDayRow.append(allDayEvents);
    container.append(allDayRow);
  }

  const scroll = element("div", "agenda-scroll");
  const timeline = element("div", "agenda-timeline");
  timeline.title = "双击空白时段添加事件";
  timeline.addEventListener("dblclick", (event) => {
    openEventEditorFromGrid(event, timeline, state.selectedDay);
  });
  for (let hour = timeGridStartHour; hour < 24; hour += 1) {
    const row = element("div", "agenda-hour");
    row.append(element("time", "agenda-hour-label", `${String(hour).padStart(2, "0")}:00`));
    timeline.append(row);
  }
  const eventLayer = element("div", "agenda-events-layer");
  for (const occurrence of timed) {
    const startMinutes = timeMinutes(occurrence.time);
    const endValue = occurrence.endTime || occurrenceEndTime(occurrence.item);
    const endMinutes = endValue ? timeMinutes(endValue) : startMinutes + 50;
    const duration = Math.max(30, endMinutes > startMinutes ? endMinutes - startMinutes : 50);
    const event = buildAgendaEvent(occurrence, key, values, false);
    event.style.setProperty("--event-top", `${timeGridOffset(startMinutes)}px`);
    event.style.setProperty("--event-height", `${timeGridEventHeight(startMinutes, startMinutes + duration)}px`);
    eventLayer.append(event);
  }
  timeline.append(eventLayer);

  const now = new Date();
  if (dateKey(now) === key) {
    const marker = element("div", "agenda-now-line");
    marker.style.setProperty("--now-top", `${timeGridOffset(now.getHours() * 60 + now.getMinutes())}px`);
    timeline.append(marker);
  }
  scroll.append(timeline);
  container.append(scroll);
  const earliest = timed.length ? Math.min(...timed.map((occurrence) => timeMinutes(occurrence.time))) : 8 * 60;
  scroll.scrollTop = Math.max(0, timeGridOffset(earliest) - timeGridHourHeight);
}

function renderWeeklyAgenda(occurrences) {
  const container = byId("weekly-agenda");
  container.replaceChildren();
  const { start } = visibleRange();
  const days = Array.from({ length: 7 }, (_, index) => addDays(start, index));
  const today = dateKey(new Date());
  const grouped = new Map(days.map((day) => [dateKey(day), []]));
  for (const occurrence of occurrences) {
    if (grouped.has(occurrence.key)) grouped.get(occurrence.key).push(occurrence);
  }

  const header = element("div", "week-header");
  header.append(element("div", "week-header-spacer"));
  for (const day of days) {
    const heading = element("button", `week-day-heading ${dateKey(day) === today ? "today" : ""}`.trim());
    heading.type = "button";
    heading.append(
      element("span", "", new Intl.DateTimeFormat("zh-HK", { weekday: "short" }).format(day)),
      element("strong", "", day.getDate()),
    );
    heading.addEventListener("click", () => {
      state.selectedDay = day;
      state.currentMonth = new Date(day.getFullYear(), day.getMonth(), 1);
      state.calendarMode = "day";
      renderDataViews();
    });
    header.append(heading);
  }
  container.append(header);

  const allDay = element("div", "week-all-day");
  allDay.append(element("span", "week-all-day-label", "全天"));
  for (const day of days) {
    const key = dateKey(day);
    const cell = element("div", "week-all-day-cell");
    for (const occurrence of (grouped.get(key) || []).filter((value) => !value.time || value.item.all_day)) {
      const entry = element("article", "week-all-day-entry");
      entry.style.setProperty("--item-color", categoryColor(occurrence.item));
      const open = element("button", "week-all-day-event", occurrence.title || occurrence.item.title);
      open.type = "button";
      open.addEventListener("click", () => renderDetail(occurrence.item, key));
      const copy = element("button", "week-all-day-copy", "AI");
      copy.type = "button";
      copy.title = "复制 AI 提示词";
      copy.disabled = !occurrence.item.agent_prompt;
      copy.addEventListener("click", () => copyText(occurrence.item.agent_prompt, `“${occurrence.item.title}”活动查询提示词已复制。`));
      entry.append(open, copy);
      cell.append(entry);
    }
    allDay.append(cell);
  }
  container.append(allDay);

  const scroll = element("div", "week-scroll");
  const timeline = element("div", "week-timeline");
  const gutter = element("div", "week-time-gutter");
  for (let hour = timeGridStartHour; hour < 24; hour += 1) {
    const label = element("time", "week-time-label", `${String(hour).padStart(2, "0")}:00`);
    label.style.setProperty("--slot", hour - timeGridStartHour);
    gutter.append(label);
  }
  timeline.append(gutter);
  const timedOccurrences = [];
  for (const day of days) {
    const key = dateKey(day);
    const column = element("div", `week-day-column ${key === today ? "today" : ""}`.trim());
    column.title = "双击空白时段添加事件";
    column.addEventListener("dblclick", (event) => {
      openEventEditorFromGrid(event, timeline, day);
    });
    const timed = (grouped.get(key) || []).filter((value) => value.time && !value.item.all_day);
    for (const layout of weekEventLayouts(timed)) {
      const { occurrence, startMinutes, endMinutes, lane, laneCount } = layout;
      timedOccurrences.push(occurrence);
      const endValue = occurrence.endTime || occurrenceEndTime(occurrence.item);
      const duration = Math.max(30, endMinutes > startMinutes ? endMinutes - startMinutes : 50);
      const event = element("article", "week-event");
      event.style.setProperty("--item-color", categoryColor(occurrence.item));
      event.style.setProperty("--event-top", `${timeGridOffset(startMinutes)}px`);
      event.style.setProperty("--event-height", `${timeGridEventHeight(startMinutes, startMinutes + duration)}px`);
      event.style.setProperty("--event-left", `${lane / laneCount * 100}%`);
      event.style.setProperty("--event-width", `${100 / laneCount}%`);
      const open = element("button", "week-event-main");
      open.type = "button";
      open.append(
        element("strong", "", occurrence.title || occurrence.item.title),
        element("time", "", endValue ? `${occurrence.time}–${endValue}` : occurrence.time),
        element("small", "", occurrence.location || occurrence.item.location || courseFor(occurrence.item).code),
      );
      open.addEventListener("click", () => renderDetail(occurrence.item, key));
      const copy = element("button", "week-event-copy", "AI");
      copy.type = "button";
      copy.title = "复制 AI 提示词";
      copy.disabled = !occurrence.item.agent_prompt;
      copy.addEventListener("click", () => copyText(occurrence.item.agent_prompt, `“${occurrence.item.title}”活动查询提示词已复制。`));
      event.append(open, copy);
      column.append(event);
    }
    if (key === today) {
      const now = new Date();
      const marker = element("div", "week-now-line");
      marker.style.setProperty("--now-top", `${timeGridOffset(now.getHours() * 60 + now.getMinutes())}px`);
      column.append(marker);
    }
    timeline.append(column);
  }
  scroll.append(timeline);
  container.append(scroll);
  const earliest = timedOccurrences.length
    ? Math.min(...timedOccurrences.map((occurrence) => timeMinutes(occurrence.time)))
    : 8 * 60;
  scroll.scrollTop = Math.max(0, timeGridOffset(earliest) - timeGridHourHeight);
}

function weekEventLayouts(occurrences) {
  const entries = occurrences.map((occurrence) => {
    const startMinutes = timeMinutes(occurrence.time);
    const endValue = occurrence.endTime || occurrenceEndTime(occurrence.item);
    const endMinutes = endValue ? timeMinutes(endValue) : startMinutes + 50;
    return { occurrence, startMinutes, endMinutes };
  }).sort((left, right) => left.startMinutes - right.startMinutes || left.endMinutes - right.endMinutes);
  const groups = [];
  for (const entry of entries) {
    const group = groups.at(-1);
    if (!group || entry.startMinutes >= group.maxEnd) {
      groups.push({ maxEnd: entry.endMinutes, entries: [entry] });
    } else {
      group.entries.push(entry);
      group.maxEnd = Math.max(group.maxEnd, entry.endMinutes);
    }
  }
  return groups.flatMap((group) => {
    const laneEnds = [];
    const assigned = group.entries.map((entry) => {
      let lane = laneEnds.findIndex((end) => end <= entry.startMinutes);
      if (lane < 0) lane = laneEnds.length;
      laneEnds[lane] = entry.endMinutes;
      return { ...entry, lane };
    });
    return assigned.map((entry) => ({ ...entry, laneCount: laneEnds.length }));
  });
}

function timeMinutes(value) {
  const [hours, minutes] = value.split(":").map(Number);
  return hours * 60 + minutes;
}

function buildAgendaEvent(occurrence, key, allOccurrences, compact) {
    const item = occurrence.item;
    const course = courseFor(item);
    const button = element("button", compact ? "agenda-item compact" : "agenda-item");
    button.type = "button";
    button.style.setProperty("--course-color", course.color);
    button.style.setProperty("--item-color", categoryColor(item));
    if (state.selectedItemId === item.item_id && state.selectedDateKey === key) button.classList.add("selected");
    const start = occurrence.time || (item.all_day ? "全天" : "待定");
    const end = occurrence.endTime || occurrenceEndTime(item);
    const copy = element("span", "agenda-copy");
    copy.append(
      element("span", "agenda-category", categoryLabels[item.category] || item.category),
      element("strong", "", occurrence.title || item.title),
      element("small", "", [course.code, occurrence.location || item.location].filter(Boolean).join(" · ")),
    );
    const materialCount = (item.materials || []).length;
    button.append(
      element("time", "agenda-time", end ? `${start}–${end}` : start),
      copy,
      element("span", "agenda-materials", materialCount ? `${materialCount} 份材料` : "查看详情"),
    );
    button.addEventListener("click", () => {
      state.selectedItemId = item.item_id;
      state.selectedDateKey = key;
      renderDetail(item, key);
      renderCalendar(allOccurrences);
    });
    return button;
}

function appendFact(list, label, value) {
  if (value === null || value === undefined || value === "") return;
  const row = element("div");
  row.append(element("dt", "", label), element("dd", "", value));
  list.append(row);
}

function formatDateTime(value) {
  if (!value) return null;
  if (!value.includes("T")) return value;
  try {
    return new Intl.DateTimeFormat("zh-HK", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: state.data.timezone,
    }).format(new Date(value));
  } catch (_error) {
    return value;
  }
}

function appendListBlock(panel, title, values, extraClass = "") {
  if (!values || !values.length) return;
  const block = element("section", `detail-block ${extraClass}`.trim());
  block.append(element("h3", "", title));
  const list = element("ul");
  for (const value of values) list.append(element("li", "", value));
  block.append(list);
  panel.append(block);
}

function sourcePreviewButton(source) {
  const pages = source.page_numbers && source.page_numbers.length ? ` · 第 ${source.page_numbers.join("、")} 页` : "";
  const note = source.note ? ` · ${source.note}` : "";
  const remoteUrl = safeHttpUrl(source.url || source.source_url);
  const button = element(source.relative_path ? "button" : remoteUrl ? "a" : "button", "source-card", `${source.title}${pages}${note}`);
  if (source.relative_path) {
    button.type = "button";
    button.addEventListener("click", () => openSourcePreview(source));
  } else if (remoteUrl) {
    button.href = remoteUrl;
    button.target = "_blank";
    button.rel = "noopener noreferrer";
  } else {
    button.type = "button";
    button.disabled = true;
  }
  if (source.relative_path) button.append(element("small", "", source.relative_path));
  return button;
}

function renderDetail(item, occurrenceKey = null) {
  const dialog = byId("item-detail-dialog");
  const panel = byId("detail-panel");
  const course = courseFor(item);
  const exception = item.recurrence && occurrenceKey
    ? recurrenceException(item.recurrence, occurrenceKey)
    : null;
  panel.replaceChildren();
  panel.style.setProperty("--course-color", course.color);
  panel.style.setProperty("--item-color", categoryColor(item));
  panel.append(element("div", "detail-course", `${course.code} · ${categoryLabels[item.category] || item.category}`));
  panel.append(element("h2", "", exception?.title || item.title));

  const pills = element("div", "detail-pills");
  pills.append(element("span", "pill category-pill", categoryLabels[item.category] || item.category));
  pills.append(element("span", "pill", item.date_status === "confirmed" ? "日期已确认" : item.date_status === "tentative" ? "日期待核实" : "日期未知"));
  if (item.weight_percent !== null && item.weight_percent !== undefined) pills.append(element("span", "pill", `占分 ${item.weight_percent}%`));
  if (item.warnings && item.warnings.length) pills.append(element("span", "pill warning", `${item.warnings.length} 项提醒`));
  panel.append(pills);
  if (item.description) panel.append(element("p", "detail-description", item.description));

  const facts = element("dl", "detail-facts");
  if (item.recurrence) {
    appendFact(facts, "本次日期", occurrenceKey || "每周重复");
    const startTime = exception?.start_time || item.recurrence.start_time;
    const endTime = exception?.end_time || item.recurrence.end_time;
    appendFact(facts, "时间", `${startTime.slice(0, 5)}–${endTime.slice(0, 5)}`);
    appendFact(facts, "有效日期", `${item.recurrence.valid_from} 至 ${item.recurrence.valid_until}`);
    appendFact(facts, "本次变更", exception?.note);
  } else {
    appendFact(facts, "开放", formatDateTime(item.opens_at));
    appendFact(facts, "开始", formatDateTime(item.starts_at));
    appendFact(facts, "结束", formatDateTime(item.ends_at));
    appendFact(facts, "DDL", formatDateTime(item.due_at) || item.due_on);
    appendFact(facts, "安排日期", item.scheduled_on);
  }
  appendFact(facts, "地点", exception?.location || item.location);
  appendFact(facts, "课业形式", item.assessment_format);
  appendFact(facts, "GPA 占比", item.weight_percent === null || item.weight_percent === undefined ? null : `${item.weight_percent}%`);
  appendFact(facts, "字数限制", item.word_limit === null || item.word_limit === undefined ? null : `${item.word_limit} 字`);
  appendFact(facts, "提交方式", item.submission_method);
  appendFact(facts, "最近核实", formatDateTime(item.last_verified_at));
  panel.append(facts);

  appendListBlock(panel, "课业要求", item.requirements);
  appendListBlock(panel, "相关政策", item.policies);
  appendListBlock(panel, "提醒与冲突", item.warnings, "warning-list");

  if (item.materials && item.materials.length) {
    const block = element("section", "detail-block related-materials");
    block.append(element("h3", "", "相关学习材料"));
    for (const material of item.materials) {
      const card = sourcePreviewButton(material);
      if (material.material_type) {
        card.append(element("small", "material-type-text", material.material_type));
      }
      block.append(card);
    }
    panel.append(block);
  }

  if (item.links && item.links.length) {
    const block = element("section", "detail-block");
    block.append(element("h3", "", "相关链接"));
    for (const link of item.links) {
      const safe = /^https?:\/\//i.test(link.url);
      const node = element(safe ? "a" : "div", "source-card", link.label);
      if (safe) {
        node.href = link.url;
        node.target = "_blank";
        node.rel = "noopener noreferrer";
      }
      block.append(node);
    }
    panel.append(block);
  }

  if (item.sources && item.sources.length) {
    const block = element("section", "detail-block");
    block.append(element("h3", "", "证据来源"));
    for (const source of item.sources) {
      block.append(sourcePreviewButton(source));
    }
    panel.append(block);
  }
  if (exception?.sources?.length) {
    const block = element("section", "detail-block");
    block.append(element("h3", "", "本次变更来源"));
    for (const source of exception.sources) block.append(sourcePreviewButton(source));
    panel.append(block);
  }
  const actions = element("div", "detail-actions");
  const copyPrompt = element("button", "button compact", "复制 AI 提示词");
  copyPrompt.type = "button";
  copyPrompt.disabled = !item.agent_prompt;
  copyPrompt.addEventListener("click", () => copyText(item.agent_prompt, `“${item.title}”活动查询提示词已复制。`));
  actions.append(copyPrompt);
  if (item.user_created) {
    const remove = element("button", "button compact danger", "删除事件");
    remove.type = "button";
    remove.addEventListener("click", () => deleteCalendarEvent(item));
    actions.append(remove);
  }
  panel.append(actions);
  if (!dialog.open) dialog.showModal();
}

function closeItemDetail() {
  state.selectedItemId = null;
  state.selectedDateKey = null;
  const dialog = byId("item-detail-dialog");
  if (dialog.open) dialog.close();
  renderDataViews();
}

function setEventTimeFieldState() {
  const allDay = byId("event-all-day").checked;
  byId("event-start-time").disabled = allDay;
  byId("event-end-time").disabled = allDay;
}

function openEventEditor(date = state.selectedDay, startTime = "09:00", endTime = "10:00") {
  const form = byId("event-editor-form");
  form.reset();
  byId("event-start-time").value = startTime;
  byId("event-end-time").value = endTime;
  byId("event-date").value = dateKey(date);
  const courseSelect = byId("event-course");
  courseSelect.replaceChildren();
  for (const course of state.data?.courses || []) {
    const option = element("option", "", `${course.code || course.title} · ${course.title}`);
    option.value = course.course_id;
    option.selected = course.course_id === state.selectedOverviewCourseId;
    courseSelect.append(option);
  }
  setEventTimeFieldState();
  const dialog = byId("event-editor-dialog");
  if (!dialog.open) dialog.showModal();
}

function closeEventEditor() {
  const dialog = byId("event-editor-dialog");
  if (dialog.open) dialog.close();
}

function localEventDateTime(date, time) {
  return new Date(`${date}T${time}:00`).toISOString();
}

async function addCalendarEvent(event) {
  event.preventDefault();
  const allDay = byId("event-all-day").checked;
  const date = byId("event-date").value;
  const startTime = byId("event-start-time").value;
  const endTime = byId("event-end-time").value;
  if (!allDay && endTime <= startTime) {
    window.alert("结束时间必须晚于开始时间。");
    return;
  }
  const title = byId("event-title").value.trim();
  if (!window.confirm(`将“${title}”写入本地课程日历。继续吗？`)) return;
  const value = {
    course_id: byId("event-course").value,
    title,
    category: byId("event-category").value,
    all_day: allDay,
    scheduled_on: allDay ? date : null,
    starts_at: allDay ? null : localEventDateTime(date, startTime),
    ends_at: allDay ? null : localEventDateTime(date, endTime),
    location: byId("event-location").value.trim() || null,
    description: byId("event-description").value.trim() || null,
  };
  const result = await runLocalMutation(
    "/api/events/add",
    { confirmed: true, event: value },
    "正在校验并添加个人事件…",
  );
  if (!result) return;
  closeEventEditor();
  await loadInformation();
  setOperationState(false, `事件已添加：${title}`);
}

async function deleteCalendarEvent(item) {
  if (!window.confirm(`确认删除个人事件“${item.title}”吗？删除前会在本机 .trash/items 保存恢复副本。`)) return;
  const result = await runLocalMutation(
    "/api/events/delete",
    { confirmed: true, confirmation: item.item_id, item_id: item.item_id },
    "正在删除个人事件…",
  );
  if (!result) return;
  closeItemDetail();
  await loadInformation();
  setOperationState(false, `事件已删除；恢复副本：${result.recoverable_from}`);
}

function renderUnscheduled() {
  const items = state.data.items.filter((item) => itemMatches(item) && !primaryDateKey(item) && !item.recurrence);
  const container = byId("unscheduled-list");
  container.replaceChildren();
  byId("unscheduled-count").textContent = `${items.length} 项`;
  if (!items.length) {
    container.append(element("p", "empty-list", "当前筛选范围没有日期待确认事项。"));
    return;
  }
  for (const item of items) {
    const course = courseFor(item);
    const button = element("button", "unscheduled-item");
    button.type = "button";
    button.style.setProperty("--course-color", course.color);
    button.style.setProperty("--item-color", categoryColor(item));
    const copy = element("span");
    copy.append(
      element("span", "category-tag", categoryLabels[item.category] || item.category),
      element("strong", "", item.title),
      element("small", "", `${course.code} · ${courseItemDateLabel(item)}`),
    );
    button.append(copy);
    button.addEventListener("click", () => {
      state.selectedItemId = item.item_id;
      state.selectedDateKey = null;
      renderDetail(item);
    });
    container.append(button);
  }
}

function formatChangeValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);
}

function renderUpdates() {
  const container = byId("updates-list");
  container.replaceChildren();
  const courses = state.data.updates?.courses || [];
  byId("updates-count").textContent = `${state.data.pending_review?.change_count || 0} 项`;
  if (!courses.length) {
    container.append(element("p", "empty-list", "当前 Moodle 快照已完成整理。"));
    return;
  }
  const actionLabels = { added: "新增", modified: "修改", removed: "删除", baseline: "首次整理" };
  const kindLabels = { deadline: "日期", activity: "项目", material: "文件" };
  for (const course of courses) {
    const group = element("article", "update-course");
    const heading = element("div", "update-course-heading");
    heading.append(
      element("div", "", null),
      element("span", "update-mode", course.mode === "full" ? "首次整理" : "增量更新"),
    );
    heading.firstChild.append(
      element("h3", "", course.course_title),
      element("p", "", `${course.course_id} · 检测至 ${formatDateTime(course.acknowledge_through)}`),
    );
    group.append(heading);
    const changes = course.changes || [];
    if (changes.length) {
      for (const change of changes) {
        const card = element("div", "change-card");
        const title = element("div", "change-title");
        title.append(
          element("span", `change-action ${change.action}`, actionLabels[change.action] || change.action),
          element("span", "change-kind", kindLabels[change.kind] || change.kind),
          element("strong", "", change.title),
        );
        card.append(title);
        if (change.field) card.append(element("code", "change-field", change.field));
        if (change.action === "modified") {
          const diff = element("div", "change-diff");
          const before = element("div");
          before.append(element("span", "", "更新前"), element("pre", "", formatChangeValue(change.before)));
          const after = element("div");
          after.append(element("span", "", "更新后"), element("pre", "", formatChangeValue(change.after)));
          diff.append(before, after);
          card.append(diff);
        }
        if (
          (change.action !== "removed" && (change.relative_path || change.text_path))
          || safeHttpUrl(change.source_url)
        ) {
          card.append(sourcePreviewButton({
            title: change.title,
            relative_path: change.action === "removed" ? null : change.relative_path || change.text_path,
            source_url: change.source_url,
          }));
        }
        group.append(card);
      }
    } else {
      const files = (course.files || []).filter((file) => file.relative_path !== "course.json");
      const note = element("p", "update-baseline", `已建立课程基线，${files.length} 个文件等待首次整理。`);
      group.append(note);
      const fileList = element("div", "baseline-files");
      for (const file of files) {
        fileList.append(sourcePreviewButton({ title: file.filename, relative_path: file.relative_path }));
      }
      group.append(fileList);
    }
    container.append(group);
  }
}

function localSearchRecords() {
  const records = [];
  for (const item of state.data.items) {
    const course = courseFor(item);
    const facts = [
      item.weight_percent !== null && item.weight_percent !== undefined ? `占分 ${item.weight_percent}%` : null,
      formatDateTime(item.due_at) || item.due_on ? `DDL ${formatDateTime(item.due_at) || item.due_on}` : null,
      item.location ? `地点 ${item.location}` : null,
    ].filter(Boolean);
    records.push({
      kind: "item",
      title: item.title,
      subtitle: [course.code, categoryLabels[item.category] || item.category, ...facts].join(" · "),
      searchable: [item.title, item.description, item.location, item.assessment_format, item.submission_method, item.weight_percent, "占分 GPA DDL 截止 地点 形式", ...(item.requirements || []), ...(item.materials || []).flatMap((material) => [material.title, material.note, material.relative_path])].filter(Boolean).join(" "),
      value: item,
    });
  }
  for (const course of state.data.courses) {
    for (const material of allCourseMaterials(course)) {
      records.push({
        kind: "material",
        title: material.title,
        subtitle: `${course.code || course.title} · ${material.material_section || "待 AI 分类"}`,
        searchable: [material.title, material.activity_name, material.section_title, course.code, course.title].filter(Boolean).join(" "),
        value: material,
      });
    }
  }
  return records;
}

function renderHomeSearch() {
  const container = byId("home-search-results");
  container.replaceChildren();
  const query = state.homeQuery.trim().toLocaleLowerCase();
  if (!query) {
    container.append(element("p", "search-hint", "可查询 DDL、占分、地点、课业形式、课件名称和课程代码。"));
    return;
  }
  const ignored = new Set(["的", "是", "什么", "多少", "请问", "我", "how", "what", "is", "the"]);
  const normalized = query
    .replace(/占分多少|占比多少/g, "占分")
    .replace(/什么时候|在哪里|是什么|有哪些|怎么样|怎么/g, " ");
  const terms = normalized.split(/[\s，。？！,.?!:：]+/).filter((value) => value && !ignored.has(value));
  const matches = localSearchRecords().filter((record) => {
    const value = `${record.title} ${record.subtitle} ${record.searchable}`.toLocaleLowerCase();
    return terms.every((term) => value.includes(term));
  }).slice(0, 12);
  if (!matches.length) {
    container.append(element("p", "search-hint", "本地信息库中没有匹配结果，可以缩短问题或改用课程代码、事项名称。"));
    return;
  }
  for (const record of matches) {
    const button = element("button", "search-result");
    button.type = "button";
    button.append(element("strong", "", record.title), element("small", "", record.subtitle));
    button.addEventListener("click", () => {
      if (record.kind === "material") {
        const remoteUrl = safeHttpUrl(record.value.source_url);
        if (!record.value.relative_path && remoteUrl) openExternalTab(remoteUrl);
        else openSourcePreview(record.value);
      } else {
        showCalendar();
        state.selectedItemId = record.value.item_id;
        state.selectedDateKey = primaryDateKey(record.value);
        renderDetail(record.value, state.selectedDateKey);
      }
    });
    container.append(button);
  }
}

function renderDataViews() {
  const occurrences = buildOccurrences();
  renderHomeFocus();
  renderMetrics(occurrences);
  renderMaterialStatus();
  renderPersonalInbox();
  renderCalendar(occurrences);
  renderUnscheduled();
  renderUpdates();
  renderHomeSearch();
  renderReviewClosure();
  renderReconciliation();
  if (state.selectedItemId) {
    const selected = state.data.items.find((item) => item.item_id === state.selectedItemId && itemMatches(item));
    if (selected) renderDetail(selected, state.selectedDateKey);
  }
  if (state.view === "course") renderCourseOverview();
}

async function copyText(value, successMessage) {
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
  } catch (_error) {
    const input = document.createElement("textarea");
    input.value = value;
    document.body.append(input);
    input.select();
    document.execCommand("copy");
    input.remove();
  }
  setOperationState(false, successMessage);
}

async function copyAgentPrompt() {
  const prompt = state.data?.review_closure?.agent_prompt;
  await copyText(prompt, "Agent 整理指令已复制。同步完成后可直接粘贴给 Agent。 ");
}

async function retryFailures() {
  const tasks = state.data?.review_closure?.retry_tasks || [];
  if (!tasks.length) return;
  const confirmed = window.confirm(`只重试最近失败的 ${tasks.length} 个课程或来源；已成功项目不会重复同步。继续吗？`);
  if (!confirmed) return;
  const job = await runLocalMutation(
    "/api/sync/retry",
    { confirmed: true },
    "正在准备精确重试…",
  );
  if (!job) return;
  renderSyncProgress(job);
  await pollCourseSync(job.job_id);
}

async function loadInformation() {
  byId("global-error").classList.add("hidden");
  if (window.location.protocol === "file:") {
    const alert = byId("global-error");
    alert.textContent = "当前打开的是静态 HTML 文件。请在项目目录运行 hsas ui，并访问终端显示的 http://127.0.0.1 地址；本地搜索、来源预览、同步和 Moodle 跳转通过该服务运行。";
    alert.classList.remove("hidden");
    document.querySelectorAll("button, input").forEach((control) => {
      control.disabled = true;
    });
    return;
  }
  try {
    const response = await fetch("/api/information", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "无法读取信息库");
    state.data = payload;
    state.selectedCourses = new Set(payload.courses.map((course) => course.course_id));
    if (!state.selectedOverviewCourseId && payload.courses.length) {
      state.selectedOverviewCourseId = payload.courses[0].course_id;
    }
    byId("data-caption").textContent = dataCaption();
    const warning = byId("data-warning");
    if (payload.warnings && payload.warnings.length) {
      warning.textContent = payload.warnings.join(" ");
      warning.classList.remove("hidden");
    } else {
      warning.classList.add("hidden");
    }
    renderCourseNavigation();
    renderCourseFilters();
    renderDataViews();
  } catch (error) {
    const alert = byId("global-error");
    alert.textContent = error.message;
    alert.classList.remove("hidden");
  }
}

function renderApplicationUpdate(value) {
  const button = byId("app-update");
  state.applicationUpdate = value;
  button.dataset.status = value.status;
  button.title = value.message || "";
  button.disabled = value.status === "checking" || value.status === "updating" || value.status === "updated";
  if (value.status === "available") {
    button.textContent = value.can_apply
      ? `更新至 ${value.latest_version}`
      : `发现更新 ${value.latest_version}`;
  } else if (value.status === "current") {
    button.textContent = "已是最新版本";
  } else if (value.status === "ahead") {
    button.textContent = "本机版本较新";
  } else if (value.status === "updated") {
    button.textContent = "更新完成 · 请重启";
  } else if (value.status === "updating") {
    button.textContent = "正在更新…";
  } else if (value.status === "error") {
    button.textContent = "检查更新";
  } else {
    button.textContent = "正在检查更新…";
  }
}

async function checkApplicationUpdate() {
  if (window.location.protocol === "file:") return;
  renderApplicationUpdate({ status: "checking", message: "正在检查 GitHub 版本。" });
  try {
    const response = await fetch("/api/update/status", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "无法检查更新");
    renderApplicationUpdate(payload);
  } catch (error) {
    renderApplicationUpdate({ status: "error", message: error.message });
  }
}

async function applyApplicationUpdate() {
  const update = state.applicationUpdate;
  if (!update || update.status !== "available") {
    await checkApplicationUpdate();
    return;
  }
  if (!update.can_apply) {
    const alert = byId("global-error");
    alert.textContent = update.message || "当前源码目录无法自动更新。";
    alert.classList.remove("hidden");
    return;
  }
  const confirmed = window.confirm(
    `将从官方 GitHub main 更新 HIQS ${update.current_version} → ${update.latest_version}。更新仅在工作树干净且可以 fast-forward 时执行；课程资料不会改变。继续吗？`,
  );
  if (!confirmed) return;
  renderApplicationUpdate({ ...update, status: "updating", message: "正在更新 HIQS。" });
  const result = await runLocalMutation(
    "/api/update/apply",
    { confirmed: true },
    "正在从 GitHub 更新 HIQS；请保持应用打开…",
  );
  if (!result) {
    await checkApplicationUpdate();
    return;
  }
  renderApplicationUpdate({
    status: result.restart_required ? "updated" : "current",
    current_version: result.current_version,
    latest_version: result.current_version,
    message: result.message,
  });
  setOperationState(false, result.message);
}

function setOperationState(running, message = "") {
  const reloadButton = byId("reload-data");
  const ocrButton = byId("run-ocr");
  const workflowButton = byId("start-workflow");
  reloadButton.disabled = running;
  workflowButton.disabled = running;
  document.querySelectorAll("#course-manager-dialog input, #course-manager-dialog button").forEach((control) => {
    control.disabled = running;
  });
  if (!running) updateCourseManagerSelection();
  const ocr = state.data?.material_status?.ocr;
  ocrButton.disabled = running || !(ocr?.capabilities?.available && ocr?.queue?.length);
  const status = byId("operation-status");
  if (message) {
    status.textContent = message;
    status.classList.remove("hidden");
  } else {
    status.classList.add("hidden");
  }
}

async function runLocalMutation(path, payload, pendingMessage) {
  byId("global-error").classList.add("hidden");
  setOperationState(true, pendingMessage);
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-HIQS-Request": "1",
      },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "操作失败");
    return result;
  } catch (error) {
    setOperationState(false);
    const alert = byId("global-error");
    alert.textContent = error.message;
    alert.classList.remove("hidden");
    return null;
  }
}

async function processOcrQueue() {
  const confirmed = window.confirm("将使用本机 OCR 处理队列中的 PDF 与图片型 PPT，并更新文本副本。继续吗？");
  if (!confirmed) return;
  const result = await runLocalMutation(
    "/api/ocr/run",
    { confirmed: true },
    "正在本机执行批量 OCR；较长的课件可能需要几分钟…",
  );
  if (!result) return;
  await loadInformation();
  setOperationState(false, `OCR 完成：${result.processed_count} 个成功，${result.failed_count} 个待处理。`);
}

async function applyInboxEntry(entry) {
  const changeCount = (entry.changes || []).length;
  const confirmed = window.confirm(`将把“${entry.title}”的 ${changeCount} 项预览变更写入 information.json。继续吗？`);
  if (!confirmed) return;
  const result = await runLocalMutation(
    "/api/inbox/apply",
    { confirmed: true, entry_id: entry.entry_id },
    "正在校验并写入个人补充信息…",
  );
  if (!result) return;
  await loadInformation();
  setOperationState(false, `个人补充信息已写入：新增 ${result.created_items} 项，更新 ${result.updated_items} 项。`);
}

function renderSyncProgress(job) {
  const panel = byId("sync-progress");
  const running = job.state === "running";
  const cancelling = running && Boolean(job.cancel_requested);
  panel.classList.toggle("hidden", !running);
  panel.classList.toggle("cancelling", cancelling);
  byId("sync-progress-label").textContent = cancelling ? "正在取消" : job.detail || "正在同步";
  byId("sync-progress-count").textContent = cancelling ? "" : `${job.completed || 0} / ${job.total || 0}`;
  const bar = byId("sync-progress-bar");
  bar.max = Math.max(1, job.total || 1);
  bar.value = Math.min(job.completed || 0, bar.max);
  byId("cancel-sync").disabled = !running || cancelling;
}

async function pollCourseSync(jobId = null, options = {}) {
  const announce = options.announce !== false;
  const refresh = options.refresh !== false;
  try {
    while (true) {
      const response = await fetch("/api/sync/status", { cache: "no-store" });
      const job = await response.json();
      if (!response.ok) throw new Error(job.error || "无法读取同步进度");
      if (jobId && job.job_id !== jobId) return null;
      renderSyncProgress(job);
      if (job.state === "running") {
        setOperationState(true, job.cancel_requested ? "正在取消" : job.detail || "正在运行课程同步工作流…");
        byId("cancel-sync").disabled = job.cancel_requested;
        await new Promise((resolve) => window.setTimeout(resolve, 700));
        continue;
      }
      if (job.state === "idle") return job;
      if (refresh) await loadInformation();
      const result = job.result || {};
      const pending = result.pending_review?.change_count || 0;
      const sourceFailures = Array.isArray(result.source_failures) ? result.source_failures.length : 0;
      const retryTasks = Array.isArray(result.retry_tasks) ? result.retry_tasks.length : 0;
      const message = job.state === "completed"
        ? result.retry_mode
          ? `精确重试完成。${retryTasks ? `仍有 ${retryTasks} 个失败项目。` : "全部失败项目已恢复。"}待 AI 整理 ${pending} 项。`
          : `同步完成：${result.succeeded_course_count || 0}/${result.discovered_course_count || 0} 门 Moodle 课程成功。${retryTasks ? `${retryTasks} 个项目需要重试。` : sourceFailures ? `${sourceFailures} 个来源需要重试。` : ""}待 AI 整理 ${pending} 项。`
        : job.state === "cancelled"
          ? `同步已取消；已完成 ${result.succeeded_course_count || 0} 门课程，已发布资料已保留。`
          : `同步失败：${job.error || "上一份有效资料已保留"}`;
      if (announce) setOperationState(false, message);
      return job;
    }
  } catch (error) {
    setOperationState(false);
    const alert = byId("global-error");
    alert.textContent = error.message;
    alert.classList.remove("hidden");
    return null;
  }
}

async function startWorkflow() {
  const confirmed = window.confirm(
    "将先打开共享浏览器供你完成一次 HKU Portal 登录并读取当前学期课程，再并发同步 Moodle、SIS Course Information 与官方课表。继续吗？",
  );
  if (!confirmed) return;
  const job = await runLocalMutation(
    "/api/sync/start",
    { confirmed: true },
    "正在启动课程同步工作流…",
  );
  if (!job) return;
  renderSyncProgress(job);
  await pollCourseSync(job.job_id);
}

async function addCourse(event) {
  event.preventDefault();
  const course = {
    course_id: byId("new-course-id").value.trim(),
    code: byId("new-course-code").value.trim(),
    title: byId("new-course-title").value.trim(),
    semester: byId("new-course-semester").value.trim() || null,
  };
  const result = await runLocalMutation(
    "/api/courses/add",
    { confirmed: true, course },
    `正在添加 ${course.code || course.course_id}…`,
  );
  if (!result) return;
  byId("add-course-form").reset();
  await loadInformation();
  renderCourseManager();
  setOperationState(false, `课程已添加：${course.code}。`);
}

async function deleteCourse(course) {
  const itemCount = state.data.items.filter((item) => item.course_id === course.course_id).length;
  const confirmed = window.confirm(
    `将删除“${course.code || course.title}”、${itemCount} 条关联事项与本地课程文件。文件会移入本机回收目录；再次同步 Moodle 可重新下载。继续吗？`,
  );
  if (!confirmed) return;
  const result = await runLocalMutation(
    "/api/courses/delete",
    { confirmed: true, confirmation: course.course_id, course_id: course.course_id },
    `正在删除 ${course.code || course.title}…`,
  );
  if (!result) return;
  state.managerSelectedCourseIds.delete(course.course_id);
  if (state.selectedOverviewCourseId === course.course_id) state.selectedOverviewCourseId = null;
  await loadInformation();
  renderCourseManager();
  if (state.view === "course" && !state.selectedOverviewCourseId) showHome();
  setOperationState(false, `课程已删除：${course.code || course.title}；同时移除 ${result.deleted_item_count} 条关联事项。`);
}

async function deleteSelectedCourses() {
  const selected = state.data.courses.filter((course) =>
    state.managerSelectedCourseIds.has(course.course_id)
  );
  if (!selected.length) return;
  const itemCount = state.data.items.filter((item) =>
    state.managerSelectedCourseIds.has(item.course_id)
  ).length;
  const labels = selected.map((course) => course.code || course.title).join("、");
  const confirmed = window.confirm(
    `将删除 ${selected.length} 门课程（${labels}）、${itemCount} 条关联事项与对应本地课程文件。文件会移入本机回收目录；再次同步 Moodle 可重新下载。继续吗？`,
  );
  if (!confirmed) return;
  const courseIds = selected.map((course) => course.course_id);
  const result = await runLocalMutation(
    "/api/courses/delete-many",
    { confirmed: true, confirmation: courseIds, course_ids: courseIds },
    `正在删除 ${selected.length} 门课程…`,
  );
  if (!result) return;
  if (state.selectedOverviewCourseId && state.managerSelectedCourseIds.has(state.selectedOverviewCourseId)) {
    state.selectedOverviewCourseId = null;
  }
  state.managerSelectedCourseIds.clear();
  await loadInformation();
  renderCourseManager();
  if (state.view === "course" && !state.selectedOverviewCourseId) showHome();
  setOperationState(false, `已删除 ${result.deleted_course_count} 门课程和 ${result.deleted_item_count} 条关联事项。`);
}

async function cancelCourseSync() {
  const result = await runLocalMutation(
    "/api/sync/cancel",
    { confirmed: true },
    "正在请求安全取消…",
  );
  if (result) {
    renderSyncProgress(result);
    setOperationState(true, "正在取消");
  }
}

byId("previous-month").addEventListener("click", () => {
  if (state.calendarMode === "day") {
    state.selectedDay = addDays(state.selectedDay, -1);
    state.currentMonth = new Date(state.selectedDay.getFullYear(), state.selectedDay.getMonth(), 1);
  } else if (state.calendarMode === "week") {
    state.selectedDay = addDays(state.selectedDay, -7);
    state.currentMonth = new Date(state.selectedDay.getFullYear(), state.selectedDay.getMonth(), 1);
  } else {
    state.currentMonth = new Date(state.currentMonth.getFullYear(), state.currentMonth.getMonth() - 1, 1);
  }
  renderDataViews();
});
byId("next-month").addEventListener("click", () => {
  if (state.calendarMode === "day") {
    state.selectedDay = addDays(state.selectedDay, 1);
    state.currentMonth = new Date(state.selectedDay.getFullYear(), state.selectedDay.getMonth(), 1);
  } else if (state.calendarMode === "week") {
    state.selectedDay = addDays(state.selectedDay, 7);
    state.currentMonth = new Date(state.selectedDay.getFullYear(), state.selectedDay.getMonth(), 1);
  } else {
    state.currentMonth = new Date(state.currentMonth.getFullYear(), state.currentMonth.getMonth() + 1, 1);
  }
  renderDataViews();
});
byId("today-button").addEventListener("click", () => {
  const today = new Date();
  state.selectedDay = today;
  state.currentMonth = new Date(today.getFullYear(), today.getMonth(), 1);
  renderDataViews();
});
byId("month-view-button").addEventListener("click", () => {
  state.calendarMode = "month";
  renderDataViews();
});
byId("week-view-button").addEventListener("click", () => {
  state.calendarMode = "week";
  state.currentMonth = new Date(state.selectedDay.getFullYear(), state.selectedDay.getMonth(), 1);
  renderDataViews();
});
byId("day-view-button").addEventListener("click", () => {
  state.calendarMode = "day";
  state.currentMonth = new Date(state.selectedDay.getFullYear(), state.selectedDay.getMonth(), 1);
  renderDataViews();
});
byId("search-input").addEventListener("input", (event) => {
  state.query = event.target.value.trim().toLocaleLowerCase();
  renderDataViews();
});
byId("home-search-input").addEventListener("input", (event) => {
  state.homeQuery = event.target.value;
  renderHomeSearch();
});
byId("select-all-courses").addEventListener("click", () => {
  state.selectedCourses = new Set(state.data.courses.map((course) => course.course_id));
  renderCourseFilters();
  renderDataViews();
});
byId("show-home").addEventListener("click", showHome);
byId("next-up-card").addEventListener("click", () => {
  const card = byId("next-up-card");
  const item = state.data?.items.find((value) => value.item_id === card.dataset.itemId);
  if (item) renderDetail(item, card.dataset.dateKey || null);
});
byId("show-calendar").addEventListener("click", showCalendar);
byId("show-reconciliation").addEventListener("click", showReconciliation);
byId("add-event-button").addEventListener("click", () => openEventEditor());
byId("reload-data").addEventListener("click", async () => {
  await loadInformation();
});
byId("app-update").addEventListener("click", applyApplicationUpdate);
byId("start-workflow").addEventListener("click", startWorkflow);
byId("retry-failures").addEventListener("click", retryFailures);
byId("copy-agent-prompt").addEventListener("click", copyAgentPrompt);
byId("cancel-sync").addEventListener("click", cancelCourseSync);
byId("run-ocr").addEventListener("click", processOcrQueue);
byId("close-preview").addEventListener("click", closeSourcePreview);
byId("source-preview").addEventListener("click", (event) => {
  if (event.target === byId("source-preview")) closeSourcePreview();
});
byId("close-item-detail").addEventListener("click", closeItemDetail);
byId("item-detail-dialog").addEventListener("click", (event) => {
  if (event.target === byId("item-detail-dialog")) closeItemDetail();
});
byId("item-detail-dialog").addEventListener("close", () => {
  if (!state.selectedItemId) return;
  state.selectedItemId = null;
  state.selectedDateKey = null;
  renderDataViews();
});
byId("close-event-editor").addEventListener("click", closeEventEditor);
byId("cancel-event-editor").addEventListener("click", closeEventEditor);
byId("event-all-day").addEventListener("change", setEventTimeFieldState);
byId("event-editor-form").addEventListener("submit", addCalendarEvent);
byId("event-editor-dialog").addEventListener("click", (event) => {
  if (event.target === byId("event-editor-dialog")) closeEventEditor();
});
byId("manage-courses").addEventListener("click", openCourseManager);
byId("close-course-manager").addEventListener("click", closeCourseManager);
byId("course-manager-dialog").addEventListener("click", (event) => {
  if (event.target === byId("course-manager-dialog")) closeCourseManager();
});
byId("add-course-form").addEventListener("submit", addCourse);
byId("course-manager-select-all").addEventListener("change", (event) => {
  state.managerSelectedCourseIds = event.target.checked
    ? new Set(state.data.courses.map((course) => course.course_id))
    : new Set();
  renderCourseManager();
});
byId("delete-selected-courses").addEventListener("click", deleteSelectedCourses);

loadInformation();
pollCourseSync();
checkApplicationUpdate();
