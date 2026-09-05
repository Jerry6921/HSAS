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

const materialTypeLabels = {
  lecture: "Lecture",
  tutorial: "Tutorial",
  notes: "Notes",
  exercises: "Exercises",
  reading: "Reading",
  assessment: "Assessment",
  course_information: "Course Information",
  announcement: "Announcements",
  other: "Other",
};

const materialTypeOrder = [
  "lecture",
  "tutorial",
  "notes",
  "exercises",
  "reading",
  "assessment",
  "course_information",
  "announcement",
  "other",
];

const state = {
  data: null,
  currentMonth: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
  selectedDay: new Date(),
  calendarMode: "month",
  selectedCourses: new Set(),
  selectedItemId: null,
  selectedDateKey: null,
  selectedOverviewCourseId: null,
  view: "home",
  query: "",
  homeQuery: "",
};

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
  const first = new Date(state.currentMonth.getFullYear(), state.currentMonth.getMonth(), 1);
  const start = addDays(first, -mondayIndex(first));
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

function buildOccurrences() {
  if (!state.data) return [];
  const { start, end } = visibleRange();
  const startKey = dateKey(start);
  const endKey = dateKey(end);
  const occurrences = [];

  for (const item of state.data.items.filter(itemMatches)) {
    if (item.recurrence) {
      const recurrence = item.recurrence;
      const excluded = new Set(recurrence.excluded_dates || []);
      const dates = new Set();
      let cursor = parseDateOnly(recurrence.valid_from > startKey ? recurrence.valid_from : startKey);
      const last = parseDateOnly(recurrence.valid_until < endKey ? recurrence.valid_until : endKey);
      while (cursor <= last) {
        const key = dateKey(cursor);
        if (recurrence.weekdays.includes(mondayIndex(cursor)) && !excluded.has(key)) dates.add(key);
        cursor = addDays(cursor, 1);
      }
      for (const key of recurrence.additional_dates || []) {
        if (key >= startKey && key <= endKey && !excluded.has(key)) dates.add(key);
      }
      for (const key of dates) occurrences.push({ item, key, time: occurrenceTime(item) });
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

function setView(view) {
  state.view = view;
  byId("home-view").classList.toggle("hidden", view !== "home");
  byId("calendar-view").classList.toggle("hidden", view !== "calendar");
  byId("course-overview-view").classList.toggle("hidden", view !== "course");
  byId("show-home").classList.toggle("active", view === "home");
  byId("show-calendar").classList.toggle("active", view === "calendar");
  byId("query-controls").classList.toggle("hidden", view === "home");
  renderCourseNavigation();
}

function showHome() {
  setView("home");
  byId("page-eyebrow").textContent = "APPLICATION";
  byId("page-title").textContent = "HIQS 首页";
  byId("data-caption").textContent = dataCaption();
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

function renderMaterialGroup(parent, title, subtitle, materials) {
  const section = element("section", "materials-group");
  const heading = element("div", "materials-heading");
  const headingCopy = element("div");
  headingCopy.append(element("h3", "", title), element("p", "", subtitle));
  heading.append(headingCopy, element("span", "material-count", `${materials.length} 项`));
  section.append(heading);
  if (!materials.length) {
    const list = element("div", "materials-list");
    list.append(element("p", "overview-empty", "当前 Moodle 快照中没有此类资料。"));
    section.append(list);
  }
  const grouped = new Map();
  for (const material of materials) {
    const type = material.material_type || "other";
    if (!grouped.has(type)) grouped.set(type, []);
    grouped.get(type).push(material);
  }
  for (const type of materialTypeOrder.filter((value) => grouped.has(value))) {
    const subgroup = element("section", "material-subgroup");
    const values = grouped.get(type);
    const subgroupHeading = element("div", "material-subgroup-heading");
    subgroupHeading.append(
      element("h4", "", materialTypeLabels[type] || type),
      element("span", "", `${values.length} 项`),
    );
    subgroup.append(subgroupHeading);
    const list = element("div", "materials-list");
    for (const material of values) renderMaterialCard(list, material);
    subgroup.append(list);
    section.append(subgroup);
  }
  parent.append(section);
}

function renderMaterialCard(list, material) {
    const hasLocal = Boolean(material.relative_path && material.exists);
    const remoteUrl = safeHttpUrl(material.source_url);
    const canOpen = Boolean(hasLocal || remoteUrl);
    const card = element(hasLocal ? "button" : remoteUrl ? "a" : "article", "material-card");
    if (hasLocal) {
      card.type = "button";
      card.addEventListener("click", () => openSourcePreview(material));
    } else if (remoteUrl) {
      card.href = remoteUrl;
      card.target = "_self";
    }
    const icon = element("span", "material-icon", material.relative_path ? "FILE" : "LINK");
    const copy = element("div", "material-copy");
    const titleLine = element("div", "material-title-line");
    titleLine.append(
      element("strong", "", material.title),
      element("span", "material-type-badge", materialTypeLabels[material.material_type] || "Other"),
    );
    if (material.change_action) {
      const labels = { baseline: "首次待整理", added: "新增", modified: "已更新", removed: "已删除" };
      titleLine.append(element("span", "update-badge", labels[material.change_action] || "有变化"));
    }
    const meta = [
      material.section_title,
      material.activity_name !== material.title ? material.activity_name : null,
      formatBytes(material.size_bytes),
      material.text_available ? "已有文本副本" : null,
    ].filter(Boolean).join(" · ");
    copy.append(titleLine, element("small", "", meta || categoryLabels[material.category] || material.category));
    if (material.download_error) copy.append(element("small", "material-error", material.download_error));
    card.append(icon, copy, element("span", "material-open", canOpen ? "预览" : "—"));
    list.append(card);
}

function safeHttpUrl(value) {
  return typeof value === "string" && /^https?:\/\//i.test(value) ? value : null;
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
    link.target = "_self";
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

  const materials = element("section", "course-materials-card");
  const materialHeading = element("div", "course-materials-title");
  materialHeading.append(element("div", "", null));
  materialHeading.firstChild.append(element("p", "eyebrow", "MOODLE ARCHIVE"), element("h2", "", "全部课件"));
  const counts = course.moodle
    ? `${course.moodle.downloaded_file_count} 个本地文件 · ${course.moodle.activity_count} 个 Moodle 项目`
    : "尚未同步 Moodle 快照";
  materialHeading.append(element("span", "archive-summary", counts));
  materials.append(materialHeading);
  renderMaterialGroup(materials, "课程学习材料", "Lecture slides、notes、readings 与其他学习内容", course.materials?.learning || []);
  renderMaterialGroup(materials, "课程信息", "Introduction、assessment、课程安排与公告", course.materials?.information || []);
  container.append(materials);
}

function renderMetrics(occurrences) {
  const filteredItems = state.data.items.filter(itemMatches);
  const monthPrefix = dateKey(state.currentMonth).slice(0, 7);
  byId("metric-courses").textContent = state.selectedCourses.size;
  byId("metric-items").textContent = filteredItems.length;
  byId("metric-month").textContent = occurrences.filter((value) => value.key.startsWith(monthPrefix)).length;
  byId("metric-unknown").textContent = filteredItems.filter((item) => item.date_status === "unknown").length;
  byId("metric-pending").textContent = state.data.pending_review?.change_count || 0;
}

function renderCalendar(occurrences) {
  const grid = byId("calendar-grid");
  grid.replaceChildren();
  const isMonth = state.calendarMode === "month";
  byId("weekday-row").classList.toggle("hidden", !isMonth);
  grid.classList.toggle("hidden", !isMonth);
  byId("daily-agenda").classList.toggle("hidden", isMonth);
  byId("month-view-button").classList.toggle("active", isMonth);
  byId("day-view-button").classList.toggle("active", !isMonth);
  byId("calendar-title").textContent = isMonth ? "课程日历" : "每日议程";
  const label = new Intl.DateTimeFormat("zh-HK", { year: "numeric", month: "long" }).format(state.currentMonth);
  byId("calendar-label").textContent = isMonth
    ? label
    : new Intl.DateTimeFormat("zh-HK", { year: "numeric", month: "long", day: "numeric", weekday: "short" }).format(state.selectedDay);
  if (!isMonth) {
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
    for (const occurrence of values.slice(0, 4)) {
      const course = courseFor(occurrence.item);
      const chip = element("button", "event-chip");
      chip.type = "button";
      chip.style.setProperty("--course-color", course.color);
      if (occurrence.item.date_status !== "confirmed") chip.classList.add("tentative");
      if (state.selectedItemId === occurrence.item.item_id && state.selectedDateKey === key) chip.classList.add("selected");
      if (occurrence.time) chip.append(element("time", "", occurrence.time));
      chip.append(document.createTextNode(occurrence.item.title));
      chip.title = `${course.code} · ${occurrence.item.title}`;
      chip.addEventListener("click", () => {
        state.selectedItemId = occurrence.item.item_id;
        state.selectedDateKey = key;
        renderDetail(occurrence.item, key);
        renderCalendar(occurrences);
      });
      list.append(chip);
    }
    if (values.length > 4) list.append(element("span", "more-count", `另有 ${values.length - 4} 项`));
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
  for (let hour = 0; hour < 24; hour += 1) {
    const row = element("div", "agenda-hour");
    row.append(element("time", "agenda-hour-label", `${String(hour).padStart(2, "0")}:00`));
    timeline.append(row);
  }
  const eventLayer = element("div", "agenda-events-layer");
  for (const occurrence of timed) {
    const startMinutes = timeMinutes(occurrence.time);
    const endValue = occurrenceEndTime(occurrence.item);
    const endMinutes = endValue ? timeMinutes(endValue) : startMinutes + 50;
    const duration = Math.max(30, endMinutes > startMinutes ? endMinutes - startMinutes : 50);
    const event = buildAgendaEvent(occurrence, key, values, false);
    event.style.setProperty("--event-top", `${startMinutes / 60 * 58}px`);
    event.style.setProperty("--event-height", `${Math.max(36, duration / 60 * 58)}px`);
    eventLayer.append(event);
  }
  timeline.append(eventLayer);

  const now = new Date();
  if (dateKey(now) === key) {
    const marker = element("div", "agenda-now-line");
    marker.style.setProperty("--now-top", `${(now.getHours() * 60 + now.getMinutes()) / 60 * 58}px`);
    timeline.append(marker);
  }
  scroll.append(timeline);
  container.append(scroll);
  const earliest = timed.length ? Math.min(...timed.map((occurrence) => timeMinutes(occurrence.time))) : 8 * 60;
  scroll.scrollTop = Math.max(0, earliest / 60 * 58 - 58);
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
    if (state.selectedItemId === item.item_id && state.selectedDateKey === key) button.classList.add("selected");
    const start = occurrence.time || (item.all_day ? "全天" : "待定");
    const end = occurrenceEndTime(item);
    const copy = element("span", "agenda-copy");
    copy.append(
      element("strong", "", item.title),
      element("small", "", [course.code, categoryLabels[item.category] || item.category, item.location].filter(Boolean).join(" · ")),
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
    button.target = "_self";
  } else {
    button.type = "button";
    button.disabled = true;
  }
  if (source.relative_path) button.append(element("small", "", source.relative_path));
  return button;
}

function renderDetail(item, occurrenceKey = null) {
  const panel = byId("detail-panel");
  const course = courseFor(item);
  panel.replaceChildren();
  panel.style.setProperty("--course-color", course.color);
  panel.append(element("div", "detail-course", `${course.code} · ${categoryLabels[item.category] || item.category}`));
  panel.append(element("h2", "", item.title));

  const pills = element("div", "detail-pills");
  pills.append(element("span", "pill", item.date_status === "confirmed" ? "日期已确认" : item.date_status === "tentative" ? "日期待核实" : "日期未知"));
  if (item.weight_percent !== null && item.weight_percent !== undefined) pills.append(element("span", "pill", `占分 ${item.weight_percent}%`));
  if (item.warnings && item.warnings.length) pills.append(element("span", "pill warning", `${item.warnings.length} 项提醒`));
  panel.append(pills);
  if (item.description) panel.append(element("p", "detail-description", item.description));

  const facts = element("dl", "detail-facts");
  if (item.recurrence) {
    appendFact(facts, "本次日期", occurrenceKey || "每周重复");
    appendFact(facts, "时间", `${item.recurrence.start_time.slice(0, 5)}–${item.recurrence.end_time.slice(0, 5)}`);
    appendFact(facts, "有效日期", `${item.recurrence.valid_from} 至 ${item.recurrence.valid_until}`);
  } else {
    appendFact(facts, "开放", formatDateTime(item.opens_at));
    appendFact(facts, "开始", formatDateTime(item.starts_at));
    appendFact(facts, "结束", formatDateTime(item.ends_at));
    appendFact(facts, "DDL", formatDateTime(item.due_at) || item.due_on);
    appendFact(facts, "安排日期", item.scheduled_on);
  }
  appendFact(facts, "地点", item.location);
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
      card.prepend(element("span", "material-type-badge", materialTypeLabels[material.material_type] || "Other"));
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
        node.target = "_self";
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
    const copy = element("span");
    copy.append(element("strong", "", item.title), element("small", "", `${course.code} · ${categoryLabels[item.category] || item.category}`));
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
    for (const material of [...(course.materials?.learning || []), ...(course.materials?.information || [])]) {
      records.push({
        kind: "material",
        title: material.title,
        subtitle: `${course.code || course.title} · ${materialTypeLabels[material.material_type] || material.material_type}`,
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
        if (!record.value.relative_path && remoteUrl) window.location.assign(remoteUrl);
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
  renderMetrics(occurrences);
  renderCalendar(occurrences);
  renderUnscheduled();
  renderUpdates();
  renderHomeSearch();
  if (state.selectedItemId) {
    const selected = state.data.items.find((item) => item.item_id === state.selectedItemId && itemMatches(item));
    if (selected) renderDetail(selected, state.selectedDateKey);
  }
  if (state.view === "course") renderCourseOverview();
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

function setOperationState(running, message = "") {
  const loginButton = byId("login-moodle");
  const syncButton = byId("sync-courses");
  const reloadButton = byId("reload-data");
  loginButton.disabled = running;
  syncButton.disabled = running;
  reloadButton.disabled = running;
  const status = byId("operation-status");
  if (message) {
    status.textContent = message;
    status.classList.remove("hidden");
  } else {
    status.classList.add("hidden");
  }
}

async function runMoodleOperation(path, pendingMessage) {
  byId("global-error").classList.add("hidden");
  setOperationState(true, pendingMessage);
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-HIQS-Request": "1",
      },
      body: JSON.stringify({ confirmed: true }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "操作失败");
    return payload;
  } catch (error) {
    setOperationState(false);
    const alert = byId("global-error");
    alert.textContent = error.message;
    alert.classList.remove("hidden");
    return null;
  }
}

async function loginMoodle() {
  const confirmed = window.confirm(
    "将打开一个 Moodle 登录窗口。请只在该窗口中输入账号并亲自完成 SSO/MFA。继续吗？",
  );
  if (!confirmed) return;
  const result = await runMoodleOperation(
    "/api/moodle/login",
    "等待你在新窗口完成 Moodle 登录…",
  );
  if (!result) return;
  setOperationState(
    false,
    `Moodle 登录成功，可访问 ${result.available_course_count} 门课程。`,
  );
}

async function synchronizeCourses() {
  const confirmed = window.confirm(
    "将同步全部可访问课程，并下载课程文件到本机。同步不会自动改写日历信息库。继续吗？",
  );
  if (!confirmed) return;
  const result = await runMoodleOperation(
    "/api/sync",
    "正在同步 Moodle 课程与文件，请保持此页面打开…",
  );
  if (!result) return;
  const failure = result.failed_course_count
    ? `，${result.failed_course_count} 门失败`
    : "";
  await loadInformation();
  const pending = result.pending_review?.change_count || 0;
  setOperationState(
    false,
    `同步完成：${result.succeeded_course_count}/${result.discovered_course_count} 门成功${failure}。待 AI 整理 ${pending} 项。`,
  );
}

byId("previous-month").addEventListener("click", () => {
  if (state.calendarMode === "day") {
    state.selectedDay = addDays(state.selectedDay, -1);
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
  } else {
    state.currentMonth = new Date(state.currentMonth.getFullYear(), state.currentMonth.getMonth() + 1, 1);
  }
  renderDataViews();
});
byId("today-button").addEventListener("click", () => {
  const now = new Date();
  state.selectedDay = now;
  state.currentMonth = new Date(now.getFullYear(), now.getMonth(), 1);
  renderDataViews();
});
byId("month-view-button").addEventListener("click", () => {
  state.calendarMode = "month";
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
byId("show-calendar").addEventListener("click", showCalendar);
byId("reload-data").addEventListener("click", loadInformation);
byId("login-moodle").addEventListener("click", loginMoodle);
byId("sync-courses").addEventListener("click", synchronizeCourses);
byId("close-preview").addEventListener("click", closeSourcePreview);
byId("source-preview").addEventListener("click", (event) => {
  if (event.target === byId("source-preview")) closeSourcePreview();
});

loadInformation();
