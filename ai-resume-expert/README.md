# AI 程序员简历专家

面向中国大陆技术岗位的证据优先简历 Skill。它将用户确认的职业事实、授权代码或文档、原简历和 JD 整理为可追溯的 Markdown 简历；确认后可在本地生成并验收 PDF。

## 快速开始

安装后可直接说：

```text
我要申请 Java 高级后端工程师，没有具体 JD。请根据我的经历帮我生成简历；信息不够时一次只问一个最关键的问题。
```

它不会编造经历、个人贡献、技能、数字或结果。读取授权代码只能证明项目事实，不能直接证明个人贡献；私有材料的读取和保存均需明确授权。

开发或诊断时使用统一入口：

```bash
python3 ai-resume-expert/scripts/resume_skill.py doctor
python3 ai-resume-expert/scripts/resume_skill.py route '优化我的后端工程师简历'
```

正式交付物写入当前工作目录的 `reports/ai-resume-expert/`，不会写入 Skill 安装目录。Markdown 是权威源文件；PDF 需要用户确认 Markdown、通过本地自动检查，并由用户完成最终视觉签收。

## macOS PDF 渲染提示

在 macOS 上通过 LibreOffice 渲染 PDF、且当前 Agent 使用命令沙箱时，应让整个 `resume_skill.py render` 命令请求沙箱外执行。仅放行该命令内部的 `soffice` 无法让受限的父进程脱离沙箱；批准范围应精确到 `render` 子命令，**不要关闭整个 Codex 沙箱**。

例如：

```bash
python3 ai-resume-expert/scripts/resume_skill.py render confirmed-resume.md --confirmed --package resume-package.json
```

如果 LibreOffice 出现 `Abort trap: 6`（退出码 `134`），应将其视为渲染失败：保留并交付已确认的 Markdown 与可打印 HTML，说明降级原因；不要把未验证的 PDF 称为合格交付物。

完整支持范围、授权边界、交付门槛和 PDF 降级规则见 [SKILL.md](SKILL.md)。虚构示例见 [examples](../examples/ai_resume_expert/README.md)。
