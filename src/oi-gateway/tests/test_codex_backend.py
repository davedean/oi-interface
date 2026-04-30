from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from channel.backend import AgentBackendError, AgentRequest
from channel.codex_backend import CodexBackend


def make_request() -> AgentRequest:
    return AgentRequest(
        user_text="hello",
        source_device_id="dev1",
        input_kind="transcript",
        stream_id="s1",
        transcript="hello",
        session_key="oi:device:dev1",
        correlation_id="c1",
    )


class Proc:
    def __init__(self, *, stdout=b"", stderr=b"", returncode=0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self.killed = False

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True

    async def wait(self):
        return None


def test_codex_backend_extract_text_helpers():
    backend = CodexBackend.from_command_text("codex exec --json", timeout_seconds=5)
    assert backend.command == ["codex", "exec", "--json"]

    assert backend._extract_text_content("hello") == "hello"
    assert backend._extract_text_content(["a", {"text": "b"}, {"content": "c"}]) == "abc"
    assert backend._extract_text_content([1, {}]) is None

    assert backend._extract_text_from_event({"type": "response.output_text.delta", "delta": "hi"}) == "hi"
    assert backend._extract_text_from_event({"type": "response.output_text.done", "text": "done"}) == "done"
    assert backend._extract_text_from_event({"part": {"text": "part"}}) == "part"
    assert backend._extract_text_from_event({"message": {"role": "assistant", "content": [{"text": "msg"}]}}) == "msg"
    assert backend._extract_text_from_event({"response": "resp"}) == "resp"
    assert backend._extract_text_from_output("") == ""
    assert backend._extract_text_from_output("not json") == "not json"
    assert backend._extract_text_from_output('{"type":"response.output_text.delta","delta":"a"}\n{"type":"text","text":"b"}') == "ab"
    assert backend._extract_text_from_output('{"foo":1}') == ""


@pytest.mark.asyncio
async def test_codex_backend_success_failure_timeout_and_empty_text():
    backend = CodexBackend(timeout_seconds=5)

    success_stdout = b'{"type":"response.output_text.delta","delta":"Hello "}\n{"type":"text","text":"world"}\n'
    with patch("channel.cli_backend.asyncio.create_subprocess_exec", return_value=Proc(stdout=success_stdout, stderr=b"", returncode=0)):
        response = await backend.send_request(make_request())
        assert response.response_text == "Hello world"
        assert response.backend_name == "codex"

    with patch("channel.cli_backend.asyncio.create_subprocess_exec", return_value=Proc(stdout=b"", stderr=b"boom", returncode=1)):
        with pytest.raises(AgentBackendError, match="boom"):
            await backend.send_request(make_request())

    with patch("channel.cli_backend.asyncio.create_subprocess_exec", return_value=Proc(stdout=b'{"foo":1}\n', stderr=b"", returncode=0)):
        with pytest.raises(AgentBackendError, match="no assistant text"):
            await backend.send_request(make_request())

    proc = Proc()

    async def fake_wait_for(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError

    with patch("channel.cli_backend.asyncio.create_subprocess_exec", return_value=proc), patch("channel.cli_backend.asyncio.wait_for", side_effect=fake_wait_for):
        with pytest.raises(AgentBackendError, match="timed out"):
            await backend.send_request(make_request())
        assert proc.killed is True
