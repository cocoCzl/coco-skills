# 大乐透与双色球号码推荐 Skill

这是一个本地优先、可审计的大乐透与双色球号码推荐 Skill。首次使用自动同步官方历史，后续自动增量更新；大乐透要求从首期连续覆盖，双色球当前要求官网可得的 `2013001` 至最新期连续覆盖，并会明确显示这一范围。结果仅供娱乐与参考，不保证中奖。

## 能做什么

- 自动同步、归档和校验官方历史开奖数据；
- 查看数据是否连续、是否已确认最新；
- 生成随机未出现组合、热号倾向或冷号倾向号码；
- 生成多注、按需避开本地历史推荐；
- 对三种策略运行可复现的历史回测。
- 直接输出简洁、稳定的中文号码结果、数据状态和免责声明。

## 不做什么

- 不保证中奖、收益或概率优势；
- 不绕过反爬、验证码、登录或其他访问限制；
- 不支持胆拖、复式、追加、购买或支付；
- 不在数据不完整时生成任何兜底号码。

## 安装

```bash
cp -R lottery-number-recommendation ~/.codex/skills/
```

面向普通用户的安装、自动同步和对话示例见 [`examples/lottery_number_recommendation/README.md`](../examples/lottery_number_recommendation/README.md)。面向 agent 的执行规则见 [`SKILL.md`](SKILL.md)。官方接口、访问边界和范围升级说明见 [`references/official-sources.md`](references/official-sources.md)。

## 开发检查

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/check_all_skills.py
```
