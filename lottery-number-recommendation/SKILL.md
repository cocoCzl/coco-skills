---
name: lottery-number-recommendation
description: 为中国大乐透和双色球提供自动官方历史同步、号码推荐和回测。用户提到大乐透、双色球、热号、冷号、遗漏、随机未出现组合、彩票选号/推荐/预测或回测/效果/统计时使用；每次推荐前同步并校验官方数据。大乐透要求首期完整覆盖；双色球明确使用官网当前可得的 2013001 至今区间。不得承诺中奖、盈利或绕过数据源访问限制；其他彩票和购买代办不适用。
---

# 大乐透与双色球号码推荐

提供基于选号假设的娱乐性推荐，不预测中奖。只有历史连续覆盖至最新已开奖期，才可称“历史未出现组合”：大乐透从首期至今；双色球当前为官网可自动验证的 `2013001` 至今。

## 模型首先这样做

`scripts/lottery_skill.py` 是唯一入口；先解析原始请求，避免模型自行拆参数：

```bash
python3 <skill-dir>/scripts/lottery_skill.py doctor
python3 <skill-dir>/scripts/lottery_skill.py parse-request '<用户原始请求>'
```

解析为 `clarify` 或 `refuse` 时按原因响应；`recommend` 时分别执行每种彩票请求。JSON 的稳定状态和错误码见 [`references/agent-interface.md`](references/agent-interface.md)。

## 请求路由

- 只处理用户点名的彩票；未指定细节而同时请求两种时，各给 1 注 `random`。
- 热号/高频是 `hot`，冷号/遗漏是 `cold`，随机/未出现组合是 `random`。
- 同种彩票同时要求多个模式时先澄清，不静默混合。
- 拒绝“必中、保证盈利、最大概率发财”等承诺，可改为娱乐推荐或历史回测。
- 标准单式仅支持大乐透 5+2、双色球 6+1；不支持胆拖、复式、追加或购买操作。

## 数据门槛与性能

推荐和回测前先同步。每日第一次全量复核以发现历史更正；当天后续请求合并必要新增页。运行数据、原始响应、不可变标准化快照和审计记录写入当前工作目录的 `data/lottery-number-recommendation/`。

```bash
python3 <skill-dir>/scripts/lottery_skill.py sync
python3 <skill-dir>/scripts/lottery_skill.py recommend --game ssq --count 3 --mode hot --window 50 --strength strong --output text
```

只使用中国体彩网和中国福彩网的公开接口/归档。不得使用第三方历史、用户补档、Cookie 注入、验证码/WAF 绕过或登录自动化。HTTP、格式、分页或连续性失败时停止对应彩票，返回 `next_action`；不要生成普通随机号码兜底。双彩请求允许另一种彩票独立成功。

官方来源和失败含义见 [`references/official-sources.md`](references/official-sources.md)，历史字段见 [`references/data-format.md`](references/data-format.md)。

## 生成规则

- 所有模式过滤已验证历史中的完整组合；同次多注不重复，可复用单个号码。
- `random` 在合法且历史未出现的组合上等概率抽取。
- `hot` 融合 0.25×、1×、2.5×窗口频率，按分区理论出现率平滑并限制权重，避免短期噪声主导。
- `cold` 使用截至最新期的分区连续遗漏。热/冷只改变抽样倾向，不构成中奖概率优势。
- 正常生成用新种子；本地审计保存种子、参数和数据版本，面向用户不展示种子。
- 面向用户优先使用 `--output text` 并直接转发，不改写覆盖范围、统计含义或免责声明。

输出每种彩票只写一段共享状态，随后每注一行；热/冷号只附极简统计。默认在聊天返回，只有用户要求保存时写入 `reports/lottery-number-recommendation/`。

## 回测

只有用户明确要求回测、效果或统计时运行。回测从预热结束到最新期，目标期之后的数据不可参与当期策略；默认每期 200 次可复现抽样，并比较 `random`、旧线性热号、新 `hot` 与 `cold`。

```bash
python3 <skill-dir>/scripts/lottery_skill.py backtest dlt --window 200 --trials 200
```

报告覆盖期、截止期、数据版本、分区平均命中、各奖级命中和相对随机的区块自助法 95% 区间。只有区间下界大于零，才可称为该历史划分下的改善；不外推为未来优势。

若中国福彩网未来自然公开从 `2003001` 起的连续双色球官方记录，全量同步可创建新数据版本并升级覆盖范围；不得用非官方补档提前宣称首期完整。
