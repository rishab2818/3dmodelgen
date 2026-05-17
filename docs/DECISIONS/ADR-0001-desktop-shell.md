# ADR-0001: Desktop shell — Tauri + React

**Status:** Accepted
**Date:** 2026-05-16
**Deciders:** user (project owner), Claude (architect)

## Context

The product is a desktop application. It must:

- Run on Windows 11 (primary), Linux (secondary), macOS (best-effort).
- Embed a real-time 3D viewer.
- Spawn a long-lived Python backend process.
- Stay snappy on low-end hardware (the dev machine has integrated graphics).
- Be installable as a single signed binary.

Three serious candidates: **Tauri + React**, **Electron + React**, **PySide6 / PyQt**.

## Decision

**Tauri + React (TypeScript strict mode).** Frontend is React + Tailwind + shadcn/ui. 3D viewer is React Three Fiber. Tauri's Rust core stays thin (file dialogs, window mgmt, spawning the Python backend); business logic lives in Python.

## Consequences

**Good**
- Final binary in the 10–30 MB range vs. 150+ MB for Electron.
- Native webview (WebView2 on Windows, WebKit on macOS) — better memory profile than bundled Chromium.
- Strong type-safety story end-to-end: zod schemas → TS types + Pydantic models on the backend.
- Rust toolchain is already installed on the dev box.

**Bad**
- Cross-platform webview means visual rendering can subtly differ (Windows WebView2 vs. macOS WebKit). We will pin our UI to features that work everywhere and explicitly test on all three.
- Tauri's plugin ecosystem is smaller than Electron's. We will likely write a tiny Rust plugin or two (e.g., for keychain).
- Rust learning curve if the team grows — though for v1 the Rust footprint is tiny.

**Neutral**
- We can't ship the Python backend as a "lambda" — it must be a real, supervised subprocess. Tauri handles this fine but it does mean we have a multi-process app to debug.

## Alternatives considered

**Electron + React.** Maturer ecosystem, but binary size and memory cost are real (and felt) on low-end hardware. The user explicitly wants this to feel fast and polished — Electron makes that harder.

**PySide6 / PyQt.** Simplest from a "Python everywhere" perspective. Rejected because (a) the UI ceiling is lower — we want a 2026-grade desktop app, not a 2010-grade one; (b) the 3D viewer story is weak: QtQuick3D is workable but nowhere near the polish of Three.js / R3F; (c) packaging signed Windows installers from PyInstaller has historically been a debugging tax.

**Pure web app, no desktop wrapper.** Rejected because the spec is explicit: desktop application, local execution, no cloud requirement.
