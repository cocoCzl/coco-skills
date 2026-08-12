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
