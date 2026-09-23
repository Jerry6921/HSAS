import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ReconciliationIsland } from "./reconciliation-island";

describe("ReconciliationIsland", () => {
  it("renders source presence without turning missing coverage into a conflict", () => {
    const markup = renderToStaticMarkup(
      <ReconciliationIsland
        options={{
          authority: "Moodle facts take priority when sources conflict.",
          countLabel: "1 门课程",
          courses: [
            {
              courseCode: "DEMO1001",
              title: "Demo Course",
              state: "needs-attention",
              stateLabel: "资料待补充",
              note: "SIS has not been collected yet.",
              sources: [
                { key: "moodle", label: "Moodle", present: true },
                { key: "sis", label: "SIS", present: false },
              ],
            },
          ],
        }}
      />,
    );

    expect(markup).toContain("DEMO1001");
    expect(markup).toContain("Moodle");
    expect(markup).toContain("SIS");
    expect(markup).toContain("已有");
    expect(markup).toContain("缺失");
    expect(markup).not.toContain("冲突");
  });

  it("renders the empty state", () => {
    const markup = renderToStaticMarkup(
      <ReconciliationIsland
        options={{ authority: "Moodle first", countLabel: "0 门课程", courses: [] }}
      />,
    );

    expect(markup).toContain("当前没有课程对账数据");
  });
});
