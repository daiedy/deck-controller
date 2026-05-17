import { PanelSection, PanelSectionRow, ButtonItem, Field } from "@decky/ui";
import { useBackend } from "../hooks/useBackend";
import { ProfilePicker } from "./ProfilePicker";

const STATE_LABELS: Record<string, string> = {
  idle: "Idle",
  broadcasting: "Broadcasting",
  connected: "Connected",
};

const STATE_COLORS: Record<string, string> = {
  idle: "#888",
  broadcasting: "#f59e0b",
  connected: "#22c55e",
};

export function MainView() {
  const { status, isLoading, actionInProgress, lastError, clearError, actions } = useBackend();

  const stateLabel = STATE_LABELS[status.state] || status.state;
  const stateColor = STATE_COLORS[status.state] || "#888";

  const handleToggle = async () => {
    if (status.state === "idle") {
      await actions.startBroadcasting();
    } else {
      await actions.stopBroadcasting();
    }
  };

  const buttonLabel = actionInProgress
    ? actionInProgress
    : status.state === "idle"
      ? "Start Broadcasting"
      : "Stop Broadcasting";

  return (
    <>
      <PanelSection title="Status">
        <PanelSectionRow>
          <Field
            label="State"
            description={
              status.connected_device ? `Connected to ${status.connected_device.name}` : undefined
            }
          >
            <span style={{ color: stateColor, fontWeight: "bold" }}>{stateLabel}</span>
          </Field>
        </PanelSectionRow>

        {status.connected_device && (
          <PanelSectionRow>
            <Field label="Device" description={status.connected_device.address}>
              {status.connected_device.name}
            </Field>
          </PanelSectionRow>
        )}

        {lastError && (
          <PanelSectionRow>
            <Field label="Error">
              <span style={{ color: "#ef4444", fontSize: "0.85em" }}>{lastError}</span>
            </Field>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title="Controls">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={isLoading || !!actionInProgress}
            onClick={handleToggle}
          >
            {buttonLabel}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <ProfilePicker />
    </>
  );
}
