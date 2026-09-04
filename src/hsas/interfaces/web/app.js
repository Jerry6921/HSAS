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
  selectedCourses: new Set(),
  selectedItemId: null,
  selectedDateKey: null,
  selectedOverviewCourseId: null,
  view: "calendar",
  query: "",
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

function showCalendar() {
  state.view = "calendar";
  byId("calendar-view").classList.remove("hidden");
  byId("course-overview-view").classList.add("hidden");
  byId("show-calendar").classList.add("active");
  byId("page-eyebrow").textContent = "CALENDAR";
  byId("page-title").textContent = "课程信息，一眼查清";
  byId("data-caption").textContent = dataCaption();
  renderCourseNavigation();
}

function showCourseOverview(courseId) {
  state.view = "course";
  state.selectedOverviewCourseId = courseId;
  byId("calendar-view").classList.add("hidden");
  byId("course-overview-view").classList.remove("hidden");
  byId("show-calendar").classList.remove("active");
  renderCourseNavigation();
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
    const localUrl = material.relative_path && material.exists
      ? `/api/material?path=${encodeURIComponent(material.relative_path)}`
      : null;
    const remoteUrl = material.source_url && /^https?:\/\//i.test(material.source_url)
      ? material.source_url
      : null;
    const card = element(localUrl || remoteUrl ? "a" : "article", "material-card");
    if (localUrl || remoteUrl) {
      card.href = localUrl || remoteUrl;
      card.target = "_blank";
      card.rel = "noreferrer";
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
    card.append(icon, copy, element("span", "material-open", localUrl || remoteUrl ? "↗" : "—"));
    list.append(card);
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
  const facts = [course.semester, ...(course.instructors || [])].filter(Boolean).join(" · ");
  heroCopy.append(element("p", "", facts || "课程身份已建立，其他资料待 AI 整理。"));
  hero.append(heroCopy);
  if (course.moodle && /^https?:\/\//i.test(course.moodle.url)) {
    const link = element("a", "button", "打开 Moodle");
    link.href = course.moodle.url;
    link.target = "_blank";
    link.rel = "noreferrer";
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
  const label = new Intl.DateTimeFormat("zh-HK", { year: "numeric", month: "long" }).format(state.currentMonth);
  byId("calendar-label").textContent = label;
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
    cell.append(element("span", "day-number", day.getDate()));
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

  if (item.links && item.links.length) {
    const block = element("section", "detail-block");
    block.append(element("h3", "", "相关链接"));
    for (const link of item.links) {
      const safe = /^https?:\/\//i.test(link.url);
      const node = element(safe ? "a" : "div", "source-card", link.label);
      if (safe) {
        node.href = link.url;
        node.target = "_blank";
        node.rel = "noreferrer";
      }
      block.append(node);
    }
    panel.append(block);
  }

  if (item.sources && item.sources.length) {
    const block = element("section", "detail-block");
    block.append(element("h3", "", "证据来源"));
    for (const source of item.sources) {
      const pages = source.page_numbers && source.page_numbers.length ? ` · 第 ${source.page_numbers.join("、")} 页` : "";
      const note = source.note ? ` · ${source.note}` : "";
      const caption = `${source.title}${pages}${note}`;
      const safe = source.url && /^https?:\/\//i.test(source.url);
      const node = element(safe ? "a" : "div", "source-card", caption);
      if (safe) {
        node.href = source.url;
        node.target = "_blank";
        node.rel = "noreferrer";
      } else if (source.relative_path) {
        node.append(element("small", "", ` · ${source.relative_path}`));
      }
      block.append(node);
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

function renderDataViews() {
  const occurrences = buildOccurrences();
  renderMetrics(occurrences);
  renderCalendar(occurrences);
  renderUnscheduled();
  if (state.selectedItemId) {
    const selected = state.data.items.find((item) => item.item_id === state.selectedItemId && itemMatches(item));
    if (selected) renderDetail(selected, state.selectedDateKey);
  }
  if (state.view === "course") renderCourseOverview();
}

async function loadInformation() {
  byId("global-error").classList.add("hidden");
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
  loginButton.disabled = running;
  syncButton.disabled = running;
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
  state.currentMonth = new Date(state.currentMonth.getFullYear(), state.currentMonth.getMonth() - 1, 1);
  renderDataViews();
});
byId("next-month").addEventListener("click", () => {
  state.currentMonth = new Date(state.currentMonth.getFullYear(), state.currentMonth.getMonth() + 1, 1);
  renderDataViews();
});
byId("today-button").addEventListener("click", () => {
  const now = new Date();
  state.currentMonth = new Date(now.getFullYear(), now.getMonth(), 1);
  renderDataViews();
});
byId("search-input").addEventListener("input", (event) => {
  state.query = event.target.value.trim().toLocaleLowerCase();
  renderDataViews();
});
byId("select-all-courses").addEventListener("click", () => {
  state.selectedCourses = new Set(state.data.courses.map((course) => course.course_id));
  renderCourseFilters();
  renderDataViews();
});
byId("show-calendar").addEventListener("click", showCalendar);
byId("reload-data").addEventListener("click", loadInformation);
byId("login-moodle").addEventListener("click", loginMoodle);
byId("sync-courses").addEventListener("click", synchronizeCourses);

loadInformation();
