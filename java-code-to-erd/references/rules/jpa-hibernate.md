# JPA 与 Hibernate 规则

解析 `Entity`、`Table`、`Id`、`EmbeddedId`、`Column`、`JoinColumn(s)`、`JoinTable` 和四种标准关系注解。表、字段或 referenced column 只有明确写出，或命名策略能由项目配置确定时才能确认。

`JoinColumn` 产生 `ORM_RELATION`，不产生 `DDL_FOREIGN_KEY`。关系注解支持代码数量关系；唯一约束和主键支持数据库约束数量关系，两者分开保存。

处理字段访问、属性访问、MappedSuperclass、Embedded、继承、SecondaryTable、CollectionTable、MapsId、`orm.xml` 和 `hbm.xml`。无法可靠还原的 formula、动态映射或覆盖顺序进入未解析项。

Spring Data 原生 SQL走通用 SQL规则。JPQL/HQL 先解析实体和属性映射。派生查询方法只补充字段使用，不能单独证明新表关系。
