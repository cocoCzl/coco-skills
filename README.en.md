# Coco Skills

[中文](README.md)

An open-source collection of Skills for Codex and other AI agents. Every top-level Skill includes `SKILL.md` for agent instructions and a concise README for people.

## Included Skills

| Skill | Purpose | Docs |
|---|---|---|
| `ai-resume-expert` | Evidence-first resume creation, review, JD tailoring, and local PDF delivery for mainland China technical roles | [README](ai-resume-expert/README.md) · [SKILL.md](ai-resume-expert/SKILL.md) |
| `football-betting-assistant` | Chinese football betting analysis, reference combinations, post-match review, and backtesting support | [README](football-betting-assistant/README.md) · [SKILL.md](football-betting-assistant/SKILL.md) |
| `java-code-to-erd` | Evidence-backed database-model and ERD reconstruction from Java source, ORM mappings, and SQL | [README](java-code-to-erd/README.md) · [SKILL.md](java-code-to-erd/SKILL.md) |
| `lottery-number-recommendation` | Official-history validation, number generation, and backtesting support for DLT and SSQ | [README](lottery-number-recommendation/README.md) · [SKILL.md](lottery-number-recommendation/SKILL.md) |

## Install

Install a specific Skill with [skills.sh](https://skills.sh/):

```bash
npx skills add cocoCzl/coco-skills -g --agent codex --skill football-betting-assistant
```

For local development, run this from the repository root:

```bash
# List installable Skills
npx skills add . --list --full-depth

# Install a Skill from the local source tree
npx skills add . -g --agent codex --skill football-betting-assistant
```

You can also copy a Skill directory directly. For Codex:

```bash
cp -R football-betting-assistant ~/.codex/skills/
```

Remove `-g` for a project-level installation. Agent-specific install locations vary. Install only the top-level Skill source directory; do not commit or edit local runtime directories such as `.agents/`, `.claude/`, or `.pi/`.

## Use

After installation, ask for the relevant task in natural language. The agent follows each Skill's trigger conditions, workflow, and safety boundaries in `SKILL.md`. See the Skill READMEs and [`examples/`](examples/) for task-specific examples.

User-facing artifacts are written to `reports/<skill-name>/` in the current workspace. Reusable runtime data, where applicable, stays in the Skill's declared `data/` namespace rather than its install directory.

## Development

Repository development requires Python 3.10+. Before submitting changes, run:

```bash
python3 scripts/check_all_skills.py
python3 -m unittest discover -s tests -p 'test_*.py'
```

```text
skill-name/                 # Installable Skill source
  SKILL.md                  # Agent entry point
  README.md                 # Human-facing overview
  references/ schemas/ scripts/
examples/                   # Runnable examples
tests/                      # Repository tests and fixtures
evals/                      # Behavioral evaluation cases
```

See [QUALITY_STANDARD.md](QUALITY_STANDARD.md) for quality requirements and [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidance.

## License

[MIT](LICENSE)
