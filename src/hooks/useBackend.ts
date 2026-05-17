import { useEffect, useState, useCallback, useRef } from "react";
import { callable } from "@decky/api";

interface ConnectedDevice {
  address: string;
  name: string;
}

interface Status {
  state: "idle" | "broadcasting" | "connected";
  running: boolean;
  connected_device: ConnectedDevice | null;
  input_active: boolean;
}

interface Device {
  address: string;
  name: string;
}

interface ConfigData {
  controller_name: string;
  auto_connect: boolean;
  polling_rate_hz: number;
  deadzone: number;
  enable_gyro: boolean;
  enable_trackpads: boolean;
  bt_device_class: string;
  max_connections: number;
}

const startBroadcasting = callable<[], { success: boolean; state?: string; error?: string }>(
  "start_broadcasting",
);
const stopBroadcasting = callable<[], { success: boolean; state?: string; error?: string }>(
  "stop_broadcasting",
);
const getStatus = callable<[], Status & { success: boolean }>("get_status");
const getDevices = callable<[], Device[]>("get_devices");
const setConfigValue = callable<[string, unknown], { success: boolean; config?: ConfigData }>(
  "set_config",
);
const getConfigValues = callable<[], { success: boolean; config?: ConfigData }>("get_config");
const removeDevice = callable<[string], { success: boolean; error?: string }>("remove_device");

export function useBackend() {
  const [status, setStatus] = useState<Status>({
    state: "idle",
    running: false,
    connected_device: null,
    input_active: false,
  });
  const [devices, setDevices] = useState<Device[]>([]);
  const [config, setConfig] = useState<ConfigData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      const result = await getStatus();
      if (result.success) {
        setStatus({
          state: result.state,
          running: result.running,
          connected_device: result.connected_device,
          input_active: result.input_active,
        });
      }
    } catch (e) {
      console.error("Failed to get status:", e);
    }
  }, []);

  const refreshDevices = useCallback(async () => {
    try {
      const result = await getDevices();
      setDevices(result);
    } catch (e) {
      console.error("Failed to get devices:", e);
    }
  }, []);

  const refreshConfig = useCallback(async () => {
    try {
      const result = await getConfigValues();
      if (result.success && result.config) {
        setConfig(result.config);
      }
    } catch (e) {
      console.error("Failed to get config:", e);
    }
  }, []);

  const handleStartBroadcasting = useCallback(async () => {
    setIsLoading(true);
    setActionInProgress("Starting...");
    setLastError(null);
    try {
      const result = await startBroadcasting();
      if (result.success) {
        await refreshStatus();
      } else {
        setLastError(result.error || "Failed to start broadcasting");
      }
      return result;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setLastError(msg);
      return { success: false, error: msg };
    } finally {
      setIsLoading(false);
      setActionInProgress(null);
    }
  }, [refreshStatus]);

  const handleStopBroadcasting = useCallback(async () => {
    setIsLoading(true);
    setActionInProgress("Stopping...");
    setLastError(null);
    try {
      const result = await stopBroadcasting();
      if (result.success) {
        await refreshStatus();
      } else {
        setLastError(result.error || "Failed to stop broadcasting");
      }
      return result;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setLastError(msg);
      return { success: false, error: msg };
    } finally {
      setIsLoading(false);
      setActionInProgress(null);
    }
  }, [refreshStatus]);

  const handleSetConfig = useCallback(async (key: string, value: unknown) => {
    try {
      const result = await setConfigValue(key, value);
      if (result.success && result.config) {
        setConfig(result.config);
      }
      return result;
    } catch (e) {
      console.error("Failed to set config:", e);
      return { success: false, error: String(e) };
    }
  }, []);

  // Initial load
  useEffect(() => {
    const init = async () => {
      setIsLoading(true);
      await Promise.all([refreshStatus(), refreshDevices(), refreshConfig()]);
      setIsLoading(false);
    };
    init();
  }, [refreshStatus, refreshDevices, refreshConfig]);

  // Auto-refresh status every 2 seconds when active
  useEffect(() => {
    if (status.state !== "idle") {
      intervalRef.current = setInterval(refreshStatus, 2000);
    } else if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [status.state, refreshStatus]);

  return {
    status,
    devices,
    config,
    isLoading,
    actionInProgress,
    lastError,
    clearError: () => setLastError(null),
    actions: {
      startBroadcasting: handleStartBroadcasting,
      stopBroadcasting: handleStopBroadcasting,
      setConfig: handleSetConfig,
      getConfig: refreshConfig,
      refreshDevices,
      refreshStatus,
      removeDevice: async (address: string) => {
        try {
          return await removeDevice(address);
        } catch (e) {
          console.error("Failed to remove device:", e);
          return { success: false, error: String(e) };
        }
      },
    },
  };
}
