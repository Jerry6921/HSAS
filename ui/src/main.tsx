import { createRoot, type Root } from "react-dom/client";
import { CalendarIsland } from "./calendar-island";
import type { ModernCalendarOptions } from "./types";
import "./styles.css";

const roots = new WeakMap<HTMLElement, Root>();

window.HIQSModernCalendar = {
  mount(element: HTMLElement, options: ModernCalendarOptions) {
    let root = roots.get(element);
    if (!root) {
      root = createRoot(element);
      roots.set(element, root);
    }
    root.render(<CalendarIsland options={options} />);
  },
  unmount(element: HTMLElement) {
    const root = roots.get(element);
    if (!root) return;
    root.unmount();
    roots.delete(element);
  },
};
