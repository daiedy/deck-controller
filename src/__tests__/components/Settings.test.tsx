vi.mock("../../hooks/useBackend", () => ({
  useBackend: vi.fn(),
}));

import { render, screen } from "@testing-library/react";
import { Settings } from "../../components/Settings";
import { useBackend } from "../../hooks/useBackend";

const defaultConfig = {
  controller_name: "Deck Controller",
  auto_connect: false,
  polling_rate_hz: 125,
  deadzone: 0.05,
  enable_gyro: false,
  enable_trackpads: false,
  bt_device_class: "0x002508",
  max_connections: 1,
};

const mockActions = {
  startBroadcasting: vi.fn(),
  stopBroadcasting: vi.fn(),
  setConfig: vi.fn(),
  getConfig: vi.fn(),
  refreshDevices: vi.fn(),
  refreshStatus: vi.fn(),
  removeDevice: vi.fn(),
};

describe("Settings", () => {
  beforeEach(() => {
    vi.mocked(useBackend).mockReturnValue({
      status: { state: "idle", running: false, connected_device: null, input_active: false },
      devices: [],
      config: defaultConfig,
      isLoading: false,
      actions: mockActions,
    });
  });

  it("shows loading state when config is null", () => {
    vi.mocked(useBackend).mockReturnValue({
      status: { state: "idle", running: false, connected_device: null, input_active: false },
      devices: [],
      config: null,
      isLoading: true,
      actions: mockActions,
    });

    render(<Settings />);
    expect(screen.getByText("Loading configuration...")).toBeDefined();
  });

  it("renders setting controls", () => {
    render(<Settings />);
    expect(screen.getByTestId("TextField")).toBeDefined();
    expect(screen.getAllByTestId("ToggleField").length).toBeGreaterThanOrEqual(3);
    expect(screen.getByTestId("SliderField")).toBeDefined();
    expect(screen.getAllByTestId("DropdownItem").length).toBeGreaterThanOrEqual(2);
  });

  it("has all sections (General, Input, Bluetooth)", () => {
    render(<Settings />);
    const sections = screen.getAllByTestId("PanelSection");
    const titles = sections.map((s) => s.getAttribute("title"));
    expect(titles).toContain("General");
    expect(titles).toContain("Input");
    expect(titles).toContain("Bluetooth");
  });
});
