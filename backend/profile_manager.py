"""Profile management for Deck Controller."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger("deck-controller.profile_manager")


@dataclass
class Profile:
    """A controller profile defining which reports to send and input behavior."""

    name: str
    active_reports: list[str] = field(default_factory=lambda: ["gamepad"])
    trackpad_mode: str = "disabled"  # "mouse", "disabled"
    mouse_sensitivity: float = 1.0
    scroll_sensitivity: float = 1.0
    gyro_sensitivity: float = 1.0

    def sends_gamepad(self) -> bool:
        return "gamepad" in self.active_reports

    def sends_mouse(self) -> bool:
        return "mouse" in self.active_reports

    def sends_motion(self) -> bool:
        return "motion" in self.active_reports

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Profile:
        return cls(
            name=data.get("name", "Custom"),
            active_reports=data.get("active_reports", ["gamepad"]),
            trackpad_mode=data.get("trackpad_mode", "disabled"),
            mouse_sensitivity=data.get("mouse_sensitivity", 1.0),
            scroll_sensitivity=data.get("scroll_sensitivity", 1.0),
            gyro_sensitivity=data.get("gyro_sensitivity", 1.0),
        )


# Default profiles
DEFAULT_PROFILES: list[Profile] = [
    Profile(
        name="Gamepad + Mouse",
        active_reports=["gamepad", "mouse"],
        trackpad_mode="mouse",
        mouse_sensitivity=1.0,
        scroll_sensitivity=1.0,
    ),
    Profile(
        name="Gamepad",
        active_reports=["gamepad"],
        trackpad_mode="disabled",
    ),
    Profile(
        name="Desktop",
        active_reports=["mouse"],
        trackpad_mode="mouse",
        mouse_sensitivity=1.0,
        scroll_sensitivity=1.0,
    ),
    Profile(
        name="FPS",
        active_reports=["gamepad", "motion"],
        trackpad_mode="mouse",  # right trackpad as fine aim
        mouse_sensitivity=0.5,
        gyro_sensitivity=1.0,
    ),
    Profile(
        name="Racing",
        active_reports=["gamepad", "motion"],
        trackpad_mode="disabled",
        gyro_sensitivity=1.5,
    ),
    Profile(
        name="Media",
        active_reports=["mouse"],
        trackpad_mode="mouse",
        mouse_sensitivity=1.2,
        scroll_sensitivity=1.5,
    ),
]


class ProfileManager:
    """Manages controller profiles — loading, saving, switching."""

    def __init__(self, settings_dir: str) -> None:
        self._settings_dir = settings_dir
        self._profiles_path = os.path.join(settings_dir, "profiles.json")
        self._profiles: list[Profile] = []
        self._active_index: int = 0
        self._load()

    def _load(self) -> None:
        """Load profiles from disk, or use defaults."""
        try:
            with open(self._profiles_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._profiles = [Profile.from_dict(p) for p in data.get("profiles", [])]
            self._active_index = data.get("active_index", 0)
            if not self._profiles:
                self._profiles = list(DEFAULT_PROFILES)
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            self._profiles = list(DEFAULT_PROFILES)
            self._active_index = 0

        # Clamp active index
        if self._active_index >= len(self._profiles):
            self._active_index = 0

        logger.info(
            "Loaded %d profiles, active: %s",
            len(self._profiles),
            self.active_profile.name,
        )

    def _save(self) -> None:
        """Persist profiles to disk."""
        os.makedirs(self._settings_dir, exist_ok=True)
        data = {
            "profiles": [p.to_dict() for p in self._profiles],
            "active_index": self._active_index,
        }
        with open(self._profiles_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @property
    def active_profile(self) -> Profile:
        """Currently active profile."""
        return self._profiles[self._active_index]

    @property
    def profiles(self) -> list[Profile]:
        """All available profiles."""
        return list(self._profiles)

    def switch_profile(self, index: int) -> Profile:
        """Switch to profile by index.

        Args:
            index: Profile index (0-based).

        Returns:
            The newly active profile.

        Raises:
            IndexError: If index is out of range.
        """
        if not 0 <= index < len(self._profiles):
            raise IndexError(f"Profile index {index} out of range (0-{len(self._profiles) - 1})")
        self._active_index = index
        self._save()
        logger.info("Switched to profile: %s", self.active_profile.name)
        return self.active_profile

    def switch_by_name(self, name: str) -> Profile | None:
        """Switch to profile by name (case-insensitive).

        Returns:
            The profile if found, None otherwise.
        """
        for i, p in enumerate(self._profiles):
            if p.name.lower() == name.lower():
                return self.switch_profile(i)
        return None

    def add_profile(self, profile: Profile) -> int:
        """Add a new profile.

        Returns:
            Index of the new profile.
        """
        self._profiles.append(profile)
        self._save()
        return len(self._profiles) - 1

    def remove_profile(self, index: int) -> bool:
        """Remove a profile by index. Cannot remove if only one remains.

        Returns:
            True if removed.
        """
        if len(self._profiles) <= 1:
            return False
        if not 0 <= index < len(self._profiles):
            return False
        self._profiles.pop(index)
        if self._active_index >= len(self._profiles):
            self._active_index = len(self._profiles) - 1
        self._save()
        return True

    def to_dict(self) -> dict[str, Any]:
        """Serialize full state for RPC."""
        return {
            "profiles": [p.to_dict() for p in self._profiles],
            "active_index": self._active_index,
            "active_profile": self.active_profile.to_dict(),
        }
