"""Tests for CronTool._list_jobs() output formatting.

NOTE: CronTool was not ported to agent-harness (it was part of nanobot.agent.tools.cron).
These tests are kept as a reference for when CronTool is ported.

The cron service types (CronSchedule, CronJobState, etc.) are available in
agent_harness.cron.types for reference.
"""

# CronTool is not yet ported to agent-harness.
# These tests would validate the _format_timing, _format_state, and _list_jobs methods
# of the CronTool class which wraps CronService with LLM-facing methods.
