import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { callable } from "@decky/api";
import { ProfilePicker } from "../../components/ProfilePicker";

// Extract RPC mocks created by ProfilePicker's module-level callable() calls
const rpc: Record<string, ReturnType<typeof vi.fn>> = {};
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(callable as any).mock.calls.forEach((call: string[], i: number) => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  rpc[call[0]] = (callable as any).mock.results[i].value;
});

const mockProfiles = [
  {
    name: "Default",
    active_reports: ["gamepad"],
    trackpad_mode: "mouse",
    mouse_sensitivity: 5,
    scroll_sensitivity: 3,
    gyro_sensitivity: 5,
  },
  {
    name: "FPS",
    active_reports: ["gamepad", "mouse"],
    trackpad_mode: "mouse",
    mouse_sensitivity: 8,
    scroll_sensitivity: 3,
    gyro_sensitivity: 7,
  },
];

describe("ProfilePicker", () => {
  beforeEach(() => {
    Object.values(rpc).forEach((fn) => fn.mockReset());
    rpc.get_profiles.mockResolvedValue({
      success: true,
      profiles: mockProfiles,
      active_index: 0,
    });
    rpc.switch_profile.mockResolvedValue({
      success: true,
      profile: mockProfiles[1],
    });
  });

  it("shows loading state", () => {
    rpc.get_profiles.mockReturnValue(new Promise(() => {}));
    render(<ProfilePicker />);
    expect(screen.getByText("Loading profiles...")).toBeDefined();
  });

  it("renders profile buttons", async () => {
    render(<ProfilePicker />);

    await waitFor(() => {
      expect(screen.getByText("Default ✓")).toBeDefined();
    });
    expect(screen.getByText("FPS")).toBeDefined();
  });

  it("active profile button is disabled", async () => {
    render(<ProfilePicker />);

    await waitFor(() => {
      expect(screen.getByText("Default ✓")).toBeDefined();
    });

    const activeBtn = screen.getByText("Default ✓");
    expect(activeBtn.hasAttribute("disabled")).toBe(true);
  });

  it("calls switchProfile when switching", async () => {
    render(<ProfilePicker />);

    await waitFor(() => {
      expect(screen.getByText("FPS")).toBeDefined();
    });

    await userEvent.click(screen.getByText("FPS"));

    await waitFor(() => {
      expect(rpc.switch_profile).toHaveBeenCalledWith(1);
    });
  });
});
