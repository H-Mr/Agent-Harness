# 依赖注入

llm-harness 采取了一个强硬的立场：**每个依赖都是显式的，每个参数都是必需的。**

## 为什么没有默认值？

```python
# llm-harness 风格 — 一切显式
harness = Harness(
    provider=OpenAICompatProvider(api_key="sk-xxx"),
    model="deepseek-chat",
    tools=my_tools,        # 必需
    sandbox=my_sandbox,    # 必需
    memory=my_memory,      # 可选 — 显式传入 None
    permissions=my_perms,  # 可选 — 显式传入 None
)
```

这是经过深思熟虑的设计：

1. **没有隐藏耦合。** 你可以在调用处看到 Agent 依赖的每一个组件。
2. **没有文件系统副作用。** 构造函数从不读取文件、环境变量或全局配置。
3. **可测试。** 每个依赖都可以替换为 mock。
4. **可审计。** 静态分析工具可以验证所有依赖都已提供。

## 回调注入

因部署环境而异的行为通过回调注入，而非子类覆盖：

```python
loop = AgentLoop(
    on_build_context=lambda msg, history: [
        {"role": "system", "content": "You are helpful."},
        *history,
        {"role": "user", "content": msg.content},
    ],
    on_tool_check=lambda name, tool, args: (
        permission_checker.evaluate(name, ...)
    ),
    on_error=lambda exc, ctx: logger.exception("Error in %s", ctx),
)
```

这意味着你无需子类化 `AgentLoop` 即可更改系统提示词、权限逻辑或错误处理。

## 构造函数 vs 工厂

`Harness` 是框架中唯一的"工厂"。`ToolFactory` 是一个便利工具，用于构建标准的 15 个工具及其注入的依赖。对于自定义设置，你可以绕过这两者，直接连接 `AgentLoop` + `Agent`：

```python
loop = AgentLoop(provider=..., tools=..., model=...,
                 on_build_context=..., on_tool_check=..., on_error=...)
agent = Agent(loop=loop)
result = await agent.process(msg, session=session, cwd=cwd)
```

## 对比

| 特性 | llm-harness | 典型框架 |
|---------|-------------|-------------------|
| 提供者 | 构造函数参数 | 环境变量 / 全局单例 |
| 工具 | 注入的 `ToolRegistry` | 自动发现 / 装饰器注册 |
| 配置 | 传入的 Pydantic 模型 | 内部读取 YAML 文件 |
| 会话 | 调用者传入 `Session` | 框架管理生命周期 |
| 工作区 | 调用者传入 `cwd: Path` | 框架内部解析 |
