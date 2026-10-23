# 集合与泛型

来源：一（六）集合处理，正文 p.10–14。下列 API 修正为融合决策 D5，不替换原级别。

- 【强制，1】覆写 equals 时配套 hashCode；作为哈希键/Set 元素的自定义值对象保持两者一致，不在存储期间修改决定哈希的状态。已继承正确实现不用重复生成。
- 【强制，2–4】集合判空用 isEmpty（先处理引用 null）；`Collectors.toMap`（Java 8+）显式决定重复键合并策略，不能随意选“后者覆盖”；value 为 null 必须按契约处理。
- 【强制，5–8、11】subList 是视图，不强转 ArrayList；需要独立副本用 `new ArrayList<>(view)`。Map 的 keySet/values/entrySet 不支持 add；不可变集合不增删。`Arrays.asList` 固定长度，支持 set 且与原数组相互影响，但不支持 add/remove；不是“完全不可变”。父列表结构变更会使相关视图失效。
- 【强制，9–10】类型化数组用 `toArray(new T[0])`；Java 11+ 若项目采用 `toArray(T[]::new)` 可保留。不强转无参 toArray 的 Object[]。addAll 前确认参数非 null；不把 null 自动改为空而掩盖非法输入。
- 【强制，12–13】PECS：extends 适合读取为 T，不能添加非 null 的 T；super 可添加 T、读取静态类型是 Object，不能直接假定为 T。新代码不用 raw type；接旧接口时逐元素校验类型，别靠 unchecked cast 消音。
- 【强制，14】foreach 不对同一普通集合做结构增删；单线程可用 Iterator.remove 或 Java 8+ removeIf（集合支持且谓词不干扰遍历）。并发场景明确集合契约和所有访问者共享的同步协议，单锁 iterator 不保证安全。
- 【强制，15；JDK7+ 原文条件】Comparator 保证反对称、传递和相等一致性；用 `Integer.compare` 等避免减法溢出。错误比较器不一定每次抛异常。
- 【推荐，16–19】Java 7+ 用菱形泛型，不用原文“全省略”示例中的 raw 构造；合理预估容量，别把默认 16 强制塞到所有集合；要同时用 K/V 时遍历 entrySet 或 Map.forEach；按实现检查 null 支持。
- 【参考，20–21】有序性、稳定迭代顺序和去重按业务选择；不要把 HashMap 当前迭代结果当契约，去重需保序时不能随便换 HashSet。

自行编写 Java 8+ 片段（调用前已保证 names 非 null 且可修改）：

```java
// 反例：foreach 内 names.remove(name)。
names.removeIf(name -> name == null || name.isEmpty());
String[] array = names.toArray(new String[0]);
```
