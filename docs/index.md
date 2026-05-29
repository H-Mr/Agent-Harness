# llm-harness

纯异步、依赖注入的 Agent 开发框架。

## 什么是 llm-harness？

llm-harness 是一个 **Agent 引擎内核** —— 提供 `Harness`（组装器）、`Agent`（无状态引擎）和 `AgentLoop`（ReAct 骨架）。你只需自带 LLM 提供商、工具、沙箱、内存后端和会话存储即可。

**不是** LangChain 封装，**不是** Dify 竞品。它是一个精炼的、约 7,000 行的库，只做一件事：以可插拔的方式运行 ReAct Agent 循环。

## 快速预览

```python
from llm_harness import Harness, Agent, Session, ToolRegistry, Config, load_config

config = load_config("harness.yaml")
harness = Harness(provider=..., model="claude-sonnet-4-6", tools=..., sandbox=...)
agent = harness.create_agent()

session = Session(key="user:chat-1")
result = await agent.process(msg, session=session, cwd=Path("/workspace"))
print(result.final_content)
```

## 从何处开始

- **刚接触？** → [7 天掌握路线](tutorials/7-day-mastery.md)
- **想直接运行？** → [快速入门](tutorials/quickstart.md)
- **解决特定问题？** → [操作指南](how-to/custom-tool.md)
- **需要 API 详情？** → [参考文档](reference/harness.md)
- **对设计感兴趣？** → [原理说明](explanation/architecture.md)
