# Backtesting And Calibration

Use backtesting to improve decision quality with measured evidence. The goal is better-calibrated probabilities and clearer Pass rules, not certainty.

## Required Sample Shape

Every historical sample must be a pre-match snapshot plus the final result:

- Fixture identity, kickoff time, competition, and venue context.
- Odds and lines observed before kickoff, with source and timestamp.
- Team context observed before kickoff, with source and timestamp.
- Model probabilities and score candidates created before kickoff.
- Reference grade, model confidence, data confidence, and risk points.
- Actual full-time score and derived market outcomes.

Do not use post-match xG, post-match reports, or final lineup knowledge unless it was actually available before kickoff. Legacy manually assembled prediction files may be converted into standard prediction snapshots for review, but every missing probability, line, grade, lineup, or market field must remain unavailable.

## Metrics To Report

Report each metric separately:

- 胜平负命中率: whether the highest model result probability matched the actual result.
- 大小球命中率: whether the model's over/under lean matched the final total against the observed line.
- 总进球覆盖率: whether the discrete total-goals set covered the final total, and whether 5+ / 6+ / 7+ tails were omitted when pre-match tail risk was material.
- 比分覆盖率: whether the final score was included in Top 1, Top 3, or the supplied coverage set.
- 组合构造错误率: whether the final score or handicap outcome was present in score coverage / protection candidates but omitted from the actual ticket leg.
- 票腿命中率: evaluate saved ticket legs separately from model probability leans; do not let a correct score coverage hide a failed purchase-plan leg.
- Brier score: lower is better for probability calibration.
- Log loss: lower is better; heavily penalizes confident wrong forecasts.
- Calibration buckets: compare predicted probability buckets with actual hit rates.
- Grade breakdown: A/B/C/Pass sample count and hit rate.

## Improvement Rules

Only change model rules after a pattern repeats across enough samples. Good changes are concrete:

- Downgrade A/B picks when current data is single-source, stale, or conflicting.
- Add Pass when model edge is small and the odds source is not consensus.
- Widen score coverage for high total-xG matches or clear two-way scoring paths.
- Widen total-goals coverage or downgrade totals tickets when total xG is high, the handicap is deep, final-round goal-difference pressure exists, or 5+ goal tail probability is material.
- Audit one-goal paths separately: if a candidate score such as `0:1` or `1:0` was available before kickoff but the ticket omitted total goals 1 or the matching handicap result, count it as a portfolio-construction issue before changing xG priors.
- Track event-tail misses separately from ordinary low-total misses. Red cards, penalties, weather delays, altitude, home-crowd pressure, and chase-game states should trigger wider 4/5-goal protection or downgrade rules when they were knowable pre-match.
- Avoid forcing exact-score portfolios when score probability mass is diffuse.
- Do not collapse protected handicap paths into a single leg. If the model says `+1` needs one-goal-loss protection, add `让平` or downgrade; if `-1 让负` has a meaningful cover-score path, add protection or downgrade.
- If a miss was already in score coverage or protection candidates, tune portfolio construction before changing xG priors.
- Track competitions separately when tempo or rotation patterns differ.

## Report Wording

Use cautious language:

- "历史样本显示..."
- "这类场景需要降级..."
- "下一轮应优先验证..."

Avoid:

- "以后一定提高命中"
- "这个规则保证有效"
- "按回测买就行"
