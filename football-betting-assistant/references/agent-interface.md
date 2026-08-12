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
