# 输出与视觉质量

默认目录为 `reports/java-code-to-erd/`：

- `database-model.json`：唯一事实模型；
- `database-analysis.md`：结果优先的分析报告；
- `database-erd.mmd`：数量和可选性足够明确的 Crow's Foot ERD；
- `database-relations.mmd`：可靠但数量未知的逻辑关系图，只有需要时生成；
- `database.dbml`：只有 DDL 外键生成正式 `Ref`；
- `erd/`：大型项目的总览和稳定分组图；
- `artifact-manifest.json`：本 Skill 管理的生成物清单。

图中关系标签必须用 `DDL`、`ORM`、`MAP`、`JOIN`、`SQL`、`CODE`、`USER` 等文字表达来源，不能只靠颜色。冲突和候选不进入默认图。宽表超过 20 个字段时只展示键和关系字段，并标出省略数量。

若生成 SVG，逐张检查文字截断、节点重叠、连线拥挤、长名称、标签可读性、方向和图例。任一问题存在时拆图或调整布局，不得声称视觉验收完成。没有 `mmdc` 时不安装，保留 Mermaid 源并标记 `SOURCE_ONLY`；这只表示未完成本机图形检查，不影响数据库模型的完成状态。
