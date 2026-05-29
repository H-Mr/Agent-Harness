# llm-harness

纯异步、依赖注入的 AI Agent 开发框架。一个 ~7,000 行的引擎内核，做一件事：运行 ReAct Agent 循环，所有组件可插拔。

[![PyPI](https://img.shields.io/pypi/v/llm-harness)](https://pypi.org/project/llm-harness/)
[![Python](https://img.shields.io/pypi/pyversions/llm-harness)](https://pypi.org/project/llm-harness/)
[![文档](https://img.shields.io/badge/文档-中文-blue)](https://h-mr.github.io/llm-harness/)

## 定位

- **不是** LangChain 套壳
- 不是 Dify 替代品
- **是** 纯异步、无状态、依赖注入的 Agent 引擎内核

## 快速开始

```bash
pip install llm-harness[openai]
```

```python
import os, asyncio
from pathlib import Path
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory

async def main():
    provider = OpenAICompatProvider(
        api_key=os.environ["LLM_HARNESS_API_KEY"],
        api_base="https://api.deepseek.com",
    )
    sandbox = SRTSandboxBackend(Path("./workspace"))
    factory = ToolFactory(sandbox=sandbox)
    tools = ToolRegistry()
    for name in ["read_file", "write_file", "web_search"]:
        tool = factory.build(name)
        if tool:
            tools.register(tool)

    harness = Harness(provider=provider, model="deepseek-chat", tools=tools, sandbox=sandbox)
    agent = harness.create_agent()

    session = Session(key="user:chat1")
    msg = InboundMessage("cli", "user", "c1", "What is 2+2?")
    result = await agent.process(msg, session=session, cwd=Path("./workspace"))
    print(result.final_content)

asyncio.run(main())
```

## 三层架构

```
InboundMessage → Agent → AgentLoop → Harness
                   │          │           │
              纯引擎     ReAct 骨架    组装器
              零状态     回调注入      全部依赖显式传入
```

## 核心特性

- **Protocol 驱动**：SandboxBackend / MemoryBackend / AgentBackend / SessionBackend 全部 Protocol，无需继承
- **15 个内置工具**：文件 I/O、搜索、执行、子代理、MCP 集成
- **20+ LLM 服务商**：OpenAI / Anthropic / DeepSeek / DashScope / Gemini / 等
- **权限检查**：9 步检查链，内置敏感路径拒绝列表
- **记忆系统**：TencentDB Gateway 管道模式（capture → 自动提取 → recall）
- **可观测性**：11 种结构化事件类型
- **WebSocket 通道**：支持多前端接入
- **Hook 系统**：Command / HTTP / Prompt / Agent 四种钩子类型
- **Skills 渐进披露**：系统提示词只列名称，LLM 按需加载完整内容

## 测试

```bash
pytest tests/ -q
# 293 passed, 4 skipped
```

## 文档

完整中文文档：**[h-mr.github.io/llm-harness](https://h-mr.github.io/llm-harness/)**

- [7 天掌握 llm-harness](https://h-mr.github.io/llm-harness/tutorials/7-day-mastery/)
- [快速开始](https://h-mr.github.io/llm-harness/tutorials/quickstart/)
- [操作指南](https://h-mr.github.io/llm-harness/how-to/custom-tool/)
- [API 参考](https://h-mr.github.io/llm-harness/reference/harness/)
- [架构说明](https://h-mr.github.io/llm-harness/explanation/architecture/)

## License

MIT
