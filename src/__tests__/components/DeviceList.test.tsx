vi.mock("../../hooks/useBackend", () => ({
  useBackend: vi.fn(),
}));

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DeviceList } from "../../components/DeviceList";
import { useBackend } from "../../hooks/useBackend";

const mockActions = {
  startBroadcasting: vi.fn().mockResolvedValue({ success: true }),
  stopBroadcasting: vi.fn().mockResolvedValue({ success: true }),
  setConfig: vi.fn().mockResolvedValue({ success: true }),
  getConfig: vi.fn().mockResolvedValue(undefined),
  refreshDevices: vi.fn().mockResolvedValue(undefined),
  refreshStatus: vi.fn().mockResolvedValue(undefined),
  removeDevice: vi.fn().mockResolvedValue({ success: true }),
};

describe("DeviceList", () => {
  beforeEach(() => {
    Object.values(mockActions).forEach((fn) => fn.mockClear());
    vi.mocked(useBackend).mockReturnValue({
      status: { state: "idle", running: false, connected_device: null, input_active: false },
      devices: [],
      config: null,
      isLoading: false,
      actions: mockActions,
    });
  });

  it("shows 'No paired devices' when empty", () => {
    render(<DeviceList />);
    expect(screen.getByText(/No paired devices/)).toBeDefined();
  });

  it("renders devices with names", () => {
    vi.mocked(useBackend).mockReturnValue({
      status: { state: "idle", running: false, connected_device: null, input_active: false },
      devices: [
        { address: "AA:BB:CC:DD:EE:FF", name: "PS5 Controller" },
        { address: "11:22:33:44:55:66", name: "Xbox Pad" },
      ],
      config: null,
      isLoading: false,
      actions: mockActions,
    });

    render(<DeviceList />);
    const fields = screen.getAllByTestId("Field");
    const labels = fields.map((f) => f.getAttribute("label"));
    expect(labels).toContain("PS5 Controller");
    expect(labels).toContain("Xbox Pad");
  });

  it("remove button calls removeDevice and refreshDevices", async () => {
    vi.mocked(useBackend).mockReturnValue({
      status: { state: "idle", running: false, connected_device: null, input_active: false },
      devices: [{ address: "AA:BB:CC:DD:EE:FF", name: "Test Device" }],
      config: null,
      isLoading: false,
      actions: mockActions,
    });

    render(<DeviceList />);

    await userEvent.click(screen.getByText("Remove"));

    await waitFor(() => {
      expect(mockActions.removeDevice).toHaveBeenCalledWith("AA:BB:CC:DD:EE:FF");
      expect(mockActions.refreshDevices).toHaveBeenCalled();
    });
  });

  it("refresh button calls refreshDevices", async () => {
    render(<DeviceList />);

    await userEvent.click(screen.getByText("Refresh"));

    expect(mockActions.refreshDevices).toHaveBeenCalled();
  });
});
