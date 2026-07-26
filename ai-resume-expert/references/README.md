# AI Resume Expert 参考资料目录

本目录是 `ai-resume-expert` 的离线知识库。主入口只负责流程与路由；执行具体任务时按下表加载最小必要资料，避免把所有岗位知识一次塞入上下文。

## 加载规则

1. 使用 `CONTEXT.md` 中的规范术语；本目录不重新定义同义词。
2. 生成或优化简历时，先加载通用规则、访谈门槛、证据治理，再加载一个目标岗位策略。
3. 有 JD 时额外加载 JD 与项目选择资料；没有 JD 时称为“岗位基准版”，不得声称完成具体岗位匹配。
4. 诊断原简历时加载诊断资料；只有用户明确要求优化时才再加载生成与输出资料。
5. 只有 Markdown 已由用户明确确认、联系方式已确认且要生成 PDF 时，才加载最终输出与 PDF 门槛。
6. 复合岗位只组合直接相关的策略。例如“后端 + 大模型应用”加载后端与 AI/LLM；不要加载全部岗位。
7. 文件或要求冲突时，优先顺序为：不可突破的真实性、安全与产品边界 > `CONTEXT.md` 规范术语 > 用户当前任务范围与合法偏好 > 岗位策略 > 表达模板。用户要求不能放宽授权、证据、保密或不虚构门槛。

## 路由表

| 场景 | 必读 | 按需加读 |
|---|---|---|
| 直接描述生成 | `common-resume-rules.md`、`interview-and-readiness.md`、`evidence-jd-and-projects.md` | 一个或两个 `roles/` 策略、`output-and-quality-gates.md` |
| 代码/文档辅助 | 上述三份 | `repository-evidence-and-confidentiality.md`、岗位策略 |
| 原简历诊断 | `common-resume-rules.md`、`resume-diagnosis.md` | 岗位策略、`evidence-jd-and-projects.md` |
| 原简历优化 | 诊断所需资料 + `interview-and-readiness.md`、`evidence-jd-and-projects.md` | 岗位策略、`output-and-quality-gates.md` |
| JD 定制 | 生成/优化所需资料 | `evidence-jd-and-projects.md` 中的 JD 四态覆盖、岗位策略中的 JD 提示 |
| PDF 交付 | 已确认的 Markdown 和事实真源 | `output-and-quality-gates.md` |
| 职业证据库 | `evidence-jd-and-projects.md`、[`../schemas/README.md`](../schemas/README.md) | 不得把目标 JD 文案写回真源 |

## 通用资料

- [`common-resume-rules.md`](common-resume-rules.md)：真实性、STAR、量化、ATS、篇幅、技能、项目归属和职业阶段。
- [`interview-and-readiness.md`](interview-and-readiness.md)：自然访谈、单问优先级、候选回答、批量问卷与最低证据门槛。
- [`evidence-jd-and-projects.md`](evidence-jd-and-projects.md)：证据状态、冲突、追踪表、JD 四态、项目排序和职业事实真源。
- [`repository-evidence-and-confidentiality.md`](repository-evidence-and-confidentiality.md)：本地代码/文档授权、安全扫描、事实提取、覆盖声明与保密脱敏。
- [`resume-diagnosis.md`](resume-diagnosis.md)：致命/重大/一般诊断、视觉审查、OCR 降级和修改对照。
- [`output-and-quality-gates.md`](output-and-quality-gates.md)：交付物模板、自审、面试可辩护性、投递就绪和 PDF 门槛。
- [`role-routing.md`](role-routing.md)：目标岗位规范化、交叉岗位、职业阶段和有限降级。

## 首版岗位策略

- [`roles/backend.md`](roles/backend.md)
- [`roles/frontend.md`](roles/frontend.md)
- [`roles/fullstack.md`](roles/fullstack.md)
- [`roles/client-mobile.md`](roles/client-mobile.md)
- [`roles/test-development.md`](roles/test-development.md)
- [`roles/devops-sre-cloud-platform.md`](roles/devops-sre-cloud-platform.md)
- [`roles/data-engineering.md`](roles/data-engineering.md)
- [`roles/algorithm-ml.md`](roles/algorithm-ml.md)
- [`roles/ai-llm.md`](roles/ai-llm.md)
- [`roles/tech-lead-architect.md`](roles/tech-lead-architect.md)

所有示例均为虚构、脱敏示例。示例中的写法可以复用，事实和数字不能移植到用户简历。
