# Contributing

感谢你改进 `coco-skills`。这个仓库的目标是让别人 clone 后可以直接理解、安装和验证每个 skill，而不是依赖某个人本地的 agent 运行态目录。

## 添加新 Skill

每个 skill 应放在仓库顶层的独立目录中：

```text
skill-name/
  SKILL.md
  README.md
```

推荐按需添加：

```text
references/
examples/
schemas/
scripts/
```

`SKILL.md` 应包含清晰的触发描述、执行边界、需要读取的参考文件和输出要求。`README.md` 应面向人类使用者说明安装、配置和示例。运行时 skill 目录不放测试代码。

## 开发环境

仓库脚本、单元测试和 CI 的最低版本是 **Python 3.10**。核心 Skill 保持标准库优先；只有维护或验证 `ai-resume-expert` 的真实本地 PDF 路径时，才在虚拟环境中安装可选依赖：

```bash
python3 -m venv .venv-ai-resume-expert
. .venv-ai-resume-expert/bin/activate
python -m pip install --requirement ai-resume-expert/requirements-pdf.txt
```

GitHub Actions 会在 Python 3.10 和 3.12 运行结构检查及全量单元测试，并在 Ubuntu 24.04 + Python 3.12 上单独验证真实 WeasyPrint、Poppler 和中文字体 PDF 栈。不要把个人机器的 PDF、PNG、预览或签收记录提交到仓库。

## 不要提交的内容

不要提交：

- 真实 API key、token、密码、cookie 或私有配置。
- `.agent/`、`.agents/`、`.claude/`、`.codex/`、`.pi/`、`.venv/`、`.venv-*/`、`skills-lock.json` 等本地运行态文件。
- `data/`、`reports/`、`output/`、`.skill-workspaces/` 等本地数据、生成物或评估运行目录。
- `.env`、IDE 配置、系统缓存、`.DS_Store`、`__pycache__/`、测试缓存。
- 只能在个人机器上生效的绝对路径或个人用户名。

修改已有 skill 时必须改仓库顶层的源码目录，例如 `football-betting-assistant/`。不要把 `.agents/skills/...`、`.codex/skills/...` 或其他本地安装态目录当作源码；这些目录不会作为 GitHub 发布内容，也不应该出现在提交中。

如果示例需要配置，请使用占位符，例如：

```bash
THE_ODDS_API_KEY=your_api_key
```

## 检查要求

提交前运行：

```bash
python3 scripts/check_all_skills.py
```

## 文档要求

新增或修改 skill 时，请同步更新：

- skill 自己的 `README.md`
- 示例输出或输入
- 仓库根目录 `README.md` 的 skill 列表

## 安全和合规

Skill 可以指导用户配置外部服务，但不能内置凭据、绕过访问限制、抓取未授权数据，或暗示拥有未验证的实时数据能力。涉及投注、医疗、法律、金融等高风险领域时，应保留清晰的限制说明和风险提示。
