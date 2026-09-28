import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AttentionRadar, RecentUpdateVisual } from "./home-island";
import type { HomeAttentionItem, HomeAttentionSnapshot, HomeRecentUpdate } from "./types";

function item(index: number): HomeAttentionItem {
  return {
    attention_id: `attention-${index}`,
    fingerprint: `fingerprint-${index}`,
    course_code: "DEMO1001",
    course_title: "Demo Course",
    information_item_id: `item-${index}`,
    title: `Attention ${index}`,
    severity: index === 1 ? "high" : "medium",
    reason_codes: [index === 1 ? "SOURCE_CONFLICT" : "DUE_DATE_TENTATIVE"],
    missing_fields: [],
    conflicting_sources: [],
    evidence: [],
    actions: [{ kind: "open_item", item_id: `item-${index}` }],
  };
}

function render(snapshot: HomeAttentionSnapshot) {
  return renderToStaticMarkup(
    <AttentionRadar snapshot={snapshot} onAction={() => undefined} onReviewChanges={() => undefined} onCreateDraft={async () => true} onCopyPrompt={() => undefined} />,
  );
}

describe("AttentionRadar", () => {
  it("shows every entry as a compact review row", () => {
    const markup = render({ state: "ready", items: [item(1), item(2), item(3), item(4)] });

    expect(markup).toMatch(/<details[^>]*class="hiqs-attention-fold"/);
    expect(markup).toContain("<summary");
    expect(markup).toContain("4");
    expect(markup).toContain("待确认");
    expect(markup).toContain("Attention 1");
    expect(markup).toContain("Attention 4");
    expect(markup).toContain("来源冲突");
    expect(markup).toContain("复制 AI 问答提示词");
  });

  it("identifies the missing information and offers manual entry only for item facts", () => {
    const missing = { ...item(2), missing_fields: ["submission_method"], reason_codes: ["SUBMISSION_DETAILS_MISSING"] } as HomeAttentionItem;
    const login = { ...item(3), information_item_id: null, reason_codes: ["LOGIN_REQUIRED"], actions: [{kind: "login_source" as const}] } as HomeAttentionItem;
    const markup = render({ state: "ready", items: [missing, login] });

    expect(markup).not.toContain("缺少或待核");
    expect(markup).toContain("提交方式");
    expect(markup).toContain("手动补充");
    expect(markup).toContain("需要登录");
    expect(markup.match(/手动补充/g)).toHaveLength(1);
    expect(markup).toContain('class="hiqs-attention-status">需要登录');
    expect(markup).not.toContain('class="hiqs-attention-facts" aria-label="待补充信息"><span>来源同步失败');
  });

  it("keeps source workflow states out of the review list", () => {
    const changed = { ...item(2), title: "Source change", reason_codes: ["SOURCE_CHANGED_REVIEW_PENDING"] } as HomeAttentionItem;
    const failed = { ...item(3), title: "Source failure", reason_codes: ["SOURCE_SYNC_FAILED"] } as HomeAttentionItem;
    const actionable = { ...item(4), title: "Missing date", reason_codes: ["DUE_DATE_UNKNOWN", "SOURCE_CHANGED_REVIEW_PENDING"] } as HomeAttentionItem;
    const markup = render({ state: "ready", items: [changed, failed, actionable] });

    expect(markup).not.toContain("Source change");
    expect(markup).not.toContain("Source failure");
    expect(markup).toContain("Missing date");
    expect(markup).toContain(">1<");
  });

  it("keeps empty and isolated-error states explicit", () => {
    const empty = render({ state: "ready", items: [] });
    expect(empty).toContain("未来两周没有需要优先核实的事项");
    expect(empty).not.toContain("复制 AI 问答提示词");
    expect(render({ state: "error", items: [], error: "offline" })).toContain("课程资料与日历仍可正常使用");
  });
});

describe("RecentUpdateVisual", () => {
  it("shows Agent results as activities, confirmations, updates, and materials", () => {
    const outcome = (record_id: string, title: string, details: string[]) => ({
      record_id,
      title,
      kind: "deadline" as const,
      details,
    });
    const recent: HomeRecentUpdate = {
      applied_at: "2026-09-28T10:00:00+08:00",
      summary: {
        added: 2,
        modified: 4,
        removed: 0,
        change_count: 6,
        course_count: 1,
        activities_added: 1,
        activities_updated: 1,
        activities_confirmed: 1,
        materials_added: 1,
      },
      courses: [{
        course_id: "DEMO1001-2026-S1",
        course_title: "Demo Course",
        mode: "completed",
        changes: [],
        activities_added: [outcome("quiz-1", "Quiz 1", ["截止日期：2026-10-02"])],
        activities_confirmed: [outcome("assignment-1", "Assignment 1", ["日期状态：已确认", "截止日期：2026-10-15"])],
        activities_updated: [outcome("tutorial-1", "Tutorial", ["地点：MB201"])],
        materials_added: [{...outcome("slides-1", "Week 1 slides", ["归类：Lecture slides"]), kind: "material"}],
      }],
    };

    const markup = renderToStaticMarkup(
      <RecentUpdateVisual recent={recent} pending={[]} onOpenSource={() => undefined} />,
    );

    expect(markup).toContain("本次整理结果");
    expect(markup).toContain("新增活动");
    expect(markup).toContain("信息已确认");
    expect(markup).toContain("活动信息变更");
    expect(markup).toContain("资料变化");
    expect(markup).toContain("Assignment 1");
    expect(markup).toContain("日期状态：已确认 · 截止日期：2026-10-15");
    expect(markup.match(/Assignment 1/g)).toHaveLength(1);
  });
});
