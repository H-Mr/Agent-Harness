# 如何创建定时任务

本文将指导你如何使用 llm-harness 的 Cron 系统创建和管理定时任务。

---

## Cron 系统概述

llm-harness 的 Cron 系统由三层组成：

```
┌──────────────────────────────────────────────────┐
│                  CronService                      │
│  管理作业生命周期：添加/删除/启用/禁用/执行        │
│  持久化到 jobs.json，支持热加载                    │
├──────────────────────────────────────────────────┤
│                  CronJob                          │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐      │
│  │Schedule  │  │Payload   │  │State      │      │
│  │- kind    │  │- message │  │- nextRunAt│      │
│  │- expr    │  │- channel │  │- lastRun  │      │
│  │- tz      │  │- to      │  │- history  │      │
│  └──────────┘  └──────────┘  └───────────┘      │
├──────────────────────────────────────────────────┤
│              Cron 工具（Agent 可调用）             │
│  cron_create / cron_list / cron_delete /          │
│  cron_toggle                                      │
└──────────────────────────────────────────────────┘
```

- **CronService** — 核心服务，管理作业的调度和执行，将作业持久化到 `jobs.json`
- **CronJob** — 作业定义，包含调度计划、触发内容、运行状态
- **Cron 工具** — Agent 可以通过自然语言调用的工具接口

### 三种调度类型

| 类型 | 说明 | 适用场景 |
|------|------|----------|
| `at` | 指定时间执行一次 | 一次性提醒 |
| `every` | 按固定间隔重复执行 | 定期检查 |
| `cron` | 标准 Cron 表达式 | 复杂的周期性调度 |

---

## 1. 创建一个每天早上的报告任务

### 通过代码创建

```python
import asyncio
from pathlib import Path
from agent_harness.cron.service import CronService
from agent_harness.cron.types import CronSchedule

async def main():
    cron = CronService(store_path=Path.home() / ".agent-harness" / "cron" / "jobs.json")

    # 创建每天早上 9:00（北京时间）执行的任务
    job = cron.add_job(
        name="daily-report",
        schedule=CronSchedule(
            kind="cron",
            expr="0 9 * * *",
            tz="Asia/Shanghai",
        ),
        message="请生成今天的运营数据报告，包含昨日的核心指标、趋势分析、异常告警。",
    )

    print(f"任务创建成功，ID: {job.id}")
    print(f"下次执行时间: {job.state.next_run_at_ms}")

asyncio.run(main())
```

### 通过 Agent 自然语言创建

在 Agent 对话中直接告诉它：

```
帮我创建一个每天早上 9 点的定时任务，提示我生成日报。
```

Agent 会自动调用 `cron_create` 工具完成创建。

### 配置持久化

任务创建后自动保存到 `~/.agent-harness/cron/jobs.json`：

```json
{
  "version": 1,
  "jobs": [
    {
      "id": "a1b2c3d4",
      "name": "daily-report",
      "enabled": true,
      "schedule": {
        "kind": "cron",
        "expr": "0 9 * * *",
        "tz": "Asia/Shanghai",
        "atMs": null,
        "everyMs": null
      },
      "payload": {
        "kind": "agent_turn",
        "message": "请生成今天的运营数据报告...",
        "deliver": false,
        "channel": null,
        "to": null
      },
      "state": {
        "nextRunAtMs": 1717405200000,
        "lastRunAtMs": null,
        "lastStatus": null,
        "lastError": null,
        "runHistory": []
      },
      "createdAtMs": 1717318800000,
      "updatedAtMs": 1717318800000,
      "deleteAfterRun": false
    }
  ]
}
```

---

## 2. 创建一个每 5 分钟的检查任务

### 使用 `every` 调度

```python
# 每 5 分钟检查一次服务状态
job = cron.add_job(
    name="health-check",
    schedule=CronSchedule(
        kind="every",
        every_ms=5 * 60 * 1000,  # 5 分钟（毫秒）
    ),
    message="请检查各服务健康状态，包括 API 响应时间、错误率、资源使用情况。如发现异常请告警。",
)
```

### 间隔格式速查表

| 人类可读 | 毫秒值 |
|----------|--------|
| `30s` | `30_000` |
| `5m` | `300_000` |
| `1h` | `3_600_000` |
| `6h` | `21_600_000` |
| `1d` | `86_400_000` |

Agent 调用 `cron_create` 时支持字符串形式（`"5m"`、`"1h"`、`"1d"`），无需手动换算毫秒。

---

## 3. Cron 工具的使用

Agent 在运行过程中可以通过 4 个内置工具管理定时任务。

### cron_create — 创建任务

```json
{
  "name": "cron_create",
  "input": {
    "name": "weekly-summary",
    "schedule_kind": "cron",
    "schedule_expr": "0 10 * * 1",
    "message": "生成上周工作总结和本周计划",
    "tz": "Asia/Shanghai"
  }
}
```

| 参数 | 类型 | 说明 | 必填 |
|------|------|------|------|
| `name` | `string` | 任务名称 | 是 |
| `schedule_kind` | `"at"` / `"every"` / `"cron"` | 调度类型 | 是 |
| `schedule_expr` | `string` | 调度表达式，根据 `kind` 含义不同 | 是 |
| `message` | `string` | 触发时发送给 Agent 的消息 | 是 |
| `channel` | `string` | 交付通道（如 `"weixin"`） | 否 |
| `chat_id` | `string` | 接收者标识 | 否 |
| `tz` | `string` | 时区（仅 `cron` 类型有效） | 否 |

### cron_list — 列出任务

```json
{
  "name": "cron_list",
  "input": {
    "include_disabled": true
  }
}
```

输出示例：

```
ID         NAME                 ENABLED NEXT RUN (UTC)        SCHEDULE
────────── ──────────────────── ─────── ───────────────────── ──────────────────────
a1b2c3d4   daily-report         yes     2026-06-01 01:00:00   cron 0 9 * * *
e5f6g7h8   health-check         yes     2026-05-24 10:35:00   every 5m
i9j0k1l2   weekly-summary       no      -                     cron 0 10 * * 1

(3 jobs total)
```

### cron_delete — 删除任务

```json
{
  "name": "cron_delete",
  "input": {
    "job_id": "a1b2c3d4"
  }
}
```

### cron_toggle — 启用/禁用任务

```json
{
  "name": "cron_toggle",
  "input": {
    "job_id": "e5f6g7h8",
    "enabled": false
  }
}
```

---

## 4. CronSchedule 的表达式格式

### `cron` 类型 — 标准 Cron 表达式

```
┌───────── 分钟 (0-59)
│ ┌──────── 小时 (0-23)
│ │ ┌─────── 日 (1-31)
│ │ │ ┌────── 月 (1-12)
│ │ │ │ ┌───── 星期 (0-7, 0和7都表示周日)
│ │ │ │ │
* * * * *
```

常用示例：

| 表达式 | 说明 |
|--------|------|
| `0 9 * * *` | 每天早上 9:00 |
| `0 9 * * 1-5` | 工作日早上 9:00 |
| `*/5 * * * *` | 每 5 分钟 |
| `0 0 * * *` | 每天午夜 |
| `0 8,18 * * *` | 每天早上 8 点和下午 6 点 |
| `0 0 1 * *` | 每月 1 日零点 |

### `every` 类型 — 固定间隔

Agent 的 `cron_create` 工具支持人类可读的间隔字符串：

| 输入 | 含义 |
|------|------|
| `"30s"` | 每 30 秒 |
| `"5m"` | 每 5 分钟 |
| `"1h"` | 每小时 |
| `"6h"` | 每 6 小时 |
| `"1d"` | 每天 |

### `at` 类型 — 一次性执行

支持 ISO 8601 格式或 Unix 毫秒时间戳：

| 输入 | 含义 |
|------|------|
| `"2026-05-25T09:00:00Z"` | UTC 时间 2026-05-25 09:00 |
| `"2026-05-25T17:00:00+08:00"` | 北京时间 2026-05-25 17:00 |
| `"1717405200000"` | Unix 毫秒时间戳 |

!!! tip "一次性任务的自动清理"
    对于 `at` 类型任务，可以通过 `delete_after_run=True` 参数让任务执行后自动删除，适用于一次性提醒。

---

## 5. 时区支持

`cron` 类型的调度支持通过 `tz` 参数指定时区。

### 支持的时区格式

标准 IANA 时区名称（`zoneinfo` 支持的所有时区）：

```python
# 北京时间
CronSchedule(kind="cron", expr="0 9 * * *", tz="Asia/Shanghai")

# 东京时间
CronSchedule(kind="cron", expr="0 10 * * *", tz="Asia/Tokyo")

# 美国东部时间
CronSchedule(kind="cron", expr="0 8 * * *", tz="America/New_York")

# UTC
CronSchedule(kind="cron", expr="0 0 * * *", tz="UTC")
```

### 时区规则

- `tz` **仅对 `cron` 类型有效**，对 `every` 和 `at` 设置 `tz` 会触发验证错误
- 不设置 `tz` 时默认使用系统时区
- 时区解析基于 Python 标准库 `zoneinfo`

---

## 6. 通过系统通道触发 Agent

Cron 任务可以将消息交付到指定的 IM 通道，实现定时消息通知。

### 交付到微信

```python
job = cron.add_job(
    name="morning-news",
    schedule=CronSchedule(kind="cron", expr="0 8 * * *", tz="Asia/Shanghai"),
    message="请整理今日要闻，包括科技动态、行业趋势和关键市场数据。",
    deliver=True,              # 启用交付
    channel="weixin",          # 交付到微信通道
    to="wx_user_001",          # 接收者 ID
)
```

### 交付到飞书

```python
job = cron.add_job(
    name="daily-report",
    schedule=CronSchedule(kind="cron", expr="0 18 * * 1-5", tz="Asia/Shanghai"),
    message="请生成今日工作总结报告。",
    deliver=True,
    channel="feishu",
    to="oc_xxxxxxxxxx",        # 飞书群聊 ID 或用户 Open ID
)
```

### Payload 字段详解

| 字段 | 说明 |
|------|------|
| `deliver` | `true` 时将 Agent 回复发送到指定通道，`false` 时仅记录日志 |
| `channel` | 目标通道名称，需与通道配置中的名称一致 |
| `to` | 接收者标识（微信用户 ID / 飞书 Open ID 或 Chat ID） |

### Cron 任务回调集成

在 CronService 初始化时注册 `on_job` 回调，控制任务触发后的行为：

```python
from agent_harness.cron.service import CronService
from agent_harness.cron.types import CronJob


async def handle_job(job: CronJob) -> str | None:
    """当 Cron 任务触发时调用此回调。

    Args:
        job: 被触发的任务对象

    Returns:
        Agent 的回复文本，或 None
    """
    print(f"任务触发: {job.name}")
    print(f"消息内容: {job.payload.message}")

    if job.payload.deliver:
        # 通过通道交付：将消息发送给 Agent 处理，将结果交付给用户
        # 实际项目中在此集成 Agent.process()
        print(f"交付到 {job.payload.channel} → {job.payload.to}")

    return f"任务 {job.name} 已完成"


cron = CronService(
    store_path=Path.home() / ".agent-harness" / "cron" / "jobs.json",
    on_job=handle_job,
)
```

---

## 7. 完整示例：定时任务服务

```python
"""cron-agent.py — 带有定时任务的 Agent 服务"""
import asyncio
import logging
from pathlib import Path

from agent_harness import Harness, Agent, AnthropicProvider
from agent_harness.cron.service import CronService
from agent_harness.cron.types import CronJob, CronSchedule

logging.basicConfig(level=logging.INFO)


async def handle_cron_job(job: CronJob) -> str | None:
    """处理 Cron 触发的任务。"""
    logging.info("Cron job triggered: %s | message: %s", job.name, job.payload.message)

    if job.payload.deliver:
        # TODO: 在此集成 Agent.process() 和通道交付
        logging.info(
            "Would deliver to %s → %s", job.payload.channel, job.payload.to
        )

    return f"Job {job.name} executed"


async def main():
    cron = CronService(
        store_path=Path.home() / ".agent-harness" / "cron" / "jobs.json",
        on_job=handle_cron_job,
    )

    await cron.start()
    print("Cron 服务已启动")

    # 创建一些示例任务
    cron.add_job(
        name="health-check",
        schedule=CronSchedule(kind="every", every_ms=300_000),  # 5 分钟
        message="执行系统健康检查",
    )

    cron.add_job(
        name="daily-summary",
        schedule=CronSchedule(
            kind="cron", expr="0 18 * * 1-5", tz="Asia/Shanghai"
        ),
        message="生成今日工作总结",
        deliver=True,
        channel="weixin",
        to="wx_manager",
    )

    print(f"已配置 {len(cron.list_jobs())} 个定时任务")

    # 保持运行
    try:
        while True:
            await asyncio.sleep(10)
            # 每 10 秒打印一次服务状态
            status = cron.status()
            print(f"Cron 运行中 | 任务数: {status['jobs']}")
    except KeyboardInterrupt:
        cron.stop()
        print("Cron 服务已停止")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 相关参考

- [Cron API 参考](../api/cron.md) — `CronService`、`CronJob`、`CronSchedule` 完整 API
- [观测追踪](enable-observability.md) — Cron 任务触发和完成事件追踪
- [通道对接](multi-channel.md) — 定时消息交付到 IM 通道
