# AI Resume Expert deterministic contracts

本目录定义职业事实、证据追踪、简历交付门槛和可选职业证据库的稳定数据契约。它们服务于事实治理与本地工具衔接，不负责模型写作。

## 目录

- [何时读取哪个 Schema](#何时读取哪个-schema)
- [CLI 速查](#cli-速查)
- [仓库扫描到证据记录的映射](#仓库扫描到证据记录的映射)
- [最小有效 resume_package](#最小有效-resume_package)
- [最小有效独立 evidence_trace](#最小有效独立-evidence_trace)
- [职业证据库最小文件与操作输入](#职业证据库最小文件与操作输入)

## 何时读取哪个 Schema

| 文件 | 读取时机 | 用途 |
|---|---|---|
| `evidence-record.schema.json` | 从访谈、原简历、代码或文档建立素材清单时 | 表达来源、状态、归属确认、披露、量化依据和冲突；`observed_project_fact` 不能证明个人贡献 |
| `resume-package.schema.json` | 生成 Markdown 前，以及用户确认 Markdown、准备生成 PDF 前 | 把目标岗位、时间线、正式陈述、技能、追踪表、自审、确认哈希和联系方式放入同一交付门槛 |
| `evidence-trace.schema.json` | 需要把证据追踪表作为独立产物交付或复验时 | 在不复制简历全文的前提下，把正式陈述关联到职业事实 |
| `career-evidence-store.schema.json` | 用户明确选择创建、更新或复用本地职业证据库时 | 保存与目标岗位/JD 文案分离的已确认、可披露职业事实 |
| `pdf-visual-signoff.schema.json` | 自动 PDF 验收通过、用户逐页确认彩色与灰度预览后 | 绑定自动验收报告、当前 PDF、Markdown 和预览文件哈希；只有有效记录才能解除 PDF 交付阻断 |

规则边界：

- 扫描仓库得到的记录保持 `fact_type: project_fact`、`status: observed_project_fact`、`ownership.confirmed_by_user: false` 和 `resume_eligible: false`。
- 代码、文档或 Git 只能产生项目事实和候选线索。个人经历陈述必须再引用已由用户确认的 `personal_contribution` 或 `star_evidence`。
- 数字型结果的 `source_ids` 必须真实存在于所引用事实的 `sources` 中，并具有依据与用户确认。
- `disclosure.status: approved` 或 `sanitized` 只有在 `confirmed_by_user: true` 后才可支持投递文案；`sanitized` 还必须提供 `sanitized_statement`。原内部陈述不得进入职业证据库或正式简历。
- `conflict.status: resolved` 必须同时记录非空 `resolution` 和 `resolved_by_user: true`；没有用户澄清的冲突仍是阻断项。
- Schema 是交换格式；实际交付还必须运行确定性校验器。所有 CLI 正常输出和错误输出都是 JSON，阻断时返回非零状态码。

## CLI 速查

以下命令从 Skill 根目录执行；也可把脚本路径换成绝对路径。

```text
python3 scripts/validate_resume_package.py /absolute/path/resume-package.json
python3 scripts/validate_resume_package.py /absolute/path/resume-package.json --stage pdf
python3 scripts/validate_resume_package.py /absolute/path/evidence-trace.json

python3 scripts/validate_pdf.py /absolute/path/resume.pdf --source-markdown /absolute/path/resume.md --output-dir /absolute/path/reports
python3 scripts/record_pdf_visual_signoff.py --validation-report /absolute/path/resume.validation.json --output /absolute/path/resume.visual-signoff.json --confirmed-by-user
python3 scripts/validate_pdf.py /absolute/path/resume.pdf --source-markdown /absolute/path/resume.md --visual-signoff /absolute/path/resume.visual-signoff.json --output-dir /absolute/path/reports

python3 scripts/scan_repository.py /absolute/path/repository --authorized
python3 scripts/scan_repository.py /absolute/path/repository --authorized --include-git-hints --git-authorized

python3 scripts/extract_resume.py /absolute/path/resume.md --authorized
python3 scripts/extract_resume.py /absolute/path/resume.docx --authorized
python3 scripts/extract_resume.py /absolute/path/resume.pdf --authorized

python3 scripts/career_store.py create --path /absolute/user/work/career-evidence.json --input /absolute/path/confirmed-facts.json --opt-in
python3 scripts/career_store.py update --path /absolute/user/work/career-evidence.json --input /absolute/path/update-facts.json --opt-in
python3 scripts/career_store.py reuse --path /absolute/user/work/career-evidence.json --target-role "Java 后端开发工程师" --opt-in
```

安全说明：`scan_repository.py` 的 `--authorized` 只授权静态读取，不授权运行代码、构建、测试、脚本、容器、网络或 Git。Git 线索必须再同时提供 `--include-git-hints --git-authorized`。`extract_resume.py` 只探测固定的本地 `pdftotext` 命令，不接受任意可执行文件覆盖。职业证据库写入路径必须由用户指定且位于 Skill 包外。

## 仓库扫描到证据记录的映射

`scan_repository.py` 同时输出两种视图：

- `project_facts` 是便于 Agent 向用户解释的扫描发现。
- `evidence_records` 是可直接合并进 `resume_package.career_facts` 的 `evidence-record.schema.json` 兼容记录，来源不会在转换时丢失。

映射后的关键字段固定如下：

| 扫描含义 | `evidence_records` 字段 |
|---|---|
| 只能证明项目存在某项能力 | `fact_type: project_fact` |
| 尚未由用户确认事实与归属 | `status: observed_project_fact`、`resume_eligible: false` |
| 不能归功于用户 | `ownership.status: pending`、`ownership.confirmed_by_user: false` |
| 尚未完成可披露确认 | `disclosure.status: unknown` |
| 已查看来源 | `sources[].source_id/type/locator`，locator 使用不暴露内部代号的安全定位符 |
| 尚无互斥材料 | `conflict.status: none` |

这些记录可以进入素材清单，但不能原样支撑正式陈述或技能。只有用户确认项目事实、个人角色、行动、结果和披露边界后，才能新增独立的 `personal_contribution`/`star_evidence` 确认事实；不要直接把扫描记录改名成个人贡献。

## 最小有效 `resume_package`

下面示例可通过 Markdown 门槛；联系方式允许在这一阶段为空。PDF 门槛还需把 `stage` 改为 `pdf_ready`，将 `markdown.confirmed_by_user` 设为 `true`，补齐 `markdown.path`、已确认内容的 `sha256`、`confirmed_at`，以及经过用户确认的姓名、手机号、邮箱和城市。

```json
{
  "schema_version": "1.0",
  "kind": "resume_package",
  "stage": "markdown_draft",
  "target": {
    "role": "Java 后端开发工程师",
    "level": "高级",
    "market": "中国大陆",
    "language": "中文",
    "version_type": "role_baseline"
  },
  "timeline": [
    {
      "id": "timeline-1",
      "type": "employment",
      "organization": "某企业软件公司",
      "role": "后端开发工程师",
      "start": "2022.01",
      "end": "至今",
      "confirmed_by_user": true
    }
  ],
  "career_facts": [
    {
      "id": "fact-contribution-1",
      "fact_type": "personal_contribution",
      "statement": "设计并实现异步任务状态与异常追踪机制。",
      "status": "confirmed",
      "sources": [
        {
          "source_id": "source-user-1",
          "type": "user_statement",
          "locator": "本次职业访谈：异步任务经历"
        }
      ],
      "ownership": {
        "status": "confirmed",
        "confirmed_by_user": true,
        "confirmation_source_id": "source-user-1"
      },
      "disclosure": {
        "status": "approved",
        "confirmed_by_user": true
      },
      "star": {
        "situation": "耗时任务阻塞接口且异常难以追踪。",
        "task": "改造任务执行与状态记录。",
        "action": "隔离耗时任务并记录状态和异常上下文。",
        "result": "接口能够快速返回，问题定位更可追踪。",
        "confirmed_by_user": true
      },
      "quantification": {
        "kind": "qualitative",
        "confirmed_by_user": true
      },
      "conflict": {
        "status": "none"
      }
    }
  ],
  "claims": [
    {
      "id": "claim-1",
      "text": "设计并实现异步任务状态与异常追踪机制，使接口能够快速返回并增强问题定位的可追踪性。",
      "claim_type": "experience",
      "included": true,
      "fact_ids": ["fact-contribution-1"],
      "ownership_required": true,
      "ownership_confirmed": true,
      "disclosure_status": "approved",
      "star": {
        "role": "任务执行模块后端开发者",
        "action": "隔离耗时任务并补充状态和异常记录。",
        "result": "接口快速返回，问题定位更可追踪。",
        "confirmed_by_user": true
      },
      "quantification": {
        "kind": "qualitative",
        "confirmed_by_user": true
      },
      "interview_defensible": true
    }
  ],
  "skills": [
    {
      "name": "Java",
      "proficiency": "proficient",
      "fact_ids": ["fact-contribution-1"],
      "confirmed_by_user": true
    }
  ],
  "evidence_trace": [
    {
      "claim_id": "claim-1",
      "fact_ids": ["fact-contribution-1"],
      "ownership_confirmed": true,
      "disclosure_status": "approved",
      "quantification_confirmed": true
    }
  ],
  "conflicts": [],
  "confidentiality_blockers": [],
  "markdown": {
    "confirmed_by_user": false,
    "self_review": {
      "facts": true,
      "target_alignment": true,
      "confidentiality": true,
      "duplication": true,
      "length": true,
      "defensibility": true
    }
  },
  "contact": {
    "confirmed_by_user": false
  }
}
```

仓库级可执行示例位于 `tests/fixtures/ai_resume_expert/resume-package-valid.json`。

## 最小有效独立 `evidence_trace`

`facts` 使用与上例相同的完整 `fact-contribution-1` 记录：

```json
{
  "schema_version": "1.0",
  "kind": "evidence_trace",
  "facts": [
    {
      "id": "fact-contribution-1",
      "fact_type": "personal_contribution",
      "statement": "设计并实现异步任务状态与异常追踪机制。",
      "status": "confirmed",
      "sources": [
        {
          "source_id": "source-user-1",
          "type": "user_statement",
          "locator": "本次职业访谈：异步任务经历"
        }
      ],
      "ownership": {
        "status": "confirmed",
        "confirmed_by_user": true
      },
      "disclosure": {
        "status": "approved",
        "confirmed_by_user": true
      },
      "conflict": {
        "status": "none"
      }
    }
  ],
  "claims": [
    {
      "id": "claim-1",
      "claim_type": "experience",
      "included": true,
      "fact_ids": ["fact-contribution-1"]
    }
  ],
  "entries": [
    {
      "claim_id": "claim-1",
      "fact_ids": ["fact-contribution-1"],
      "ownership_confirmed": true,
      "disclosure_status": "approved",
      "quantification_confirmed": true
    }
  ]
}
```

## 职业证据库最小文件与操作输入

职业证据库只保存确认事实，不保存原简历全文、源码摘录或 JD 文案。最小已创建文件如下：

```json
{
  "schema_version": "1.0",
  "kind": "career_evidence_store",
  "store_id": "career-store-fictional",
  "created_at": "2026-07-26T12:00:00Z",
  "updated_at": "2026-07-26T12:00:00Z",
  "target_independent": true,
  "facts": [
    {
      "id": "fact-contribution-1",
      "fact_type": "personal_contribution",
      "statement": "设计并实现异步任务状态与异常追踪机制。",
      "status": "confirmed",
      "sources": [
        {
          "source_id": "source-user-1",
          "type": "user_statement",
          "locator": "本次职业访谈：异步任务经历"
        }
      ],
      "ownership": {
        "status": "confirmed",
        "confirmed_by_user": true
      },
      "disclosure": {
        "status": "approved",
        "confirmed_by_user": true
      },
      "conflict": {
        "status": "none"
      }
    }
  ]
}
```

`create` 的 `/absolute/path/confirmed-facts.json` 可以是上面的事实数组包装：

```json
{
  "facts": [
    {
      "id": "fact-contribution-1",
      "fact_type": "personal_contribution",
      "statement": "设计并实现异步任务状态与异常追踪机制。",
      "status": "confirmed",
      "sources": [
        {
          "source_id": "source-user-1",
          "type": "user_statement",
          "locator": "本次职业访谈：异步任务经历"
        }
      ],
      "ownership": {
        "status": "confirmed",
        "confirmed_by_user": true
      },
      "disclosure": {
        "status": "approved",
        "confirmed_by_user": true
      },
      "conflict": {
        "status": "none"
      }
    }
  ]
}
```

`update` 使用同一包装格式，只提交要新增或按稳定 `id` 替换的确认事实。例如 `/absolute/path/update-facts.json`：

```json
{
  "facts": [
    {
      "id": "fact-skill-postgresql",
      "fact_type": "skill",
      "statement": "在后端项目中使用 PostgreSQL 完成数据访问开发。",
      "status": "confirmed",
      "sources": [
        {
          "source_id": "source-user-2",
          "type": "user_statement",
          "locator": "本次职业访谈：技能使用情况"
        }
      ],
      "ownership": {
        "status": "confirmed",
        "confirmed_by_user": true
      },
      "disclosure": {
        "status": "approved",
        "confirmed_by_user": true
      },
      "conflict": {
        "status": "none"
      }
    }
  ]
}
```

`reuse` 是只读操作，但仍要求用户明确 `--opt-in`。`--target-role` 只出现在本次命令输出的请求上下文，不会写回事实库；该 CLI 不接受 JD 全文参数。
