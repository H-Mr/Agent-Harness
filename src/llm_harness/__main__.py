"""Worker subprocess entry point — internal, used by SubprocessBackend."""

import os
import sys
import asyncio


def main():
    if "--worker" in sys.argv:
        asyncio.run(worker_main())
    else:
        print("llm-harness is an engine library — use the API directly", file=sys.stderr)
        print("  from llm_harness import AgentLoop, Session, Harness", file=sys.stderr)


async def worker_main():
    """Worker process: read prompt from stdin, run ReAct loop, write result to stdout."""
    import argparse
    from llm_harness.adapters.providers.registry import detect_provider, instantiate_provider
    from llm_harness.core.tools.base import ToolRegistry
    from llm_harness.core.loop import AgentLoop

    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--agent-def", type=str, required=True)
    parser.add_argument("--tools", type=str, default="read_file,glob,grep,web_search")
    parser.add_argument("--model", type=str, default="")
    parser.add_argument("--workspace", type=str, default="")
    parser.add_argument("--permissions", type=str, default="default")
    args = parser.parse_args()

    prompt = sys.stdin.read().strip()
    if not prompt:
        print("Error: no prompt on stdin")
        return

    spec = detect_provider(args.model or "claude-sonnet-4-6")
    if spec is None:
        print("Error: cannot detect provider")
        return

    provider = instantiate_provider(spec)
    model = args.model or spec.default_model or "claude-sonnet-4-6"

    from llm_harness.core.swarm.definitions import get_definition
    agent_def = get_definition(args.agent_def)
    if agent_def is None:
        print(f"Error: unknown agent definition '{args.agent_def}'")
        return

    from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
    from llm_harness.core.tools.factory import ToolFactory

    workspace_arg = getattr(args, 'workspace', None) or os.environ.get('LLM_HARNESS_ACCOUNT_WS', '.')
    sandbox = SRTSandboxBackend(workspace_arg)
    factory = ToolFactory(sandbox=sandbox)
    tool_names = args.tools.split(",")
    tool_registry = ToolRegistry()
    for name in tool_names:
        tool = factory.build(name)
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


if __name__ == "__main__":
    main()
