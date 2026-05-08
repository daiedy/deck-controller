import { renderHook, act, waitFor } from "@testing-library/react";
import { callable } from "@decky/api";
import { useBackend } from "../../hooks/useBackend";

// Extract RPC mocks created by module-level callable() calls in useBackend
const rpc: Record<string, ReturnType<typeof vi.fn>> = {};
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(callable as any).mock.calls.forEach((call: string[], i: number) => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  rpc[call[0]] = (callable as any).mock.results[i].value;
});

const defaultStatus = {
  success: true,
  state: "idle" as const,
  running: false,
  connected_device: null,
  input_active: false,
};

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

describe("useBackend", () => {
  beforeEach(() => {
    Object.values(rpc).forEach((fn) => fn.mockReset());
    rpc.get_status.mockResolvedValue(defaultStatus);
    rpc.get_devices.mockResolvedValue([]);
    rpc.get_config.mockResolvedValue({ success: true, config: defaultConfig });
    rpc.start_broadcasting.mockResolvedValue({ success: true, state: "broadcasting" });
    rpc.stop_broadcasting.mockResolvedValue({ success: true, state: "idle" });
    rpc.set_config.mockResolvedValue({ success: true, config: defaultConfig });
    rpc.remove_device.mockResolvedValue({ success: true });
  });

  it("calls getStatus, getDevices, getConfig on initial load", async () => {
    const { result } = renderHook(() => useBackend());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(rpc.get_status).toHaveBeenCalledTimes(1);
    expect(rpc.get_devices).toHaveBeenCalledTimes(1);
    expect(rpc.get_config).toHaveBeenCalledTimes(1);
  });

  it("startBroadcasting calls RPC and refreshes status", async () => {
    const { result } = renderHook(() => useBackend());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await act(async () => {
      await result.current.actions.startBroadcasting();
    });

    expect(rpc.start_broadcasting).toHaveBeenCalledTimes(1);
    expect(rpc.get_status).toHaveBeenCalledTimes(2);
  });

  it("stopBroadcasting calls RPC and refreshes status", async () => {
    const { result } = renderHook(() => useBackend());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await act(async () => {
      await result.current.actions.stopBroadcasting();
    });

    expect(rpc.stop_broadcasting).toHaveBeenCalledTimes(1);
    expect(rpc.get_status).toHaveBeenCalledTimes(2);
  });

  it("setConfig updates config state", async () => {
    const updatedConfig = { ...defaultConfig, controller_name: "New Name" };
    rpc.set_config.mockResolvedValue({ success: true, config: updatedConfig });

    const { result } = renderHook(() => useBackend());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await act(async () => {
      await result.current.actions.setConfig("controller_name", "New Name");
    });

    expect(rpc.set_config).toHaveBeenCalledWith("controller_name", "New Name");
    expect(result.current.config?.controller_name).toBe("New Name");
  });

  it("sets up auto-refresh interval when state is not idle", async () => {
    vi.useFakeTimers();

    rpc.get_status.mockResolvedValue({
      ...defaultStatus,
      state: "broadcasting",
      running: true,
    });

    renderHook(() => useBackend());

    // Flush initial load
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });

    const callsAfterInit = rpc.get_status.mock.calls.length;
    expect(callsAfterInit).toBeGreaterThanOrEqual(1);

    // Advance past the 2-second interval
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(rpc.get_status.mock.calls.length).toBeGreaterThan(callsAfterInit);

    vi.useRealTimers();
  });
});
