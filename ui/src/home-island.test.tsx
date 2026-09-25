import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AttentionRadar } from "./home-island";
import type { HomeAttentionItem, HomeAttentionSnapshot } from "./types";

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
    <AttentionRadar snapshot={snapshot} onAction={() => undefined} onReviewChanges={() => undefined} onCreateDraft={async () => true} />,
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
    expect(render({ state: "ready", items: [] })).toContain("未来两周没有需要优先核实的事项");
    expect(render({ state: "error", items: [], error: "offline" })).toContain("课程资料与日历仍可正常使用");
  });
});
