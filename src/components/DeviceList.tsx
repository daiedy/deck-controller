import { PanelSection, PanelSectionRow, ButtonItem, Field } from "@decky/ui";
import { useBackend } from "../hooks/useBackend";

export function DeviceList() {
  const { devices, actions, isLoading } = useBackend();

  return (
    <PanelSection title="Paired Devices">
      {devices.length === 0 ? (
        <PanelSectionRow>
          <Field label="No devices">
            No paired devices found. Start broadcasting to pair a new device.
          </Field>
        </PanelSectionRow>
      ) : (
        devices.map((device) => (
          <PanelSectionRow key={device.address}>
            <Field
              label={device.name}
              description={device.address}
            >
              <ButtonItem
                layout="below"
                disabled={isLoading}
                onClick={async () => {
                  await actions.removeDevice(device.address);
                  await actions.refreshDevices();
                }}
              >
                Remove
              </ButtonItem>
            </Field>
          </PanelSectionRow>
        ))
      )}

      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={isLoading}
          onClick={() => actions.refreshDevices()}
        >
          Refresh
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}
