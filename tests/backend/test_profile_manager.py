"""Tests for backend.profile_manager — profile CRUD and switching."""

from __future__ import annotations

import json

import pytest

from backend.profile_manager import DEFAULT_PROFILES, Profile, ProfileManager


# ---- Profile dataclass ----


class TestProfile:
    def test_default_values(self):
        p = Profile(name="Test")
        assert p.name == "Test"
        assert p.active_reports == ["gamepad"]
        assert p.trackpad_mode == "disabled"
        assert p.mouse_sensitivity == 1.0

    def test_sends_gamepad(self):
        p = Profile(name="A", active_reports=["gamepad"])
        assert p.sends_gamepad() is True
        assert p.sends_mouse() is False
        assert p.sends_motion() is False

    def test_sends_mouse(self):
        p = Profile(name="A", active_reports=["mouse"])
        assert p.sends_mouse() is True
        assert p.sends_gamepad() is False

    def test_sends_motion(self):
        p = Profile(name="A", active_reports=["gamepad", "motion"])
        assert p.sends_motion() is True
        assert p.sends_gamepad() is True

    def test_to_dict(self):
        p = Profile(name="X", active_reports=["gamepad"], mouse_sensitivity=0.5)
        d = p.to_dict()
        assert d["name"] == "X"
        assert d["mouse_sensitivity"] == 0.5
        assert isinstance(d, dict)

    def test_from_dict(self):
        d = {"name": "FromDict", "active_reports": ["mouse"], "gyro_sensitivity": 2.0}
        p = Profile.from_dict(d)
        assert p.name == "FromDict"
        assert p.active_reports == ["mouse"]
        assert p.gyro_sensitivity == 2.0
        # Non-specified values get defaults
        assert p.trackpad_mode == "disabled"

    def test_from_dict_with_defaults(self):
        p = Profile.from_dict({})
        assert p.name == "Custom"
        assert p.active_reports == ["gamepad"]

    def test_roundtrip(self):
        original = Profile(name="RT", active_reports=["gamepad", "mouse"], mouse_sensitivity=0.7)
        restored = Profile.from_dict(original.to_dict())
        assert restored.name == original.name
        assert restored.active_reports == original.active_reports
        assert restored.mouse_sensitivity == original.mouse_sensitivity


# ---- ProfileManager ----


class TestProfileManagerInit:
    def test_loads_defaults_when_no_file(self, tmp_path):
        pm = ProfileManager(settings_dir=str(tmp_path))
        assert len(pm.profiles) == len(DEFAULT_PROFILES)
        assert pm.active_profile.name == DEFAULT_PROFILES[0].name

    def test_loads_from_file(self, tmp_path):
        data = {
            "profiles": [{"name": "Custom1"}, {"name": "Custom2"}],
            "active_index": 1,
        }
        (tmp_path / "profiles.json").write_text(json.dumps(data))

        pm = ProfileManager(settings_dir=str(tmp_path))
        assert len(pm.profiles) == 2
        assert pm.active_profile.name == "Custom2"

    def test_empty_profiles_in_file_uses_defaults(self, tmp_path):
        data = {"profiles": [], "active_index": 0}
        (tmp_path / "profiles.json").write_text(json.dumps(data))

        pm = ProfileManager(settings_dir=str(tmp_path))
        assert len(pm.profiles) == len(DEFAULT_PROFILES)

    def test_clamps_active_index(self, tmp_path):
        data = {
            "profiles": [{"name": "Only"}],
            "active_index": 99,
        }
        (tmp_path / "profiles.json").write_text(json.dumps(data))

        pm = ProfileManager(settings_dir=str(tmp_path))
        assert pm.active_profile.name == "Only"

    def test_invalid_json_uses_defaults(self, tmp_path):
        (tmp_path / "profiles.json").write_text("broken{{")
        pm = ProfileManager(settings_dir=str(tmp_path))
        assert len(pm.profiles) == len(DEFAULT_PROFILES)


class TestProfileManagerSwitch:
    def test_switch_profile(self, tmp_path):
        pm = ProfileManager(settings_dir=str(tmp_path))
        p = pm.switch_profile(1)
        assert p.name == DEFAULT_PROFILES[1].name
        assert pm.active_profile.name == DEFAULT_PROFILES[1].name

    def test_switch_profile_out_of_range(self, tmp_path):
        pm = ProfileManager(settings_dir=str(tmp_path))
        with pytest.raises(IndexError):
            pm.switch_profile(999)

    def test_switch_profile_negative(self, tmp_path):
        pm = ProfileManager(settings_dir=str(tmp_path))
        with pytest.raises(IndexError):
            pm.switch_profile(-1)

    def test_switch_by_name(self, tmp_path):
        pm = ProfileManager(settings_dir=str(tmp_path))
        p = pm.switch_by_name("FPS")
        assert p is not None
        assert p.name == "FPS"

    def test_switch_by_name_case_insensitive(self, tmp_path):
        pm = ProfileManager(settings_dir=str(tmp_path))
        p = pm.switch_by_name("fps")
        assert p is not None
        assert p.name == "FPS"

    def test_switch_by_name_not_found(self, tmp_path):
        pm = ProfileManager(settings_dir=str(tmp_path))
        assert pm.switch_by_name("nonexistent") is None

    def test_switch_persists(self, tmp_path):
        pm = ProfileManager(settings_dir=str(tmp_path))
        pm.switch_profile(2)

        pm2 = ProfileManager(settings_dir=str(tmp_path))
        assert pm2.active_profile.name == DEFAULT_PROFILES[2].name


class TestProfileManagerCRUD:
    def test_add_profile(self, tmp_path):
        pm = ProfileManager(settings_dir=str(tmp_path))
        count_before = len(pm.profiles)
        idx = pm.add_profile(Profile(name="New"))
        assert len(pm.profiles) == count_before + 1
        assert pm.profiles[idx].name == "New"

    def test_add_persists(self, tmp_path):
        pm = ProfileManager(settings_dir=str(tmp_path))
        pm.add_profile(Profile(name="Persisted"))

        pm2 = ProfileManager(settings_dir=str(tmp_path))
        names = [p.name for p in pm2.profiles]
        assert "Persisted" in names

    def test_remove_profile(self, tmp_path):
        pm = ProfileManager(settings_dir=str(tmp_path))
        count_before = len(pm.profiles)
        assert pm.remove_profile(0) is True
        assert len(pm.profiles) == count_before - 1

    def test_remove_last_profile_fails(self, tmp_path):
        data = {"profiles": [{"name": "Only"}], "active_index": 0}
        (tmp_path / "profiles.json").write_text(json.dumps(data))

        pm = ProfileManager(settings_dir=str(tmp_path))
        assert pm.remove_profile(0) is False
        assert len(pm.profiles) == 1

    def test_remove_invalid_index(self, tmp_path):
        pm = ProfileManager(settings_dir=str(tmp_path))
        assert pm.remove_profile(999) is False

    def test_remove_active_clamps_index(self, tmp_path):
        data = {
            "profiles": [{"name": "A"}, {"name": "B"}],
            "active_index": 1,
        }
        (tmp_path / "profiles.json").write_text(json.dumps(data))

        pm = ProfileManager(settings_dir=str(tmp_path))
        pm.remove_profile(1)
        # Active was 1, now only 1 profile left → clamped to 0
        assert pm.active_profile.name == "A"


class TestProfileManagerToDict:
    def test_structure(self, tmp_path):
        pm = ProfileManager(settings_dir=str(tmp_path))
        d = pm.to_dict()
        assert "profiles" in d
        assert "active_index" in d
        assert "active_profile" in d
        assert isinstance(d["profiles"], list)
