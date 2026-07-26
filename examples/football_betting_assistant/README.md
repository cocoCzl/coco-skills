# Football Betting Assistant 新手安装和使用指南

这个目录放仓库级示例，不是运行时 skill 的必需内容。真正要安装的是仓库顶层的 `football-betting-assistant/` 目录。

`football-betting-assistant` 是一个面向中文足球竞彩、胜平负、让球胜平负、比分、大小球、总进球、串关、四串一和赛后复盘的 agent skill。它可以在 Codex 里按 skill 使用；在字节、阿里或其他类似 Codex App 的大模型软件里，也可以按“自定义规则 + 项目文件/知识库 + 可选本地命令”的方式接入。

## 能不能在其他大模型软件里用

能用，但取决于那个软件提供了哪些能力。不要假设所有软件都原生认识 Codex skill 目录。

| 软件能力 | 使用效果 | 接入方式 |
| --- | --- | --- |
| 原生支持 skills / skill 目录 | 最完整 | 安装整个 `football-betting-assistant/` 目录 |
| 支持项目规则 / 自定义系统提示词 | 可用 | 把 `football-betting-assistant/SKILL.md` 作为规则，让模型按里面的流程和边界回答 |
| 支持项目文件 / 知识库 | 更稳定 | 同时加入 `references/`、`schemas/` 和本目录的 `prompts.md` |
| 支持本地命令或 Python | 最接近 Codex 体验 | 允许模型调用 `football-betting-assistant/scripts/` 里的采集、校验、建模和报告脚本 |
| 支持联网或浏览器 | 可补当前信息 | 让模型核验赛程、伤停、天气、盘口、赔率和赛果 |
| 只支持普通聊天 | 只能半手动 | 用户需要自己提供比赛、赔率、盘口、伤停、近期状态等信息 |

最低可用条件：软件必须能读取或粘贴 `SKILL.md` 的规则。  
完整体验条件：软件能读取整个 skill 目录、能联网核验公开数据、能运行本地 Python 脚本，并能在当前项目下写入 `reports/football-betting-assistant/` 和 `data/football/`。

## Codex 安装

在仓库根目录运行：

```bash
cp -R football-betting-assistant ~/.codex/skills/
```

然后重启 Codex 会话，或开启一个新会话。不要复制 `.agent/`、`.agents/`、`.claude/`、`.pi/` 这类本地运行态目录。

安装后直接问：

```text
帮我分析北京时间明天早上四场世界杯比赛，给我一个四串一参考购买方案，重点看比分和大小球。
```

如果 skill 正常触发，agent 应该先确认比赛和北京时间，再尝试核验竞彩可买玩法、赔率/盘口、球队上下文，并在数据不足时降级或追问。

## 其他 agent 软件接入

如果你的软件不是 Codex，但类似“AI 编程助手”“智能体工作台”“带项目规则的大模型客户端”，按下面顺序配置。

1. 新建一个项目，把整个仓库或至少 `football-betting-assistant/` 放进项目目录。
2. 在项目规则、自定义指令或系统提示词里加入：

```text
当用户询问足球竞彩、胜平负、让球胜平负、比分、大小球、总进球、串关、四串一、赛前分析或赛后复盘时，请读取并遵守 football-betting-assistant/SKILL.md。
```

3. 如果软件支持知识库或项目文件，把这些路径加入可读文件：

```text
football-betting-assistant/SKILL.md
football-betting-assistant/references/
football-betting-assistant/schemas/
examples/football_betting_assistant/prompts.md
examples/football_betting_assistant/provider-setup.md
```

4. 如果软件支持命令执行，允许它在项目根目录运行 Python 脚本。普通用户不需要手动运行脚本，但 agent 可用它们做确定性计算和报告生成。
5. 如果软件支持联网或浏览器，允许它访问公开网页来核验赛程、赔率、伤停、天气和赛果。

可以用这个测试 prompt 验证接入效果：

```text
请按 football-betting-assistant 的规则，帮我看下北京时间明天的几场竞彩，重点看胜平负、让球、总进球和比分。数据不够时先告诉我缺什么，不要编赔率。
```

## 没有联网或命令执行时怎么用

如果你的软件不能联网、不能运行 Python、也不能读取本地文件，仍然可以把 `SKILL.md` 内容粘进规则里使用，但它只能做手动分析。你需要提供最少输入：

```markdown
比赛：
开赛时间：
赛事：
主客/中立：
想看玩法：胜平负 / 让球胜平负 / 比分 / 大小球 / 四串一
赔率/盘口：
伤停/首发：
近期状态或数据：
```

这种模式下，agent 不能声称自己拿到了实时赔率、实时伤停或最新赛程。没有可验证赔率/盘口时，只能做概率倾向和风险分析，不能输出完整赔率价值判断或正式参考购买方案。

## 普通用户怎么提问

面向普通使用者的提问模板：

- [`prompts.md`](prompts.md)：中文竞彩、比分、大小球、四串一、半全场、赛后复盘等自然语言请求。
- [`provider-setup.md`](provider-setup.md)：可选数据源 key 的配置方式、用途和限制。

推荐提问方式：

```text
帮我分析周三080、周三081、周三082，重点看比分覆盖和总进球。请先确认可买玩法和盘口，数据不足就列出缺口，不要用第三方赔率替代中国竞彩赔率。
```

如果你有截图或赔率文本，直接贴给 agent：

```text
我有三场竞彩截图，里面有让球、比分、总进球赔率。请按截图里的可买玩法分析，不要用第三方赔率替代竞彩赔率。
```

## 数据源和 API key

这个 skill 不自带 API key。没有第三方 key 时，它仍可尝试用 Sporttery 公开快照做中国竞彩赛程、可买玩法、赔率/盘口核验；但球队近期状态、阵容伤停、积分榜、天气、赛程密度等上下文可能需要公开网页、用户提供数据或额外 provider。

可选 key 的配置见 [`provider-setup.md`](provider-setup.md)。不要把真实 key 写进 README、聊天记录、issue、PR 或报告正文。

## Structured JSON Examples

这些 JSON 用于开发、校验和离线复现，不是普通用户必须填写的模板：

- `single-match-input.json`：单场分析结构化输入。
- `portfolio-input.json`：组合/串关结构化输入。
- `single-match-model-input.json`：模型计算链路输入。
- `backtest-sample.json`：历史回测样本。

常用校验：

```bash
python3 football-betting-assistant/scripts/validate_inputs.py examples/football_betting_assistant/single-match-input.json
python3 football-betting-assistant/scripts/validate_inputs.py examples/football_betting_assistant/portfolio-input.json
python3 football-betting-assistant/scripts/validate_inputs.py examples/football_betting_assistant/backtest-sample.json
```
