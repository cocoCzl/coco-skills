# Downgrade Rules

Use these rules to decide Reference Grade, Model Confidence, Data Confidence, and when to stop.

When model probability and no-vig market probability are available, run
`scripts/grade_calculator.py` first. Treat its grade as the maximum mechanical
grade after edge thresholds and hard caps; the agent may downgrade further for
football context, but should not upgrade above the scripted cap without new
verified information.

## Reference Grades

**A**: Strong model support and strong data confidence. Requires current fixture, odds, team context, and no unresolved major source conflict. Do not assign A close to kickoff without late lineup/injury/weather/market context.

**B**: Usable lean with moderate uncertainty, single-source odds, incomplete late data, or modest value edge.

**C**: Weak lean, observation only, high variance, limited data, or poor market value.

**Pass**: Value insufficient, data insufficient, source conflict unresolved, market inconsistency unresolved, or risk too high.

Youth teams, age-group teams, and women's matches are unsupported for formal purchase plans. They should be marked `Pass` for purchase-plan purposes even when fixture and odds data are present.

## Model Confidence

Model Confidence describes the strength of the football outcome view:

- High: expected goals, score concentration, market direction, and context broadly agree.
- Medium: the model has a clear lean but meaningful uncertainty remains.
- Low: the model view is fragile, highly sensitive to assumptions, or internally split.

## Data Confidence

Data Confidence describes completeness and freshness:

- High: current data is sourced, timestamped, and mostly consistent.
- Medium: some useful data exists but one or more categories are single-source, stale, or incomplete.
- Low: major current data is unavailable, stale, conflicting, or unverified.

## Probability Analysis vs Value Judgment

Probability Analysis is allowed without odds.

Value Judgment requires verifiable Odds Data. If odds are missing or unconfirmed, say that value judgment is unavailable and do not imply something is worth buying.

## Late Calibration

When a match is close to kickoff, missing or unconfirmed lineups, injuries, weather, or market movement prevents an A grade. Continue with Base Analysis only if the user accepts elevated uncertainty.

Use `scripts/late_update_rules.py` when timing inputs are structured:

- More than 12 hours before kickoff: early analysis is capped at `B`.
- Two to six hours before kickoff: attempt or request injury, lineup, and market updates.
- Within 60 minutes of kickoff: missing confirmed lineups prevent A grade.
- Match-result odds movement of at least 0.08 creates a warning.
- Match-result odds movement of at least 0.15 requires reevaluation.
- Handicap-line or total-goals center movement requires reevaluation.
- Already-started matches or matches not confirmed available for sale do not receive new pre-match purchase plans.

## Withhold Reference Purchase Plans

Withhold Reference Purchase Plans or Portfolio Variants when:

- Fixtures cannot be confirmed.
- Home/away or neutral-site context is unknown.
- Odds are required for value judgment but unavailable.
- Core source conflicts remain unresolved.
- Data confidence is low across multiple matches.
- Portfolio Correlation risk is high and cannot be explained or reduced.
- Team type is unsupported, including youth teams, age-group teams, or women's matches.
- Team type is unknown and no suitable same-type competition parameter pool can be verified; in that case keep analysis-only or cap at `C`.
- Conservative main plans depend on C-grade legs, hand-set xG without structured inputs, unconfirmed lineups near kickoff, weak score coverage, or material total-goals tail risk.

Withhold "模型最稳" / "稳健方向" labels when:

- The leg is B/B-minus and has single-source odds, unconfirmed lineups, or missing late injury/weather/market context.
- The leg has a one-goal score path in Top 3/protection candidates but the chosen handicap or total-goals selection excludes that path.
- The leg has red-card, penalty, weather-delay, altitude, home-crowd, chase-game, goal-difference, or 5+ goal tail risk and the chosen total-goals selection stops below 5 without backup.
- `scripts/preflight_risk_audit.py` returns a blocking issue.

## Total-Goals Tail Downgrades

Downgrade or withhold narrow totals and exact-score core tickets when:

- Final xG total is high enough to make the score matrix diffuse.
- A favorite is on a deep handicap and both "controlled win" and "blowout" scripts are plausible.
- Final-round group context creates goal-difference or best-third-place pressure.
- 5+ goal tail probability is material but the ticket only covers 2/3/4 or low exact-score clusters.
- A low-total assumption is based only on "淘汰赛谨慎" while event-risk flags make 4/5 goals plausible.

In these cases, either widen the total-goals set, move the leg to a high-variance optional plan, or mark it Pass for conservative portfolios.

## One-Goal Path Protection

Do not let a ticket contradict the score matrix. If `0:1`, `1:0`, or any one-goal total appears in Top 3 or explicit protection candidates:

- A total-goals ticket must include 1, or be downgraded/paired with a backup.
- A deep handicap ticket must include the handicap outcome implied by that one-goal score, or be downgraded.
- A direction-only leg may remain as probability analysis, but it must not be labelled "模型最稳" unless the omitted path is explicitly explained and protected elsewhere.

## Language Guardrails

Forbidden certainty and pressure language:

- 必中
- 稳赢
- 稳胆
- 包中
- 必买
- 重仓
- 这单稳了
- 回本
- 翻本

Forbidden advice categories:

- Personalized stake size.
- Bankroll allocation.
- Kelly bet size.
- Recovery betting.
- Chasing losses.

Ticket-tier totals are allowed only when expressed as unit-count math, such as `8 注 x 2 元/注 = 16 元`. Do not turn this into bankroll allocation or pressure language.

Rewrite direct commands into Reference Purchase Plan wording. For example, use “基础比分覆盖可作为参考，结构是 2 x 2 x 2 x 2 = 16 注” instead of “买这个”.

## Missing Data

Mark missing current data as unconfirmed. If missing data is critical, ask the user for it instead of forcing a recommendation.
