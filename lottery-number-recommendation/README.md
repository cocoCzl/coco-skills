# 大乐透与双色球号码推荐 Skill

[English](README.en.md)

这是一个本地优先、可审计的大乐透与双色球号码推荐 Skill。首次使用自动同步官方历史，后续自动增量更新；大乐透要求从首期连续覆盖，双色球当前要求官网可得的 `2013001` 至最新期连续覆盖，并会明确显示这一范围。

## 能做什么

- 自动同步、归档和校验官方历史开奖数据；
- 查看数据是否连续、是否已确认最新；
- 生成随机未出现组合、热号倾向或冷号倾向号码；
- 生成多注、按需避开本地历史推荐；
- 对随机、热号、冷号策略运行可复现的历史回测；两种彩票都保留旧线性热号作对照，并使用多次抽样评估。
- 直接输出简洁、稳定的中文号码结果和数据状态。

默认结果直接返回到对话；只有用户要求保存文件时，才写入当前工作目录的 `reports/lottery-number-recommendation/`。官方历史与推荐审计继续使用 `data/lottery-number-recommendation/`，不会与报告混放。

## 不做什么

- 不提供保证中奖、收益或概率优势的承诺；
- 不绕过反爬、验证码、登录或其他访问限制；
- 不支持胆拖、复式、追加、购买或支付；
- 不在数据不完整时生成任何兜底号码。

## 热号策略

大乐透和双色球的 `hot` 都使用以请求窗口为中心的 1/4、1 倍、2.5 倍窗口（权重为 20% / 50% / 30%）。每个分区频率会按自身理论出现率经过均匀先验平滑，最终抽样权重被限制在 0.75–1.50；因此热号只会获得有限倾向，不会因为近期偶发高频而垄断选号。两种彩票的 `backtest` 默认每期每策略抽样 200 次，并报告相对随机策略的 95% 区间；该结果只描述历史样本。

## 安装

```bash
cp -R lottery-number-recommendation ~/.codex/skills/
```

面向普通用户的安装、自动同步和对话示例见 [`examples/lottery_number_recommendation/README.md`](../examples/lottery_number_recommendation/README.md)。面向 agent 的执行规则见 [`SKILL.md`](SKILL.md)。官方接口、访问边界和范围升级说明见 [`references/official-sources.md`](references/official-sources.md)。

## 开发检查

先用无联网诊断确认本地缓存状态；日常自然语言请求仍先走 `parse-request`：

```bash
python3 lottery-number-recommendation/scripts/lottery_skill.py doctor
python3 lottery-number-recommendation/scripts/lottery_skill.py parse-request '双色球三注强热号'
```

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/check_all_skills.py
```
