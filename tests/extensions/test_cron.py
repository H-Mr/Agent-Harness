"""Tests for the cron service (service.py, types.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from llm_harness.extensions.cron import (
    CronJob,
    CronJobState,
    CronPayload,
    CronRunRecord,
    CronSchedule,
    CronService,
)
from llm_harness.extensions.cron.service import (
    _compute_next_run,
    _now_ms,
    _validate_schedule_for_add,
)

# =============================================================================
# Dataclass creation
# =============================================================================


class TestCronDataclasses:
    """CronJob / CronSchedule / CronPayload / CronJobState creation."""

    def test_cron_schedule(self):
        s = CronSchedule(kind="every", every_ms=60000)
        assert s.kind == "every"
        assert s.every_ms == 60000

    def test_cron_payload(self):
        p = CronPayload(kind="agent_turn", message="hello", channel="cli")
        assert p.kind == "agent_turn"
        assert p.message == "hello"
        assert p.channel == "cli"

    def test_cron_job_state(self):
        state = CronJobState(next_run_at_ms=1000, last_status="ok")
        assert state.next_run_at_ms == 1000
        assert state.last_status == "ok"

    def test_cron_run_record(self):
        r = CronRunRecord(run_at_ms=1000, status="ok", duration_ms=50)
        assert r.run_at_ms == 1000
        assert r.status == "ok"
        assert r.duration_ms == 50

    def test_cron_job(self):
        job = CronJob(
            id="abc123",
            name="test-job",
            schedule=CronSchedule(kind="every", every_ms=30000),
            payload=CronPayload(message="ping"),
        )
        assert job.id == "abc123"
        assert job.name == "test-job"
        assert job.enabled is True


# =============================================================================
# _compute_next_run
# =============================================================================


class TestComputeNextRun:
    """_compute_next_run schedule computation."""

    def test_every_schedule(self):
        """now_ms + every_ms for 'every' kind."""
        result = _compute_next_run(CronSchedule(kind="every", every_ms=60000), 1000)
        assert result == 61000

    def test_every_zero_interval(self):
        """Returns None when every_ms is 0 or negative."""
        assert _compute_next_run(CronSchedule(kind="every", every_ms=0), 1000) is None
        assert _compute_next_run(CronSchedule(kind="every", every_ms=-1), 1000) is None

    def test_at_schedule_past(self):
        """Returns None when at_ms is in the past."""
        assert _compute_next_run(CronSchedule(kind="at", at_ms=500), 1000) is None

    def test_at_schedule_future(self):
        """Returns at_ms when it is in the future."""
        result = _compute_next_run(CronSchedule(kind="at", at_ms=2000), 1000)
        assert result == 2000

    def test_cron_expression(self):
        """Cron expression produces a future timestamp."""
        result = _compute_next_run(CronSchedule(kind="cron", expr="* * * * *"), 0)
        assert result is not None
        assert result > 0

    def test_cron_invalid_expr(self):
        """Invalid cron expression returns None."""
        result = _compute_next_run(CronSchedule(kind="cron", expr="not-a-cron"), 1000)
        assert result is None

    def test_no_match_unknown_kind(self):
        """Unknown schedule kind returns None."""
        result = _compute_next_run(CronSchedule(kind="every"), 1000)
        assert result is None


# =============================================================================
# _validate_schedule_for_add
# =============================================================================


class TestValidateSchedule:
    """_validate_schedule_for_add schedule validation."""

    def test_rejects_tz_for_non_cron(self):
        """Raises ValueError if tz is set for non-cron schedules."""
        s = CronSchedule(kind="every", every_ms=60000, tz="UTC")
        with pytest.raises(ValueError, match="tz can only be used with cron"):
            _validate_schedule_for_add(s)

    def test_accepts_cron_no_tz(self):
        """No error when cron schedule has no tz."""
        _validate_schedule_for_add(CronSchedule(kind="cron", expr="0 9 * * *"))

    def test_accepts_valid_timezone(self):
        """Valid timezone with cron is accepted."""
        s = CronSchedule(kind="cron", expr="0 9 * * *", tz="UTC")
        _validate_schedule_for_add(s)  # must not raise

    def test_rejects_invalid_timezone(self):
        """Invalid timezone raises ValueError."""
        s = CronSchedule(kind="cron", expr="0 9 * * *", tz="Not/A_Timezone")
        with pytest.raises(ValueError):
            _validate_schedule_for_add(s)


# =============================================================================
# CronService
# =============================================================================


class TestCronService:
    """CronService public API."""

    @pytest.fixture
    def service(self, tmp_workspace: Path):
        """CronService backed by a temp file and a no-op on_job."""
        store = tmp_workspace / "cron" / "jobs.json"
        return CronService(store_path=store, on_job=AsyncMock())

    def test_add_job_creates_with_valid_id(self, service: CronService):
        """add_job creates a job whose ID is 8 characters long."""
        job = service.add_job(
            name="test", schedule=CronSchedule(kind="every", every_ms=60000), message="hello",
        )
        assert len(job.id) == 8

    def test_add_job_schedules_next_run(self, service: CronService):
        """add_job sets next_run_at_ms from the schedule."""
        job = service.add_job(
            name="test", schedule=CronSchedule(kind="every", every_ms=60000), message="hello",
        )
        assert job.state.next_run_at_ms is not None
        assert job.state.next_run_at_ms > _now_ms()

    def test_list_jobs_only_enabled_by_default(self, service: CronService):
        """list_jobs returns only enabled jobs when include_disabled is not set."""
        service.add_job(name="enabled", schedule=CronSchedule(kind="every", every_ms=60000), message="a")
        job2 = service.add_job(name="disabled", schedule=CronSchedule(kind="every", every_ms=30000), message="b")
        service.enable_job(job2.id, enabled=False)
        jobs = service.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].name == "enabled"

    def test_list_jobs_include_disabled(self, service: CronService):
        """list_jobs(include_disabled=True) returns all jobs."""
        service.add_job(name="a", schedule=CronSchedule(kind="every", every_ms=60000), message="x")
        job2 = service.add_job(name="b", schedule=CronSchedule(kind="every", every_ms=30000), message="y")
        service.enable_job(job2.id, enabled=False)
        assert len(service.list_jobs(include_disabled=True)) == 2

    def test_remove_job_by_id(self, service: CronService):
        """remove_job removes the job and returns True."""
        job = service.add_job(
            name="to-go", schedule=CronSchedule(kind="every", every_ms=60000), message="x",
        )
        assert service.remove_job(job.id) is True
        assert service.get_job(job.id) is None

    def test_remove_job_nonexistent(self, service: CronService):
        """remove_job returns False for an ID that does not exist."""
        assert service.remove_job("does-not-exist") is False

    def test_enable_job_toggle(self, service: CronService):
        """enable_job toggles the enabled flag and recomputes next_run."""
        job = service.add_job(
            name="toggle", schedule=CronSchedule(kind="every", every_ms=60000), message="x",
        )
        # Disable
        service.enable_job(job.id, enabled=False)
        disabled = service.get_job(job.id)
        assert disabled.enabled is False
        assert disabled.state.next_run_at_ms is None

        # Re-enable
        service.enable_job(job.id, enabled=True)
        enabled = service.get_job(job.id)
        assert enabled.enabled is True
        assert enabled.state.next_run_at_ms is not None

    def test_get_job_returns_job(self, service: CronService):
        """get_job returns the job by ID."""
        job = service.add_job(
            name="find-me", schedule=CronSchedule(kind="every", every_ms=60000), message="x",
        )
        assert service.get_job(job.id).name == "find-me"

    def test_get_job_nonexistent(self, service: CronService):
        """get_job returns None for an unknown ID."""
        assert service.get_job("nobody-here") is None

    def test_status(self, service: CronService):
        """status returns running state, job count and next wake."""
        service.add_job(
            name="s", schedule=CronSchedule(kind="every", every_ms=60000), message="x",
        )
        st = service.status()
        assert st["enabled"] is False  # service not started
        assert st["jobs"] == 1
        assert st["next_wake_at_ms"] is not None

    def test_save_load_round_trip(self, tmp_workspace: Path):
        """Jobs persist on disk across CronService instances."""
        store = tmp_workspace / "cron" / "jobs.json"

        svc1 = CronService(store_path=store, on_job=AsyncMock())
        svc1.add_job(
            name="persist", schedule=CronSchedule(kind="every", every_ms=60000), message="hello",
        )

        svc2 = CronService(store_path=store, on_job=AsyncMock())
        jobs = svc2.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].name == "persist"

    def test_add_job_unsaved_then_load(self, tmp_workspace: Path):
        """Jobs saved once survive service restart."""
        store = tmp_workspace / "cron" / "jobs.json"
        svc = CronService(store_path=store, on_job=AsyncMock())
        svc.add_job(
            name="survivor", schedule=CronSchedule(kind="every", every_ms=60000), message="hi",
        )
        svc2 = CronService(store_path=store, on_job=AsyncMock())
        names = [j.name for j in svc2.list_jobs()]
        assert "survivor" in names

    # ------------------------------------------------------------------
    # Job execution
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_job_execution_updates_status_and_history(self, tmp_workspace: Path):
        """_execute_job sets last_status and appends a run record."""
        on_job = AsyncMock()
        store = tmp_workspace / "cron" / "jobs.json"
        svc = CronService(store_path=store, on_job=on_job)
        job = svc.add_job(
            name="exec", schedule=CronSchedule(kind="every", every_ms=60000), message="go",
        )
        await svc._execute_job(job)

        assert job.state.last_status == "ok"
        assert job.state.last_error is None
        assert len(job.state.run_history) == 1
        assert job.state.run_history[0].status == "ok"

    @pytest.mark.asyncio
    async def test_job_execution_error_handling(self, tmp_workspace: Path):
        """_execute_job records error when on_job raises."""
        on_job = AsyncMock(side_effect=ValueError("boom"))
        store = tmp_workspace / "cron" / "jobs.json"
        svc = CronService(store_path=store, on_job=on_job)
        job = svc.add_job(
            name="fails", schedule=CronSchedule(kind="every", every_ms=60000), message="go",
        )
        await svc._execute_job(job)

        assert job.state.last_status == "error"
        assert job.state.last_error == "boom"
        assert len(job.state.run_history) == 1
        assert job.state.run_history[0].status == "error"

    @pytest.mark.asyncio
    async def test_delete_after_run(self, tmp_workspace: Path):
        """One-shot 'at' jobs with delete_after_run are removed after execution."""
        on_job = AsyncMock()
        store = tmp_workspace / "cron" / "jobs.json"
        svc = CronService(store_path=store, on_job=on_job)
        future_ms = _now_ms() + 3600000

        job = svc.add_job(
            name="one-shot",
            schedule=CronSchedule(kind="at", at_ms=future_ms),
            message="boom",
            delete_after_run=True,
        )
        await svc._execute_job(job)
        assert svc.get_job(job.id) is None

    @pytest.mark.asyncio
    async def test_at_job_disabled_after_run(self, tmp_workspace: Path):
        """'at' jobs without delete_after_run are disabled after execution."""
        on_job = AsyncMock()
        store = tmp_workspace / "cron" / "jobs.json"
        svc = CronService(store_path=store, on_job=on_job)
        future_ms = _now_ms() + 3600000

        job = svc.add_job(
            name="stay",
            schedule=CronSchedule(kind="at", at_ms=future_ms),
            message="keep",
            delete_after_run=False,
        )
        await svc._execute_job(job)

        assert svc.get_job(job.id) is not None
        assert svc.get_job(job.id).enabled is False
        assert svc.get_job(job.id).state.next_run_at_ms is None

    @pytest.mark.asyncio
    async def test_run_history_capped(self, tmp_workspace: Path):
        """run_history is capped at MAX_RUN_HISTORY (20)."""
        on_job = AsyncMock()
        store = tmp_workspace / "cron" / "jobs.json"
        svc = CronService(store_path=store, on_job=on_job)
        job = svc.add_job(
            name="hist", schedule=CronSchedule(kind="every", every_ms=60000), message="x",
        )

        for _ in range(25):
            await svc._execute_job(job)

        assert len(job.state.run_history) == 20
        # The last entry should be the most recent
        assert job.state.run_history[-1].status == "ok"

    @pytest.mark.asyncio
    async def test_run_job_manual(self, tmp_workspace: Path):
        """run_job executes a job and saves state."""
        on_job = AsyncMock()
        store = tmp_workspace / "cron" / "jobs.json"
        svc = CronService(store_path=store, on_job=on_job)
        job = svc.add_job(
            name="manual", schedule=CronSchedule(kind="every", every_ms=60000), message="x",
        )
        result = await svc.run_job(job.id)
        assert result is True
        assert job.state.last_status == "ok"
        on_job.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_job_disabled_no_force(self, tmp_workspace: Path):
        """run_job returns False for disabled jobs without force."""
        on_job = AsyncMock()
        store = tmp_workspace / "cron" / "jobs.json"
        svc = CronService(store_path=store, on_job=on_job)
        job = svc.add_job(
            name="disabled", schedule=CronSchedule(kind="every", every_ms=60000), message="x",
        )
        svc.enable_job(job.id, enabled=False)
        result = await svc.run_job(job.id)
        assert result is False
        on_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_job_nonexistent(self, tmp_workspace: Path):
        """run_job returns False for a non-existent job ID."""
        svc = CronService(store_path=tmp_workspace / "cron" / "jobs.json", on_job=AsyncMock())
        assert await svc.run_job("no-such-id") is False

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_start_stop(self, tmp_workspace: Path):
        """start and stop the service."""
        store = tmp_workspace / "cron" / "jobs.json"
        svc = CronService(store_path=store, on_job=AsyncMock())
        await svc.start()
        assert svc.status()["enabled"] is True
        svc.stop()
        assert svc.status()["enabled"] is False
