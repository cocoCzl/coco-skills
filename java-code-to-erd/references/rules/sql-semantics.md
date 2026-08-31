# SQL 语义规则

解析 SELECT、INSERT、UPDATE、DELETE、MERGE、FROM、JOIN、ON、USING、WHERE 和 HAVING。CTE、子查询别名和临时查询结果不能误当持久表；`SELECT *` 不会虚构字段。

JOIN 的等值字段比较是 `SQL_JOIN`；WHERE/HAVING 的跨表等值比较是 `SQL_COLUMN_COMPARISON`。非等值比较只形成对象或查询依赖，不形成外键式关系。

SQL 书写顺序不决定引用方向。需要 DDL 键、唯一约束、ORM owning side 或明确代码逻辑支持方向。方言未知时保留原始大小写和引号信息，存在歧义的对象不自动合并。
