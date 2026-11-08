# Device and Vision Plugins Implementation Plan

> **For agentic workers:** Execute inline with tests, then independent final review.

**Goal:** Add discoverable device/vision/interface plugin contracts and runnable official identity-reader, camera, OCR and serial plugins.

**Architecture:** Optional manifest.plugin describes kind, mode, transport and contract independently of existing JS/executable/native-library implementation type. Strict capability schemas expose stable JSON outputs; four versioned pure-JS mock plugins demonstrate the full install/run/release path without inventing vendor SDK support.

**Tech Stack:** Rust validation, QuickJS ES modules, JSON Schema, existing signed registry/CI, Astro catalogue.

**Spec:** User requested plugin functionality such as ID-card readers returning fixed identity structures, camera, OCR, common devices and hardware interfaces.

## Global Constraints

- Four official targets remain windows-x64, macos-arm64, linux-x64, linux-arm64.
- Existing extensions remain compatible; no native permission is implicitly granted by plugin metadata.
- All mock data explicitly identifies mode=mock. Identity data is synthetic; no real identity image/number is included.
- No claim of actual hardware, camera capture or OCR recognition without a vendor/engine adapter.
- New plugins use formal extension/version directories and normal signed packaging, not examples.

## Review Focus

- Invalid plugin kind/mode/transport/contract must be rejected in Rust and schema.
- Native adapter metadata must not bypass existing explicit process/native authorization.
- Identity fields, camera frames, OCR regions and serial responses must have enforced output contracts.
- Four-platform packaging/tests and release expected coverage must discover new plugins.
- Website must label simulations and stop implying every plugin is native-math or that only three extensions exist.

### Task 1: Plugin manifest contract

- [x] Add RED Rust tests for optional plugin metadata and invalid/mismatched fields.
- [x] Add strict optional Plugin struct/validation and manifest JSON schema; keep legacy manifests accepted.
- [x] Include plugin changes in PR semantic diff and test the change.

### Task 2: Official devices and contract tests

- [x] Add RED integration coverage for stable outputs, unknown devices, malformed image input, output-schema enforcement and signed install/download.
- [x] Add id-card-reader, camera, ocr and serial-port 0.1.0 mock plugins with metadata/presubmit and complete output schemas.
- [x] Run capability tests through real QuickJS/client and pack/install with temporary test keys.
- [x] Include device tests in global CI/release pipelines without production credentials.

### Task 3: Discovery and documentation

- [x] Display plugin kind/mode/transport/contract and appropriate per-plugin commands in site.
- [x] Update homepage/catalogue counts, identity structure and adapter authoring docs, including native C ABI constraints.
- [x] Run Rust/Python/workflow/site checks, browser layout review and independent final review.

Ruling: Work in the existing all-untracked workspace; no external publication or real device access is authorized/needed.

## Verification record

- RED/GREEN observed for optional plugin validation, explicit-null rejection, missing official plugins, camera PNG CRC and camera→OCR input compatibility.
- Rust workspace27 tests, fmt, clippy and build passed.
- Registry9, PR diff/workflow14, release-pipeline2 and device integration3 passed. Existing signed distribution/native isolation/file-host suites also passed.
- All4 new per-extension presubmits passed locally with actual QuickJS; planner emits all4 supported targets.
- Astro check0 errors/warnings;10 static pages built with /foundry/ link verification.
- Chromium32 route/viewport combinations and8 WCAG audits passed; no overflow, broken anchors or console errors.
- Focused independent review and final delta review found no Critical/Important issues.
- Mock plugins are formal installable artifacts, not claims of working vendor SDKs or live OCR/camera hardware. Hosted Windows/macOS/ARM CI and actual device adapters remain outside local evidence.

- Long device schemas now use native collapsible details with bounded keyboard-scrollable code. Expanded identity contract checked at mobile width:440px viewport panel, keyboard focusable, zero Axe violations.
