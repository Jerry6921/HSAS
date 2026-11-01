# Third-party notices

## Canvas UI Ripple

HIQS includes a browser-ready copy of the Vanilla WebGL Ripple component from
[Canvas UI](https://canvasui.dev/). The component is distributed by its authors
under the MIT License with the Commons Clause restriction described by the
Canvas UI project. HIQS uses it as an interface effect and does not resell or
redistribute the component as a standalone library.

The vendored source is stored at `src/hsas/web/static/ripple.js`. TypeScript
annotations were mechanically removed so the component can run in HIQS without
adding a JavaScript build toolchain.

## Removed browser client

The former local React dashboard and its bundled dependencies (React, FullCalendar,
Motion, Tailwind helpers and Lucide icons) were removed together with `ui/` and
`src/hsas/web/`. No frontend runtime is shipped or required. The removed sources and
their licence notices remain available in git history.
