# AI Resume Expert 验收追踪

本表把 [PRD](./PRD-ai-resume-expert.md) 的 AC-01～AC-52 映射到实现切片和可观察验证。行为评测位于 `evals/ai_resume_expert/evals.json`，确定性契约测试位于 `tests/ai_resume_expert/`。行为评测允许文案差异，只验证必要行为、禁止行为和产物属性。

> 自动 PDF 验收与 AIRES-024 的人工视觉签收是两个门槛：源 Markdown 绑定的自动检查通过后，PDF 状态仍为 `visual_signoff_pending`，不可交付。只有用户查看代表性页面并确认，且签收记录与 PDF、Markdown、预览资源哈希一致时，才可成为 `qualified`。真实 PDF CI 只验证自动链路，不替代该 HITL 步骤，也不证明某台本机已通过真实 PDF 验收。

| AC | Issue | 主要实现 | 验证证据 |
|---|---|---|---|
| AC-01 | AIRES-001/003 | `SKILL.md` 第一响应与单问门槛 | Eval 1、4；`test_skill_contract.py` |
| AC-02 | AIRES-002 | 岗位基准版路由与输出契约 | Eval 3 |
| AC-03 | AIRES-004 | JD 四态覆盖与证据化关键词 | Eval 8、9 |
| AC-04 | AIRES-004 | 多目标岗位分流 | Eval 6、7 |
| AC-05 | AIRES-001/012 | 不支持岗位有限降级 | Eval 2、23 |
| AC-06 | AIRES-001/019 | 五类请求模式与统一真源 | Eval 3、24、27、28、30 |
| AC-07 | AIRES-013/014 | 项目事实与个人贡献分离 | Eval 25；`test_repository_scan.py` |
| AC-08 | AIRES-002/014 | 未确认贡献阻断 | Eval 4、25；`test_evidence_tools.py` |
| AC-09 | AIRES-002/014/021 | 用户确认事实可进入真源 | `evidence-record.schema.json`；`test_evidence_tools.py` |
| AC-10 | AIRES-014/019 | 证据冲突阻断 | Eval 26、30；`test_evidence_tools.py` |
| AC-11 | AIRES-002/014 | 无可靠数字使用定性结果 | Eval 16、17、20、26 |
| AC-12 | AIRES-002/014 | 量化依据与确认状态 | Eval 3、19；`test_evidence_tools.py` |
| AC-13 | AIRES-003 | 一次一个高价值问题、不重复 | Eval 1、4 |
| AC-14 | AIRES-003 | 候选回答可全部否定 | Eval 4 |
| AC-15 | AIRES-003 | 批量结构化问卷 | Eval 5 |
| AC-16 | AIRES-002/003 | 最低证据门槛 | Eval 4；`validate_resume_package.py` 契约测试 |
| AC-17 | AIRES-013 | 私有材料授权与平台提示 | Eval 24；`test_repository_scan.py` |
| AC-18 | AIRES-013 | 敏感、依赖、构建和大文件排除 | Eval 25；`test_repository_scan.py` |
| AC-19 | AIRES-013 | 静态只读、不执行 | Eval 24、25；`test_repository_scan.py` |
| AC-20 | AIRES-013 | Git 独立授权 | Eval 24；`test_repository_scan.py` |
| AC-21 | AIRES-013 | 扫描覆盖声明 | Eval 25；`test_repository_scan.py` |
| AC-22 | AIRES-013/014 | 私有源码与内部标识不进入产物 | Eval 25、36；`test_repository_scan.py` |
| AC-23 | AIRES-016/018 | 原简历只读、优化稿另存 | Eval 28；`test_resume_extraction.py` |
| AC-24 | AIRES-005 | 项目排序、理由、淘汰与用户决定 | Eval 10 |
| AC-25 | AIRES-005 | 公司核心项目归入任职经历 | Eval 3、10 |
| AC-26 | AIRES-005/011 | 转型证明项目明确来源 | Eval 12 |
| AC-27 | AIRES-002/007～012 | 技能与经历互证 | Eval 3、9、13～22 |
| AC-28 | AIRES-002 | STAR 用于核实、正文不显示标签 | Eval 3 |
| AC-29 | AIRES-004 | 未满足 JD 只进入证据差距 | Eval 8、9 |
| AC-30 | AIRES-005/006 | 岗位/阶段动态结构与项目数量 | Eval 10～12 |
| AC-31 | AIRES-002/006 | 最小必要个人信息 | `common-resume-rules.md`；Eval 3 |
| AC-32 | AIRES-015 | 三档诊断、不自动重写 | Eval 27 |
| AC-33 | AIRES-004/015 | 无假分数、ATS 百分比或录用概率 | Eval 8、27 |
| AC-34 | AIRES-018 | 独立优化稿与四列修改对照 | Eval 28 |
| AC-35 | AIRES-014/019 | 关键陈述来源、确认与保密状态 | Eval 3、30；`evidence-trace.schema.json` |
| AC-36 | AIRES-016/017 | 完整诊断与文本诊断能力降级 | Eval 29；`test_resume_extraction.py` |
| AC-37 | AIRES-002/020 | 初稿九项自审 | Eval 3、31 |
| AC-38 | AIRES-012/020 | 不可辩护强陈述降级或删除 | Eval 20～22、31 |
| AC-39 | AIRES-019/020 | 初稿无冲突、待确认、保密阻断与大量占位符 | `validate_resume_package.py`；`test_evidence_tools.py` |
| AC-40 | AIRES-020/022 | Markdown 明确确认后才生成 PDF | Eval 33、34；`test_pdf_pipeline.py` |
| AC-41 | AIRES-020/022 | PDF 前联系方式已确认 | Eval 31、33；`test_evidence_tools.py` |
| AC-42 | AIRES-022/023/024 | 自动验证单栏、文本型、稳定顺序、灰度、1～2 页 | Eval 34；`test_pdf_pipeline.py`；真实 PDF QA（自动检查） |
| AC-43 | AIRES-023/024 | 自动检查字体、分页、截断、链接、孤行与可读性；哈希绑定的用户视觉签收才解除交付阻断 | `validate_pdf.py --visual-signoff`；`record_pdf_visual_signoff.py`；`test_pdf_pipeline.py`；AIRES-024 用户签收待完成 |
| AC-44 | AIRES-023 | PDF 失败降级到 Markdown + HTML | Eval 35；`test_pdf_pipeline.py` |
| AC-45 | AIRES-021 | 职业证据库显式选择与指定路径 | Eval 32；`test_career_store.py` |
| AC-46 | AIRES-021 | 证据库敏感与文案字段过滤 | Eval 32；`test_career_store.py` |
| AC-47 | AIRES-021/022/025 | 用户产物与真源不写入 Skill 包；简历产物默认进入 `reports/ai-resume-expert/` | Eval 32、34；`test_career_store.py`；`test_pdf_pipeline.py`；Git 状态审计 |
| AC-48 | AIRES-007～012/025 | 每个首版岗位策略的基准与 JD 行为评测 | Eval 3、8、13～22、37～46；`test_skill_contract.py` |
| AC-49 | AIRES-006/025 | 四个职业阶段结构差异 | Eval 3、11、12、22 |
| AC-50 | AIRES-019/025 | 输入模式、岗位/JD、访谈拒绝、冲突、保密、视觉与降级完整矩阵 | Eval 1～55；`test_skill_contract.py` |
| AC-51 | AIRES-013/016/021/023/024 | 脱敏 fixture、临时目录与黑盒契约 | `test_repository_scan.py`、`test_resume_extraction.py`、`test_evidence_tools.py`、`test_career_store.py`、`test_pdf_pipeline.py`（含签收有效/无效/陈旧与哈希不匹配） |
| AC-52 | AIRES-001/025 | 入口、README、总览、示例、评测、结构与 CI 发布门槛 | `scripts/check_all_skills.py`；`test_skill_contract.py`；GitHub Actions 基础矩阵与 PDF QA |

## 发布检查命令

```bash
python3 scripts/check_all_skills.py
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m json.tool evals/ai_resume_expert/evals.json >/dev/null
```

PDF 自动验收之外，还应检查 Git 状态，确认没有真实简历、个人信息、公司源码、密钥、生成报告、视觉签收 JSON 或私有配置进入提交范围。公开 CI 的自动通过不是默认视觉风格的用户签收。
