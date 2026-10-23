# Java 数据访问

仅编写/修改/审查 JDBC、ORM、SQL 或事务时读取。只还原模型/ERD 时由 java-code-to-erd 按证据保留现有结构，不能用规范臆造或删掉关系。这里是数据访问精选，不是完整 MySQL 建表手册。

- 【强制】用户值参数绑定（四 3）；MyBatis 值用 `#{}`，不能 `${}` 直接插值（五（四）4）。列名/排序等无法绑定的标识符用明确允许列表映射，不能把占位符伪用于表名。
- 【强制】选择所需列而非 SELECT *，布尔字段 is_xxx 映射 Java xxx；显式 resultMap 和类型映射用于 XML Mapper（五（四）1–3），不强迫 JPA 使用 MyBatis 配置。DO/字段类型匹配（一（四）11），检查 unsigned bigint 的完整范围，不能认为所有无符号 bigint 都装进 Long。
- 【强制】统计行用 count(*)；SUM 空结果可能 null；分页 count=0 则不再查；多表列加别名限定（五（三）1–3、5、9）。统计非 null 值本来就应 count(column)，不能误改业务。MySQL 空值判断默认按五（三）4 用 ISNULL，跨数据库/项目明确采用 IS NULL 时保持，不比较 `= NULL`。
- 【强制】并发唯一性由数据库唯一约束兜底（五（二）1），不能只“先查后插”。【推荐】检查隐式类型转换、分页成本及索引利用（五（二）5–10）；依实际执行计划判断，不凭规则虚构性能改善。
- 【强制】有 update_time 的记录同步更新时间（五（四）7）；【推荐】只更新目标字段（8）。事务异常不能被 catch 后误提交（二（二）5）；核实框架代理、自调用、回滚类型和传播，不能只加一个注解声称已回滚（框架适用性补充）。
- 【参考】事务按需，不滥用；涉及缓存/消息还需补偿策略（五（四）9）。资源关闭读取资源资料；异常转换读取异常资料，只加载这次相关部分。

MySQL 的命名、逻辑删除、禁外键/级联、禁存储过程是手册五（一）及五（三）在其工程语境的【强制】规定；本 Skill 不借局部 Java 修复迁移现有数据库、不删项目外键、不自动改变删除语义。确需设计/变更 schema 时先看项目数据库规范与迁移方案；其他数据库不机械套 MySQL 规则。金额冲突见 D3。

自行编写 Java 8+ JDBC 片段（conn 借入；statement/result 由此处拥有）：

```java
try (PreparedStatement statement = conn.prepareStatement(
    "SELECT display_name FROM account WHERE id = ?")) {
    statement.setLong(1, accountId);
    try (ResultSet result = statement.executeQuery()) {
        return result.next() ? result.getString("display_name") : null;
    }
}
```

方法应声明 SQLException 与可空返回契约，不关闭借入 conn。参数绑定不等于权限校验通过。
