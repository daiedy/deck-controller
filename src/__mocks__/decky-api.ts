import { vi } from "vitest";

export const callable = vi.fn((_name: string) => vi.fn(async (..._args: unknown[]) => ({})));

export const definePlugin = vi.fn((fn: () => unknown) => fn);

export const staticClasses = {
  Title: "title-class",
  GamepadButton: "gamepad-button-class",
};

export const routerHook = {
  addRoute: vi.fn(),
  removeRoute: vi.fn(),
};
