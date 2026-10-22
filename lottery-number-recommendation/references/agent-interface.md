# Agent 统一入口

`scripts/lottery_skill.py` 是唯一主入口。参数不明确时用 `parse-request` 解析自然语言，明确操作可直接执行；推荐和回测会按各自流程同步并校验历史。`doctor` 只检查本地能力与缓存，不联网。

```bash
python3 <skill-dir>/scripts/lottery_skill.py parse-request '双色球三注强热号'
python3 <skill-dir>/scripts/lottery_skill.py recommend --game ssq --count 3 --mode hot --output text
```

JSON 输出包含稳定的 `status`、`data_status`、`next_action`、`error_code` 和耗时；原业务结果仍放在 `data`。同步失败时不得绕过错误或改用普通随机数。

`recommend` 和 `backtest` 已各自执行同步与完整性验证，不要在它们之前重复 `sync`。只有单独更新数据才调用 `sync`。`doctor` 为按需本地诊断，不代表当前官方数据已验证。每日全量更正复核与后续最新页检查不能跳过。回测默认四策略、每期 200 次及区块自助区间，成本随评估期数增加。
