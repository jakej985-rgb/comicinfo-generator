Read plan.md completely before making any changes.

First, inspect the entire repository and understand the existing architecture,
including all providers, metadata resolution, ComicInfo generation, archive
writing, caching, automation, CLI, web UI, and tests.

Do NOT start coding immediately.

Before implementing the remediation plan, create and populate:

docs/
├── architecture.md
├── metadata-resolution.md
├── provider-contract.md
├── archive-safety.md
├── automation.md
└── testing.md

These must document the ACTUAL current implementation, not an imagined
architecture.

Then compare the current implementation against plan.md and identify:
- What already exists
- What is partially implemented
- What is missing
- What needs to be replaced
- What is unsafe
- Any assumptions in plan.md that need adjustment based on the actual code

Do not remove working functionality just to match the plan.

After the documentation and gap analysis are complete, implement plan.md
in the specified priority order.

Important:
- Do not rewrite the project from scratch.
- Preserve working functionality.
- Make changes incrementally.
- Run tests after each major phase.
- Do not make destructive filesystem changes.
- Do not automatically rename/recreate comic library directories.
- Never silently overwrite existing ComicInfo metadata.
- Do not silently accept low-confidence comic matches.
- Keep the application usable throughout the migration.

At the end of each phase:
1. Run the relevant tests.
2. Fix failures before moving on.
3. Update the documentation if the implementation differs from the plan.
4. Summarize what changed.

Do not skip phases simply because the current code appears to work.