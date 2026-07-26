# Workflow

Follow this workflow before producing any football betting report.

## Runtime Modes

**Agent mode**: Use when browsing, search, local files, configured APIs, or calculators are available. Actively perform Fixture Discovery, Live Verification, data collection, and model calculation.

**Assisted context mode**: Use when the user or local files provide partial data. Validate what is supplied, identify gaps, and ask only for missing critical fields.

**Offline fallback mode**: Use when no live tools are available. Use only user-provided data and never invent current fixtures, odds, lineups, injuries, or weather.

## Request Classification

Classify the user request as one of:

1. Single-Match Analysis.
2. Betting Portfolio, full-slate analysis with ticket limits by market family.
3. Post-Match Review.
4. Historical Backtest / Calibration.

If the user asks for 6, 8, 10, or more matches in a portfolio, analyze every fixture individually. Do not ask them to reduce the slate before analysis. Apply limits only when constructing ticket plans: exact-score tickets up to four matches; 胜平负 / 让球胜平负 direction tickets up to eight matches; 大小球 / 总进球 direction tickets up to eight matches.

If the user asks to improve hit rate, accuracy, calibration, or model quality, route to Historical Backtest / Calibration. Do not claim the skill can improve future outcomes without measured historical evidence.

## Single-Match Analysis Flow

1. Confirm teams, competition, kickoff time, timezone, and home/away or neutral venue.
2. Collect Odds Data when Value Judgment is requested or implied.
3. Collect Team Form Window and current team context: recent form, injuries/lineups, schedule density, motivation/competition context, weather/venue context, and relevant market movement when tools or authorized providers are available.
4. For group-stage matches, collect current standings or played results. If played results are available, calculate standings and motivation flags with `scripts/competition_context_calculator.py`.
5. Build a Data Summary Table.
6. Estimate expected goals from attack/defense strength, venue, competition scoring environment, and recent form. Prefer `scripts/xg_prior_calculator.py` when xG/xGA and league-average inputs exist.
7. Apply bounded Bayesian-style updates for injuries, lineups, motivation, schedule, weather, and market movement. Show the code/range when using `references/model-parameters.md`; otherwise label the adjustment qualitative.
8. Use the Poisson model to derive result, goals, and score probabilities. Use `scripts/poisson_calculator.py` when available; otherwise label the probabilities approximate.
9. Compare model probabilities with implied probabilities when odds exist.
10. Apply edge thresholds and downgrade rules. Prefer `scripts/grade_calculator.py` when model probability and no-vig market probability exist.
11. Before final purchase-plan output, apply `scripts/late_update_rules.py` when kickoff timing, lineup status, sales availability, or odds movement data are available.
12. If a single-match recommendation includes a formal ticket leg, run or manually apply `scripts/preflight_risk_audit.py` checks against the structured record. Resolve blocking issues before using "模型最稳" or "稳健方向" language.
13. Produce the Single-Match Report template.

Single-match reports must include a visible evidence chain:

- 数据来源：name the source categories used, such as official fixture page, odds aggregator/bookmaker, team news outlet, stats site, weather source, or user-provided data.
- 基础面：form, attack/defense, injuries/lineups, venue/weather, motivation/schedule.
- 数学模型：prior xG, bounded Bayesian adjustments, final xG, Poisson concentration, and result/total-goals probabilities.
- 玩法判断：separate probability lean from odds value.
- 风险：why the grade is not higher, and what late information could change it.

For group-stage final-round matches, calculate qualification context before treating motivation as a model adjustment. Include current points, goal difference, ranking routes under plausible results, rotation probability, and potential knockout-stage opponents. Use motivation flags such as `already_in_advance_zone`, `draw_may_be_sufficient`, `third_place_race`, `must_win_pressure`, and `route_selection_risk`. Treat "避强队" or "选路线" only as a motivation/risk modifier, not as certain team behavior. For World Cup, Euro, Copa America, Asian Cup, AFCON, and similar tournament final-round group matches, complete structured group context is required for any formal "模型最稳" or "稳健方向" plan; if it is missing, mark the match `group_context_missing`, explain the missing standings/routing fields, and exclude that leg from the main plan.

## Betting Portfolio Flow

1. Confirm the full concrete fixture slate. For 6, 8, 10, or more matches, keep the full slate in the report and analyze every match.
2. Default to the 经理人详版 for 四串一, 串关, "明天第三轮", "明天早上", and multi-group final-round requests unless the user asks for a short answer. Use this order: 先给全场次结论 -> 北京时间比赛清单 -> 小组当前战绩/积分/出线形势 -> 玩法可买性 -> 赔率与市场中心 -> 模型怎么来的 -> 全场逐场分析 -> 模型最稳主单 -> 比分4串1 -> 方向类组合 -> 备选/替换 -> 可选小组合 -> 组合风险.
3. Start with a 北京时间比赛清单 / 今日赛程确认 section that lists every match, exact kickoff time in the user's timezone, group/competition, venue context, and current data confidence. If the user says "明天", convert it to an exact date using the current date and timezone.
4. For tournament group-stage slates, verify or calculate current group ranking, points, win-draw-loss record, goal difference, qualification pressure, rotation risk, and potential knockout-route context before using motivation as a model adjustment. If played results are available, run `scripts/competition_context_calculator.py`; if unavailable, show an "未确认" cell and downgrade data confidence instead of omitting the section. For final-round group slates, do not upgrade a match into the "模型最稳" or "稳健方向" main plan unless both teams have matched structured group context.
5. Build a compact 赔率与市场中心 section before the match notes. When correct-score odds are available, list the lowest-price score cluster for each match and explain what the market center implies.
6. Explain the math model in user-readable language before or during the match notes: expected-goals prior, bounded Bayesian adjustment direction, final xG, Poisson score concentration, odds implied/no-vig probability when odds exist, edge/grade caps, and whether the calculator/script or an approximation was used.
7. Run the Single-Match Analysis flow in compact but substantive prose for each match before giving any portfolio plan. Each match should read like a decision note, not only a row in a table.
8. For each match, include source notes, group/table context, basic football context, match script, model record, result lean, handicap lean, over-under/total-goals lean, score ranking, reference grade, and risk.
9. Check Portfolio Correlation: competition stage, same group/table incentives, rotation, weather clusters, and shared market assumptions.
10. Exclude Pass matches or matches with severe Information Sufficiency gaps from tickets, but still show their single-match analysis and explain why they are not in the main plan.
11. Build portfolio variants from the actual model confidence, score concentration, market availability, and user intent. Do not force fixed 2/16/32/48 元 tiers or force a 4/6/8-leg ticket. Conservative main plans must inherit the risk paths described in the analysis: use `risk_flags`, `tail_risk_flags`, `protection_candidates`, `must_protect_selections`, score candidates, and handicap line to expand, downgrade, or exclude narrow legs before calculating units.
12. Run `scripts/score_coverage_analyzer.py` and `scripts/portfolio_builder.py` when structured graded legs exist, then run `scripts/preflight_risk_audit.py` on the report input or prediction snapshot before final naming. Any blocking audit issue must be resolved by protection, downgrade, or removal before a leg can remain in "模型最稳" or "稳健方向".
13. Apply ticket limits by market family: exact-score tickets may use up to four matches; 胜平负 / 让球胜平负 direction tickets may use up to eight matches; 大小球 / 总进球 direction tickets may use up to eight matches. Mixed tickets may use up to eight matches, but if exact-score legs dominate, keep them to four matches.
14. If the strongest fourfold contains any obvious risk leg (missing group context, low data confidence, high rotation risk, route-selection risk, market/result conflict, audit block, or unprotected tail), also provide a "更稳三串一" that removes the riskiest leg. If fewer than three low-risk eligible legs remain, provide a "更稳二串一" and explain why the model did not force three legs.
15. Add named portfolio variants when supported by the data: 模型最稳主单, 更稳三串一/二串一, 让球/胜平负方向单, 大小球/总进球单, 单比分主推小单, 比分4串1, 基础比分覆盖, 增强比分覆盖, 混合过关单, 备选/替换, 可选小组合, 补洞单, and 搏冷/高赔率小单. Keep speculative variants clearly optional and high variance.
16. Provide More Combination Candidates only when there are extra plausible directions, and keep them separate from the main plans.
17. Provide Score Coverage for every analyzed match. Use up to four scores per match only when a match has a meaningful secondary path, such as late-goal expansion, red-card tail risk, draw protection, favorite-underperformance risk, or underdog transition threat.
18. Produce the Portfolio Report template.

Do not output a single "only correct" portfolio. If enough data exists, always offer separate market-family plans plus optional alternative combinations.

When the user asks for 比分、胜平负、大小球 together, cover all requested families:

- 让球/胜平负方向单: use only markets confirmed as buyable from the user's screenshot/source, up to eight legs. If ordinary 胜平负 is unavailable, state it is analysis-only and build the ticket from 让球胜平负 or another visible market.
- 大小球/总进球单: provide at least one pure total-goals or over-under structure when the market exists in the supplied odds, up to eight legs.
- 比分单: provide single-score, core coverage, enhanced coverage, and补洞 score sets with complete score lists for every match, but put only the four best score-concentration matches into a 比分4串1 ticket.
- 半全场单: include only when the user explicitly asks for 半全场 / 半场胜平负 / HAFU / 竞彩半全场 and verified HAFU odds exist; keep it as high variance and optional, with at most four legs.
- 混合过关单: combine the strongest buyable direction legs with totals or selected scores to reduce dependence on exact-score hits. Describe it as higher tolerance than pure score strings, not as a guarantee.

Do not compress portfolio analysis into only one summary table. The user should see why each match is included: source notes, model direction, top scores, risk, and grade.

For score portfolios, the default answer should be detailed enough that a user can understand why a 2:0 is preferred over 3:0, why a favorite may win but not cover, and which draw or underdog-goal score is the most important missing path. Avoid terse "model summary only" reports when data is available.

## Ticket Tier Construction

Construct the ticket structures from the full match slate:

- Start with the model's most defensible main plan, often using 胜平负, 让球胜平负, 大小球, or 总进球 rather than exact score for every match. The main plan may be 2串1, 3串1, 4串1, 5串1, 6串1, 7串1, or 8串1 depending on confidence; do not force a leg count.
- In conservative mode, exclude Pass, C-grade, unavailable, low-data, and weak score-coverage legs from main plans. Use `scripts/portfolio_builder.py` when structured graded legs are available.
- In tournament final-round group slates, exclude `group_context_missing` legs from the main plan. If a fourfold remains but includes high rotation or route-selection risk, create a reduced threefold from the lowest-risk legs.
- For score portfolios, identify each match's core score cluster first, then decide whether it deserves one, two, three, or four score candidates.
- For exact-score tickets, select only the four matches with the strongest score concentration and acceptable data confidence.
- Use `scripts/score_coverage_analyzer.py` or the same thresholds before including exact-score legs. Diffuse score matrices should stay out of the core portfolio.
- For 胜平负 / 让球胜平负 tickets, select up to eight matches with the strongest direction confidence and confirmed buyable markets.
- For 大小球 / 总进球 tickets, select up to eight matches with the clearest total-goals or over-under edge.
- Use wider coverage on the most volatile match, not mechanically on the first match.
- Do not omit a 1-goal total path from a totals/deep-handicap ticket when `0:1`, `1:0`, or a one-goal score is inside Top 3 or explicit protection candidates.
- Do not omit the 4/5-goal tail from a narrow totals ticket when structured risk flags show red-card, penalty, weather-delay, altitude, home-crowd, chase-game, goal-difference, or 5+ probability risk. Widen, downgrade, or move the leg to optional high variance.
- Treat "covered in analysis but omitted from the ticket" as a portfolio construction error. A `+1` leg with an explicit opponent one-goal-win path needs `让平` protection or downgrade; a `-1 让负` leg with meaningful favorite-cover scores needs protection or downgrade.
- If the user proposes their own score list, evaluate it directly: say what is合理, what is漏防, and how to补洞 if they have already bought it.
- Show every ticket as `A x B x C... = N 注`; amount is `N x 2 元/unit = X 元` unless the user gives a different unit price.

Use 2 元 per unit by default only for explaining total amount, not for bankroll advice. If the user's local lottery unit price differs, state the assumed unit price and let the user adjust.

Default named portfolio variants:

- 模型最稳主单 / 稳健方向单: selects the strongest buyable legs across market families from the full slate; fewer legs are better than forcing weak matches.
- 让球/胜平负方向单: uses buyable ordinary result or handicap result markets rather than fragile exact scores.
- 大小球/总进球单: uses over-under or discrete total-goals markets when visible in the supplied odds.
- 稳健方向单: uses result, handicap result, over-under, or total-goals directions rather than fragile exact scores.
- 基础比分覆盖: uses the most concentrated score candidates from the Poisson matrix.
- 增强比分覆盖: adds one plausible secondary path for the highest-variance match or for a favorite that may only win narrowly.
- 混合过关单: combines buyable direction, total-goals, and limited score legs. It is usually less exact-score-dependent than a pure score fourfold, but still has串关 risk.
- 补洞单: covers the most obvious omitted path, such as favorite 1:0, draw drag, underdog goal, or late score expansion.
- 搏冷/高赔率小单: uses lower-probability but explainable outcomes; label it optional, high variance, and not the core plan.
- 备选/替换: lists which matches can replace a risky leg, why the replacement is more conservative or more aggressive, and which ticket it affects.
- 可选小组合: groups 2串1, 3串1, or 4串1 alternatives by stability, value, or score concentration.
- 更稳三串一 / 更稳二串一: removes the riskiest leg from a fourfold or avoids forcing a threefold when only two legs remain defensible.

Write full selections in every score coverage cell. Do not write "加 2:1"; write the complete set, such as `2:0 / 3:0 / 2:1`.

## HTML Report Output

Completed pre-match Single-Match Analysis and Betting Portfolio analysis should produce an HTML Report by default when local file writes are available.

1. Use the data priority from `references/data-sources.md`: configured API first, then user-provided odds/lines/table/screenshot, then public/authorized web lookup, then no-odds downgraded analysis when enough fixture and team context exists.
2. Do not generate a full formal prediction report when critical fixture or team context is missing. Ask for the missing inputs when the missing context blocks the requested conclusion; otherwise generate only a downgraded snapshot/context report with explicit gaps.
3. If actual odds/lines are unavailable but fixture and team context are sufficient, generate the report with Data Status `no-actual-odds-lines`. State that Ticket Plans are probability/reference structures, not complete value judgments.
4. Build structured report JSON according to `schemas/html-report.schema.json`.
5. Run `scripts/render_html_report.py <json-input> --out-dir reports/football-betting-assistant` from the current working directory. The renderer writes one self-contained HTML file and prevents overwriting by suffixing duplicate filenames.
6. Do not generate Markdown reports for completed pre-match analysis.
7. Keep the chat response to 2-4 concise summary lines plus the HTML path. Do not paste the full report into chat after successful HTML generation.
8. Treat generated report files as local outputs, not source files to commit.
9. Do not automatically open the HTML file unless the user explicitly asks.

## Post-Match Review Flow

1. If the user does not provide a report ID, prediction path, or match name, run zero-operation review with `scripts/auto_post_match_review.py`.
2. Scan saved prediction snapshots under `data/football/predictions/`. Default to the last 30 days; use all history only when the user explicitly asks.
3. Confirm actual results from user-provided results, configured result providers, or public/authorized web verification. Preferred configured providers are `FOOTBALL_DATA_API_KEY`, `API_FOOTBALL_KEY`, and `THE_ODDS_API_KEY`; public web lookup is a fallback when tools are available.
4. Match results to predictions by stable fixture IDs when available; otherwise use match name, kickoff time, competition, and team names. Low-confidence matches must be skipped and listed as `final_result_not_verified` or low-confidence identity, not forced into the review.
5. Use `scripts/auto_post_match_review.py` to write a review bundle under `data/football/reviews/` and a Chinese HTML Review under `reports/football-betting-assistant/`. Use `scripts/post_match_review.py` only for an exact single-snapshot/single-score helper flow.
6. Compare expected goals, score candidates, odds value, ticket legs, and risk points with the actual outcome.
7. Separate result-direction, handicap, over-under/total-goals, and exact-score review. A direction hit must not hide a total-goals or score-coverage miss.
8. Identify model bias, data bias, and portfolio-construction bias separately. If the actual score or handicap outcome was present in score coverage or protection candidates but not in the main ticket, label it a construction error and tighten protection/downgrade rules instead of pretending the model never saw the path. For high-scoring misses, specifically check whether total xG, deep handicap, must-win/goal-difference pressure, or red-card/late-game tail risks were underweighted.
9. Do not produce chase-loss, recovery-bet, or "下一场翻本" advice.

Do not backfill post-match information into the original pre-match prediction. Save review output separately under `data/football/reviews/` or an equivalent generated-output directory.

## Historical Backtest / Calibration Flow

Use this flow when the user wants to improve hit rate, audit predictions, or evaluate historical model quality.

1. Require historical pre-match snapshots: fixture, kickoff time, odds/line observed before kickoff, team context observed before kickoff, model probabilities, score candidates, reference grade, and actual result.
2. Reject or flag samples that mix in post-match information. If a field was not known before kickoff, mark it unavailable rather than backfilling it. Legacy manually assembled predictions must be normalized before review/backtest, and missing probabilities/lines/grades remain unavailable.
3. Validate samples with `scripts/validate_inputs.py` when they are supplied as JSON bundles.
4. Run `scripts/backtest_predictions.py` on the historical sample file when local execution is available.
5. Report hit rates for match result, over-under, and score coverage separately. Do not collapse them into one "命中率".
6. Report probability calibration with Brier score, log loss, and probability buckets. Favor better-calibrated probabilities over louder single-pick language.
7. Break results down by `reference_grade`, `model_confidence`, `data_confidence`, competition, and market type when sample size allows.
8. Convert findings into specific rule changes, such as downgrading low-data A/B picks, widening score coverage for high-total matches, checking 5+ goal tail before 2/3/4 total-goals tickets, or passing single-source odds edges below the edge threshold.
9. State sample size and limitations before giving model-improvement conclusions.

## Final Checks

Before answering:

- Separate Probability Analysis from Value Judgment.
- Check Market Consistency.
- Check kickoff/sales availability and late-update rules; do not create a new pre-match purchase plan after kickoff or when sales availability cannot be confirmed.
- Check source timestamps and data gaps.
- Apply Reference Grade and confidence rules.
- Run or manually apply the preflight risk audit: no B-grade/B-minus single-source or lineup-unconfirmed leg in "模型最稳"; no unprotected one-goal/deep-handicap path; no unprotected material 4/5-goal tail.
- For backtests, check that every sample used only pre-match data and that sample size is shown.
- For high-total or deep-handicap matches, check whether 5+ goal tail probability or goal-difference pressure should block narrow total-goals tickets and exact-score core tickets.
- For group-stage final-round matches, check that qualification context uses potential knockout-stage opponents instead of assuming the next opponent is always a round-of-16 opponent.
- Remove certainty, pressure, bankroll-allocation, personalized stake-size, and chase-loss language.
