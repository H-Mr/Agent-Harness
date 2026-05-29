# How to Create and Load Skills

## Goal

Package reusable instructions as skills that the agent can load on demand at inference time, reducing system-prompt bloat via progressive disclosure.

## Prerequisites

- Working llm-harness installation
- Understanding of the skill lifecycle: `SKILL.md` file -> `DirectorySkillLoader` -> `SkillRegistry` -> `SkillTool` -> agent invokes via the `skill` tool

## Step by Step

### 1. Understand the Skill Architecture

Skills follow a progressive-disclosure pattern. Instead of crowding the system prompt with every possible instruction, the harness loads only skill names and descriptions into the prompt. The LLM discovers and invokes the built-in `skill` tool to fetch full content when a task matches a skill's description.

The pipeline is:

```
SKILL.md files  -->  DirectorySkillLoader  -->  SkillRegistry  -->  SkillTool  -->  agent
```

Key types in `llm_harness.extensions.skills`:

| Type | Role |
|---|---|
| `SkillDefinition` | A loaded skill: name, description, content, source, path |
| `SkillLoader` (Protocol) | Interface for loading skills from any source |
| `DirectorySkillLoader` | Filesystem implementation -- scans directories for `<name>/SKILL.md` |
| `SkillRegistry` | Stores skills by name, provides lookup |
| `SkillTool` | Built-in tool (`name="skill"`) that the LLM calls to retrieve full skill content |

### 2. Create a SKILL.md File

Create a directory named after your skill containing a `SKILL.md` file. The directory name becomes the skill name (unless overridden by YAML frontmatter).

```
skills/
  sql-optimization/
    SKILL.md
  docker-ops/
    SKILL.md
```

A SKILL.md file supports optional YAML frontmatter:

```markdown
---
name: sql-optimization
description: Optimize slow SQL queries using EXPLAIN plans and index suggestions
---

# SQL Query Optimization

When asked to optimize a SQL query, follow these steps:

1. Ask the user for the full query and schema definitions (CREATE TABLE statements)
2. Request an EXPLAIN ANALYZE output if the database supports it
3. Look for:
   - Sequential scans on large tables -> suggest indexes
   - Nested loop joins without indexes -> suggest hash joins or indexes
   - Sort operations on unindexed columns -> consider covering indexes
4. Provide before/after estimates for each suggestion
```

If frontmatter is present, `name` and `description` are read from it. Otherwise the directory name is used as the skill name and the first paragraph of content becomes the description.

### 3. Load Skills with DirectorySkillLoader

Pass one or more directories to `DirectorySkillLoader`:

```python
from llm_harness.extensions.skills.loader import DirectorySkillLoader

loader = DirectorySkillLoader(["./skills", "/opt/shared-skills"], source="user")
skills = await loader.load()

for skill in skills:
    print(f"{skill.name}: {skill.description}")
```

For synchronous contexts, use the convenience function:

```python
from llm_harness.extensions.skills.loader import load_skills_from_dirs

skills = load_skills_from_dirs(["./skills"])
```

### 4. Register Skills into SkillRegistry

```python
from llm_harness.extensions.skills.registry import SkillRegistry

registry = SkillRegistry()
for skill in skills:
    registry.register(skill)

# Lookup by name
sql_skill = registry.get("sql-optimization")
print(sql_skill.content)

# List all (sorted by name)
for s in registry.list_skills():
    print(f"  {s.name}: {s.description}")
```

### 5. Wire SkillTool into the Agent

The `SkillTool` takes a `SkillRegistry` and registers itself as the `"skill"` tool, enabling the LLM to fetch skill content:

```python
from llm_harness.core.tools.skill import SkillTool
from llm_harness.core.tools.base import ToolRegistry

tool_registry = ToolRegistry()
tool_registry.register(SkillTool(registry))
```

When the LLM determines a task matches a skill's description, it calls:

```
tool: skill
arguments: {"name": "sql-optimization"}
```

And receives the full SKILL.md content as output, which is then injected into the conversation for the agent to follow.

### 6. Full Integration with Harness

```python
import asyncio
from pathlib import Path
from llm_harness.extensions.skills.loader import load_skills_from_dirs
from llm_harness.extensions.skills.registry import SkillRegistry
from llm_harness.core.tools.skill import SkillTool
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.adapters.providers.openai_compat_provider import OpenAICompatProvider
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.harness import Harness
from llm_harness.core.session.session import Session
from llm_harness.core.bus.events import InboundMessage

async def main():
    # 1. Load skills
    skill_defs = load_skills_from_dirs(["./skills"])
    skill_registry = SkillRegistry()
    for s in skill_defs:
        skill_registry.register(s)

    # 2. Create tool registry with SkillTool
    tools = ToolRegistry()
    tools.register(SkillTool(skill_registry))

    # 3. Build harness
    provider = OpenAICompatProvider(api_key=..., api_base="https://api.deepseek.com")
    sandbox = SRTSandboxBackend(Path("./workspace"))
    harness = Harness(
        provider=provider,
        model="deepseek-chat",
        tools=tools,
        sandbox=sandbox,
    )
    agent = harness.create_agent()

    # 4. Process a message -- the agent will discover the skill tool
    #    and load the sql-optimization skill when relevant
    msg = InboundMessage("cli", "user", "c1", "Help me optimize my slow query")
    result = await agent.process(msg, session=Session(key="demo:skills"), cwd=Path("."))
    print(result.final_content)

asyncio.run(main())
```

## Skill System Prompt Injection

The harness automatically injects available skill names and descriptions into the system prompt so the LLM knows what skills exist. This happens during agent creation when `SkillTool` is registered. The standard format is:

```
Available skills:
- sql-optimization: Optimize slow SQL queries using EXPLAIN plans and index suggestions
- docker-ops: Build, run, and manage Docker containers
```

## Checking Skill Requirements

Skills can declare required binaries and environment variables using the `requires` metadata convention. The `check_skill_requirements` helper validates them at load time:

```python
from llm_harness.extensions.skills.checker import check_skill_requirements

metadata = {
    "requires": {
        "bins": ["docker", "kubectl"],
        "env": ["KUBECONFIG"],
    },
}
ok, missing = check_skill_requirements(metadata)
if not ok:
    print(f"Missing: {', '.join(missing)}")
```

## Complete Example

```python
import asyncio
from pathlib import Path
from llm_harness.extensions.skills import (
    SkillRegistry,
    DirectorySkillLoader,
    load_skills_from_dirs,
    SkillDefinition,
)
from llm_harness.core.tools.skill import SkillTool
from llm_harness.core.tools.base import ToolRegistry, ToolExecutionContext

async def demo():
    # Load and register
    skill_defs = load_skills_from_dirs(["./skills"])
    skill_registry = SkillRegistry()
    for s in skill_defs:
        skill_registry.register(s)

    # Wire into tool system
    tools = ToolRegistry()
    skill_tool = SkillTool(skill_registry)
    tools.register(skill_tool)

    # Query a skill
    ctx = ToolExecutionContext(cwd=Path("."))
    result = await skill_tool.execute(
        type("Args", (), {"name": "sql-optimization"})(),
        ctx,
    )
    print(result.output)

asyncio.run(demo())
```

## Testing

```python
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from llm_harness.extensions.skills.loader import DirectorySkillLoader, parse_skill_markdown
from llm_harness.extensions.skills.registry import SkillRegistry
from llm_harness.extensions.skills.types import SkillDefinition

def test_parse_skill_markdown():
    content = """---
name: my-skill
description: A test skill
---

# My Skill

Instructions here.
"""
    name, desc = parse_skill_markdown("fallback", content)
    assert name == "my-skill"
    assert desc == "A test skill"

def test_parse_skill_markdown_no_frontmatter():
    content = "# My Skill\n\nThis is a test skill description.\n"
    name, desc = parse_skill_markdown("fallback", content)
    assert name == "My Skill"
    assert desc == "This is a test skill description."

@pytest.mark.asyncio
async def test_directory_skill_loader():
    with TemporaryDirectory() as tmp:
        skill_dir = Path(tmp) / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# My Skill\n\nDescription here.\n", encoding="utf-8")

        loader = DirectorySkillLoader([tmp])
        skills = await loader.load()
        assert len(skills) == 1
        assert skills[0].name == "My Skill"

def test_skill_registry():
    registry = SkillRegistry()
    skill = SkillDefinition(
        name="test", description="test skill",
        content="# Test", source="user",
    )
    registry.register(skill)
    assert registry.get("test") is skill
    assert len(registry.list_skills()) == 1
```
