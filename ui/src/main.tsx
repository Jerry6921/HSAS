import { createRef, useEffect, useState, type ReactNode } from "react";
import { MotionConfig } from "motion/react";
import { MotionPreference } from "./lib/motion";
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
import "./editorial.css";

const roots = new WeakMap<HTMLElement, Root>();

function WorkspaceMotion({ children }: { children: ReactNode }) {
  const [enabled, setEnabled] = useState(document.documentElement.classList.contains('motion-enabled'));
  const [reduceMotion, setReduceMotion] = useState(window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  useEffect(() => {
    const observer = new MutationObserver(() => setEnabled(document.documentElement.classList.contains('motion-enabled')));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const updatePreference = () => setReduceMotion(preference.matches);
    preference.addEventListener('change', updatePreference);
    return () => { observer.disconnect(); preference.removeEventListener('change', updatePreference); };
  }, []);
  const active = enabled && !reduceMotion;
  return <MotionPreference.Provider value={active}><MotionConfig reducedMotion={active ? 'never' : 'always'}>{children}</MotionConfig></MotionPreference.Provider>;
}

window.HIQSModernCalendar = {
  mount(element: HTMLElement, options: ModernCalendarOptions) {
    let root = roots.get(element);
    if (!root) {
      root = createRoot(element);
      roots.set(element, root);
    }
    root.render(<WorkspaceMotion><CalendarIsland options={options} /></WorkspaceMotion>);
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
    root.render(<WorkspaceMotion><HomeIsland options={options} /></WorkspaceMotion>);
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
    root.render(<WorkspaceMotion><CourseIsland options={options} /></WorkspaceMotion>);
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
      root.render(<WorkspaceMotion>{node}</WorkspaceMotion>);
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
    root.render(<WorkspaceMotion><ReconciliationIsland options={options} /></WorkspaceMotion>);
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
    flushSync(() => overlayRoot?.render(<WorkspaceMotion><OverlayIsland ref={overlayRef} initialOptions={options} /></WorkspaceMotion>));
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
