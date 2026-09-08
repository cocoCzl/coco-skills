# 大乐透与双色球号码推荐

基于官方开奖历史，为中国大乐透和双色球提供可审计的号码生成与历史回测辅助。它不承诺中奖、收益或概率优势，也不提供购买、支付、胆拖、复式或追加服务。

## 快速开始

安装后可直接说“双色球给我 3 注热号”或“回测大乐透冷号策略”。每次推荐和回测前都会同步并校验官方历史：大乐透要求从首期连续覆盖；双色球当前覆盖官网可验证的 `2013001` 至最新期。

开发或排查时使用统一入口：

```bash
python3 lottery-number-recommendation/scripts/lottery_skill.py doctor
python3 lottery-number-recommendation/scripts/lottery_skill.py parse-request '双色球三注强热号'
```

默认在对话中返回结果；用户要求保存时写入 `reports/lottery-number-recommendation/`。官方历史和审计数据保存在当前工作目录的 `data/lottery-number-recommendation/`。

完整的 Agent 执行规则见 [SKILL.md](SKILL.md)，官方来源与访问边界见 [references/official-sources.md](references/official-sources.md)，对话示例见 [examples](../examples/lottery_number_recommendation/README.md)。
