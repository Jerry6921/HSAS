import { createRef, type ReactNode } from "react";
import { flushSync } from "react-dom";
import { createRoot, type Root } from "react-dom/client";
import { CalendarIsland } from "./calendar-island";
import { HomeIsland } from "./home-island";
import { CourseIsland } from "./course-island";
import { HeadingIsland, NoticesIsland, SidebarIsland, TopbarIsland } from "./shell-island";
import { ReconciliationIsland } from "./reconciliation-island";
import { OverlayIsland, type OverlayHandle } from "./overlay-island";
import type { ModernCalendarOptions, ModernCourseOptions, ModernHomeOptions, ModernOverlayOptions, ModernReconciliationOptions, ModernShellOptions } from "./types";
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

window.HIQSModernHome = {
  mount(element: HTMLElement, options: ModernHomeOptions) {
    let root = roots.get(element);
    if (!root) {
      root = createRoot(element);
      roots.set(element, root);
    }
    document.body.classList.add("hiqs-modern-home-ready");
    root.render(<HomeIsland options={options} />);
  },
  unmount(element: HTMLElement) {
    const root = roots.get(element);
    if (!root) return;
    root.unmount();
    roots.delete(element);
    document.body.classList.remove("hiqs-modern-home-ready");
  },
};

window.HIQSModernCourse = {
  mount(element: HTMLElement, options: ModernCourseOptions) {
    let root = roots.get(element);
    if (!root) {
      root = createRoot(element);
      roots.set(element, root);
    }
    root.render(<CourseIsland options={options} />);
  },
  unmount(element: HTMLElement) {
    const root = roots.get(element);
    if (!root) return;
    root.unmount();
    roots.delete(element);
  },
};

window.HIQSModernShell = {
  mount(topbar, sidebar, heading, notices, options: ModernShellOptions) {
    const values: Array<[HTMLElement, ReactNode]> = [
      [topbar, <TopbarIsland options={options} />],
      [sidebar, <SidebarIsland options={options} />],
      [heading, <HeadingIsland options={options} />],
      [notices, <NoticesIsland options={options} />],
    ];
    for (const [element, node] of values) {
      let root = roots.get(element);
      if (!root) { root = createRoot(element); roots.set(element, root); }
      root.render(node);
    }
    document.body.classList.add("hiqs-modern-shell-ready");
  },
  unmount(...elements) {
    for (const element of elements) {
      const root = roots.get(element);
      if (root) { root.unmount(); roots.delete(element); }
    }
    document.body.classList.remove("hiqs-modern-shell-ready");
  },
};

window.HIQSModernReconciliation = {
  mount(element, options: ModernReconciliationOptions) {
    let root = roots.get(element);
    if (!root) { root = createRoot(element); roots.set(element, root); }
    root.render(<ReconciliationIsland options={options} />);
  },
  unmount(element) {
    const root = roots.get(element);
    if (root) { root.unmount(); roots.delete(element); }
  },
};

const overlayRef = createRef<OverlayHandle>();
let overlayRoot: Root | null = null;
let overlayOptions: ModernOverlayOptions | null = null;

window.HIQSModernOverlay = {
  mount(element, options) {
    overlayOptions = options;
    if (!overlayRoot) overlayRoot = createRoot(element);
    flushSync(() => overlayRoot?.render(<OverlayIsland ref={overlayRef} initialOptions={options} />));
  },
  update(options) { overlayOptions = options; overlayRef.current?.update(options); },
  openDetail(options) { overlayRef.current?.openDetail(options); },
  closeDetail() { overlayRef.current?.closeDetail(); },
  openSource(source) { overlayRef.current?.openSource(source); },
  closeSource() { overlayRef.current?.closeSource(); },
  openEventEditor(defaults) { overlayRef.current?.openEventEditor(defaults); },
  closeEventEditor() { overlayRef.current?.closeEventEditor(); },
  openCourseManager() { overlayRef.current?.openCourseManager(); },
  closeCourseManager() { overlayRef.current?.closeCourseManager(); },
};
