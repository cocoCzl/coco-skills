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
- `route` 的任务模式分别对应 `report`（单场/组合）、`review`、`backtest`。复盘和回测优先使用已有文件，不因缺少比赛名而回到赛程发现。
- `fetch --mode china-lottery` 是唯一内置抓取路径，使用 Sporttery；省略 `--mode` 保持兼容。`international-odds` 与 `analysis-only` 返回 `SOURCE_MODE_UNSUPPORTED`（退出码 3），不联网、不写快照、不切换来源。
- 海外赔率使用用户已提供或其他已授权工具取得的来源、赔率和观察时间；本入口不内置 The Odds API 适配器，配置 key 本身不代表可抓取。无赔率时只做概率分析；中国竞彩购买方案不能拿海外赔率顶替。
- `report` 已校验链接的预测快照并运行风险审计，不再对相同输入重复 `validate`/`audit`。手工生成或修改输入的路径仍需检查；数据时效和来源核实不能省略。
