import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: [],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
      "@decky/api": path.resolve(__dirname, "src/__mocks__/decky-api.ts"),
      "@decky/ui": path.resolve(__dirname, "src/__mocks__/decky-ui.ts"),
    },
  },
});
