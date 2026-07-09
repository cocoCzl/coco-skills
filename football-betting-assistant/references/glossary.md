# Glossary

Use these terms consistently in reports, examples, schemas, and scripts.

**Decision Aid**: A pre-match analysis output that helps a user judge probabilities, risks, and betting value. It may express a betting lean or reference portfolio, but it does not promise certainty.

**Single-Match Analysis**: Analysis focused on one football match and its available betting markets.

**Betting Portfolio**: A reference set of betting leans across more than one match. Analyze every confirmed match in the user's slate; apply ticket limits by market family rather than limiting the analysis slate.

**Match Result Market**: A market on home win, draw, or away win.

**Handicap Match Result Market**: A market on home win, draw, or away win after applying a stated goal handicap.

**竞彩让球胜平负 Mapping**: Apply the stated home-team handicap to the actual score, then judge win/draw/loss. Formula: `home goals + handicap line - away goals`; positive means `让胜`, zero means `让平`, negative means `让负`. Under a `-1` line, a favorite one-goal win such as `1:0` or `2:1` is `让平`, not `让负`.

**Correct Score Market**: A market on the exact final score.

**Over-Under Market**: A market on whether total goals finish above or below a stated goal line such as 2.5, 2.75, or 3.0.

**Total Goals Market**: A market on a discrete total-goals bucket, such as 0, 1, 2, 3, 4, 5, 6, or 7+.

**Odds Data**: Market price and line information, including the source and observation time.

**Probability Analysis**: Outcome likelihood estimates that can be produced without odds data.

**Value Judgment**: An assessment of whether odds data appears favorable relative to estimated probabilities and risk. It requires verifiable odds data.

**Fixture Discovery**: Identifying concrete matches from natural-language requests, including teams, start time, competition, and venue context.

**Source Priority**: User-provided data first, configured data sources second, public web verification third, and user clarification when current data cannot be verified.

**Transparent Model**: A simplified explainable model using expected goals, Poisson distributions, Bayesian updates, and implied-probability checks without claiming black-box precision.

**Reference Grade**: A non-guaranteed confidence and value label: A, B, C, or Pass.

**Risk Tier**: Qualitative suitability for cautious, moderate, or speculative use. It is not bankroll allocation advice.

**Ticket Tier**: A reference purchase plan stated as unit count, unit price, total amount, structure, and selections. It is a formatting and coverage tool, not personalized stake sizing.

**More Combination Candidates**: Optional alternative combinations separated from the main ticket tiers. They are not mandatory additional purchases.

**Late Calibration**: Adjusting analysis with late-breaking context such as lineups, injuries, weather, schedule congestion, or odds movement.

**Score Candidate Set**: A fixed set of three correct-score candidates for one match: primary, secondary, and upset-aware.

**Score Coverage**: Portfolio-facing score suggestions. Keep it compact by default, and expand up to four scores only when needed for a declared ticket-tier unit count.

**Market Consistency**: Result, score, total-goals, and over-under leans should tell a coherent match story. Any conflict must be recalibrated or explained.

**Portfolio Correlation**: Shared context between matches or markets, such as competition stage, table incentives, rotation, weather, or schedule pressure.

**Information Sufficiency**: Whether available match, market, and context data can support the requested analysis.

**Post-Match Review**: Retrospective analysis comparing assumptions with actual outcomes; it does not produce recovery bets.

**Agent-First Skill**: A football assistant that actively uses available tools to discover fixtures, collect odds, gather team context, and verify current information.

**Authorized Public Source**: A public or user-authorized source for fixture, odds, lineup, injury, weather, or team-context data.

**Data Source Credential**: Optional credential for football data services, distinct from large-model API credentials.

**Source Timestamp**: Source name and observation time for current data.

**Source Conflict**: A mismatch between data sources on facts, odds, lines, lineups, injuries, or context.

**Model Confidence**: Strength of the football outcome view after model and context analysis.

**Data Confidence**: Completeness, freshness, and source agreement of collected data.

**Model Basis**: Concise explanation of expected goals, score concentration, Bayesian adjustments, and odds value comparison.
