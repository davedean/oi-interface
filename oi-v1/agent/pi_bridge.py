#!/usr/bin/env python3
"""Bridge oi device commands to a pi RPC session.

This is intentionally small and allowlisted: the device/server queues high-level
commands, and the bridge translates only known verbs into pi RPC commands.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import Any

import oi


ALLOWED_VERBS = {"status", "abort", "steer", "follow_up", "prompt", "speak"}


class PiRpcClient:
    """Line-delimited JSON RPC client for `pi --mode rpc`."""

    def __init__(self, argv: list[str] | None = None):
        self.argv = argv or ["pi", "--mode", "rpc"]
        self.proc = subprocess.Popen(
            self.argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._next_id = 1

    def call(self, payload: dict) -> dict:
        if self.proc.stdin is None or self.proc.stdout is None:
            raise RuntimeError("pi rpc process pipes are closed")
        payload = dict(payload)
        payload.setdefault("id", f"oi-{self._next_id}")
        self._next_id += 1
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if msg.get("type") == "response" and msg.get("id") == payload.get("id"):
                if not msg.get("success", False):
                    raise RuntimeError(msg.get("error") or msg)
                return msg
        raise RuntimeError("pi rpc ended before response")

    def close(self) -> None:
        try:
            self.proc.terminate()
        except Exception:
            pass


def rpc_payload_for_command(command: dict) -> dict:
    verb = command.get("verb")
    args = command.get("args") or {}
    if verb not in ALLOWED_VERBS:
        raise ValueError(f"unsupported command verb: {verb}")
    if verb == "status":
        return {"type": "get_state"}
    if verb == "abort":
        return {"type": "abort"}
    if verb in ("steer", "follow_up", "prompt"):
        message = args.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ValueError(f"{verb} command requires args.message")
        payload = {"type": verb, "message": message}
        if verb == "prompt" and args.get("streamingBehavior"):
            payload["streamingBehavior"] = args["streamingBehavior"]
        return payload
    raise ValueError(f"unsupported command verb: {verb}")


def execute_command(rpc: Any, command: dict) -> dict:
    verb = command.get("verb")
    if verb == "speak":
        args = command.get("args") or {}
        text = args.get("message", "")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("speak command requires args.message")
        return oi.speak(text)
    payload = rpc_payload_for_command(command)
    return rpc.call(payload)


def bridge_once(session_id: str, rpc: Any, after_seq: int = 0) -> int:
    """Poll once, execute queued commands, ack/fail each. Returns latest seq seen."""
    latest = after_seq
    for command in oi.poll_commands(session_id, after_seq=after_seq):
        seq = int(command.get("seq") or 0)
        try:
            result = execute_command(rpc, command)
            oi.ack_command(command["command_id"], result=result)
            latest = max(latest, seq)
        except Exception as e:
            oi.fail_command(command.get("command_id", "?"), e)
            latest = max(latest, seq)
    return latest


def run_bridge(session_id: str, name: str = "", cwd: str = "", interval: float = 1.0) -> None:
    rpc = PiRpcClient()
    after_seq = 0
    try:
        while True:
            oi.register_session(session_id, name=name, cwd=cwd, kind="pi", status="online")
            after_seq = bridge_once(session_id, rpc, after_seq=after_seq)
            time.sleep(interval)
    finally:
        rpc.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="bridge oi commands to a pi RPC session")
    p.add_argument("--session-id", required=True)
    p.add_argument("--name", default="")
    p.add_argument("--cwd", default="")
    p.add_argument("--interval", type=float, default=1.0)
    args = p.parse_args(argv)
    run_bridge(args.session_id, name=args.name, cwd=args.cwd, interval=args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
