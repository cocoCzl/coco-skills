# 足球竞彩助手

为中文足球竞彩提供赛前概率分析、比分覆盖、参考组合、赛后复盘和历史回测。输出仅为决策辅助，不承诺中奖、盈利或“稳赢”；不提供资金管理、追损或个性化下注金额建议。

## 快速开始

安装后可直接提出比赛和目标玩法，例如：

```text
分析明天的四场足球竞彩，给一个重点看比分和大小球的四串一参考方案。
```

开发或诊断时使用统一入口：

```bash
python3 football-betting-assistant/scripts/football_skill.py doctor
python3 football-betting-assistant/scripts/football_skill.py route '明天竞彩四串一'
```

正式赛前分析会核实赛程、赔率、可售玩法、球队信息和赛事背景。缺少可验证数据时会降级或停止，不会用记忆补全。HTML 报告写入 `reports/football-betting-assistant/`，快照与复盘数据写入 `data/football/`。

完整流程、数据边界、模型和输出规则见 [SKILL.md](SKILL.md)；可复制的提问示例见 [examples](../examples/football_betting_assistant/README.md)。

明确操作直接执行；`doctor`/`route` 仅按需。简单查询或局部解释直接聊天，完整分析才生成报告和快照。内置 `fetch --mode china-lottery` 仅支持 Sporttery；海外赔率需已有/另行授权来源，缺少时明确降级，不切换来源。`report` 已执行校验和风险审计，相同输入无需重复跑。

内置 `report` 仅生成市场快照报告，成功生成仍保留模型未运行的降级状态。单场 xG/泊松入口及输入、报告衔接限制见 [接口说明](references/agent-interface.md#按需运行单场模型)；当前没有自动球队抓取到完整模型报告的端到端管线。
