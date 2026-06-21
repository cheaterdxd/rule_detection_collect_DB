# AGENTS.md

Behavioral guidelines and project rules for HelpMe. These rules apply to the whole repository unless a more specific `AGENTS.md` exists in a child directory.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 0. HelpMe Project Rules

`docs/goal.md` is the source of truth for the final product. HelpMe is a local-first AI personal operating system: Calendar + Todo + Deadline + Habit + Goal + AI Planner + Daily Assistant.

Project direction:
- Keep the current stack unless the user explicitly approves a change: React + TypeScript frontend, Fastify backend, SQLite/Drizzle-style local data, Ollama/local AI first.
- Python is not the default backend. Add it later only if a separate worker for heavy AI/data processing is clearly needed.
- Build a real web server app, not a GitHub Pages-only static site.
- UX should be light, focused, and easy to understand. Avoid cluttered dashboards and excessive explanatory text.
- Use icons/buttons when they communicate better than repeated labels, especially in dense UI.
- The Orb is the primary AI command layer across the app.

AI and data safety:
- Mutating AI commands must be proposal-first: parse intent, create a proposal, validate it, show it to the user, then write data only after confirmation.
- Backend validation is required before writes and again at confirmation time for scheduling/conflict-sensitive actions.
- Do not silently delete, reschedule, or rewrite user data from AI output.
- LLM output must be treated as untrusted. Validate structured output before use.
- For AI-required commands, local AI failure, invalid JSON, or low confidence must return a safe error/clarification state instead of silently guessing with a manual parser.
- Non-AI screens and direct CRUD should keep working from SQLite when local AI is offline.

Roadmap and release rules:
- `docs/project_plan.md` describes the roadmap.
- `docs/project_todo.md` is the tracked checklist. Update and tick it only when a part is actually complete.
- Before starting implementation or analysis for a roadmap item, state the active goal clearly: the project part number and the exact DOD item(s) from `docs/goal_dod_checklist.md`.
- When finishing work, state which part and DOD item(s) were completed, which verification was run, and whether the todo/checklist status changed.
- Each major change must be committed and pushed as its own feature/release instead of batching many parts into one commit.
- Before marking a feature complete, run the relevant verification. For normal feature releases, use:

```powershell
npm run db:reset
npm run check
npm run build
```

- For docs-only changes, a build is not required, but still inspect the diff and commit separately.
- Never revert user changes unless the user explicitly asks. If files are already deleted by the user and the user confirms the deletion, commit the deletion.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them; don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it; don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that your changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" -> "Write tests for invalid inputs, then make them pass"
- "Fix the bug" -> "Write a test that reproduces it, then make it pass"
- "Refactor X" -> "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```text
1. [Step] -> verify: [check]
2. [Step] -> verify: [check]
3. [Step] -> verify: [check]
```

Strong success criteria let you loop independently. Weak criteria such as "make it work" require clarification.

---

**These guidelines are working if:** diffs stay focused, rewrites decrease, and clarification happens before implementation mistakes.
