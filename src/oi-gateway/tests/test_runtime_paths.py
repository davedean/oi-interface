from __future__ import annotations

from pathlib import Path
import sys

gateway_src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(gateway_src))

from registry.store import DeviceStore
from runtime_paths import gateway_db_path, oi_home


def test_oi_home_prefers_explicit_override(tmp_path, monkeypatch):
    monkeypatch.setenv("OI_HOME", str(tmp_path / "oi-home"))
    assert oi_home() == tmp_path / "oi-home"


def test_oi_home_uses_xdg_config_home_when_set(tmp_path, monkeypatch):
    monkeypatch.delenv("OI_HOME", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert oi_home() == tmp_path / "xdg" / "oi"


def test_gateway_db_path_defaults_under_oi_state(tmp_path, monkeypatch):
    monkeypatch.setenv("OI_HOME", str(tmp_path / "oi-home"))
    assert gateway_db_path() == tmp_path / "oi-home" / "state" / "oi-gateway" / "oi-gateway.db"


def test_device_store_defaults_to_gateway_state_db(tmp_path, monkeypatch):
    monkeypatch.setenv("OI_HOME", str(tmp_path / "oi-home"))

    store = DeviceStore()
    try:
        assert store.db_path == str(
            tmp_path / "oi-home" / "state" / "oi-gateway" / "oi-gateway.db"
        )
        assert Path(store.db_path).exists()
    finally:
        store.close()
