---
trigger: always_on
---

AI_ENGINEERING_RULES

Core:
- Solve current requirements only.
- Prefer the simplest correct solution.
- Prefer explicit code over abstraction.
- Prefer direct logic over indirection.
- Prefer modification over creation.
- Prefer existing patterns over new patterns.
- Prefer built-in libraries over external dependencies.
- Correctness > Simplicity > Readability > Maintainability > Performance > Extensibility.

Requirements:
- Implement only explicitly requested behavior.
- Do not assume future requirements.
- Do not add speculative features.
- Follow YAGNI.

Simplicity:
- Prefer if/else over dispatchers.
- Prefer direct execution over routing systems.
- Prefer functions over classes.
- Prefer inline logic over unnecessary helpers.
- Prefer fewer files, layers, and dependencies.

Abstractions:
- Every abstraction must solve a real current problem.
- Every abstraction must reduce overall complexity.
- Every abstraction must justify its existence.
- If simpler code works, use simpler code.

Functions:
- Do not create helpers that add no value.
- Avoid single-use functions unless they improve readability, isolate complex logic, or improve testability.
- Keep logic close to where it is used.

Classes:
- Use classes only when state, behavior grouping, polymorphism, or architecture requires them.
- Do not create classes for simple procedural logic.

Files:
- Minimize file count.
- Split files only when readability or module boundaries require it.

Dependencies:
- Use standard library first.
- Reuse existing dependencies when possible.
- Add dependencies only when necessary.

Refactoring:
- Do not refactor working code without a clear reason.
- Valid reasons: bug, performance issue, maintainability issue, explicit request.
- Personal preference is not a valid reason.

Codebase Exploration:
- Read relevant files before coding.
- Understand existing architecture.
- Understand existing patterns.
- Reuse established approaches.

Complexity:
- Complexity is a cost.
- Every function, class, file, dependency, layer, and abstraction must provide measurable value.
- Prefer the lowest-complexity solution that satisfies requirements.

Layers:
- Prefer Input→Processing→Output.
- Avoid unnecessary intermediate layers.
- Every layer must justify itself.

Testing:
- Verify functionality.
- Verify edge cases.
- Verify error handling.
- Verify existing behavior is not broken.

Self Review:
- Remove unnecessary functions.
- Remove unnecessary classes.
- Remove unnecessary files.
- Remove unnecessary abstractions.
- Remove dead code.
- Remove duplication that genuinely harms maintainability.
- Remove speculative code.

Final Check:
- Can this be solved with fewer files?
- Can this be solved with fewer functions?
- Can this be solved with fewer classes?
- Can this be solved with fewer dependencies?
- Can this be solved with fewer abstractions?
- If yes, simplify.

Completion:
- Requirement satisfied.
- Existing patterns followed.
- No speculative features.
- No premature abstractions.
- Minimal complexity.
- Tested.
- Self-reviewed.
- Simplest correct solution delivered.