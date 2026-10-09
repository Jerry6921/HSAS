import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { CourseIsland } from "./course-island";
import type { ModernCourseOptions } from "./types";

function options(overrides: Partial<ModernCourseOptions> = {}): ModernCourseOptions {
  return {
    courseId: "DEMO-S1",
    code: "DEMO1001",
    title: "Demo Course",
    facts: "2026 · 3 credits",
    operationRunning: false,
    onRefresh: () => undefined,
    overview: "A course overview.",
    objectives: ["Understand the core concepts"],
    sources: [],
    grades: [{ title: "Assignment", weightPercent: 20 }],
    mode: "materials",
    archiveSummary: "1 项资料",
    hasRecentPrompt: false,
    materialSections: [{
      title: "Week 1",
      toneIndex: 0,
      materials: [{
        id: "slides-1",
        title: "Week 1 slides",
        code: "PDF",
        tone: "green",
        meta: "Lecture · 4 pages",
        canOpen: true,
        hasPrompt: true,
        source: { relative_path: "courses/demo/files/week-1.pdf" },
        prompt: "Locate Week 1 slides",
      }],
    }],
    activities: [],
    onModeChange: () => undefined,
    onOpenSource: () => undefined,
    onCopyPrompt: () => undefined,
    onOpenItem: () => undefined,
    onCopyRecentPrompt: () => undefined,
    ...overrides,
  };
}

describe("CourseIsland", () => {
  it("renders course facts, material sections, and locator prompt controls", () => {
    const markup = renderToStaticMarkup(<CourseIsland options={options()} />);

    expect(markup).toContain("Demo Course");
    expect(markup).toContain("课程综合信息");
    expect(markup).toContain("Week 1 slides");
    expect(markup).toContain("定位提示词");
  });

  it("renders activity mode with explicit date status", () => {
    const markup = renderToStaticMarkup(<CourseIsland options={options({
      mode: "activities",
      activities: [{
        category: "Assessment",
        categoryKey: "assignment",
        items: [{
          itemId: "assignment-1",
          title: "Assignment 1",
          category: "Assignment",
          categoryKey: "assignment",
          dateState: "unknown",
          dateStateLabel: "日期待确认",
          meta: "Demo Course · 10%",
          hasPrompt: true,
          prompt: "Query Assignment 1",
        }],
      }],
    })} />);

    expect(markup).toContain("课程活动");
    expect(markup).toContain("Assignment 1");
    expect(markup).toContain("日期待确认");
  });
});
