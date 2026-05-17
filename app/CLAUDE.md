# app/ — Tauri + React desktop shell

> Folder-scoped rules. Read `../CLAUDE.md` first for repo-wide conventions; this file overrides nothing, only adds.

---

## 1. Stack

| Layer | Choice | Why |
|---|---|---|
| Desktop wrapper | **Tauri 2.x** | small binary, native webview |
| UI | **React 18 + TypeScript (strict)** | mainstream, hireable |
| Styling | **Tailwind CSS + shadcn/ui** | utility-first, accessible primitives |
| Client state | **Zustand** | small, no boilerplate, no Provider tree |
| Server state | **TanStack Query** | caching + retries + SSE integration |
| Forms | **react-hook-form + zod** | one schema for validation and types |
| 3D viewer | **React Three Fiber + drei** | declarative Three.js |
| Icons | **lucide-react** | one library, tree-shakable |
| Routing | **TanStack Router** | type-safe routing |
| Build | **Vite** (bundled by Tauri) | |

**No other libraries** without an ADR. We will not add Redux, MobX, RxJS, styled-components, MUI, Ant Design, or framer-motion ad hoc.

---

## 2. Project layout

```
app/
├── src/
│   ├── main.tsx                    Entry. Mounts <App/> + R3F canvas wrappers.
│   ├── App.tsx
│   ├── lib/
│   │   ├── api.ts                  TanStack Query hooks against backend HTTP.
│   │   ├── sse.ts                  SSE subscription helper.
│   │   ├── tauri.ts                Typed wrappers over Tauri IPC.
│   │   └── schemas/                zod schemas — generated from backend Pydantic.
│   ├── stores/
│   │   ├── jobs.ts                 Zustand: active job list, current selection.
│   │   ├── settings.ts             Zustand persisted to Tauri store.
│   │   └── viewer.ts               R3F viewer state (camera, wireframe, etc.).
│   ├── components/
│   │   ├── ui/                     shadcn primitives (auto-generated).
│   │   ├── jobs/                   JobList, JobTimeline, IterationCard, ScoreBars.
│   │   ├── viewer/                 ModelCanvas, ModelMesh, ViewerControls.
│   │   ├── settings/               SettingsPanel, GpuBackendPicker.
│   │   └── intake/                 ImageDropzone, JobCreateForm.
│   └── routes/                     TanStack Router file-based routes.
├── src-tauri/                      Rust side.
│   ├── src/
│   │   ├── main.rs                 Tauri setup, command registrations.
│   │   ├── backend.rs              Spawn/supervise Python backend.
│   │   ├── files.rs                Open/save dialogs, sandboxed paths.
│   │   └── keychain.rs             OS keychain wrapper (HF token, ngrok token).
│   ├── tauri.conf.json
│   └── Cargo.toml
└── package.json
```

---

## 3. IPC ↔ HTTP split

This is the rule everyone gets wrong; nail it:

| Use Tauri IPC for | Use HTTP for |
|---|---|
| Native file dialogs | Creating/listing/cancelling jobs |
| Keychain (secrets) | Per-job SSE events |
| Window/menu controls | Fetching artifacts |
| App updater (later) | Fetching exports |
| OS info (paths, displays) | Settings stored in `state.db` |

**Never** use Tauri IPC to wrap a backend HTTP endpoint. The frontend should hit the backend directly. Tauri's only job is to be the OS.

---

## 4. Type safety end-to-end

The flow:

1. Pydantic models live in `backend/models.py`.
2. `scripts/gen_ts_schemas.py` runs after every backend change → emits `app/src/lib/schemas/*.ts` as zod.
3. UI imports zod schemas → uses `z.infer<typeof ...>` for static types and `.parse()` at runtime boundaries.

**No `any`.** If a backend response is unknown shape, do not deserialize it — fix the schema instead.

---

## 5. State machine for the job UI

A job goes through visible states: `queued → preprocessing → generating → cleanup → rendering → evaluating → refining → exporting → done` (or `failed` / `cancelled` from any). The UI **reflects backend state**; it does not invent its own. SSE drives transitions. If SSE disconnects, the UI shows a "reconnecting" banner and falls back to polling `GET /jobs/{id}` until SSE recovers.

---

## 6. The 3D viewer

- One R3F `<Canvas>` per visible job.
- Loads `.glb` via `useGLTF`.
- Camera state (orbit, zoom, target) is persisted in `stores/viewer.ts` keyed by job id — so swapping the preview mesh for the final mesh keeps the user's framing.
- Wireframe toggle, lighting preview, texture toggle — all in `ViewerControls`.
- Handles meshes up to 200k triangles smoothly on integrated graphics. Above that we LOD-decimate for viewport (preserving the original on disk).

Performance budget: 60 fps for 100k tri, 30 fps for 200k tri, on Iris Xe.

---

## 7. Conventions

- One component per file. File name = export name.
- Hooks live next to the component that uses them unless reused; reused hooks go to `src/lib/hooks/`.
- All long-running interactions go through TanStack Query mutations with `onError` toasts via `sonner`.
- No inline styles. Tailwind only.
- All user-visible strings live in `src/lib/strings.ts` to ease future i18n (we are NOT doing i18n in v1 — but we centralize so we can).

---

## 8. Testing

- **Vitest** for unit (utility + hook tests).
- **Playwright (component mode)** for component tests of complex flows (intake → job → viewer).
- **Tauri end-to-end** via `webdriver-bidi` — one happy path per milestone exit criterion.

No Jest. No Cypress. No Storybook in v1 (revisit at M5).

---

## 9. Build + dev commands

```
pnpm install
pnpm tauri dev          # dev mode with HMR
pnpm tauri build        # production build
pnpm typecheck
pnpm lint
pnpm test
```

All wired in `package.json`. CI runs typecheck + lint + test + tauri build (release) on every push.
