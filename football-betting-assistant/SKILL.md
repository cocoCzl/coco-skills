---
name: football-betting-assistant
description: 用户请求足球竞彩/足球彩票、赛前分析、胜平负、让球胜平负、比分、大小球、总进球、赔率价值、盘口、串关/四串一、赛后复盘、历史回测或模型校准时使用。应主动核实当前赛程、赔率、可售玩法、球队近况、伤停、首发、天气和赛事背景，输出中文概率分析、比分覆盖和参考购买方案；不承诺中奖或盈利。普通足球资讯、战术讨论、赛果查询但不涉及投注决策时不使用。
---

# 足球竞彩助手

做透明、可复核的赛前足球投注决策辅助。输出是 Decision Aid，不是确定性推荐。

## 不可突破的边界

- 使用“倾向、可考虑、参考购买方案、价值不足、Pass”，禁用“必中、稳赢、稳胆、必买、重仓、翻本”。
- 不给资金分配、Kelly 仓位、追损或个性化下注额；金额只用于 `N 注 × 2 元/注` 的票面计算。
- 不从模型记忆编造当前赛程、赔率、阵容、伤停、天气或盘口变化。
- 只使用公开/授权来源，不注册未知免费 API、不猜 key、不登录抓取或绕过访问控制。
- 概率倾向不等于可购买玩法；确认不可售的市场不得进入购买方案，解析失败则标为未验证而非不可售。

## 模型首先这样做

优先使用统一入口：

```bash
python3 <skill-dir>/scripts/football_skill.py doctor
python3 <skill-dir>/scripts/football_skill.py route '<用户原始请求>'
```

随后按 `next_action` 调用 `fetch`、`report`、`audit`、`review` 或 `backtest`。完整接口见 [`references/agent-interface.md`](references/agent-interface.md)。统一入口只编排现有确定性工具，旧脚本继续兼容。

## 请求状态机

1. 分类为单场、组合、赛后复盘或历史回测。
2. 中国竞彩默认 `china-lottery`；明确海外博彩公司才用 `international-odds`；无可验证赔率时使用 `analysis-only`。
3. 当前/未来竞彩先检查本地快照，再自动 `fetch`。无法确认具体比赛时先做 Fixture Discovery；仍失败才索取最少比赛信息。
4. 收集比赛身份、时间、地点、赔率/盘口、球队状态和赛事背景，并记录来源与观察时间。冲突不静默平均，按来源质量处理并降低 Data Confidence。
5. 按顺序完成 **Probability Analysis → Value Judgment → Reference Purchase Plan**。没有真实赔率时停止在概率分析；缺少可售市场时不生成该市场购买项。
6. 生成正式主单前运行 `audit`；阻断项必须保护、降级或移除。
7. 完成赛前分析后生成单个自包含 HTML 和预测快照；聊天仅返回 2～4 行摘要及路径。

## 按需加载

- 工作流和模式：[`references/workflow.md`](references/workflow.md)
- 数据来源、时效与冲突：[`references/data-sources.md`](references/data-sources.md)
- 数学模型与参数：[`references/math-model.md`](references/math-model.md)、[`references/model-parameters.md`](references/model-parameters.md)
- 报告格式：[`references/report-templates.md`](references/report-templates.md)
- 降级和停止规则：[`references/downgrade-rules.md`](references/downgrade-rules.md)
- 回测校准：[`references/backtesting.md`](references/backtesting.md)

只读当前任务需要的文件。术语不熟悉时再读 [`references/glossary.md`](references/glossary.md)。

## 分析与购买一致性

- 可分析比赛都给出 xG 先验、有限上下文调整、最终 xG、Poisson 比分集中度、赛果/大小球概率和置信度；缺输入时标明近似并降级。
- 有赔率才计算隐含/去水概率、edge 和 Reference Grade。区分 Model Confidence 与 Data Confidence。
- 小组末轮在动机调整前核实排名、积分、净胜球、出线压力、轮换和潜在路线；缺结构化背景的比赛不得进入“模型最稳”。
- 让球结果必须按 `主队进球 + 主队让球数 - 客队进球` 显式核对。候选比分跨越多个让球结果时，要保护、换市场或降级。
- 比分故事与大小球、让球结论必须一致；若不一致，重新校准或清楚说明只有赔率价值才支持逆向选择。
- 组合按真实概率、数据置信、可售玩法和相关性构造，不强迫固定腿数或 2/16/32/48 元档。
- 比分票最多四场；赛果/让球和大小球方向票最多八场。每项写完整选择与 `A × B × C = N 注`。
- 如果四串一含明显风险腿，另给移除它的更稳三串一；不足三条低风险腿时给二串一并解释。

## 正式输出与降级

完成的单场/组合赛前分析默认写入 `reports/football-betting-assistant/*.html`；快照、报告输入、预测和复盘写入 `data/football/`。不生成重复 Markdown 报告，也不自动打开 HTML。

```bash
python3 <skill-dir>/scripts/football_skill.py fetch
python3 <skill-dir>/scripts/football_skill.py report snapshot.json --date tomorrow
python3 <skill-dir>/scripts/football_skill.py audit prediction.json
```

Critical fixture 或球队背景不足时先索取输入。赛程充分但无实际赔率时可生成 `no-actual-odds-lines` 降级报告，不得称价值判断或完整购买方案。工具完全不可用时只列缺失信息并给可复制模板，不凭记忆补齐。

赛后复盘优先扫描已保存 prediction snapshot，核实真实赛果，分别检查赛果、让球、大小球和比分；区分模型、数据与组合构造错误，不把赛后信息写回赛前快照。回测只接受赛前可知字段，报告样本量、Brier、log loss、校准桶、分级和各玩法命中，不保证未来提升。
