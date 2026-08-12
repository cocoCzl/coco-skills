# Agent 统一入口

`scripts/lottery_skill.py` 是唯一主入口。先用 `parse-request` 解析自然语言；推荐和回测会按各自流程同步并校验历史。`doctor` 只检查本地能力与缓存，不联网。

```bash
python3 <skill-dir>/scripts/lottery_skill.py doctor
python3 <skill-dir>/scripts/lottery_skill.py parse-request '双色球三注强热号'
python3 <skill-dir>/scripts/lottery_skill.py sync
python3 <skill-dir>/scripts/lottery_skill.py recommend --game ssq --count 3 --mode hot --output text
```

JSON 输出包含稳定的 `status`、`data_status`、`next_action`、`error_code` 和耗时；原业务结果仍放在 `data`。同步失败时不得绕过错误或改用普通随机数。
