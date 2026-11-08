# macOS ARM64 and Website Refresh Implementation Plan

> **For agentic workers:** Execute inline, then request final review.

**Goal:** Support macOS arm64 only and refresh the website across desktop/mobile.

**Architecture:** Keep four official targets in the Rust/schema contract, registry and build/release matrices. Reuse Astro's static catalogue, with a unified light visual system, clearer platform labels and accessible responsive layouts.

**Tech Stack:** Rust, Python, GitHub Actions, Astro, CSS, local Chromium/Playwright verification.

**Spec:** User: “macOS只需要arm64就行，更新一下说明，以及美化一下网页。”

## Global Constraints

- Official targets: windows-x64, macos-arm64, linux-x64, linux-arm64.
- Preserve QuickJS, executable, libffi extension behavior and signed release boundaries.
- Keep unreleased registry status accurate; no invented download links.
- Use static HTML/CSS and existing Astro dependencies; no external font requests.

## Review Focus

- Release, CI, native manifests and schema must agree on the same four targets.
- All supported viewport sizes must avoid page-level horizontal overflow.
- Project-base links, document anchors and keyboard focus must remain usable.
- Update existing 0.1.0 directories because the repository has never been committed/published.
- Do not claim actual hosted macOS/Windows runs from local Linux verification.

### Task 1: Platform alignment

- [x] Add a registry regression checking actual workflow matrices, official presubmits and manifest schema against four expected targets; observe RED.
- [x] Remove macOS x64 runners, native paths and accepted manifest platform; update release fixtures and all current documentation.
- [x] Run registry, Rust and release tests GREEN.

### Task 2: Website visual refresh

- [x] Refresh shared layout/CSS, homepage, directory, detail and docs navigation with an ivory/charcoal/orange palette.
- [x] Display accurate OS/architecture labels and release status.
- [x] Keep links, interactions and layouts accessible with reduced-motion support.

### Task 3: Verification

- [x] Build/check Astro with project base and validate links.
- [x] Inspect Chromium desktop/mobile screenshots and layout/console results; fix visible issues.
- [x] Run platform checks, extension tests and actionlint; request final focused review.

Ruling: Use the existing workspace; project has no commits and is entirely untracked. No external publication or key configuration is part of this task.

## Verification record

- Rust workspace fmt/test/build and clippy passed after manifest platform removal.
- Registry9, PR diff/workflow13, release-pipeline2 and real signed distribution tests passed.
- actionlint v1.7.11 passed all workflows.
- Astro check: zero errors/warnings/hints; all6 static pages built under /foundry/ with verified internal links.
- Chromium checked homepage/catalogue/native detail/docs at1440,768,390,320px:16 combinations, no page overflow, broken fragment anchors or browser errors.
- Axe WCAG2A/AA and2.1AA checks on all4 page types: zero violations after helper-text contrast fixes.
- Screenshots and machine-readable browser report: dist/site-review/.
- Independent review found an overly broad platform test; constrained it to current official0.1.0 fixtures, preserving arbitrary extension platform subsets. Final review found no remaining Important issues.
- Actual hosted macOS/Windows/Linux ARM64 CI remains pending GitHub execution. Local functional checks ran on Linux x64.
