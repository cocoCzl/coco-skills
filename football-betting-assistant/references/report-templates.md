# Report Templates

Default report language is Chinese Betting Vocabulary. Keep math visible but concise. Prefer a rich analysis report over a thin table-only response when data and tools are available.

## Single-Match Report

```markdown
## [主队] vs [客队]：赛前分析

### 1. 数据来源与比赛确认
| 项目 | 当前信息 | 来源/时间 | 置信度 |
|---|---|---|---|
| 比赛 | [赛事、轮次、开赛时间、主客/中立] | [来源] | 高/中/低 |
| 赔率/盘口 | [胜平负、让球、大小球/总进球] | [来源] | 高/中/低 |
| 近期状态 | [近5/近10场摘要] | [来源] | 高/中/低 |
| 攻防数据 | [xG/xGA 或进失球] | [来源] | 高/中/低 |
| 伤停/首发 | [已确认/预计/未确认] | [来源] | 高/中/低 |
| 天气/场地 | [天气、场地、旅途] | [来源] | 高/中/低 |
| 赛程密度 | [休息天数、旅途、轮换压力] | [来源] | 高/中/低 |
| 战意/赛制 | [出线、净胜球、排名路线、轮换、潜在淘汰赛对手] | [来源] | 高/中/低 |
| 赔率变化 | [开赔/即时/盘口变化；不可得则写未确认] | [来源] | 高/中/低 |
| 数据缺口 | [缺失或冲突项] | [来源] | 高/中/低 |

> 数据来源说明：[用中文说明引用了哪些来源，例如官方赛程、赔率聚合源/单一公司、球队新闻、数据站、天气源、用户提供截图；可以不贴 URL，但必须写来源名和观察时间。]
> 若没有核验到实际赔率/盘口，必须在本节顶部写：`竞彩赔率/盘口状态：未获取或未验证。本报告只包含概率分析，不包含赔率价值判断，不提供正式参考购买方案。`

### 2. 基础面分析
- 近期状态：
- 攻防结构：
- 伤停/首发：
- 天气/场地/赛程：
- 赔率变化：
- 战意/赛制：[小组赛第 3 轮需说明出线形势、净胜球、排名路线、轮换概率、潜在淘汰赛对手；"避强队/选路线"只能作为动机修正，不能当作确定行为]

### 3. 赔率/盘口表
| 市场 | 盘口 | 赔率/范围 | 来源 | 观察时间 | 置信度 |
|---|---|---|---|---|---|
| 胜平负 | - | 主胜/平/客胜 | [bookmaker/aggregator] | [time] | 高/中/低 |
| 让球 | [line] | 主/客或让胜/让平/让负 | [bookmaker/aggregator] | [time] | 高/中/低 |
| 大小球 | [line] | 大/小 | [bookmaker/aggregator] | [time] | 高/中/低 |

### 4. 数学模型
- 基础 xG prior：
- 贝叶斯修正：[写明修正代码/目标/幅度；若为定性修正，标注定性]
- 最终 xG：
- 泊松比分集中：
- 赔率隐含概率/去水概率：
- edge/评级封顶：
- 模型记录：[xG prior 脚本 / 泊松脚本 / 赔率脚本 / 评级脚本 / 手算近似 / 数据不足无法计算]

### 5. 结论摘要
- 胜平负倾向：
- 让球胜平负倾向：
- 大小球/总进球倾向：
- 参考等级：A/B/C/Pass
- 模型置信度：高/中/低
- 数据置信度：高/中/低

### 6. 概率判断
| 市场 | 概率/区间 | 说明 |
|---|---:|---|
| 主胜 |  |  |
| 平局 |  |  |
| 客胜 |  |  |
| 大球 |  | 盘口： |
| 小球 |  | 盘口： |

### 7. 比分排序
| 排名 | 比分 | 概率层级 | 使用场景 |
|---:|---|---|---|
| 1 |  | 最高/高/中 | 主推/覆盖/风险 |
| 2 |  | 高/中 |  |
| 3 |  | 中/冷门 |  |

### 8. 参考购买方案
- 胜平负/让球：
- 大小球/总进球：
- 比分覆盖：
- 不建议项：

### 9. 风险点
- 
```

## Portfolio Report

```markdown
## 多场小组赛收官参考方案

### 0. 先给总方案

模型最稳主单：
- [模型选择的 2-8 个可买方向；不强行凑满]

胜平负/让球方向单：
- [最多8场；只写可买市场]

比分4串1：
- [比赛1比分]
- [比赛2比分]
- [比赛3比分]
- [比赛4比分]

核心判断：[用 2-4 句说明这组不是保证，只是当前数据下最顺的强弱、比分、大小球路径；指出哪些比赛进入主单，哪些只做备选或单场观察。]

### 1. 北京时间比赛清单 / 全场次先看结论
| 编号 | 北京时间 | 比赛 | 当前胜平负 | 可买市场 | 胜平负/让球倾向 | 大小球/总进球 | 比分主区间 | 稳度 | 最大风险 |
|---|---|---|---|---|---|---|---|---|---|

稳度排序：[从高到低列出]
主线方向：[用一句话说明模型最稳主单方向]
比分思路：[说明是偏小比分、强弱分明、还是有一两场可能打穿]

### 2. 比赛大纲 / 今日赛程确认
| 编号 | 比赛 | 时间 | 赛事 | 主客/中立 | 数据置信度 | 赔率/盘口来源 |
|---|---|---|---|---|---|---|

### 3. 小组当前战绩 / 积分 / 出线形势
| 小组 | 球队 | 当前排名 | 当前胜平负 | 积分 | 净胜球 | 出线/排名压力 | 轮换风险 | 潜在淘汰赛对手/路径 | 对本场模型的影响 | 来源/时间 |
|---|---|---:|---|---:|---:|---|---|---|---|---|

> 如果小组积分、当前胜平负、净胜球或潜在淘汰赛路径无法核验，保留本节并写明"未确认"，同时降低数据置信度。不要因为查不到就省略战意层。

### 4. 数据来源总览
| 类别 | 使用来源 | 观察时间 | 说明 |
|---|---|---|---|
| 赛程 |  |  |  |
| 赔率/盘口 |  |  |  |
| 球队状态/伤停 |  |  |  |
| 天气/场地 |  |  |  |
| 小组积分/排名 |  |  |  |
| 赔率变化 |  |  |  |

### 5. 玩法可买性与赔率市场中心
| 比赛 | 普通胜平负是否可买 | 让球胜平负 | 比分低赔区间 | 大小球/总进球中心 | 市场含义 |
|---|---|---|---|---|---|

> 购买方案只能使用可买市场。不可买的普通胜平负可以用于概率分析，但不能写入竞彩购买单。

### 6. 模型怎么来的
- 预期进球：先用双方强弱、攻防质量、主客/中立、赛事环境和盘口强度形成 `prior xG`；有 xG/xGA 和联赛均值时优先用 `xg_prior_calculator.py`。
- 贝叶斯修正：再根据伤停、首发、赛程密度、小组战意、天气、市场变化做上调或下调；可映射到规则表时写明代码、目标和幅度。
- 泊松比分：用最终 xG 生成比分矩阵，得到胜平负、大小球/总进球和比分集中区。
- 赔率隐含概率：有完整赔率时计算去水概率，用来判断市场是否已经充分反映该方向。
- edge/评级封顶：用模型概率减市场去水概率，按阈值和数据置信度、单源赔率、首发状态、来源冲突等规则封顶。
- 模型记录：[xG prior 脚本 / 泊松脚本 / 赔率脚本 / 评级脚本 / 手算近似 / 数据不足近似]。这是决策辅助，不是结果保证。

### 7. 逐场分析

#### [编号]. [主队] vs [客队]
- 数据依据：[来源名 + 时间；不需要默认贴链接]
- 小组/战意：[排名、积分、净胜球、出线压力、轮换风险；无法确认时说明缺口]
- 基础面：[用 1-2 段自然语言说明状态、攻防、伤停、场地]
- 比赛剧本：[谁会控球、谁会收缩、早进球/久攻不下/红牌或换人会怎样影响比分]
- 数学模型：[prior xG -> 贝叶斯修正代码/幅度 -> final xG；泊松比分集中；赔率隐含概率/去水概率；edge/评级封顶]
- 胜平负概率：[主胜/平/客胜区间 + 首选]
- 让球判断：[让胜/让平/让负或 handicap cover 路径；必须按 `主队进球 + 主队让球 - 客队进球` 映射核心比分。例：`-1` 下 `1:0/2:1 -> 让平`，`1:1 -> 让负`，`2:0 -> 让胜`；解释赢球但不穿/打穿的条件]
- 大小球/总进球：[盘口或总进球倾向 + 为什么]
- 比分分布：[低赔比分表或候选排序；区分主单比分、核心覆盖、增强覆盖、补防]
- 等级/风险：[A/B/C/Pass + 关键风险]

### 8. 胜平负与大小球汇总
| 比赛 | 普通胜平负分析 | 可买让球/方向 | 大小球/总进球 | 来源/时间 | 置信度 |
|---|---|---|---|---|---|

### 9. 比分覆盖建议
| 比赛 | 核心比分 | 增强覆盖 | 漏洞/补防 | 不建议 |
|---|---|---|---|---|

### 10. 参考购买方案
| 类型 | 注数组合 | 合计 | 每场选择 | 适用场景 | 风险 |
|---|---:|---:|---|---|---|
| 模型最稳主单 | [按模型选择数量计算，最多8腿] | [N 注 x 2 元/注 = X 元] | [从全场次中筛出的最稳可买方向；可以少于8场] | [主参考] |  |
| 稳健方向单 | [按实际选择数量计算，最多8腿] | [N 注 x 2 元/注 = X 元] | [胜平负/让球/大小球/总进球中的低波动选择] | [不想强压比分] |  |
| 让球/胜平负方向单 | [按实际选择数量计算，最多8腿] | [N 注 x 2 元/注 = X 元] | [只写可买的普通胜平负或让球胜平负方向；不可买普通胜平负不得放入] | [不想强压比分] |  |
| 大小球/总进球单 | [按实际选择数量计算，最多8腿] | [N 注 x 2 元/注 = X 元] | [筛选盘口最清楚的大小球或总进球选择] | [想避开精确比分] |  |
| 单比分主推小单 | [最多4场，例如 1 x 1 x 1 x 1 = 1 注] | [N x 2 元/unit] | [四场主推比分] | [高方差小单] |  |
| 比分4串1 / 基础比分覆盖 | [最多4场，例如 2 x 2 x 2 x 2 = 16 注] | [N x 2 元/unit] | [从全场次中挑比分最集中的四场] | [核心比分区间] |  |
| 增强比分覆盖 | [最多4场，按实际选择数量计算] | [N x 2 元/unit] | [每场写完整比分集合，例如 葡萄牙 2:0/3:0/2:1；不要写“加 2:1”] | [提高容错] |  |
| 混合过关单 | [最多8腿，按实际选择数量计算] | [N 注 x 2 元/注 = X 元] | [可买方向 + 大小球/总进球 + 少量比分] | [降低对纯比分四串一的依赖] | 串关仍有波动 |
| 补洞单 | [按实际选择数量计算] | [N x 2 元/unit] | [覆盖最大漏防路径] | [已买主单或想补关键漏洞] |  |
| 搏冷/高赔率小单 | [按实际选择数量计算] | [N x 2 元/unit] | [低概率但可解释剧本] | [只作可选参考] | 高方差 |

### 11. 如果用户已有购买方案
- 这组合理的地方：
- 最大漏防：
- 最该补的比分/方向：
- 已买后可考虑的补洞单：

### 12. 组合相关性检查
- 独立性/相关性：
- 共同风险：
- 不建议强行纳入的场次：

### 13. 备选/替换
| 原主单场次 | 可替换场次 | 替换后结构 | 更保守/更激进 | 理由 |
|---|---|---|---|---|

### 14. 可选小组合 / 更多组合候选
| 组合 | 注数/金额 | 每场选择 | 使用条件 | 风险 |
|---|---:|---|---|---|

### 15. Pass / 排除项
- 
```

Portfolio rules:

- Analyze every confirmed match in the slate, even when there are 6, 8, 10, or more matches.
- Apply ticket limits by market family: exact-score tickets up to four matches; 胜平负 / 让球胜平负 direction tickets up to eight matches; 大小球 / 总进球 direction tickets up to eight matches.
- The model may choose fewer legs than the maximum. Do not force a 4/6/8-leg ticket.
- Do not hard-code 2/16/32/48 元 plans. Pick the coverage widths from the score probabilities and user intent, then calculate units and amount.
- Keep amount and unit count explicit. With the default 2 元/unit, 16 units equals 32 元, not 16 元.
- More Combination Candidates are optional alternatives, not extra mandatory purchases.
- Score Coverage may include up to four scores per match only when the football case supports wider coverage.
- When the user provides a proposed ticket, evaluate their ticket first before suggesting replacement plans.
- Exclude matches that are Pass or have severe data gaps.
- Main-ticket selections must remain consistent with the risk section. If the analysis says a draw, one-goal margin, favorite-cover, underdog-goal, or late-expansion path is important, the ticket table must either include the protection selection, downgrade the match to backup, or explicitly list it under Pass / 排除项.
- Do not present a single narrow handicap leg as "模型最稳" when score coverage already shows its miss path. Examples: `+1 让胜` needs `让平` if opponent one-goal win is a main path; `-1 让负` needs protection or downgrade if 2:0 / 3:1 cover scores are meaningful.
- Do not collapse handicap vocabulary into ordinary win/draw/loss language. A `-1 让负` ticket only covers the favorite failing to win after the handicap is applied; favorite one-goal wins are `让平`, not `让负`. Whenever cited score candidates imply multiple handicap outcomes, show the mapping and either select all required outcomes, use another market, or downgrade/exclude the leg.

## HTML Report Structure

Completed pre-match reports should be rendered as a single self-contained HTML Report through `scripts/render_html_report.py`. The assistant should build structured JSON instead of hand-writing HTML.

Required top-level sections:

- 报告摘要 / Report Summary
- 北京时间比赛清单 / Beijing-Time Fixture List
- 赛制背景总分析 / Competition Context Analysis
- 先给方向总表 / Direction Summary Table
- 模型排序 / Model Rankings
- 逐场深度分析 / Per-Match Deep Analysis
- 购买方案 / Ticket Plans
- 入选与排除理由 / Selection Rationale
- 备选/替换与可选小组合 / Backup / Replacement and Optional Small Combination
- 风险与数据缺口 / Risks and Data Gaps

HTML Report rules:

- Generate HTML only for completed pre-match analysis; do not create Markdown reports.
- Save under the current working directory's `reports/football-betting/`.
- Chat output after generation is only a concise summary plus the HTML path.
- If actual odds/lines are unavailable, use Data Status `no-actual-odds-lines`, show a top-of-report warning `竞彩赔率/盘口状态：未获取或未验证`, and label Ticket Plans as probability/reference structures rather than full value judgments.
- Never invent odds, handicap lines, over-under lines, total-goals prices, or correct-score prices. Missing market data must stay blank, `未获取`, `未验证`, or `不可用`.
- When China lottery odds/lines are missing, do not present official-looking Reference Purchase Plans. Use only Probability Analysis and a clearly marked `待赔率确认` reference structure if the fixture and team context are sufficient.
- The renderer validates Score 4-Fold and Direction Ticket limits before writing the file.

## Post-Match Review

Default post-match reviews should be generated as one Chinese HTML Review through `scripts/auto_post_match_review.py` when local execution is available. Save the HTML under `reports/football-betting/` and the structured review bundle under `data/football/reviews/`. Use this structure for each reviewed match:

```markdown
## 赛后复盘：[比赛或组合]

### 1. 赛前判断回顾

### 2. 实际结果与关键转折

### 3. 模型偏差

### 4. 数据偏差

### 5. 下次调整
```

Do not include chase-loss, recovery-bet, bankroll allocation, Kelly sizing, or personalized stake-size advice. Ticket-tier amounts are allowed only as unit-count totals requested by the user.
