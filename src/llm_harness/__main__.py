"""llm-harness entry point — --worker mode or normal startup."""

import sys
import asyncio


def main():
    if "--worker" in sys.argv:
        asyncio.run(worker_main())
    else:
        asyncio.run(normal_main())


async def worker_main():
    """Worker process: read prompt from stdin, run ReAct loop, write result to stdout."""
    import argparse, json
    from llm_harness.adapters.providers.registry import detect_provider
    from llm_harness.core.tools.base import ToolRegistry
    from llm_harness.core.loop import AgentLoop

    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--agent-def", type=str, required=True)
    parser.add_argument("--tools", type=str, default="read_file,glob,grep,web_search")
    parser.add_argument("--skills-path", type=str, default="")
    parser.add_argument("--model", type=str, default="")
    args = parser.parse_args()

    prompt = sys.stdin.read().strip()
    if not prompt:
        print("Error: no prompt on stdin")
        return

    spec = detect_provider(args.model or "claude-sonnet-4-6")
    if spec is None:
        print("Error: cannot detect provider")
        return

    provider = _instantiate_provider(spec)
    model = args.model or spec.default_model or "claude-sonnet-4-6"

    from llm_harness.core.swarm.definitions import get_definition
    agent_def = get_definition(args.agent_def)
    if agent_def is None:
        print(f"Error: unknown agent definition '{args.agent_def}'")
        return

    tool_names = args.tools.split(",")
    tool_registry = ToolRegistry()
    for name in tool_names:
        tool = _build_worker_tool(name, tool_registry)
        if tool:
            tool_registry.register(tool)

    async def build_ctx(msg, history):
        return [{"role": "system", "content": agent_def.system_prompt},
                {"role": "user", "content": msg.content}]

    loop = AgentLoop(
        provider=provider, tools=tool_registry, model=model,
        on_build_context=build_ctx,
        on_tool_check=lambda n, t, a: type("OK", (), {"allowed": True})(),
        on_error=lambda e, c: None,
    )

    class _Msg:
        channel = "worker"; sender_id = "worker"; chat_id = "task"; content = prompt
        @property
        def session_key(self): return "worker:task"

    result = await loop.run(_Msg(), [])
    print(result.final_content or "")


async def normal_main():
    """Normal startup — load config, create harness and channel."""
    from llm_harness.config import load_config
    config = load_config()
    print(f"llm-harness v0.1.0 — model={config.agent.model}")


def _instantiate_provider(spec):
    if spec.backend == "anthropic":
        from llm_harness.adapters.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
    return OpenAICompatProvider(model=spec.default_model or "", api_base=spec.default_api_base or "")


def _build_worker_tool(name, registry):
    """Build a single tool for worker context (independent tools only)."""
    if name == "web_search":
        from llm_harness.core.tools.web_search import WebSearchTool
        return WebSearchTool()
    if name == "web_fetch":
        from llm_harness.core.tools.web_fetch import WebFetchTool
        return WebFetchTool()
    return None


if __name__ == "__main__":
    main()
