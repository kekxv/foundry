# Google Style and Initial Commit Implementation Plan

> **For agentic workers:** Execute inline; final verification and focused review before commit.

**Goal:** Organize the project, apply reproducible Google-oriented code formatting, and create the first local commit.

**Architecture:** Python uses pinned YAPF Google plus isort Google; JS/TS and web/data/docs files use pinned Prettier with Google GTS7 options and the Astro plugin. Rust uses rustfmt for the workspace and independent native extension workspaces. A single Python command checks or writes all formats, and CI enforces it.

**Spec:** User: “整理一下，提交一下，代码格式使用google的风格”.

## Constraints

- Preserve public interfaces, JSON contracts, four-platform support and release security boundaries.
- Do not commit keys, runtime/build artifacts, screenshots, dependencies or caches.
- Use existing configured Git author, branch feat/foundry; commit locally, no remote publication.
- This is an initial repository snapshot, so version directories can be formatted before first publication.

## Tasks

- [x] Add formatter/editor configuration, pinned tools, one format/check command and contributing guide.
- [x] Apply Python/JS/TS/Astro/CSS/YAML/JSON/Markdown and Rust formatting; update stale uncommitted-state documentation.
- [x] Add format CI, run format check and functional suites, inspect actual browser regressions and review staged changes.
- [x] Create initial commit and verify commit contents plus clean worktree.

## Review Focus

- Google YAPF and GTS options must be pinned and documented without implying an official Google Rust/Astro style.
- Standalone native Rust workspaces must be formatted as well.
- Prettier must not traverse target/dist/node_modules or include generated assets.
- Formatting must not alter embedded JS/Rust fixture behavior or workflow semantics.
- New initial commit must exclude all private material and build output.

## Verification evidence

- Unified format check passed, including independent native Rust workspaces.
- Workspace: 27 tests passed; Clippy with warnings denied and build passed.
- Python: registry (9), diff/workflow (14), release pipeline (2), device plugins (3), distribution (1), native isolation (1), and host files (1) passed.
- Website: Astro check reported no errors, warnings, or hints; all 10 pages built and project-base links passed.
- Browser: 32 layouts passed without overflow, broken anchors, or page errors; 8 accessibility audits reported no violations.
- All workflows passed actionlint. Staged files passed whitespace checks and contained no dependency/build directories or detected credentials.
- This machine validates Linux x64; other platforms and remote publishing require their GitHub runners and repository configuration.
