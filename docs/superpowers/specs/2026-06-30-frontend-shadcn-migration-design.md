# Frontend → shadcn/ui migration (1:1)

**Date:** 2026-06-30
**Branch:** ui-tweaks

## Goal

Replace the hand-rolled global stylesheet (`frontend/src/index.css`, ~310 lines of
bespoke semantic classes) with a real component foundation: **shadcn/ui + Tailwind v4**.

The visual result is **1:1** with the current dashboard for every screen — same dark
control-room look, same sections, same layout, same flow — with one exception (the
activity box, see Out of scope). The *only* allowed visible change is that **mobile must
stop breaking**: the stat cards and page no longer overflow horizontally.

This is a foundation/architecture change, not a redesign.

## Why

- All styling lives in one global CSS file with magic numbers; every screen reinvents its
  own measures, nothing is a coherent system.
- Layout is desktop-first with a `max-width: 880px` media query bolted on as a patch.
  Mobile is an afterthought — the originating bug is stat cards clipped off-screen.
- The decided stack was React + shadcn; the build drifted to bespoke CSS and lost that
  foundation. This realigns it.

## Foundation

- **Tailwind v4** via `@tailwindcss/vite` (CSS-first config, no `tailwind.config.js`
  needed). Chosen over v3: current standard, works cleanly with Vite 8 + React 19, and
  shadcn supports it.
- **shadcn/ui** components copied into the repo under `src/components/ui/` (we own them).
- Path alias `@/*` → `src/*` added to `vite.config.ts` and `tsconfig` so shadcn imports
  resolve.
- The existing **OKLCH color values** (the actual bg/surface/border/ink/muted/faint/
  accent/pos/neg colors, radius, fonts) are reused so the look stays 1:1. **But they are
  mapped onto shadcn's expected variable structure** (`--background`, `--foreground`,
  `--card`, `--border`, `--primary`, `--muted`, etc.), not by forcing the old names
  (`--bg`, `--surface`, custom z-index scale) into Tailwind. Tailwind v4 and shadcn
  already use OKLCH natively, so the values drop in without conversion. **Rule: follow
  the standard shadcn/Tailwind setup; reuse our color values, never bend the framework
  to keep old plumbing.** If a token can't map cleanly, the standard setup wins and we
  keep only the value.

## Component mapping

| Current | Becomes |
|---|---|
| `AgentFormModal`, `ConfirmDeleteModal`, `ShareLinksModal` (hand-rolled `.modal-overlay`) | shadcn **Dialog** (accessible focus-trap/Esc for free) |
| `.btn-ghost` / `.btn-primary` / `.btn-danger` | shadcn **Button** variants |
| modal `input` / `textarea` / `select` / `label` | shadcn **Input / Textarea / Select / Label** |
| `.stat` cards, `.card`, `.chart-card`, `.two-col` cards | shadcn **Card** + Tailwind layout utilities |
| `.sidebar` (desktop rail) + `.sheet` (mobile drawer) | rail re-styled with Tailwind; mobile drawer → shadcn **Sheet** |
| `PositionsTable` (`.ptable`) | shadcn **Table** |
| `EquityChart` (recharts) | unchanged logic; only its container card re-styled |
| `Sparkline`, `InstructionsBlock`, `Login`, `AgentSidebar` | re-styled with Tailwind, same markup/behavior |
| `EventsFeed` (activity box) | **untouched** — see Out of scope |

## Responsive strategy

Rebuilt **mobile-first** with Tailwind breakpoints instead of the single desktop-down
media query:

- Base (mobile): single fluid column. Every block is full-width of its container; no
  fixed widths that push past the viewport. Stat cards stack in a 2-col grid that
  actually fits (tracks allowed to shrink), not a desktop grid squeezed down.
- `md`/`lg` and up: restore the persistent sidebar rail + content layout and the
  two-column cards, matching today's desktop look.

Success criterion: at any viewport width nothing overflows horizontally
(`document.scrollWidth <= viewport`), and the desktop view is visually identical to now.

## Testing

- Existing per-component tests (`src/__tests__/*`) must stay green. They assert behavior
  (rendering, callbacks, auth gating) more than styling.
- Where a test asserts on a removed class name or DOM structure, update the assertion to
  the new structure — without weakening what it verifies.
- `npm test` (vitest) green is part of done.

## Execution

Migration lands as a **single big-bang change** (user's choice) — not component-by-
component. Accepted trade-off: the app is non-functional mid-migration and the diff is
large / harder to review. Mitigated by git (revertible) and the test suite as the
correctness gate.

**Build order within the migration (de-risk theming):**

1. **Stand up shadcn + Tailwind with its STOCK default theme first.** Migrate all
   components onto shadcn primitives and get the app working and tests green using
   shadcn's own out-of-the-box colors. Do not touch our palette yet. This proves the
   setup is clean and isolates any framework/setup issues from theming issues.
2. **Then apply our colors**, as a distinct second step: map our OKLCH values onto the
   already-working shadcn variable structure. No inventing, no forcing, no bending the
   setup — just swap the values. If the app was 1:1 in structure after step 1, step 2
   only changes the look to match today's palette.

## Out of scope

- **EventsFeed (the activity box).** Left functional but visually neutral; it keeps its
  current markup/classes for now. We design it in detail together *after* this migration
  lands. Do not invest design effort here.
- No new features, no changed behavior, no backend changes.
- No visual redesign of anything else — same look, new foundation.

## Risks

- Large diff touching every component + build config + `index.css` + tests.
- shadcn/Tailwind v4 setup must coexist with the existing Vitest config (`vitest/config`
  in `vite.config.ts`) — the `@tailwindcss/vite` plugin and path alias go in the same file.
- `EquityChart`/recharts styling currently leans on global CSS for its container; verify
  it still renders correctly inside a shadcn Card.
