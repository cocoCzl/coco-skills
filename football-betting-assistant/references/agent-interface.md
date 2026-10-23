# Agent 统一入口

模型优先调用 `scripts/football_skill.py`。它负责业务路由、能力诊断、旧脚本委派和统一错误解释，不复制数学模型。

```bash
python3 <skill-dir>/scripts/football_skill.py doctor
python3 <skill-dir>/scripts/football_skill.py route '明天竞彩四串一'
python3 <skill-dir>/scripts/football_skill.py fetch
python3 <skill-dir>/scripts/football_skill.py report snapshot.json --date tomorrow
python3 <skill-dir>/scripts/football_skill.py validate report-input.json
python3 <skill-dir>/scripts/football_skill.py audit prediction.json
python3 <skill-dir>/scripts/football_skill.py review
python3 <skill-dir>/scripts/football_skill.py backtest samples.json
```

统一结果信封包含 `status`、`data_status`、`next_action`、`artifacts`、`warnings`、`error_code` 和耗时。报告进入正式主单前，`audit` 必须允许 `main_plan_allowed`；否则保护、降级或移除风险选项。

联网并不是 `doctor` 的一部分。网络不可用、官方源被拦截和“市场确认不可售”是不同状态，不得互相代替。

## 按操作选择开销和来源

- 明确请求直接进入操作；`doctor`、`route`、`--help` 均按需。术语、已有报告局部解释直接聊天。
- `route` 的任务模式分别对应 `report`（单场/组合市场快照）、`review`、`backtest`。复盘和回测优先使用已有文件，不因缺少比赛名而回到赛程发现。
- `fetch --mode china-lottery` 是唯一内置抓取路径，使用 Sporttery；省略 `--mode` 保持兼容。`international-odds` 与 `analysis-only` 返回 `SOURCE_MODE_UNSUPPORTED`（退出码 3），不联网、不写快照、不切换来源。
- 海外赔率使用用户已提供或其他已授权工具取得的来源、赔率和观察时间；本入口不内置 The Odds API 适配器，配置 key 本身不代表可抓取。无赔率时只做概率分析；中国竞彩购买方案不能拿海外赔率顶替。
- `report` 已校验链接的预测快照并运行风险审计，不再对相同输入重复 `validate`/`audit`。手工生成或修改输入的路径仍需检查；数据时效和来源核实不能省略。

## 校验、产物与分析状态

`validate_inputs.py` 是标准库业务校验器，非通用 JSON Schema 引擎。`kind=odds` 对齐赔率 Schema 的字段集合、必填、枚举、类型、有限数值边界和 selections；`observed_at` 检查带时区的日期时间（不支持闰秒）。其他 kind 只检查已实现的必填及业务规则，不承诺完整 Schema 验证。Schema 保留完整接口约束，外部严格验证器可另行使用。非法输入退出 1，返回 `valid=false/errors/warnings`；包装入口返回 `DATA_VALIDATION_FAILED`。缺赔率的合法 null 保留降级警告。

`report` 在写产物前校验来源快照，生成时检查报告必填字段和票面一致性，之后校验预测快照并审计风险。退出 0 仅表示产物已生成且这些检查通过：外层仍为 `status=degraded`，`data_status` 透传 `usable-but-downgraded` 或 `no-actual-odds-lines`；聊天摘要也明确未运行模型。风险阻断仍优先返回 `blocked/RISK_AUDIT_BLOCKED`、退出 3。`main_plan_allowed` 只代表风险规则无阻断，不证明概率模型已运行，更不能独立授权升级为完整购买方案。

## 按需运行单场模型

有真实球队数据时直接调用，不再抓取或重复诊断：

```bash
python3 <skill-dir>/scripts/match_model_calculator.py model-input.json
```

输入必需 `teams.home_xg_for/home_xg_against/away_xg_for/away_xg_against`，应来自可追溯的球队攻防数据，并在报告记录来源和观察时间。可选 `league.home_xg/away_xg`（省略采用 1.45/1.15 基准，须披露假设）、`context.venue_type`、有证据的 `context.adjustments`、`odds.home_price/draw_price/away_price` 与 `over_under_line`、`grading.market_key`（home/draw/away/over/under）及置信度/阵容等分级条件。参数含义见 [模型](math-model.md) 和 [参数](model-parameters.md)。

返回 `kind=match_model_record`，`model_record` 含 prior、poisson、implied_probability、grade；缺四项球队输入退出 2，不填补 xG。缺赔率仍可计算球队概率，`value_judgment_available=false`，不做价值判断。可用仓库中的 `examples/football_betting_assistant/single-match-model-input.json` 离线复现，它是计算示例，不是实时比赛证据；独立安装时自行提供输入。

当前 `build_snapshot_report.py` 不消费 `match_model_record`，也没有从抓取球队数据到模型报告的自动端到端管线。需要完整报告时由 Agent 根据已算记录填入 [报告模板](report-templates.md) 的分析字段，调用 `render_html_report.py`，再校验预测快照和审计风险；不能把模型记录当作现成报告输入。模型计算完成、报告生成、输入检查和可形成购买方案分别判断，不因其中一项成功替代其他门槛。

子进程必须输出 JSON 对象；空、非 JSON 或非对象输出返回 `INVALID_CHILD_OUTPUT`，保留 `raw_output` 和可执行下一步。stderr 未在结构化结果中出现的行保存在 `data.child_diagnostics`（level 为 log/warning/error）；INFO/DEBUG 不变成警告，成功命令的其他诊断同时列入 warnings，失败仍以退出码决定阻断，不因 stderr 单独升级致命状态。报告校验/审计子步骤也保留各自诊断。
