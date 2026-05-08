vi.mock("../../hooks/useBackend", () => ({
  useBackend: vi.fn(),
}));

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MainView } from "../../components/MainView";
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

describe("MainView", () => {
  beforeEach(() => {
    Object.values(mockActions).forEach((fn) => fn.mockClear());
    vi.mocked(useBackend).mockReturnValue({
      status: {
        state: "idle",
        running: false,
        connected_device: null,
        input_active: false,
      },
      devices: [],
      config: null,
      isLoading: false,
      actions: mockActions,
    });
  });

  it("renders idle state with 'Idle' text", () => {
    render(<MainView />);
    expect(screen.getByText("Idle")).toBeDefined();
  });

  it("renders connected state with device info", () => {
    vi.mocked(useBackend).mockReturnValue({
      status: {
        state: "connected",
        running: true,
        connected_device: { address: "AA:BB:CC:DD:EE:FF", name: "Test Device" },
        input_active: true,
      },
      devices: [],
      config: null,
      isLoading: false,
      actions: mockActions,
    });

    render(<MainView />);
    expect(screen.getByText("Connected")).toBeDefined();
    expect(screen.getByText("Test Device")).toBeDefined();
  });

  it("button says 'Start Broadcasting' when idle", () => {
    render(<MainView />);
    expect(screen.getByText("Start Broadcasting")).toBeDefined();
  });

  it("button says 'Stop Broadcasting' when active", () => {
    vi.mocked(useBackend).mockReturnValue({
      status: {
        state: "broadcasting",
        running: true,
        connected_device: null,
        input_active: false,
      },
      devices: [],
      config: null,
      isLoading: false,
      actions: mockActions,
    });

    render(<MainView />);
    expect(screen.getByText("Stop Broadcasting")).toBeDefined();
  });

  it("button click calls correct action", async () => {
    render(<MainView />);

    await userEvent.click(screen.getByText("Start Broadcasting"));

    expect(mockActions.startBroadcasting).toHaveBeenCalledTimes(1);
  });
});
