# Super Lotto and Double Color Ball Number Recommendation Skill

[中文](README.md)

This local-first, auditable Skill recommends numbers for China Sports Lottery Super Lotto (DLT) and China Welfare Lottery Double Color Ball (SSQ). On first use it synchronizes official draw history; later requests update only newly available draws. DLT requires continuous coverage from its first draw. SSQ currently requires continuous coverage from the official, publicly available range starting at `2013001`, and the output states that scope.

## What it does

- Synchronizes, archives, and validates official draw history.
- Reports whether the history is continuous and current.
- Produces random historically unseen combinations, hot-number-biased selections, or cold-number-biased selections.
- Produces multiple tickets and can avoid complete combinations previously generated in the local audit log.
- Runs reproducible historical backtests for random, hot, and cold strategies; the legacy linear hot strategy is retained as a control.
- Returns compact Chinese number results and data status directly in chat.

Results stay in chat unless the user asks to save a file, in which case reports go to `reports/lottery-number-recommendation/`. Official history and the recommendation audit log stay under `data/lottery-number-recommendation/` in the current workspace.

## Boundaries

- It does not make guarantees about winning, returns, or probability advantage.
- It does not bypass anti-bot controls, CAPTCHAs, logins, or other access restrictions.
- It supports standard single tickets only: DLT 5+2 and SSQ 6+1. It does not support dantuo, multiple, add-on, purchase, or payment workflows.
- It does not generate fallback numbers when official data is incomplete.

## Hot-number method

For both games, `hot` combines frequencies from 0.25×, 1×, and 2.5× the requested window with weights of 20%, 50%, and 30%. Frequencies are smoothed against the expected rate for each number zone, then capped to weights from 0.75 to 1.50. This gives recent frequency a limited influence without allowing short-term noise to dominate. The default backtest samples each strategy 200 times per draw and reports a 95% interval relative to the random baseline for the selected historical range.

## Installation

```bash
cp -R lottery-number-recommendation ~/.codex/skills/
```

For end-user setup, automatic synchronization, and Chinese chat examples, see [`examples/lottery_number_recommendation/README.md`](../examples/lottery_number_recommendation/README.md). Agent instructions are in [`SKILL.md`](SKILL.md). Official sources, access limits, and scope upgrades are documented in [`references/official-sources.md`](references/official-sources.md).

## Development checks

Use the offline diagnostic to inspect local cache state. Natural-language requests should still use `parse-request` first:

```bash
python3 lottery-number-recommendation/scripts/lottery_skill.py doctor
python3 lottery-number-recommendation/scripts/lottery_skill.py parse-request '双色球三注强热号'
```

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/check_all_skills.py
```
