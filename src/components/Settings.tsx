import {
  PanelSection,
  PanelSectionRow,
  Field,
  ToggleField,
  SliderField,
  DropdownItem,
  TextField,
} from "@decky/ui";
import { useBackend } from "../hooks/useBackend";

const POLLING_RATE_OPTIONS = [
  { label: "125 Hz", data: 125 },
  { label: "250 Hz", data: 250 },
  { label: "500 Hz", data: 500 },
];

export function Settings() {
  const { config, actions, isLoading } = useBackend();

  if (!config) {
    return (
      <PanelSection title="Settings">
        <PanelSectionRow>
          <Field label="Loading...">Loading configuration...</Field>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  return (
    <>
      <PanelSection title="General">
        <PanelSectionRow>
          <TextField
            label="Controller Name"
            value={config.controller_name}
            onChange={(e) => actions.setConfig("controller_name", e.target.value)}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <ToggleField
            label="Auto Connect"
            description="Automatically connect to the last paired device on startup"
            checked={config.auto_connect}
            onChange={(value) => actions.setConfig("auto_connect", value)}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <DropdownItem
            label="Polling Rate"
            description="Input polling frequency"
            rgOptions={POLLING_RATE_OPTIONS}
            selectedOption={config.polling_rate_hz}
            onChange={(option) => actions.setConfig("polling_rate_hz", option.data)}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Input">
        <PanelSectionRow>
          <SliderField
            label="Deadzone"
            description={`Current: ${(config.deadzone * 100).toFixed(0)}%`}
            value={config.deadzone}
            min={0}
            max={0.25}
            step={0.01}
            onChange={(value) => actions.setConfig("deadzone", value)}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <ToggleField
            label="Enable Gyro"
            description="Forward gyroscope data (experimental)"
            checked={config.enable_gyro}
            onChange={(value) => actions.setConfig("enable_gyro", value)}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <ToggleField
            label="Enable Trackpads"
            description="Forward trackpad input (experimental)"
            checked={config.enable_trackpads}
            onChange={(value) => actions.setConfig("enable_trackpads", value)}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Back Buttons">
        <PanelSectionRow>
          <Field label="Back Buttons" description="L4, L5, R4, R5 mapped as HID buttons 14-17">
            Enabled (always active)
          </Field>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Bluetooth">
        <PanelSectionRow>
          <DropdownItem
            label="Max Connections"
            description="Maximum simultaneous connections"
            rgOptions={[
              { label: "1", data: 1 },
              { label: "2", data: 2 },
              { label: "3", data: 3 },
              { label: "4", data: 4 },
            ]}
            selectedOption={config.max_connections}
            onChange={(option) => actions.setConfig("max_connections", option.data)}
          />
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}
