# Dependency Injection

llm-harness takes a strong stance: **every dependency is explicit, every
parameter is required.**

## Why No Defaults?

```python
# llm-harness style — everything explicit
harness = Harness(
    provider=OpenAICompatProvider(api_key="sk-xxx"),
    model="deepseek-chat",
    tools=my_tools,        # required
    sandbox=my_sandbox,    # required
    memory=my_memory,      # optional — explicit None
    permissions=my_perms,  # optional — explicit None
)
```

This is deliberate:

1. **No hidden coupling.** You can see every component the Agent depends on
   at the call site.
2. **No filesystem side-effects.** The constructor never reads files,
   environment variables, or global config.
3. **Testable.** Every dependency is replaceable with a mock.
4. **Auditable.** Static analysis tools can verify all dependencies are
   provided.

## Callback Injection

Behavior that varies between deployments is injected as callbacks, not
subclass overrides:

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

This means you can change the system prompt, permission logic, or error
handling without subclassing `AgentLoop`.

## Constructor vs Factory

`Harness` is the only "factory" in the framework. `ToolFactory` is a
convenience for building the standard 15 tools with injected dependencies.
For custom setups, you can bypass both and wire `AgentLoop` + `Agent` directly:

```python
loop = AgentLoop(provider=..., tools=..., model=...,
                 on_build_context=..., on_tool_check=..., on_error=...)
agent = Agent(loop=loop)
result = await agent.process(msg, session=session, cwd=cwd)
```

## Comparison

| Pattern | llm-harness | Typical Framework |
|---------|-------------|-------------------|
| Provider | Constructor param | Env var / global singleton |
| Tools | Injected `ToolRegistry` | Auto-discovered / decorator-registered |
| Config | Pydantic model passed in | YAML file read internally |
| Session | Caller passes `Session` | Framework manages lifecycle |
| Workspace | Caller passes `cwd: Path` | Framework resolves internally |
