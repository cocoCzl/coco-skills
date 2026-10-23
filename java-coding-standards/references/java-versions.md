# 按项目适配 Java 版本

只在选择有版本要求的语法/API 或排查编译兼容性时加载；不要求每个 DTO 都读版本矩阵。

1. 区分构建运行 JDK、编译器 toolchain、release/source/target、生产运行 JDK。Maven 继承/profile、Gradle toolchain/options.release、不同 source set 可能不一致，先查本次模块生效配置。`java -version` 不能代替编译目标。
2. `--release` 同时限制语法和平台 API；仅 source/target 不足以阻止误用新 JDK API。已有构建怎么验证就复用，不能擅自修改构建。库依赖的最低运行版本、反射/序列化框架的特性支持也要核实。
3. 不预设 Java 8 为默认或统一保守降级。在目标版本和项目约定支持时使用清晰的现代语法；不为“现代化”改无关代码、升级 JDK 或打开 preview。低于示例最低版本时选项目兼容写法；版本未知且会改变实现时说明缺项并确认。

| 特性/API | 最低正式版本与条件 |
| --- | --- |
| diamond、Objects.equals、try-with-resources | 7；不适用于更旧目标 |
| lambda、Stream、java.time | 8；旧项目可用既有兼容 API，日期共享仍需线程安全 |
| List.of、已有 effectively-final 变量作为 try 资源 | 9；List.of 不可变且不接收 null |
| 局部变量 var | 10；不泛用于字段/方法参数，仍需可读性 |
| String.isBlank、Collection.toArray(IntFunction) | 11；不能误投到 release 8 |
| 标准 switch 表达式 | 14；旧式 switch 落入规则不机械套箭头分支 |
| text block | 15；内容空格/换行可能有语义，不能只按格式宽度切内容 |
| record、Stream.toList | 16；record 需框架支持，toList 结果不可修改，不等价于所有旧 collect 契约 |
| sealed class | 17；穷尽模式匹配 switch 是另一特性，不能混淆最低版本 |
| 虚拟线程、正式模式匹配 switch | 21；虚拟线程不池化，限制的是下游并发/资源，结合项目策略和 JEP 444 |
| 25 及更新 JDK | 按实际 release、正式/预览状态与项目框架判断；不因运行 JDK 新就默认可用所有新特性，不把黄山版未提及视为禁止 |

手册与现代规则冲突按来源决策 D6–D7；以上版本/API 信息是适配补充，不称为黄山版原文。下面是自行编写的可执行语法/API 示例，不是项目应采用的新架构；测试代码可直接断言/抛 AssertionError，生产代码按项目异常约定。

Java 11+（Version11Example.java）：

```java
public class Version11Example {

    public static void main(String[] args) {
        var text = "  ";
        if (!text.isBlank()) {
            throw new AssertionError("Expected blank text");
        }
    }
}
```

Java 17+（Version17Example.java，record 与完整 enum switch；Java 17 不使用模式匹配 switch）：

```java
public class Version17Example {

    record Item(String name) {}

    enum State { READY, DONE }

    public static void main(String[] args) {
        Item item = new Item("sample");
        int status = switch (State.READY) {
            case READY -> 1;
            case DONE -> 2;
        };
        if (status != 1 || !"sample".equals(item.name())) {
            throw new AssertionError("Unexpected value");
        }
    }
}
```

Java 21+（Version21Example.java，独立示例拥有 executor；只提交单任务，不作为无界服务池模板）：

```java
import java.util.concurrent.Executors;

public class Version21Example {

    public static void main(String[] args) throws Exception {
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var result = executor.submit(() -> "done");
            if (!"done".equals(result.get())) {
                throw new AssertionError("Unexpected result");
            }
        }
    }
}
```

以上示例可在更高版本的兼容编译目标上运行；编译成功不等于已验证实际生产运行时。维护验证分别记录 `--release` 交叉编译和真正运行的 JDK，不冒充所有版本实测通过。
