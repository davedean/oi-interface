import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUSH = ROOT / "scripts" / "push.sh"
VERSION = ROOT / "firmware" / "version.py"


class PushScriptCase(unittest.TestCase):
    def setUp(self):
        self.original_version = VERSION.read_text() if VERSION.exists() else None
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.env_file = self.tmp_path / "webrepl.env"
        self.env_file.write_text('WEBREPL_PASSWORD="test"\n')

    def tearDown(self):
        if self.original_version is None:
            try:
                VERSION.unlink()
            except FileNotFoundError:
                pass
        else:
            VERSION.write_text(self.original_version)
        self.tmp.cleanup()

    def run_push(self, fake_cli, *args, extra_env=None):
        fake_path = self.tmp_path / "fake_webrepl.py"
        fake_path.write_text(textwrap.dedent(fake_cli))
        env = os.environ.copy()
        env.update({
            "OI_ENV_FILE": str(self.env_file),
            "OI_WEBREPL_CLI": str(fake_path),
            "OI_HOST": "example.test",
        })
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["bash", str(PUSH), *args],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_shell_syntax(self):
        result = subprocess.run(["bash", "-n", str(PUSH)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_upload_failure_exits_nonzero(self):
        result = self.run_push(
            """
            import sys
            print('op:put')
            print('passwd:test')
            print('boom', file=sys.stderr)
            sys.exit(7)
            """,
            "main.py",
        )
        self.assertEqual(result.returncode, 7)
        self.assertIn("WebREPL upload failed", result.stderr)

    def test_success_with_all_output_filtered_still_exits_zero(self):
        result = self.run_push(
            """
            print('op:put')
            print('passwd:test')
            """,
            "main.py",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[oi push] done", result.stdout)

    def test_reset_failure_exits_nonzero(self):
        result = self.run_push(
            """
            import sys
            if '--command' in sys.argv:
                print('reset failed', file=sys.stderr)
                sys.exit(9)
            print('ok')
            """,
            "--reset",
            "main.py",
        )
        self.assertEqual(result.returncode, 9)
        self.assertIn("WebREPL reset failed", result.stderr)

    def test_dry_run_skips_webrepl_and_missing_env_file(self):
        missing_env = self.tmp_path / "missing.env"
        result = self.run_push(
            """
            import sys
            print('should not be called')
            sys.exit(7)
            """,
            "--dry-run",
            "main.py",
            extra_env={"OI_ENV_FILE": str(missing_env)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dry-run: push main.py", result.stdout)

    def test_status_mode_prints_config_without_env_file(self):
        missing_env = self.tmp_path / "missing.env"
        result = self.run_push(
            """
            import sys
            print('should not be called')
            sys.exit(7)
            """,
            "--status",
            "main.py",
            extra_env={"OI_ENV_FILE": str(missing_env)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[oi push] status", result.stdout)
        self.assertIn("- version.py", result.stdout)
        self.assertIn("- main.py", result.stdout)


if __name__ == "__main__":
    unittest.main()
