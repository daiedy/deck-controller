import { PanelSection, PanelSectionRow, ButtonItem, Field } from "@decky/ui";
import { useBackend } from "../hooks/useBackend";

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
  const { status, isLoading, actions } = useBackend();

  const stateLabel = STATE_LABELS[status.state] || status.state;
  const stateColor = STATE_COLORS[status.state] || "#888";

  const handleToggle = async () => {
    if (status.state === "idle") {
      await actions.startBroadcasting();
    } else {
      await actions.stopBroadcasting();
    }
  };

  return (
    <>
      <PanelSection title="Status">
        <PanelSectionRow>
          <Field
            label="State"
            description={
              status.connected_device
                ? `Connected to ${status.connected_device.name}`
                : undefined
            }
          >
            <span style={{ color: stateColor, fontWeight: "bold" }}>
              {stateLabel}
            </span>
          </Field>
        </PanelSectionRow>

        {status.connected_device && (
          <PanelSectionRow>
            <Field label="Device" description={status.connected_device.address}>
              {status.connected_device.name}
            </Field>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title="Controls">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={isLoading}
            onClick={handleToggle}
          >
            {status.state === "idle" ? "Start Broadcasting" : "Stop Broadcasting"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}
