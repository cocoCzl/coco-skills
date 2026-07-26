# Coco Skills

`coco-skills` 是一个面向 Codex / agent 工作流的开源 skill 合集仓库。带有 `SKILL.md` 的顶层目录是可独立安装和阅读的 skill；`tests/`、`examples/`、`evals/`、`scripts/` 等是仓库级开发资料。

当前包含：

| Skill | 用途 | 入口 |
|---|---|---|
| `ai-resume-expert` | 面向中国大陆技术岗位的证据优先简历生成、诊断、JD 定制与本地 PDF 交付 | [`ai-resume-expert/SKILL.md`](ai-resume-expert/SKILL.md) |
| `football-betting-assistant` | 中文足球竞彩、赛前分析、胜平负、让球、比分、大小球、串关和赛后复盘辅助 | [`football-betting-assistant/SKILL.md`](football-betting-assistant/SKILL.md) |
| `lottery-number-recommendation` | 大乐透与双色球的完整历史校验、号码推荐和回测辅助 | [`lottery-number-recommendation/SKILL.md`](lottery-number-recommendation/SKILL.md) |

## 安装使用

把需要的 skill 目录复制或链接到你的 agent skills 目录中。例如：

```bash
cp -R football-betting-assistant ~/.codex/skills/
```

例如安装程序员简历专家：

```bash
cp -R ai-resume-expert ~/.codex/skills/
```

不同 agent 的 skills 目录可能不同；以你使用的 agent 文档为准。仓库里的顶层 skill 目录才是开源源码，`.agent/`、`.agents/`、`.claude/`、`.pi/` 等目录是本地运行态或安装态目录，不应该提交。开发或修复已有 skill 时，必须只修改顶层源码目录，例如 `football-betting-assistant/`，不要修改 `.agents/skills/...` 的本地安装副本。

本仓库的开发脚本、单元测试和 CI 要求 **Python 3.10+**。核心 Skill 脚本保持标准库优先；只有需要本地 PDF 交付时才需要额外安装 PDF 渲染依赖。

### `ai-resume-expert` 的本地 PDF 前置能力

该 Skill 的权威简历源文件是 Markdown，PDF 只是由“Markdown → 可打印 HTML”派生的本地交付物。生成 Markdown/HTML 不需要额外 Codex Skill、插件、云端服务或 API key。

需要最终 PDF 时，本机准备一个渲染器即可：LibreOffice / `soffice` 为优先路径，WeasyPrint / `weasyprint` 为备用路径；无需因为 LibreOffice 不可用而必须重装它。要把 PDF 标为完整自动验收通过，还需 Poppler 的 `pdfinfo`、`pdftotext`、`pdftoppm`、`pdffonts`。

macOS 完整路径示例：

```bash
brew install --cask libreoffice  # 可选：首选渲染器
brew install poppler             # 完整 PDF 验收

# 或在虚拟环境中使用备用渲染器
brew install cairo pango gdk-pixbuf libffi
python3 -m venv .venv-ai-resume-expert
. .venv-ai-resume-expert/bin/activate
python -m pip install --requirement ai-resume-expert/requirements-pdf.txt
export PATH="$PWD/.venv-ai-resume-expert/bin:$PATH"
```

Ubuntu 24.04 完整路径示例（与 PDF CI 使用相同的 WeasyPrint + Poppler 路径）：

```bash
sudo apt-get update
sudo apt-get install --yes \
  fontconfig fonts-noto-cjk poppler-utils \
  libcairo2 libffi-dev libgdk-pixbuf-2.0-0 \
  libpango-1.0-0 libpangocairo-1.0-0 shared-mime-info

python3 -m venv .venv-ai-resume-expert
. .venv-ai-resume-expert/bin/activate
python -m pip install --upgrade pip
python -m pip install --requirement ai-resume-expert/requirements-pdf.txt
export PATH="$PWD/.venv-ai-resume-expert/bin:$PATH"
```

LibreOffice 仍可按各系统包管理器安装，且会优先使用；上述 WeasyPrint 路径足以作为完整的本地 PDF 渲染与验证方案。Windows 和其他未在 CI 覆盖的平台属于尽力支持：手动安装可用的 LibreOffice 或 WeasyPrint、Poppler 与中文字体后再运行；若不能提供完整本地栈，应明确交付 Markdown 与可打印 HTML，而不是声称 PDF 已合格。

两个渲染器均不可用/失败，或 Poppler 验收能力不完整时，Skill 会保留并交付 Markdown 与可打印 HTML，不能把未合格的 PDF 称为投递就绪。安装细节、校验命令与降级规则见 [`ai-resume-expert/README.md`](ai-resume-expert/README.md)。

## 仓库结构

推荐每个 skill 使用类似结构：

```text
skill-name/
  SKILL.md
  README.md
  references/
  schemas/
  scripts/
```

其中 `SKILL.md` 是 agent 触发和执行 skill 的主入口；`README.md` 面向人类使用者；`references/`、`schemas/`、`scripts/` 按需提供。运行时 skill 目录不放测试代码或样例数据。

仓库级测试统一放在：

```text
tests/
  skill_name/
    test_*.py
```

仓库级样例和 fixture 统一放在：

```text
examples/
  skill_name/
    *.json
tests/
  fixtures/
    skill_name/
      *.json
```

仓库级行为验收样例统一放在：

```text
evals/
  skill_name/
    evals.json
```

`tests/`、`examples/`、`evals/` 下的目录名使用 Python 友好的下划线形式，例如 `football_betting_assistant/` 对应 `football-betting-assistant`。测试入口、测试 fixture、样例数据和 eval 描述不要放进运行时 skill 目录。

## 生成物目录

面向用户的文件统一写入当前工作目录的 `reports/<skill-name>/`，其中子目录名与顶层 Skill 目录完全一致：

- `reports/ai-resume-expert/`
- `reports/football-betting-assistant/`
- `reports/lottery-number-recommendation/`（仅在用户要求把推荐或回测保存为文件时创建）

不要再创建通用 `output/` 目录，也不要把生成物写进 Skill 安装目录。同步历史、预测快照等可复用运行数据继续放在各 Skill 已声明的 `data/` 命名空间中，不与用户可见报告混放。

## 开发检查

如需做仓库级开发检查，使用仓库根目录下的工具脚本，不把测试入口放进单个 skill 运行时目录：

```bash
python3 scripts/check_all_skills.py
python3 -m unittest discover -s tests -p 'test_*.py'
python3 football-betting-assistant/scripts/validate_inputs.py examples/football_betting_assistant/single-match-input.json
python3 football-betting-assistant/scripts/fetch_match_data.py --football --raw-input tests/fixtures/football_betting_assistant/raw/sporttery-football-sample.json --out /private/tmp/football-snapshots
```

GitHub Actions 会在 Python 3.10 和 3.12 上运行结构检查与全量单元测试；另有固定 Ubuntu 24.04 + Python 3.12 的 PDF QA，安装 WeasyPrint、Poppler 和 Noto CJK 字体后强制执行真实 PDF 渲染与验收测试。PDF 栈不可用时该 QA 会失败，不会静默跳过。

## 贡献

欢迎添加新 skill 或改进已有 skill。提交前请确认：

- 不提交真实 API key、token、密码或私有数据。
- 不提交本地安装态目录，例如 `.agent/`、`.agents/`、`.claude/`、`.pi/`。
- 不提交 IDE、系统缓存或临时文件。
- 每个 skill 至少包含 `SKILL.md` 和面向使用者的 `README.md`。
- 有脚本、schema 或示例输入时，提供可运行的检查命令。

详细约定见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

## 许可

本仓库使用 [MIT License](LICENSE)。
