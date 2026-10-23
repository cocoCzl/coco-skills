# Agent 统一入口

模型优先调用 `scripts/resume_skill.py`，只有需要调试单个能力时才直接调用底层脚本。入口不改变旧命令或业务 Schema，只增加稳定结果信封。

```bash
python3 <skill-dir>/scripts/resume_skill.py doctor
python3 <skill-dir>/scripts/resume_skill.py route '帮我优化 Java 后端简历'
python3 <skill-dir>/scripts/resume_skill.py extract resume.docx --authorized
python3 <skill-dir>/scripts/resume_skill.py scan ./repo --authorized
python3 <skill-dir>/scripts/resume_skill.py validate resume-package.json
python3 <skill-dir>/scripts/resume_skill.py render resume.md
```

结果信封固定包含 `status`、`data_status`、`next_action`、`artifacts`、`warnings`、`error_code` 和耗时。`blocked` 表示必须先处理授权、证据、输入或依赖；`degraded` 表示可以继续，但不能宣称完整能力已经执行。

不要绕过入口返回的阻断项。底层数据位于 `data` 字段，保持原脚本格式，便于旧调用迁移。

明确操作直接调用，不必先运行 `--help`、`doctor`、`route`。`route` 只是启发式建议；复杂否定/混合意图由 Agent 判断，可用 `--intent diagnosis|optimization|repository_evidence|pdf_delivery|generation` 和 `--target-role` 传入已有结论，不重问上下文。输入格式独立于交付意图。`visual_signoff_pending` 表示自动检查通过且用户尚未签收；Agent 完成页面视觉检查后可以交付供审阅，不伪造 `qualified`。

子进程输出必须是 JSON 对象；空、非 JSON 或非对象输出以 `INVALID_CHILD_OUTPUT` 阻断并保留 `raw_output`。stderr 中未在结构化结果出现的诊断保存在 `data.child_diagnostics`，区分 log/warning/error；INFO/DEBUG 不作为警告，成功命令的其他 stderr 同时列入 warnings。退出码决定失败或降级，不因有日志就判为失败；失败和能力缺失始终提供 next_action。
