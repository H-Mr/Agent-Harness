# 如何实现自定义 Sandbox Backend

## 目标

将默认的 SRTSandboxBackend 替换为你自己的实现——基于容器的 sandbox、远程执行服务，或简化的本地文件系统。

## 前置条件

- 了解 SandboxBackend Protocol（8 个方法）

## 分步指南

### 1. 理解 Protocol

`llm_harness.adapters.sandbox.backend` 中定义的完整 SandboxBackend Protocol：

```python
class SandboxBackend(Protocol):
    async def create_session(self, session_key: str) -> SandboxSession: ...
    async def destroy_session(self, session_key: str) -> None: ...
    async def read_file(self, session_key: str, path: str) -> str: ...
    async def write_file(self, session_key: str, path: str, content: str) -> None: ...
    async def list_dir(self, session_key: str, path: str) -> list[str]: ...
    async def glob(self, session_key: str, pattern: str) -> list[str]: ...
    async def grep(self, session_key: str, pattern: str, path: str) -> list[str]: ...
    async def execute(self, session_key: str, command: str, *, cwd: str = "/workspace",
                      env: dict | None = None, timeout: int = 60) -> ExecResult: ...
```

### 2. 实现全部 8 个方法

以下是一个最小化的本地文件系统 sandbox——与 SRTSandboxBackend 一样进行路径限制，但没有 srt OS 包装层：

```python
import re, asyncio, shlex
from pathlib import Path
from llm_harness.adapters.sandbox.backend import SandboxSession, ExecResult

class LocalSandboxBackend:
    def __init__(self, workspace_root: str | Path):
        self._root = Path(workspace_root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        p = (self._root / path).resolve()
        if not str(p).startswith(str(self._root)):
            raise PermissionError(f"Path traversal denied: {path!r}")
        return p

    async def create_session(self, session_key: str) -> SandboxSession:
        return SandboxSession(session_key=session_key, volume_path=str(self._root), sandbox_id="local")

    async def destroy_session(self, session_key: str) -> None:
        pass

    async def read_file(self, session_key: str, path: str) -> str:
        p = self._resolve(path)
        return p.read_text(encoding="utf-8") if p.is_file() else ""

    async def write_file(self, session_key: str, path: str, content: str) -> None:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    async def list_dir(self, session_key: str, path: str) -> list[str]:
        p = self._resolve(path)
        return [str(x.relative_to(p)) for x in p.iterdir()] if p.is_dir() else []

    async def glob(self, session_key: str, pattern: str) -> list[str]:
        results = list(self._root.glob(pattern))
        return [str(r.relative_to(self._root)) for r in results]

    async def grep(self, session_key: str, pattern: str, path: str) -> list[str]:
        p = self._resolve(path)
        if p.is_file():
            return self._grep_file(p, pattern)
        if p.is_dir():
            results = []
            for f in p.rglob("*"):
                if f.is_file():
                    results.extend(self._grep_file(f, pattern))
            return results
        return []

    @staticmethod
    def _grep_file(p: Path, pattern: str) -> list[str]:
        return [f"{i+1}:{line}" for i, line in enumerate(p.read_text(encoding="utf-8").splitlines())
                if re.search(pattern, line)]

    async def execute(self, session_key: str, command: str, *, cwd="/workspace", env=None, timeout=60) -> ExecResult:
        try:
            proc = await asyncio.create_subprocess_shell(
                command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, cwd=cwd, env=env
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return ExecResult(
                output=stdout.decode("utf-8", errors="replace") if stdout else "",
                exit_code=proc.returncode or 0,
                is_error=proc.returncode != 0,
            )
        except asyncio.TimeoutError:
            return ExecResult(output="Command timed out", exit_code=-1, is_error=True)
```

### 3. 注入到 Harness

```python
sandbox = LocalSandboxBackend("/workspace")
harness = Harness(provider=..., model=..., tools=..., sandbox=sandbox)
```

## 测试

```python
@pytest.mark.asyncio
async def test_local_sandbox_read_write(tmp_path):
    sandbox = LocalSandboxBackend(tmp_path)
    await sandbox.write_file("s1", "test.txt", "hello")
    content = await sandbox.read_file("s1", "test.txt")
    assert content == "hello"

@pytest.mark.asyncio
async def test_local_sandbox_traversal_blocked(tmp_path):
    sandbox = LocalSandboxBackend(tmp_path)
    with pytest.raises(PermissionError, match="traversal"):
        await sandbox.read_file("s1", "../etc/passwd")
```
