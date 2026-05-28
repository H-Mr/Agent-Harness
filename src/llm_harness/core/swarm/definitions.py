"""Agent definitions — built-in sub-agent types."""

from dataclasses import dataclass, field

@dataclass
class AgentDefinition:
    name: str
    description: str
    system_prompt: str
    tools_allow: list[str] = field(default_factory=list)
    tools_deny: list[str] = field(default_factory=list)
    tools_extra: list[str] = field(default_factory=list)
    model: str = ""


_BUILTIN: dict[str, AgentDefinition] = {
    "general-purpose": AgentDefinition(
        name="general-purpose", description="Handle any general task",
        system_prompt="You are a helpful AI assistant. Complete the task described in the prompt."),
    "researcher": AgentDefinition(
        name="researcher", description="Search, collect, and analyze information",
        system_prompt="You are a research agent. Gather information, analyze data, and report findings concisely."),
    "planner": AgentDefinition(
        name="planner", description="Decompose complex tasks and design approaches",
        system_prompt="You are a planning agent. Decompose complex tasks into steps, identify dependencies, and design approaches."),
    "executor": AgentDefinition(
        name="executor", description="Execute specific operational steps",
        system_prompt="You are an execution agent. Follow the specified steps precisely and report results."),
    "reviewer": AgentDefinition(
        name="reviewer", description="Verify, check, and compare results",
        system_prompt="You are a review agent. Verify outputs against requirements, check for errors, report pass/fail with evidence."),
}


def get_definition(name: str) -> AgentDefinition | None:
    return _BUILTIN.get(name)

def list_definitions() -> list[AgentDefinition]:
    return list(_BUILTIN.values())

def register_definition(defn: AgentDefinition) -> None:
    _BUILTIN[defn.name] = defn
