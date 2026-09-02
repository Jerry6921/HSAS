(() => {
  "use strict";

  const state = {
    snapshot: null,
    selectedItemId: null,
    recordId: null,
    courseInformation: null,
    courseInfoTab: "overview",
    courseColors: new Map(),
    taskFilters: { courseIds: null, knownCourseIds: null, dateFrom: "", dateTo: "", includeUnconfirmed: true, includeMissing: true },
  };
  const byId = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const priorityLabels = {
    critical: "最高",
    high: "较高",
    medium: "中等",
    planned: "计划中",
  };
  const courseStateLabels = {
    current: "已同步",
    failed: "上次失败",
    unknown: "状态未知",
    invalid: "归档无效",
  };

  function formatMinutes(value) {
    if (value === null || value === undefined) return "未估算";
    const minutes = Number(value);
    if (minutes < 60) return `${minutes} 分钟`;
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    return rest ? `${hours} 小时 ${rest} 分` : `${hours} 小时`;
  }

  function formatDateTime(value) {
    if (!value) return "时间未知";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("zh-HK", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    }).format(date);
  }

  function formatDue(value, confirmed) {
    if (!value) return "未公布日期";
    const date = new Date(value.length === 10 ? `${value}T00:00:00` : value);
    const formatted = Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-HK", {
      month: "short", day: "numeric", hour: value.length === 10 ? undefined : "2-digit", minute: value.length === 10 ? undefined : "2-digit",
    }).format(date);
    return `${confirmed ? "官方日期" : "日期待确认"} · ${formatted}`;
  }

  function courseCode(item) {
    const match = String(item.course_title || "").match(/[A-Z]{2,8}\d{3,5}/i);
    return match ? match[0].toUpperCase() : String(item.course_id || "未知课程");
  }

  function courseHue(courseId) {
    let hash = 0;
    for (const character of String(courseId)) hash = ((hash << 5) - hash + character.charCodeAt(0)) | 0;
    return Math.abs(hash) % 360;
  }

  function assignCourseColors(items) {
    const used = new Set(state.courseColors.values());
    [...new Set(items.map((item) => item.course_id))].sort().forEach((courseId) => {
      if (state.courseColors.has(courseId)) return;
      let slot = courseHue(courseId) % 16;
      for (let offset = 0; offset < 16 && used.has(slot); offset += 1) slot = (slot + 1) % 16;
      state.courseColors.set(courseId, slot);
      used.add(slot);
    });
  }

  function courseColorClass(courseId) {
    return `course-color-${state.courseColors.get(courseId) ?? courseHue(courseId) % 16}`;
  }

  function shortDate(value) {
    if (!value) return null;
    const date = new Date(value.length === 10 ? `${value}T00:00:00` : value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("zh-HK", { month: "short", day: "numeric" }).format(date);
  }

  function dateKey(value) {
    return value ? String(value).slice(0, 10) : null;
  }

  async function request(path, options = {}) {
    const response = await fetch(path, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
    return data;
  }

  function setBusy(button, busy, text) {
    if (!button.dataset.originalText) button.dataset.originalText = button.textContent;
    button.disabled = busy;
    button.textContent = busy ? text : button.dataset.originalText;
  }

  function showToast(message) {
    const toast = byId("toast");
    toast.textContent = message;
    toast.classList.remove("hidden");
    window.setTimeout(() => toast.classList.add("hidden"), 2600);
  }

  function showError(message) {
    const error = byId("global-error");
    error.textContent = message;
    error.classList.toggle("hidden", !message);
  }

  async function loadDashboard() {
    byId("loading").classList.remove("hidden");
    showError("");
    try {
      state.snapshot = await request("/api/dashboard");
      renderDashboard();
      document.querySelectorAll(".page").forEach((page) => page.classList.add("hidden"));
      byId("page-today").classList.remove("hidden");
    } catch (error) {
      showError(error.message);
    } finally {
      byId("loading").classList.add("hidden");
    }
  }

  function renderMoodleSession(result) {
    const label = byId("moodle-session-state");
    const syncButton = byId("open-sync");
    label.className = "session-state";
    if (result.status === "logged_in") {
      label.classList.add("logged-in");
      label.textContent = `Moodle：已登录 · ${result.available_course_count} 门课`;
      byId("open-moodle-login").classList.add("hidden");
      syncButton.disabled = false;
      syncButton.textContent = "同步全部课程";
    } else if (result.status === "logged_out") {
      label.classList.add("logged-out");
      label.textContent = "Moodle：未登录";
      byId("open-moodle-login").classList.remove("hidden");
      syncButton.disabled = true;
      syncButton.textContent = "请先登录 Moodle";
    } else {
      label.classList.add("unknown");
      label.textContent = "Moodle：状态检查失败";
      byId("open-moodle-login").classList.remove("hidden");
      syncButton.disabled = true;
      syncButton.textContent = "登录状态未确认";
    }
    label.dataset.error = result.error || "";
  }

  async function checkMoodleSession(showFailure = true) {
    const button = byId("check-moodle-session");
    setBusy(button, true, "检查中…");
    try {
      const result = await request("/api/moodle/session", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-HSAS-Request": "1" },
        body: "{}",
      });
      renderMoodleSession(result);
      if (showFailure && result.error) showToast(result.error);
    } catch (error) {
      renderMoodleSession({ status: "unknown", available_course_count: 0, error: error.message });
      if (showFailure) showToast(`登录状态检查失败：${error.message}`);
    } finally {
      setBusy(button, false);
    }
  }

  function renderDashboard() {
    const data = state.snapshot;
    assignCourseColors(data.items);
    byId("metric-urgent").textContent = data.summary.urgent_item_count;
    byId("metric-effort").textContent = formatMinutes(data.summary.remaining_minutes);
    byId("metric-status").textContent = data.summary.status === "current" ? "最新" : data.summary.status === "stale" ? "需更新" : "不可用";
    byId("metric-updated").textContent = data.summary.updated_at ? `${formatDateTime(data.summary.updated_at)} 更新` : "尚无有效计划";
    byId("plan-caption").textContent = data.summary.key_item_count
      ? `当前计划包含 ${data.summary.key_item_count} 个关键事项；学习时段仍由你决定。`
      : "同步课程并生成计划后，这里会显示优先事项。";

    const warningBox = byId("plan-warnings");
    const warnings = data.warnings || [];
    warningBox.innerHTML = warnings.length ? `<ul>${warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")}</ul>` : "";
    warningBox.classList.toggle("hidden", warnings.length === 0);

    if (!state.selectedItemId || !data.items.some((item) => item.plan_item_id === state.selectedItemId)) {
      state.selectedItemId = data.items[0]?.plan_item_id || null;
    }
    renderTaskList();
    renderTaskDetail();
    renderCourses();
    renderTaskFilters();
  }

  function filteredTasks() {
    if (!state.snapshot) return [];
    const filters = state.taskFilters;
    return state.snapshot.items.filter((item) => {
      if (filters.courseIds && !filters.courseIds.has(item.course_id)) return false;
      const date = dateKey(item.due);
      if (!date) return filters.includeMissing;
      if (!item.due_confirmed && !filters.includeUnconfirmed) return false;
      if (filters.dateFrom && date < filters.dateFrom) return false;
      if (filters.dateTo && date > filters.dateTo) return false;
      return true;
    });
  }

  function renderTaskFilters() {
    const courses = [...new Map(state.snapshot.items.map((item) => [item.course_id, item])).values()];
    const availableIds = new Set(courses.map((item) => item.course_id));
    if (state.taskFilters.courseIds === null) {
      state.taskFilters.courseIds = new Set(availableIds);
    } else {
      availableIds.forEach((id) => {
        if (!state.taskFilters.knownCourseIds?.has(id)) state.taskFilters.courseIds.add(id);
      });
    }
    state.taskFilters.courseIds = new Set([...state.taskFilters.courseIds].filter((id) => availableIds.has(id)));
    state.taskFilters.knownCourseIds = availableIds;
    const options = byId("course-filter-options");
    options.innerHTML = courses.map((item) => `
      <label class="course-filter-chip ${courseColorClass(item.course_id)}">
        <input type="checkbox" data-filter-course="${escapeHtml(item.course_id)}" ${state.taskFilters.courseIds.has(item.course_id) ? "checked" : ""}>
        <span>${escapeHtml(courseCode(item))}</span>
      </label>
    `).join("") || '<span class="muted-text">暂无课程</span>';
    byId("filter-date-from").value = state.taskFilters.dateFrom;
    byId("filter-date-to").value = state.taskFilters.dateTo;
    byId("filter-date-unconfirmed").checked = state.taskFilters.includeUnconfirmed;
    byId("filter-date-missing").checked = state.taskFilters.includeMissing;
    options.querySelectorAll("[data-filter-course]").forEach((input) => input.addEventListener("change", () => {
      if (input.checked) state.taskFilters.courseIds.add(input.dataset.filterCourse);
      else state.taskFilters.courseIds.delete(input.dataset.filterCourse);
      applyTaskFilters();
    }));
    updateFilterSummary();
  }

  function applyTaskFilters() {
    const visible = filteredTasks();
    if (!visible.some((item) => item.plan_item_id === state.selectedItemId)) {
      state.selectedItemId = visible[0]?.plan_item_id || null;
    }
    renderTaskList();
    renderTaskDetail();
    updateFilterSummary();
  }

  function updateFilterSummary() {
    const count = filteredTasks().length;
    byId("task-filter-summary").textContent = `显示 ${count} / ${state.snapshot.items.length} 项`;
  }

  function renderTaskList() {
    const list = byId("task-list");
    const items = filteredTasks();
    if (!items.length) {
      list.innerHTML = '<div class="empty-state">没有符合当前筛选条件的关键事项。</div>';
      return;
    }
    list.innerHTML = items.map((item, index) => `
      <button type="button" class="task-row ${item.plan_item_id === state.selectedItemId ? "selected" : ""}" data-task-index="${index}" role="option" aria-selected="${item.plan_item_id === state.selectedItemId}">
        <span class="task-title-line"><span class="tagged-title"><span class="course-chip ${courseColorClass(item.course_id)}">${escapeHtml(courseCode(item))}</span><span class="date-chip ${item.due ? (item.due_confirmed ? "" : "unconfirmed") : "missing"}">${escapeHtml(item.due ? shortDate(item.due) : "日期未公布")}${item.due && !item.due_confirmed ? " · 未确认" : ""}</span><strong>${escapeHtml(item.title)}</strong></span><span class="priority-label priority-${item.priority}">${priorityLabels[item.priority]}</span></span>
        <span class="task-meta"><span>${escapeHtml(item.course_title)}</span><span>${formatMinutes(item.remaining_minutes)}剩余</span><span>${escapeHtml(formatDue(item.due, item.due_confirmed))}</span></span>
        <span class="progress-head"><span>已完成 ${formatMinutes(item.completed_minutes)}</span><span>${item.progress_percent}%</span></span>
        <span class="progress-track" role="progressbar" aria-valuenow="${item.progress_percent}" aria-valuemin="0" aria-valuemax="100"><span class="progress-bar" style="width:${item.progress_percent}%"></span></span>
      </button>
    `).join("");
    list.querySelectorAll("[data-task-index]").forEach((button) => button.addEventListener("click", () => {
      state.selectedItemId = items[Number(button.dataset.taskIndex)].plan_item_id;
      renderTaskList();
      renderTaskDetail();
    }));
  }

  function renderTaskDetail() {
    const panel = byId("task-detail");
    const item = state.snapshot.items.find((candidate) => candidate.plan_item_id === state.selectedItemId);
    if (!item) {
      panel.innerHTML = '<div class="empty-state">选择一个事项查看详情。</div>';
      return;
    }
    const reasons = item.reasons.length ? item.reasons : ["Planner 未提供额外说明。"];
    const criteria = item.completion_criteria.length ? item.completion_criteria : ["尚未定义完成标准。"];
    const sources = item.source_references.length
      ? item.source_references.map((source) => {
          const pages = source.page_numbers.length ? ` · 第 ${source.page_numbers.join("、")} 页` : "";
          const path = source.relative_path ? `<code>${escapeHtml(source.relative_path)}</code>` : escapeHtml(source.source_type);
          return `<li>${path}${escapeHtml(pages)}${source.note ? ` · ${escapeHtml(source.note)}` : ""}</li>`;
        }).join("")
      : "<li>当前事项未附本地课件引用。</li>";
    panel.innerHTML = `
      <span class="course-tag">${escapeHtml(item.course_title)}</span>
      <h2>${escapeHtml(item.title)}</h2>
      <p class="detail-description">${escapeHtml(item.description || item.priority_rationale)}</p>
      <div class="detail-block"><h3>为什么现在做</h3><ul>${reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul></div>
      <div class="detail-block"><h3>怎样算完成</h3><ul>${criteria.map((criterion) => `<li>${escapeHtml(criterion)}</li>`).join("")}</ul></div>
      <details class="detail-block"><summary>课件与课程依据（${item.source_references.length}）</summary><ul class="source-list">${sources}</ul></details>
      ${item.warnings.length ? `<div class="notice warning"><ul>${item.warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")}</ul></div>` : ""}
      <div class="detail-actions"><button type="button" id="record-progress" class="button primary">记录进度</button></div>
    `;
    byId("record-progress").addEventListener("click", openExecutionDialog);
  }

  function renderCourses() {
    const list = byId("course-list");
    if (!state.snapshot.courses.length) {
      list.innerHTML = '<div class="empty-state">尚无本地课程归档。可以先登录 Moodle，再同步课程。</div>';
      return;
    }
    list.innerHTML = state.snapshot.courses.map((course) => `
      <article class="course-row">
        <div><h2>${escapeHtml(course.title)}</h2><p>${escapeHtml(course.course_id)} · ${course.activity_count} 个活动 · ${course.file_count} 份文件 · ${formatDateTime(course.collected_at)}${course.change_count ? ` · ${course.change_count} 项变更` : ""}</p>${course.error ? `<p class="priority-critical">${escapeHtml(course.error)}</p>` : ""}</div>
        <div class="course-actions"><span class="course-state ${course.sync_status}">${courseStateLabels[course.sync_status]}</span><button type="button" class="button" data-course-info="${escapeHtml(course.course_id)}">课程信息</button><button type="button" class="button" data-course-materials="${escapeHtml(course.course_id)}">查看课件</button></div>
      </article>
    `).join("");
    list.querySelectorAll("[data-course-info]").forEach((button) => button.addEventListener("click", () => {
      openCourseInformation(button.dataset.courseInfo);
    }));
    list.querySelectorAll("[data-course-materials]").forEach((button) => button.addEventListener("click", () => {
      openCourseMaterials(button.dataset.courseMaterials);
    }));
  }

  function displayValue(value, suffix = "") {
    return value === null || value === undefined || value === "" ? "未提供" : `${value}${suffix}`;
  }

  function infoMetric(label, value, note = "") {
    return `<article><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>${note ? `<small>${escapeHtml(note)}</small>` : ""}</article>`;
  }

  function infoRows(rows) {
    return `<dl class="info-kv">${rows.map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>`;
  }

  function allCourseActivities(archive) {
    return [
      ...(archive.sections || []).flatMap((section) => (section.activities || []).map((activity) => ({ section, activity }))),
      ...(archive.unassigned_activities || []).map((activity) => ({ section: null, activity })),
    ];
  }

  function renderInfoOverview(archive) {
    const stats = archive.stats || {};
    const course = archive.course || {};
    const assessments = archive.assessments || {};
    const types = Object.entries(stats.activity_types || {});
    return `
      <div class="info-stat-grid">
        ${infoMetric("Sections", displayValue(stats.section_count))}
        ${infoMetric("Activities", displayValue(stats.activity_count))}
        ${infoMetric("已下载文件", displayValue(stats.downloaded_file_count), stats.downloaded_bytes === null || stats.downloaded_bytes === undefined ? "大小未提供" : formatBytes(stats.downloaded_bytes))}
        ${infoMetric("已分析 PDF", displayValue(stats.analyzed_pdf_count), stats.pdf_word_count === null || stats.pdf_word_count === undefined ? "字数未提供" : `${stats.pdf_word_count} 词`)}
      </div>
      <div class="info-grid">
        <section class="info-panel"><h2>课程与归档</h2>${infoRows([
          ["课程 ID", displayValue(course.course_id)],
          ["Schema", displayValue(archive.schema_version)],
          ["来源", displayValue(archive.source)],
          ["采集时间", formatDateTime(archive.collected_at)],
          ["Moodle 声明 Sections", displayValue(course.declared_section_count)],
          ["实际返回 Sections", displayValue(course.returned_section_count)],
          ["最大上传大小", course.max_upload_bytes === null || course.max_upload_bytes === undefined ? "未提供" : formatBytes(course.max_upload_bytes)],
          ["原始状态路径", displayValue(archive.raw_state_path)],
        ])}${course.url ? `<a class="text-link" href="${escapeHtml(course.url)}" target="_blank" rel="noreferrer">在 Moodle 打开课程</a>` : ""}</section>
        <section class="info-panel"><h2>活动类型</h2>${types.length ? `<div class="type-counts">${types.map(([type, count]) => `<span><strong>${escapeHtml(count)}</strong>${escapeHtml(type)}</span>`).join("")}</div>` : '<p class="muted-text">未提供活动类型统计。</p>'}<h2 class="subheading">Assessment 摘要</h2>${infoRows([
          ["评分构成", displayValue(assessments.grading_basis)],
          ["普通权重合计", assessments.total_weight_percent === null || assessments.total_weight_percent === undefined ? "未知" : `${assessments.total_weight_percent}%`],
          ["Assessment 项目", String((assessments.items || []).length)],
          ["分组", String((assessments.groups || []).length)],
        ])}</section>
      </div>`;
  }

  function renderAssessmentSources(sources) {
    if (!sources?.length) return '<li>未提供来源。</li>';
    return sources.map((source) => {
      const pages = source.page_numbers?.length ? ` · 第 ${source.page_numbers.join("、")} 页` : "";
      const location = source.relative_path || source.section_id || source.activity_id || "未提供位置";
      return `<li><strong>${escapeHtml(source.source_type)}</strong> · ${escapeHtml(location)}${escapeHtml(pages)}${source.note ? ` · ${escapeHtml(source.note)}` : ""}</li>`;
    }).join("");
  }

  function renderInfoAssessments(archive) {
    const data = archive.assessments || {};
    const warnings = data.warnings || [];
    const items = data.items || [];
    const groups = data.groups || [];
    return `
      ${warnings.length ? `<div class="notice warning"><strong>数据提醒</strong><ul>${warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")}</ul></div>` : ""}
      <section class="info-panel assessment-summary"><h2>评分摘要</h2>${infoRows([
        ["评分构成", displayValue(data.grading_basis)],
        ["普通权重合计", data.total_weight_percent === null || data.total_weight_percent === undefined ? "未知" : `${data.total_weight_percent}%`],
        ["解析器", displayValue(data.parser_version)],
      ])}<p class="info-note">分组权重用于解释结构；下列子项目的普通权重才用于逐项展示，避免重复相加。Bonus 独立显示。</p></section>
      ${groups.length ? `<section class="info-panel"><h2>Assessment 分组</h2><div class="assessment-group-list">${groups.map((group) => `<article><div><strong>${escapeHtml(group.title)}</strong><span>${group.weight_percent === null || group.weight_percent === undefined ? "权重未知" : `${group.weight_percent}%`}</span></div>${group.description ? `<p>${escapeHtml(group.description)}</p>` : ""}<small>置信度 ${displayValue(group.confidence)} · ${escapeHtml((group.extraction_methods || []).join("、") || "提取方式未提供")}</small></article>`).join("")}</div></section>` : ""}
      <section class="assessment-list"><h2>Assessment 项目（${items.length}）</h2>${items.length ? items.map((item) => {
        const timing = [
          item.opens_on ? `开放：${shortDate(item.opens_on)}` : null,
          item.due_at ? `截止：${formatDateTime(item.due_at)}` : item.due_on ? `截止：${shortDate(item.due_on)}` : null,
          item.scheduled_on ? `安排：${shortDate(item.scheduled_on)}` : null,
        ].filter(Boolean);
        return `<article class="assessment-card">
          <div class="assessment-head"><div><span class="assessment-type">${escapeHtml(item.assessment_type || "类型未提供")}</span><h3>${escapeHtml(item.title)}</h3></div><div class="weight-stack"><strong>${item.weight_percent === null || item.weight_percent === undefined ? "权重未知" : `${item.weight_percent}%`}</strong>${item.bonus_percent === null || item.bonus_percent === undefined ? "" : `<span>Bonus +${escapeHtml(item.bonus_percent)}%</span>`}</div></div>
          <div class="assessment-facts"><span>${timing.length ? timing.map(escapeHtml).join(" · ") : "日期未提供"}</span><span>字数：${escapeHtml(displayValue(item.word_limit))}</span><span>状态：${escapeHtml(displayValue(item.status))}</span><span>置信度：${escapeHtml(displayValue(item.confidence))}</span><span>${item.visible_in_course ? "课程页可见" : "课程页未见"}</span></div>
          ${item.description ? `<p>${escapeHtml(item.description)}</p>` : ""}
          ${item.requirements?.length ? `<div class="compact-list"><strong>要求</strong><ul>${item.requirements.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul></div>` : ""}
          <details><summary>提取依据与来源</summary><p class="info-note">${escapeHtml((item.extraction_methods || []).join("、") || "提取方式未提供")}</p><ul class="source-list">${renderAssessmentSources(item.sources)}</ul></details>
        </article>`;
      }).join("") : '<div class="empty-state compact">course.json 未提供 Assessment 项目。</div>'}</section>
      ${(data.policies || []).length ? `<section class="info-panel"><h2>课程政策</h2><ul>${data.policies.map((policy) => `<li>${escapeHtml(policy)}</li>`).join("")}</ul></section>` : ""}`;
  }

  function renderInfoActivity(activity) {
    const status = [activity.module_name || activity.module || activity.category, activity.download_status, activity.visible === false ? "隐藏" : null, activity.has_restrictions ? "有限制" : null].filter(Boolean);
    const completion = activity.completion_state === null || activity.completion_state === undefined ? "未提供" : String(activity.completion_state);
    const metadata = Object.entries(activity.metadata || {});
    return `<article class="structure-activity"><div><h3>${escapeHtml(activity.name)}</h3><p>${status.map(escapeHtml).join(" · ")} · 完成状态 ${escapeHtml(completion)} · ${activity.files?.length || 0} 个文件</p></div>${activity.url ? `<a class="text-link" href="${escapeHtml(activity.url)}" target="_blank" rel="noreferrer">Moodle</a>` : ""}${activity.download_error ? `<p class="file-warning">${escapeHtml(activity.download_error)}</p>` : ""}${metadata.length ? `<details><summary>Metadata</summary>${infoRows(metadata.map(([key, value]) => [key, typeof value === "object" ? JSON.stringify(value) : displayValue(value)]))}</details>` : ""}</article>`;
  }

  function renderInfoStructure(archive) {
    const sections = archive.sections || [];
    const unassigned = archive.unassigned_activities || [];
    return `<div class="structure-list">${sections.map((section, index) => `<details class="material-section" ${section.current || index === 0 ? "open" : ""}><summary>${escapeHtml(section.title || "未命名 Section")}<span>${section.activities?.length || 0} 项${section.current ? " · 当前" : ""}${section.visible === false ? " · 隐藏" : ""}</span></summary><div>${(section.activities || []).map(renderInfoActivity).join("") || '<p class="empty-inline">没有 Activity</p>'}</div></details>`).join("")}${unassigned.length ? `<details class="material-section"><summary>未归属 Section<span>${unassigned.length} 项</span></summary><div>${unassigned.map(renderInfoActivity).join("")}</div></details>` : ""}</div>`;
  }

  function renderInfoQuality(archive) {
    const activities = allCourseActivities(archive);
    const failed = activities.filter(({ activity }) => activity.download_error);
    const files = activities.flatMap(({ section, activity }) => (activity.files || []).map((file) => ({ section, activity, file })));
    const stats = archive.stats || {};
    return `
      <div class="info-stat-grid">${infoMetric("下载成功", displayValue(stats.downloaded_file_count))}${infoMetric("下载失败", displayValue(stats.failed_download_count))}${infoMetric("下载总量", stats.downloaded_bytes === null || stats.downloaded_bytes === undefined ? "未提供" : formatBytes(stats.downloaded_bytes))}${infoMetric("PDF 总词数", displayValue(stats.pdf_word_count))}</div>
      ${failed.length ? `<div class="notice error"><strong>下载失败</strong><ul>${failed.map(({ activity }) => `<li>${escapeHtml(activity.name)}：${escapeHtml(activity.download_error)}</li>`).join("")}</ul></div>` : '<div class="notice success">course.json 未记录下载失败。</div>'}
      <section class="info-panel"><h2>文件清单（${files.length}）</h2><div class="quality-files">${files.length ? files.map(({ section, activity, file }) => {
        const analysis = file.analysis;
        const coverage = analysis?.page_count ? `${analysis.pages_with_text}/${analysis.page_count} 页有文本` : "文本覆盖未提供";
        const warnings = analysis?.warnings || [];
        return `<details><summary><span><strong>${escapeHtml(file.filename)}</strong><small>${escapeHtml(section?.title || "未归属")} · ${escapeHtml(activity.name)}</small></span><span>${escapeHtml(formatBytes(file.size_bytes))}</span></summary>${infoRows([
          ["相对路径", displayValue(file.relative_path)], ["Content-Type", displayValue(file.content_type)], ["SHA-256", displayValue(file.sha256)], ["下载时间", formatDateTime(file.downloaded_at)], ["验证时间", formatDateTime(file.validated_at)], ["PDF 分析", analysis ? `${displayValue(analysis.status)} · ${coverage}` : "未进行"], ["词数", analysis ? displayValue(analysis.word_count) : "未提供"], ["预计阅读", analysis?.estimated_reading_minutes === null || analysis?.estimated_reading_minutes === undefined ? "未提供" : `${analysis.estimated_reading_minutes} 分钟`], ["OCR", analysis ? (analysis.ocr_required ? "需要" : "不需要") : "未提供"],
        ])}${warnings.length ? `<p class="file-warning">${warnings.map(escapeHtml).join("；")}</p>` : ""}</details>`;
      }).join("") : '<p class="muted-text">没有文件。</p>'}</div></section>`;
  }

  function renderCourseInformationTab(tab) {
    if (!state.courseInformation) return;
    state.courseInfoTab = tab;
    document.querySelectorAll("[data-info-tab]").forEach((button) => {
      const active = button.dataset.infoTab === tab;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
    });
    const archive = state.courseInformation.course_json;
    const content = byId("course-info-content");
    if (tab === "overview") content.innerHTML = renderInfoOverview(archive);
    else if (tab === "assessments") content.innerHTML = renderInfoAssessments(archive);
    else if (tab === "structure") content.innerHTML = renderInfoStructure(archive);
    else if (tab === "quality") content.innerHTML = renderInfoQuality(archive);
    else {
      content.innerHTML = '<pre id="course-json-view" class="json-view" aria-label="course.json 内容"></pre>';
      byId("course-json-view").textContent = JSON.stringify(archive, null, 2);
    }
  }

  async function openCourseInformation(courseId) {
    document.querySelectorAll(".page").forEach((page) => page.classList.add("hidden"));
    byId("page-course-info").classList.remove("hidden");
    byId("course-info-title").textContent = "课程信息";
    byId("course-info-caption").textContent = "正在读取并验证 course.json…";
    byId("course-info-content").innerHTML = '<div class="loading-state">正在读取 course.json…</div>';
    byId("copy-course-json").disabled = true;
    state.courseInformation = null;
    state.courseInfoTab = "overview";
    try {
      const information = await request(`/api/courses/${encodeURIComponent(courseId)}`);
      state.courseInformation = information;
      byId("course-info-title").textContent = information.course_title;
      byId("course-info-caption").textContent = `Course ${information.course_id} · 采集于 ${formatDateTime(information.collected_at)}`;
      byId("copy-course-json").disabled = false;
      renderCourseInformationTab("overview");
    } catch (error) {
      byId("course-info-content").innerHTML = `<div class="notice error">无法读取课程信息：${escapeHtml(error.message)}</div>`;
    }
  }

  async function openCourseMaterials(courseId) {
    document.querySelectorAll(".page").forEach((page) => page.classList.add("hidden"));
    byId("page-materials").classList.remove("hidden");
    byId("materials-course-title").textContent = "课程课件";
    byId("materials-caption").textContent = "正在读取本地课程归档…";
    byId("materials-summary").textContent = "";
    byId("materials-list").innerHTML = '<div class="loading-state">正在读取课件目录…</div>';
    try {
      const catalog = await request(`/api/courses/${encodeURIComponent(courseId)}/materials`);
      renderMaterials(catalog);
    } catch (error) {
      byId("materials-list").innerHTML = `<div class="notice error" role="alert">${escapeHtml(error.message)}</div>`;
    }
  }

  function renderMaterials(catalog) {
    byId("materials-course-title").textContent = catalog.course_title;
    byId("materials-caption").textContent = `本地归档采集于 ${formatDateTime(catalog.collected_at)}。`;
    byId("materials-summary").textContent = `${catalog.downloaded_file_count} 份已下载文件 · ${catalog.analyzed_pdf_count} 份 PDF 已分析 · ${catalog.failed_download_count} 项下载失败`;
    const sections = catalog.sections.filter((section) => section.activities.length);
    if (!sections.length) {
      byId("materials-list").innerHTML = '<div class="empty-state">这门课程的本地归档没有课件活动。</div>';
      return;
    }
    byId("materials-list").innerHTML = sections.map((section, sectionIndex) => `
      <details class="material-section" ${section.current || sectionIndex === 0 ? "open" : ""}>
        <summary>${escapeHtml(section.title || "未命名 Section")}<span>${section.activities.length} 项内容${section.visible ? "" : " · 当前隐藏"}</span></summary>
        <div>${section.activities.map(renderMaterialActivity).join("")}</div>
      </details>
    `).join("");
  }

  function renderMaterialActivity(activity) {
    const files = activity.files.length
      ? `<div class="file-list">${activity.files.map((file) => renderMaterialFile(file)).join("")}</div>`
      : "";
    const statusBits = [activity.download_status.replaceAll("_", " ")];
    if (!activity.visible) statusBits.push("当前不可见");
    if (activity.has_restrictions) statusBits.push("有限制");
    if (activity.download_error) statusBits.push(activity.download_error);
    const moodleLink = activity.moodle_url
      ? `<a class="text-link moodle-link" href="${escapeHtml(activity.moodle_url)}" target="_blank" rel="noreferrer">在 Moodle 查看</a>`
      : "";
    return `
      <article class="material-activity">
        <div class="activity-heading"><h2>${escapeHtml(activity.name)}</h2><span>${escapeHtml(activity.category)}</span></div>
        <p class="activity-meta">${statusBits.map(escapeHtml).join(" · ")}</p>
        ${files}${moodleLink}
      </article>
    `;
  }

  function renderMaterialFile(file) {
    const analysis = file.analysis;
    const detail = analysis
      ? `${analysis.page_count} 页 · ${analysis.word_count} 词 · 文本提取 ${analysis.status}`
      : `${formatBytes(file.size_bytes)} · 未进行 PDF 文本分析`;
    const warnings = analysis && (analysis.ocr_required || analysis.warnings.length)
      ? `<small class="file-warning">${analysis.ocr_required ? "需要 OCR；" : ""}${analysis.warnings.map(escapeHtml).join("；")}</small>`
      : "";
    const action = file.available
      ? `<a class="text-link" href="${escapeHtml(file.open_url)}" target="_blank" rel="noreferrer">打开本地文件</a>`
      : '<span class="course-state failed">文件缺失</span>';
    return `<div class="file-row"><div><strong>${escapeHtml(file.filename)}</strong><small>${escapeHtml(detail)}</small>${warnings}</div>${action}</div>`;
  }

  function formatBytes(value) {
    const bytes = Number(value || 0);
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  function openExecutionDialog() {
    const item = state.snapshot.items.find((candidate) => candidate.plan_item_id === state.selectedItemId);
    if (!item) return;
    state.recordId = `execution:web:${crypto.randomUUID()}`;
    byId("execution-item-title").textContent = item.title;
    byId("planned-minutes").value = item.remaining_minutes ? Math.min(item.remaining_minutes, 90) : 60;
    byId("actual-minutes").value = "";
    byId("progress-minutes").value = "";
    byId("completed").checked = false;
    byId("execution-notes").value = "";
    byId("execution-confirmed").checked = false;
    byId("execution-error").classList.add("hidden");
    byId("execution-dialog").classList.remove("hidden");
    byId("actual-minutes").focus();
  }

  function closeDialogs() {
    document.querySelectorAll(".dialog-backdrop").forEach((dialog) => dialog.classList.add("hidden"));
  }

  document.querySelectorAll(".nav-button").forEach((button) => button.addEventListener("click", () => {
    document.querySelectorAll(".nav-button").forEach((candidate) => candidate.classList.toggle("active", candidate === button));
    document.querySelectorAll(".page").forEach((page) => page.classList.add("hidden"));
    byId(`page-${button.dataset.page}`).classList.remove("hidden");
  }));
  document.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", closeDialogs));
  document.querySelectorAll(".dialog-backdrop").forEach((dialog) => dialog.addEventListener("click", (event) => {
    if (event.target === dialog) closeDialogs();
  }));

  byId("reload-dashboard").addEventListener("click", async (event) => {
    setBusy(event.currentTarget, true, "正在载入…");
    await loadDashboard();
    setBusy(event.currentTarget, false);
  });

  ["filter-date-from", "filter-date-to"].forEach((id) => byId(id).addEventListener("change", () => {
    state.taskFilters.dateFrom = byId("filter-date-from").value;
    state.taskFilters.dateTo = byId("filter-date-to").value;
    applyTaskFilters();
  }));
  byId("filter-date-unconfirmed").addEventListener("change", (event) => {
    state.taskFilters.includeUnconfirmed = event.currentTarget.checked;
    applyTaskFilters();
  });
  byId("filter-date-missing").addEventListener("change", (event) => {
    state.taskFilters.includeMissing = event.currentTarget.checked;
    applyTaskFilters();
  });
  byId("reset-task-filters").addEventListener("click", () => {
    state.taskFilters = {
      courseIds: new Set(state.snapshot.items.map((item) => item.course_id)),
      knownCourseIds: new Set(state.snapshot.items.map((item) => item.course_id)),
      dateFrom: "",
      dateTo: "",
      includeUnconfirmed: true,
      includeMissing: true,
    };
    renderTaskFilters();
    applyTaskFilters();
  });

  document.querySelectorAll("[data-info-tab]").forEach((button) => button.addEventListener("click", () => {
    renderCourseInformationTab(button.dataset.infoTab);
  }));

  byId("execution-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button[type="submit"]');
    const errorBox = byId("execution-error");
    errorBox.classList.add("hidden");
    setBusy(button, true, "正在记录…");
    try {
      const result = await request("/api/executions", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-HSAS-Request": "1" },
        body: JSON.stringify({
          plan_item_id: state.selectedItemId,
          record_id: state.recordId,
          planned_minutes: Number(byId("planned-minutes").value),
          actual_minutes: Number(byId("actual-minutes").value),
          progress_minutes: Number(byId("progress-minutes").value),
          completed: byId("completed").checked,
          notes: byId("execution-notes").value,
          confirmed: byId("execution-confirmed").checked,
        }),
      });
      closeDialogs();
      await loadDashboard();
      showToast(result.plan_refreshed ? "进度已记录，计划已重新生成" : `进度已记录；计划更新失败：${result.refresh_error}`);
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove("hidden");
    } finally {
      setBusy(button, false);
    }
  });

  byId("open-sync").addEventListener("click", () => {
    byId("sync-confirmed").checked = false;
    byId("sync-error").classList.add("hidden");
    byId("sync-dialog").classList.remove("hidden");
  });

  byId("check-moodle-session").addEventListener("click", () => checkMoodleSession(true));
  byId("open-moodle-login").addEventListener("click", () => {
    byId("login-error").classList.add("hidden");
    byId("login-dialog").classList.remove("hidden");
  });

  byId("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button[type="submit"]');
    const errorBox = byId("login-error");
    errorBox.classList.add("hidden");
    setBusy(button, true, "等待完成 SSO/MFA…");
    try {
      const result = await request("/api/moodle/login", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-HSAS-Request": "1" },
        body: JSON.stringify({ confirmed: true }),
      });
      renderMoodleSession(result);
      closeDialogs();
      showToast(`Moodle 登录成功，发现 ${result.available_course_count} 门课程`);
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove("hidden");
    } finally {
      setBusy(button, false);
    }
  });

  byId("back-to-courses").addEventListener("click", () => {
    document.querySelectorAll(".page").forEach((page) => page.classList.add("hidden"));
    byId("page-courses").classList.remove("hidden");
  });

  byId("back-from-course-info").addEventListener("click", () => {
    document.querySelectorAll(".page").forEach((page) => page.classList.add("hidden"));
    byId("page-courses").classList.remove("hidden");
  });

  byId("copy-course-json").addEventListener("click", async () => {
    const content = state.courseInformation ? JSON.stringify(state.courseInformation.course_json, null, 2) : "";
    try {
      await navigator.clipboard.writeText(content);
      showToast("course.json 已复制");
    } catch (_error) {
      showToast("浏览器未允许复制；可以在 JSON 视图中手动选择");
    }
  });

  byId("sync-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button[type="submit"]');
    const errorBox = byId("sync-error");
    errorBox.classList.add("hidden");
    setBusy(button, true, "正在同步…");
    try {
      const result = await request("/api/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-HSAS-Request": "1" },
        body: JSON.stringify({ confirmed: byId("sync-confirmed").checked }),
      });
      closeDialogs();
      await loadDashboard();
      showToast(`同步完成：${result.succeeded} 门成功，${result.failed} 门失败`);
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove("hidden");
    } finally {
      setBusy(button, false);
    }
  });

  loadDashboard();
  checkMoodleSession(false);
})();
