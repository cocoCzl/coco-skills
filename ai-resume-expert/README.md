# AI 程序员简历专家

面向中国大陆技术岗位的证据优先简历 Skill。它将用户确认的职业事实、授权代码或文档、原简历和 JD 整理为可追溯的 Markdown 简历；确认后可在本地生成并验收 PDF。

## 快速开始

安装后可直接说：

```text
我要申请 Java 高级后端工程师，没有具体 JD。请根据我的经历帮我生成简历；复用我已提供的信息，只补问少量相关关键缺口。
```

它不会编造经历、个人贡献、技能、数字或结果。读取授权代码只能证明项目事实，不能直接证明个人贡献；私有材料的读取和保存均需明确授权。

开发或诊断时使用统一入口：

```bash
python3 ai-resume-expert/scripts/resume_skill.py doctor
python3 ai-resume-expert/scripts/resume_skill.py route '优化我的后端工程师简历'
```

正式交付物写入当前工作目录的 `reports/ai-resume-expert/`，不会写入 Skill 安装目录。Markdown 是权威源文件。内容确认后可导出 PDF；自动检查通过且 Agent 已检查所有页面后即可交付供审阅，用户审阅状态单列，不强制追加签收。可选用户签收记录仍绑定当前文件哈希。

明确任务直接执行对应命令，不必先跑 `--help`、`doctor`、`route`。路由只是建议，PDF 输入不等于 PDF 导出；复杂意图由 Agent 判断。普通文字任务不必创建 JSON 包；结构化交接和 PDF 仍需确定性包校验。资料按 [阶段索引](references/index.md) 加载。

PDF 实际出错时再看 [按需故障排查](references/pdf-troubleshooting.md)，依据依赖、字体、渲染器及当前沙箱错误处理权限问题。

完整支持范围、授权边界、交付门槛和 PDF 降级规则见 [SKILL.md](SKILL.md)。虚构示例见 [examples](../examples/ai_resume_expert/README.md)。
