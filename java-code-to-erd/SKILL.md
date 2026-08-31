---
name: java-code-to-erd
description: Analyze Java project source, ORM mappings, Mapper SQL, JDBC SQL, DDL, Flyway, and Liquibase to reconstruct an evidence-backed database model and generate Mermaid ERD, DBML, and Markdown reports. Use for Java table/column/relationship discovery or code-to-ERD requests. Do not use for non-Java projects, live database connections, forward database design, or ordinary Java code review.
---

# Java Code to ERD

Reconstruct the database model expressed by a Java repository. The result describes project evidence, not a live database.

## Non-negotiable boundaries

- Never connect to a database, execute SQL or migrations, build/run the target project, access the network, or install software.
- Analyze repository source and project files only. Exclude tests, examples, build outputs, dependencies, external JARs, and paths outside the project unless the user explicitly includes test sources.
- Do not infer a confirmed relation from names alone. Preserve unknowns, conflicts, conditional facts, and unsupported constructs.
- Generate every artifact from the validated `database-model.json`; never produce an ERD directly from an ad-hoc reading.
- Evidence stores project-relative path and line range only—no source snippets.

## Workflow

Read [references/workflow.md](references/workflow.md), [references/data-model.md](references/data-model.md), and [references/confidence-and-conflicts.md](references/confidence-and-conflicts.md) for every analysis.

1. Run `doctor`, then `analyze` through the compatibility launcher. It selects an already-installed Python 3.10+ and never installs one:

   ```bash
   python3 <skill-dir>/scripts/launch.py doctor --project <project-root>
   python3 <skill-dir>/scripts/launch.py analyze --project <project-root>
   ```

2. Read only the detected framework rules listed in the result's `rule_references`.
3. Inspect `unresolved` and `conflicts`. Use repository reading to resolve only what static evidence supports; record manual confirmations with `review`, never by editing generated facts.
4. Re-run analysis after review or scoped inspection.
5. If Mermaid SVGs were produced, inspect them for clipping, overlap, density, labels, direction, and legend. Read [references/output-and-visual-quality.md](references/output-and-visual-quality.md).
   After every generated SVG passes that inspection, run `verify-visuals --project <project-root>` so the model and report record `VERIFIED`. Never run this command before actually viewing all SVGs.
6. Report `COMPLETE` only when the model validates and no material file, unsupported data path, unresolved construct, or conflict remains. Otherwise report `PARTIAL`; use `FAILED` only when no valid core model can be produced.

## Request modes

- Full project: `analyze` (default), writes stable artifacts under `reports/java-code-to-erd/`.
- Scoped module/package/table: add `--scope <text>`; discovery remains repository-wide.
- One object: `query --object <table>`; returns chat-ready JSON and writes nothing unless `--save` is supplied.
- Human review: `review --action confirm|exclude --from-table ... --from-column ... --to-table ... --to-column ...`.

Detailed Java/JPA, MyBatis, JDBC, SQL, and migration rules live under [references/rules/](references/rules/) and are loaded only when routed by detected technology.
