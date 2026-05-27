# Hooks — 生命周期钩子

钩子执行器与事件定义，支持 PreToolUse/PostToolUse 生命周期扩展。

## Hooks 的边界

钩子工作在**工具执行管线**的外层，在 `PRE_TOOL_USE` / `POST_TOOL_USE` / `SESSION_START` / `SESSION_END` 四个时刻触发。以下场景钩子**无法**覆盖，需使用 `LoopCallbacks` 或 `Agent` 的回调参数：

| 需求 | 为什么 Hooks 不行 | 正确方案 |
|------|------------------|---------|
| 流式输出 LLM 文本 | 流式发生在 LLM 调用内部 | `Agent(on_stream=...)` |
| 工具开始时的进度提示 | 没有对应事件 | `Agent(on_progress=...)` |
| 自定义循环终止条件 | Hooks 只能阻断单个工具 | `AgentLoop` |
| 动态修改工具列表 | Hooks 在工具调用后触发 | `LoopCallbacks.get_tool_definitions` |

钩子适合横切关注点：审计日志、安全审查、外部通知、LLM 辅助判断。不适合需要介入循环控制流的场景。

::: agent_harness.hooks.executor

::: agent_harness.hooks.events

::: agent_harness.hooks.schemas

::: agent_harness.hooks.types

::: agent_harness.hooks.loader
