# 轻量评测执行

`*/evals.json` 是行为输入和预期，`*/trigger-evals.json` 是平衡的正/负近邻触发请求。`check_all_skills.py` 和 `test_eval_contract.py` **只检查这些文件的结构**，不会运行模型。脚本回归由 `tests/` 执行，真实 Agent 结果另记。

## 对比真实 Agent

1. 修改前用 `git archive <baseline-revision>` 解到临时目录，保留旧 Skill 和相同 fixtures；当前源码保留为另一配置。不要读取本机安装态 Skill 替代仓库源码。
2. 选择同一个行为案例，在两个全新 Agent 会话中执行；给相同输入、权限、工具、模型与输出要求，唯一差异是 Skill 路径。声明从指定 `SKILL.md` 开始，实际完成任务，不让 Agent 只点评规范。Skill 已包含用户明确授权时不再追问。
3. 可用当前环境的隔离 Agent 执行能力。若只有 CLI，可分别在两套源码根目录运行下列命令；`prompt.txt` 包含案例全文、指定 Skill 路径、fixtures 和临时输出路径。CLI 不可用、缺身份或环境不支持时明确未运行，不以静态测试替代。

```bash
codex exec --help
codex exec --skip-git-repo-check --sandbox workspace-write --json \
  -C /tmp/baseline-source --output-last-message /tmp/before-answer.txt \
  - < /tmp/before-prompt.txt > /tmp/before-events.jsonl
# 用相同任务、新的独立会话在当前源码重复，事件和产物均写 /tmp
```

4. 从执行记录数真实工具调用、读取的唯一路径/字节与重复读取量、追问/确认、耗时；区分外层编排调用与实际执行调用，子进程不重复算工具调用。记录是否完成预期、脚本误路由是否被 Agent 纠正、事实是否失真。tokens 仅取运行器真实 usage；无 usage 就填 unavailable，不估算。
5. 检查两份实际产物，按案例预期打分。输出/事件/指标/查看器全部放临时目录，不提交过程日志。单次前后比较只作案例证据；耗时含模型延迟，不能归因为纯脚本改动。触发集需在仅给可用 Skill 描述的会话测试，指定 Skill 的行为执行不证明自动触发精度。

## 本轮高价值复现入口

- 简历：诊断 PDF 且否定导出；测试开发/客户端已有定位；已确认事实直接生成；缺 PDF 依赖降级。
- 足球：海外赔率 fetch 明确不支持；竞彩 raw fixture 可抓取；复盘/回测不误回赛程发现；局部让球解释不重生成报告。
- Java：批量中断恢复与完整扫描等价；修改/删除/配置变化后模型一致；无 Mermaid 时交付 mmd 并说明未视觉验证。
- 彩票：推荐内部一次同步；同日缓存复用但最新页仍校验；全量历史更正、失败恢复和回测隔离标准保持。

脚本复现和成本基准按 [QUALITY_STANDARD.md](../QUALITY_STANDARD.md) 执行。网络真实时效、完整 PDF 栈和不同模型触发精度需分别记录验证环境与缺项。
