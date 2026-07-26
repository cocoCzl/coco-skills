# AI Resume Expert 示例

本目录只包含虚构资料，用于理解 `ai-resume-expert` 的输入方式和输出边界。示例中的人物、公司、项目、域名和数字均为演示用途，不对应真实个人或企业。

## 示例文件

- `direct-backend-profile.md`：信息较充分的后端工程师直接描述。
- `backend-jd.md`：用于演示 JD 要求覆盖的虚构招聘描述。
- `legacy-resume.md`：用于诊断和优化演示的故意写差的原简历。
- `multi-project-inventory.md`：用于项目排序与淘汰理由演示的虚构多项目清单。
- `sample-resume.md`：达到最低证据门槛后的岗位基准版 Markdown 示例。
- `prompts.md`：四种输入模式和关键失败路径的自然语言请求示例。
- `visual-review-graduate.md`：应届/实习一页视觉样本源文件。
- `visual-review-transition.md`：Java 转 AI 应用的两页视觉样本源文件。
- `visual-review-tech-lead.md`：技术负责人/架构师视觉样本源文件。

## 推荐体验顺序

1. 先只发送 `direct-backend-profile.md`，观察 Skill 是否先确认目标岗位与目标职级，再生成岗位基准版。
2. 加入 `backend-jd.md`，观察要求是否被标记为“已证实 / 部分证实 / 未证实 / 不相关”，而不是生成 ATS 百分比。
3. 单独请求诊断 `legacy-resume.md`，确认它不会擅自重写整份简历。
4. 明确请求优化，并检查修改对照是否包含原文、改后、原因与证据。
5. 只有明确确认 Markdown 且补齐联系方式后，再测试本地 PDF 生成。

私有代码、公司文档和真实简历应当在使用者有权处理、理解当前平台数据政策并明确授权后才能读取。读取仓库默认只做静态分析，不等于授权执行代码、读取 Git 历史或公开内部信息。
