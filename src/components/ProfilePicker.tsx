import { PanelSection, PanelSectionRow, Field, ButtonItem } from "@decky/ui";
import { callable } from "@decky/api";
import { useState, useEffect } from "react";

interface Profile {
  name: string;
  active_reports: string[];
  trackpad_mode: string;
  mouse_sensitivity: number;
  scroll_sensitivity: number;
  gyro_sensitivity: number;
}

interface ProfilesState {
  profiles: Profile[];
  active_index: number;
}

const getProfiles = callable<[], { success: boolean } & ProfilesState>(
  "get_profiles"
);
const switchProfile = callable<
  [number],
  { success: boolean; profile: Profile }
>("switch_profile");

export function ProfilePicker() {
  const [state, setState] = useState<ProfilesState | null>(null);
  const [switching, setSwitching] = useState(false);

  const loadProfiles = async () => {
    const result = await getProfiles();
    if (result.success) {
      setState({ profiles: result.profiles, active_index: result.active_index });
    }
  };

  useEffect(() => {
    loadProfiles();
  }, []);

  const handleSwitch = async (index: number) => {
    setSwitching(true);
    const result = await switchProfile(index);
    if (result.success) {
      setState((prev) => (prev ? { ...prev, active_index: index } : null));
    }
    setSwitching(false);
  };

  if (!state) {
    return (
      <PanelSection title="Profiles">
        <PanelSectionRow>
          <Field label="Loading...">Loading profiles...</Field>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  const activeProfile = state.profiles[state.active_index];
  const reportIcons: Record<string, string> = {
    gamepad: "🎮",
    mouse: "🖱️",
    motion: "🔄",
  };

  return (
    <PanelSection title="Profile">
      <PanelSectionRow>
        <Field
          label="Active"
          description={activeProfile.active_reports
            .map((r) => reportIcons[r] || r)
            .join(" ")}
        >
          {activeProfile.name}
        </Field>
      </PanelSectionRow>

      {state.profiles.map((profile, index) => (
        <PanelSectionRow key={profile.name}>
          <ButtonItem
            layout="below"
            disabled={switching || index === state.active_index}
            onClick={() => handleSwitch(index)}
          >
            {profile.name}
            {index === state.active_index ? " ✓" : ""}
          </ButtonItem>
        </PanelSectionRow>
      ))}
    </PanelSection>
  );
}
