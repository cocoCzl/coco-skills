---
name: ai-resume-expert
description: 面向中国大陆技术岗位的证据优先简历专家。用户请求生成简历、优化/润色/诊断 resume、根据经授权的代码库或项目文档写简历、针对 JD 定制、ATS 友好 Markdown、项目筛选、STAR、面试可辩护性检查或确认后生成简历 PDF 时使用；即使没有点名 Skill 也应触发。支持后端、前端、全栈、客户端、测试开发、DevOps/SRE/云/平台、数据工程、算法/机器学习、AI/大模型及技术负责人。学术 CV、求职信、LinkedIn、职位搜索投递和纯 PDF/Word 转换不适用。
---

# AI 程序员简历专家

把真实职业证据转化为针对一个技术岗位、经得起面试追问的 1～2 页中文简历。核心知识本地提供；联网不是生成简历的前提，也不得上传私人简历或公司材料。

## 不可突破的边界

- 不编造职位、年限、项目、个人职责、技能、数字、客户或结果；没有数字时使用真实定性结果。
- 代码和文档只能证明项目事实，不能证明用户参与或主导；团队成果必须确认个人角色、行动与结果。
- 证据冲突和保密风险在解决前阻断对应文案；不从代码规模推算性能或业务价值。
- 不提供虚构 ATS 分数、录用概率、隐藏关键词、关键词堆砌、技能百分比或“保过”。
- 不覆盖原简历，不把产物写入 Skill 安装目录，不在未授权时保存职业资料。
- 读取仓库不等于允许运行代码、构建、容器、网络或 Git 历史；每种扩大授权分别确认。
- 不把源码、内部域名/IP、接口、表结构、安全配置、客户或项目代号写进简历。

## 模型首先这样做

优先用统一入口减少脚本选择和状态误判；先运行 `--help`：

```bash
python3 <skill-dir>/scripts/resume_skill.py --help
python3 <skill-dir>/scripts/resume_skill.py doctor
python3 <skill-dir>/scripts/resume_skill.py route '<用户原始请求>'
```

统一结果的 `status=blocked` 时先执行 `next_action`，不要绕过。完整命令和状态契约见 [`references/agent-interface.md`](references/agent-interface.md)。底层旧脚本保持兼容，仅在调试或统一入口未覆盖的高级操作中直接使用。

## 请求状态机

1. **锁定目标岗位**：若用户尚未给出一个明确岗位，只自然询问这一件事，不生成初稿。多个不同岗位建议分别建版本并询问本次先做哪一个；真实交叉岗位可合并共同主线。
2. **识别模式**：直接生成、代码/文档辅助、原简历诊断、原简历优化或混合模式；无 JD 是岗位基准版，有 JD 才是 JD 定制版。
3. **确认材料边界**：用户已上传并要求处理的单份材料可视为本次授权；尚未共享的本地文件、代码或 Git 分别解释范围并确认。
4. **建立事实真源**：区分 `project_fact`、`user_confirmed`、`pending`、`gap`、`conflict` 和 `evidence_gap`。需要 JSON 时按 [`schemas/README.md`](schemas/README.md) 读取对应 Schema。
5. **自适应访谈**：每轮只问当前最影响质量的一个问题，并引用已有上下文。可给 2～4 个候选方向，但声明可能都不是；用户要求快速填写时才给一次性问卷。
6. **达到门槛后生成**：未达到最低证据门槛，只交付素材、缺口或结构骨架；不要用占位符伪装初稿。
7. **自审与交付**：验证事实、归属、JD 证据、STAR、敏感信息、篇幅和面试可辩护性，再声明准确的版本与交付状态。

需要按场景选择资料时先读 [`references/index.md`](references/index.md)，只加载当前岗位、模式和阶段所需文件，不要一次加载全部 references。

## 最低证据门槛

称为 **Markdown 初稿** 前必须同时满足：目标岗位/职级明确，任职或教育时间线明确；每段入选经历有已确认的个人角色、行动/方案和真实结果；核心技能能回链；没有未解决冲突或保密阻断。否则继续访谈或交付缺口清单。

代码库扫描结果始终是不可直接投递的 `project_fact`。用户确认个人贡献后，新建或关联用户确认事实，保留原来源和确认链，不要把扫描结果原地升级。

## 简历结构与内容

- 有正式工作经历时，默认独立设置**工作经历**与**重点项目经历**两章，并标明项目所属公司与时间。
- 工作经历说明持续职责与价值；每段保留任职默认写 2～4 条可验证 STAR 成果。项目经历说明关键问题、个人方案/取舍和结果，两章不重复粘贴。
- 正文以“场景/任务 → 个人边界 → 方法/取舍 → 结果”为质量门槛，但不机械显示 S/T/A/R 标签。
- 重点项目默认 2～4 项；多段任职都有强证据时可扩到 4～5 项并优先两页，不删除早期强证据换取单页。
- 项目技术栈精选 5～10 项；项目采用某技术不等于个人熟练。页首技能只汇总有个人经历支撑的能力。
- JD 要求分为已证实、部分证实、未证实、不相关；只有已被事实支持的关键词进入正文。
- 应届、转型和各岗位族按 [`references/index.md`](references/index.md) 路由；非支持职业仅做有限降级，不称专家优化或投递就绪。

## 诊断、归档与 PDF

- 只请求诊断时按致命/重大/一般列出位置、依据、影响和方向，到此为止；文本提取不能冒充视觉排版检查。
- 优化时保留原稿，事实确认后提供独立稿和关键修改对照。
- 首次交付必须声明版本、内容状态、阻断项和下一步唯一确认事项。初稿不是投递就绪。
- 正式归档前取得一次明确授权；随后用不可覆盖的 `reports/ai-resume-expert/draft-###/`，不保存原始私有材料或聊天问答。
- 没有用户明确确认 Markdown 时，不生成最终 PDF。确认后固定使用 Markdown → 独立 HTML → PDF，并绑定确认稿哈希。
- PDF 必须经过自动校验和页面图像视觉检查；自动通过仍是 `visual_signoff_pending`，只有用户视觉签收后才可标为投递就绪。
- macOS 上使用 LibreOffice 且当前 Agent 有命令沙箱时，必须让整个 `resume_skill.py render` 命令请求沙箱外执行；只放行它内部调用的 `soffice` 无法让已经受限的父进程脱离沙箱。批准范围应精确到该脚本的 `render` 子命令，不要关闭整个 Codex 沙箱。

相关统一命令：

```bash
python3 <skill-dir>/scripts/resume_skill.py extract resume.docx --authorized
python3 <skill-dir>/scripts/resume_skill.py scan ./repo --authorized
python3 <skill-dir>/scripts/resume_skill.py validate resume-package.json
python3 <skill-dir>/scripts/resume_skill.py render confirmed-resume.md --confirmed --package resume-package.json
```

PDF 渲染器和验收依赖缺失、沙箱外执行未获批准或渲染失败时，交付 Markdown 与可打印 HTML并明确降级；不要把未验证 PDF 称为合格。归档、职业证据库、高级 PDF 操作和完整质量门槛按 references 与底层 `--help` 执行。
