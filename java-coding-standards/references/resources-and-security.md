# 资源与安全边界

- 【强制】流、连接等在异常路径关闭（二（二）6）；Java 7+ 对拥有的 AutoCloseable 优先 try-with-resources。借入资源按所有权约定，不擅自关闭；Java 9 才支持把已有 effectively-final 变量直接放进 try 资源列表。关闭异常不能覆盖主异常（API 补充）。
- 【强制】远程操作设置超时（六（三）1）；依据项目客户端区分连接、读取、请求截止时间，不假设一个 timeout 全覆盖。重试只在幂等与预算明确时使用（融合补充）。
- 【强制】用户私有资源检查权限，不能只验证已登录；外部输入验证类型、范围、大小与目标，SQL 绑定；展示敏感信息需脱敏（四 1–4）。验证只放在真正信任边界，不给所有内部方法添加重复校验。
- 【强制】HTML 输出按上下文转义，表单/AJAX 场景复用 CSRF 防护，外部重定向采用允许列表；短信/支付等有防重放与次数限制，上传限制大小和类型（四 5–9）。根据实际协议和框架实现，不给没有浏览器会话的 DTO 添加 CSRF 代码。
- 【强制原条目】配置密码需加密（四 10）；执行结论：复用项目秘密管理/加密配置，不硬编码明文、密钥或把编码当加密，不在日志、toString、示例写真实凭据。

自写 Java 8+ 方法片段，返回首行（空文件返回 null，调用方需处理）：

```java
static String readFirstLine(Path path) throws IOException {
    try (BufferedReader reader = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
        return reader.readLine();
    }
}
```

反例：仅在正常 return 前手动 close；失败路径泄漏。审查时追踪所有权、部分初始化失败和关闭顺序，不只是搜索有没有 close。
