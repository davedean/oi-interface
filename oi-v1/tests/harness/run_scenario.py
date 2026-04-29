"""Spawn fake_pi_rpc.ts with a scenario file and drive the mock device or firmware client."""
import subprocess
import sys
import os
from typing import List, Tuple


def run_scenario(
    scenario_path: str,
    client_cmd: List[str],
    timeout_s: int = 10,
) -> Tuple[int, str, str]:
    """Run a fake-peer scenario against a client process.

    Args:
        scenario_path: Path to the .jsonl scenario file.
        client_cmd: Command + args to run the RPC client.
        timeout_s: Timeout in seconds.

    Returns:
        (exit_code, stdout, stderr)
    """
    # Spawn fake peer
    fake_proc = subprocess.Popen(
        ["npx", "tsx", "tests/harness/fake_pi_rpc.ts", scenario_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=os.getcwd(),
    )

    # Spawn client, piping its stdin/stdout to fake peer's stdout/stdin
    client_proc = subprocess.Popen(
        client_cmd,
        stdin=fake_proc.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=os.getcwd(),
    )

    # Give fake_proc its stdin back
    fake_proc.stdout = None

    try:
        out, err = client_proc.communicate(timeout=timeout_s)
        fake_exit = fake_proc.wait(timeout=2)
        return client_proc.returncode, out.decode(), err.decode()
    finally:
        if fake_proc.poll() is None:
            fake_proc.kill()
        if client_proc.poll() is None:
            client_proc.kill()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: run_scenario.py <scenario.jsonl> <client_cmd> [args...]")
        sys.exit(1)
    scenario = sys.argv[1]
    client_cmd = sys.argv[2:]
    code, out, err = run_scenario(scenario, client_cmd)
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)
    sys.exit(code)
