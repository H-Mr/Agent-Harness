# 如何创建和加载 Skills

## 目标

将可复用的指令打包为 skill，使 agent 在推理时能够按需加载，通过渐进式披露减少系统 prompt 的臃肿。

## 前置条件

- 可用的 llm-harness 安装
- 了解 skill 的生命周期：`SKILL.md` 文件 -> `DirectorySkillLoader` -> `SkillRegistry` -> `SkillTool` -> agent 通过 `skill` 工具调用

## 分步指南

### 1. 理解 Skill 架构

Skill 遵循渐进式披露模式。harness 不会将每条可能的指令都塞入系统 prompt，而是只将 skill 的名称和描述加载到 prompt 中。LLM 发现并调用内置的 `skill` 工具，在任务与某个 skill 的描述匹配时获取完整内容。

流水线如下：

```
SKILL.md 文件  -->  DirectorySkillLoader  -->  SkillRegistry  -->  SkillTool  -->  agent
```

`llm_harness.extensions.skills` 中的关键类型：

| 类型 | 作用 |
|---|---|
| `SkillDefinition` | 已加载的 skill：包含名称、描述、内容、来源、路径 |
| `SkillLoader` (Protocol) | 从任意来源加载 skill 的接口 |
| `DirectorySkillLoader` | 文件系统实现——扫描目录中的 `<name>/SKILL.md` |
| `SkillRegistry` | 按名称存储 skill，提供查找功能 |
| `SkillTool` | 内置工具（`name="skill"`），LLM 调用它以获取完整的 skill 内容 |

### 2. 创建 SKILL.md 文件

创建一个以你的 skill 名称命名的目录，内含 `SKILL.md` 文件。目录名称即为 skill 名称（除非被 YAML frontmatter 覆写）。

```
skills/
  sql-optimization/
    SKILL.md
  docker-ops/
    SKILL.md
```

SKILL.md 文件支持可选的 YAML frontmatter：

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

如果存在 frontmatter，则从中读取 `name` 和 `description`。否则，目录名作为 skill 名称，内容的第一段作为描述。

### 3. 使用 DirectorySkillLoader 加载 Skill

向 `DirectorySkillLoader` 传递一个或多个目录：

```python
from llm_harness.extensions.skills.loader import DirectorySkillLoader

loader = DirectorySkillLoader(["./skills", "/opt/shared-skills"], source="user")
skills = await loader.load()

for skill in skills:
    print(f"{skill.name}: {skill.description}")
```

在同步上下文中，使用便捷函数：

```python
from llm_harness.extensions.skills.loader import load_skills_from_dirs

skills = load_skills_from_dirs(["./skills"])
```

### 4. 将 Skill 注册到 SkillRegistry

```python
from llm_harness.extensions.skills.registry import SkillRegistry

registry = SkillRegistry()
for skill in skills:
    registry.register(skill)

# 按名称查找
sql_skill = registry.get("sql-optimization")
print(sql_skill.content)

# 列出所有（按名称排序）
for s in registry.list_skills():
    print(f"  {s.name}: {s.description}")
```

### 5. 将 SkillTool 接入 Agent

`SkillTool` 接收 `SkillRegistry` 并将自身注册为 `"skill"` 工具，使 LLM 能够获取 skill 内容：

```python
from llm_harness.core.tools.skill import SkillTool
from llm_harness.core.tools.base import ToolRegistry

tool_registry = ToolRegistry()
tool_registry.register(SkillTool(registry))
```

当 LLM 确定某个任务与某个 skill 的描述匹配时，它会调用：

```
tool: skill
arguments: {"name": "sql-optimization"}
```

并接收完整的 SKILL.md 内容作为输出，然后注入到对话中供 agent 遵循。

### 6. 与 Harness 完整集成

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
    # 1. 加载 skill
    skill_defs = load_skills_from_dirs(["./skills"])
    skill_registry = SkillRegistry()
    for s in skill_defs:
        skill_registry.register(s)

    # 2. 创建包含 SkillTool 的工具注册表
    tools = ToolRegistry()
    tools.register(SkillTool(skill_registry))

    # 3. 构建 harness
    provider = OpenAICompatProvider(api_key=..., api_base="https://api.deepseek.com")
    sandbox = SRTSandboxBackend(Path("./workspace"))
    harness = Harness(
        provider=provider,
        model="deepseek-chat",
        tools=tools,
        sandbox=sandbox,
    )
    agent = harness.create_agent()

    # 4. 处理消息——agent 会发现 skill 工具，
    #    并在相关时加载 sql-optimization skill
    msg = InboundMessage("cli", "user", "c1", "Help me optimize my slow query")
    result = await agent.process(msg, session=Session(key="demo:skills"), cwd=Path("."))
    print(result.final_content)

asyncio.run(main())
```

## Skill 系统 Prompt 注入

harness 会自动将可用的 skill 名称和描述注入到系统 prompt 中，使 LLM 知道存在哪些 skill。这在注册了 `SkillTool` 创建 agent 时发生。标准格式为：

```
Available skills:
- sql-optimization: Optimize slow SQL queries using EXPLAIN plans and index suggestions
- docker-ops: Build, run, and manage Docker containers
```

## 检查 Skill 依赖

Skill 可以使用 `requires` 元数据约定声明所需的二进制文件和环境变量。`check_skill_requirements` 辅助函数在加载时进行验证：

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
    print(f"缺少: {', '.join(missing)}")
```

## 完整示例

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
    # 加载并注册
    skill_defs = load_skills_from_dirs(["./skills"])
    skill_registry = SkillRegistry()
    for s in skill_defs:
        skill_registry.register(s)

    # 接入工具系统
    tools = ToolRegistry()
    skill_tool = SkillTool(skill_registry)
    tools.register(skill_tool)

    # 查询一个 skill
    ctx = ToolExecutionContext(cwd=Path("."))
    result = await skill_tool.execute(
        type("Args", (), {"name": "sql-optimization"})(),
        ctx,
    )
    print(result.output)

asyncio.run(demo())
```

## 测试

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
