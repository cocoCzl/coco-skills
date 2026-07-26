# Data Sources

The assistant should actively verify current information when tools are available. Do not rely on model memory for current fixtures, odds, lineups, injuries, weather, or market movement.

## Source Priority

1. Local normalized football snapshots generated from public or user-authorized data.
2. In `china-lottery` mode, the built-in `sporttery` provider for publicly visible China Sports Lottery football data.
3. User-provided source, screenshot, table, link, or structured data.
4. Configured football data provider or API result. For international odds and lines, prefer The Odds API when `THE_ODDS_API_KEY` is configured.
5. Public web search or browser verification.
6. User clarification for missing data.

For tournament group-stage matches, standings and played results are a separate current-data category from odds. Prefer official or structured standings; if only played scores are available, normalize them and run `scripts/competition_context_calculator.py` to recompute points, win-draw-loss, goals for/against, goal difference, qualification pressure, rotation risk, and route-selection flags.

## Runtime Data Modes

**china-lottery** is the default for 中国体育彩票 / 竞彩 requests. Purchase plans may use only China Sports Lottery buyable markets from `sporttery` snapshots or user-provided China lottery data. Third-party bookmaker odds may be shown as international market reference, but they must not replace China lottery odds in a China lottery purchase plan.

**international-odds** is used only when the user explicitly asks for overseas bookmaker / international odds analysis or configures that mode. It may use The Odds API or a user-authorized bookmaker/aggregator provider.

**analysis-only** is used when fixture and football context are available but verifiable odds, lines, or buyable markets are missing. It can produce Probability Analysis, but not Value Judgment or Reference Purchase Plans.

## Built-In Sporttery Provider

The built-in `sporttery` provider is a best-effort public-data collector for current or future China Sports Lottery football pages. It is not an official stable API client and does not guarantee coverage for every date, market, or page layout.

The first provider implementation uses public endpoints and pages that are referenced by Sporttery's own public pages, including the football match-list endpoint exposed by the public schedule page. If that endpoint stops returning structured data, is blocked, or omits a market's odds, the provider must save the raw response when possible and mark the affected fields as missing or parser-failed.

Normal user flow:

1. The user asks naturally, such as "帮我看北京时间明天的几场世界杯比赛".
2. The assistant checks local snapshots under `data/football/snapshots/`.
3. If needed and local execution is available, the assistant runs `scripts/fetch_match_data.py` automatically.
4. The assistant reads the normalized snapshot and uses only confirmed buyable markets for China lottery purchase plans.
5. For completed snapshot-backed analysis, the assistant generates an HTML report and linked prediction snapshot with `scripts/build_snapshot_report.py`.
6. If odds/handicap data is missing, it applies the stop rules and asks for the minimum missing data.

Developer/debug CLI:

```bash
python3 football-betting-assistant/scripts/fetch_match_data.py \
  --mode china-lottery \
  --provider sporttery \
  --football \
  --out data/football/snapshots
```

For repeatable parser/debug checks, a local raw fixture can be supplied:

```bash
python3 football-betting-assistant/scripts/fetch_match_data.py \
  --mode china-lottery \
  --provider sporttery \
  --football \
  --raw-input tests/fixtures/football_betting_assistant/raw/sporttery-football-sample.json \
  --out data/football/snapshots
```

The provider may save raw public responses under a `raw/` subdirectory. Raw files and normalized snapshots are generated artifacts and should not be committed unless intentionally promoted to fixtures.

For market consistency checks, use the normalized snapshot rather than raw HTML. A market with `availability.status = available` and at least one priced selection may be used in a China lottery purchase plan. `unknown`, `unavailable`, and `parse_failed` markets must not be used in purchase plans unless the user supplies verified China lottery odds for that market.

Snapshot-backed report generation:

```bash
python3 football-betting-assistant/scripts/build_snapshot_report.py \
  data/football/snapshots/sporttery-football-YYYYMMDDTHHMMSS+0800.json \
  --date tomorrow \
  --competition 世界杯 \
  --topic "明天世界杯竞彩分析" \
  --report-out-dir reports/football-betting-assistant \
  --data-out-dir data/football
```

This command is a developer/debug entry point. In normal skill use, the assistant should run the collection, selection, report generation, and prediction-snapshot persistence automatically when local execution is available.

The generated prediction snapshot is saved under `data/football/predictions/` with the same `report_id` as the HTML report. It preserves source snapshot metadata, pre-match data gaps, model outputs, and ticket plans for future post-match review.

The provider must not:

- Log into accounts.
- Bypass WAF, captchas, paywalls, regional restrictions, or rate limits.
- Scan hidden endpoints aggressively.
- Treat blocked or parser-failed data as a confirmed unavailable market.

## Data Source Credentials

Data Source Credentials are optional credentials for football data providers: odds, fixtures, lineups, injuries, team stats, or weather. They are not large-model API keys.

Never write credentials into reports, examples, references, or scripts. Refer to environment variables or local configuration names only.

## Provider Configuration

This skill does not include credentials, but it may use a configured provider adapter when the current agent environment exposes one. A "configured football data provider or API result" means the current agent environment already exposes a user-authorized data capability, such as:

- MCP or tool calls for fixtures, odds, lineups, injuries, team stats, or weather.
- A local or internal HTTP service that the agent can call.
- Local JSON, CSV, database, or exported files supplied by the user.
- Environment variables or local config names that a separate adapter uses, such as `API_FOOTBALL_KEY`, `THE_ODDS_API_KEY`, or `WEATHER_API_KEY`.

Do not assume these providers exist. If no callable provider is available, use public/user-authorized sources when tools allow it, then fall back to asking the user for the minimum missing data.

## Recommended Odds Provider

For international odds and lines, the default recommended provider is **The Odds API** because it is designed for multi-bookmaker odds aggregation. The public official site shows a Starter free tier with limited credits and support for soccer, head-to-head odds, spreads/handicap, and totals/over-under markets. Use `THE_ODDS_API_KEY` only when the user or environment has configured it.

When The Odds API is available, request these markets first:

- `h2h` for 胜平负 / match result.
- `spreads` for handicap / 让球 lines.
- `totals` for 大小球 / over-under lines.

Normalize provider output into the skill's Odds Data fields, including source, bookmaker, observed time, line, decimal odds, and confidence. If multiple bookmakers are returned, summarize the consensus range and highlight outliers instead of copying every price.

## Optional Context Providers

API-Football can be useful for fixtures, lineups, injuries, team stats, standings, and some odds. Treat it as the preferred optional provider for team recent-form context when `API_FOOTBALL_KEY` is configured, not as the default China lottery buyable-market source.

football-data.org can provide fixtures, standings, and results for supported competitions when `FOOTBALL_DATA_API_KEY` is configured. It is useful for club competition context but does not replace China lottery odds.

TheSportsDB and OpenLigaDB can be used as low-friction public fallback sources for limited fixtures/results context when their coverage fits the competition. They should be treated as lower-depth context sources, not complete odds or lineup providers.

For recent-form-to-model conversion, use `references/model-parameters.md` and `scripts/recent_form_to_xg.py`. API-Football is the preferred enhanced team-context source; football-data.org and public fallback sources can supply fixtures, results, standings, and goals for/against proxies when xG/xGA are unavailable. Missing provider keys should downgrade precision, not block the whole analysis.

## Post-Match Result Providers

For post-match review, final scores are a separate data category from China lottery odds. Prefer configured providers in this order when available:

1. `FOOTBALL_DATA_API_KEY` for supported competition fixtures and finished scores.
2. `API_FOOTBALL_KEY` for broader fixture/result coverage.
3. `THE_ODDS_API_KEY` scores endpoints for sports/competitions covered by the configured sport keys.
4. User-provided result JSON, screenshot, table, or link.
5. Public web verification when search or browser tools are available.

Final-score records must include source name, accessed or observed time when known, and match-identity confidence. If a saved prediction snapshot lacks provider fixture IDs, match by team names, kickoff time, and competition. Low-confidence matches must be skipped and listed in the review summary rather than forced into hit/miss metrics.

When public pages provide only played scores rather than a table, use the local standings calculator instead of trusting prose summaries. The calculated context should be labelled `calculated_from_results` and still cite the score source and observation time.

Discovering an API through web search does not make it a configured provider. Do not auto-register accounts, request keys on the user's behalf, guess keys, call unknown free APIs, or treat unauthenticated endpoints as authorized data sources.

## Public Web Verification Responsibility

When browsing, search, or webpage-reading tools are available, the assistant should actively perform public web verification itself. The user does not need to manually paste public data unless tools are unavailable, public access fails, sources conflict, or the user has a more authoritative source.

If public pages require login, bypassing restrictions, captcha solving, or unauthorized scraping, stop using that source and downgrade or ask the user for authorized data.

## Public-Web-First Mode Without API Keys

When no odds API key is configured but browsing or search tools are available, behave like a web-enabled assistant:

1. Search for the exact fixture plus odds terms, such as `[home team] [away team] odds`, `[home team] vs [away team] handicap`, `[competition] odds`, or Chinese equivalents like `赔率`, `盘口`, `让球`, `大小球`.
2. Prefer pages that visibly publish current odds or lines, such as odds aggregators, bookmaker public pages, official lottery pages, or reputable live-score/odds pages.
3. Open candidate pages and extract only data that is visible without login, captcha bypassing, paid access, or restricted scraping.
4. Record source names, accessed time, market, line, and prices. If a page is a prediction article rather than an odds table, label it as prediction/context, not Odds Data.
5. Try up to two alternative public sources after the first failure or conflict, then apply the Retrieval Stop Rule.

This mode should feel as helpful as a web ChatGPT search, but it must be more explicit about source quality. If public odds are found, include them and continue with Value Judgment at the appropriate confidence level. If only predictions or stale pages are found, use them as context and say that verifiable Odds Data is still missing.

## Credential Fallback

If no provider credential exists:

1. In `china-lottery` mode, try the local snapshot and built-in `sporttery` provider.
2. Try public or user-authorized sources.
3. Apply the Retrieval Stop Rule.
4. Ask the user for missing critical data if public collection fails.
5. Downgrade rather than inventing current data.

## China Lottery Odds Stop Rule

When the user requests a China Sports Lottery purchase plan and the assistant cannot verify China lottery odds/handicap data:

1. Do not produce Value Judgment.
2. Do not produce Reference Purchase Plans.
3. If fixtures and football context exist, continue only with Probability Analysis.
4. Clearly display this status in chat and in any generated report: `竞彩赔率/盘口状态：未获取或未验证`.
5. Do not invent odds, handicap lines, over-under lines, total-goals prices, correct-score prices, market availability, or sales availability. Do not convert model probabilities or third-party international odds into China lottery odds.
6. Ask for the minimum missing fields:

```markdown
请补充这场/这几场的竞彩可买玩法和赔率/盘口：
比赛：
玩法：胜平负 / 让球胜平负 / 比分 / 总进球 / 大小球
盘口：
赔率：
截图或文字都可以。
```

## Required Current Data

For every current data item, record a Source Timestamp:

- Source name.
- Accessed or observed time.
- Timezone when relevant.
- Whether the data is confirmed, expected, stale, unavailable, or conflicting.

## Multi-Source Odds Check

For odds value judgment, prefer more than one odds source. If only one source is available:

- Continue only if the source is usable.
- Mark odds confidence as lower.
- Downgrade Value Judgment.

Do not treat one bookmaker as market consensus.

## Odds And Line Display

When odds or lines are found, include a compact odds table in the report. Show:

- Market: 胜平负, 让球/handicap, 大小球/totals, or 比分 if available.
- Source/bookmaker or aggregator.
- Observed time and timezone.
- Line, where applicable.
- Decimal prices or price range.
- Confidence and whether the source is single-source or multi-source.

If odds collection fails, state the failure category: no configured provider, public page blocked, login/captcha required, market unavailable, source conflict, or stale data.

## Source Conflict Handling

When sources conflict:

1. Surface the conflict in the Data Summary Table or risk notes.
2. Prefer official, fresher, or more specialized sources when justified.
3. If unresolved, mark the field uncertain.
4. Downgrade Data Confidence.
5. Do not silently average conflicting match facts.

## Retrieval Stop Rule

For each key category, try the primary source and no more than two alternative public or authorized sources. If still unavailable, mark the gap and continue only if Information Sufficiency remains adequate.

Key categories:

- Fixture identity.
- Odds and lines.
- Lineups and injuries.
- Team form and attacking/defensive output.
- Weather and venue context.
- Competition incentives.

## Excluded Collection Methods

Do not:

- Log into bookmaker accounts.
- Bypass access restrictions, captchas, rate limits, or regional controls.
- Depend on unauthorized scraping.
- Hardcode bookmaker credentials.
- Claim to have live odds when no source was checked.
