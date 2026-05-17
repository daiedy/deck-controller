import { callable, definePlugin } from "@decky/api";
import { Component, ErrorInfo, ReactNode } from "react";
import { FaGamepad } from "react-icons/fa";
import { MainView } from "./components/MainView";

const logFrontendError = callable<
  [error: string, stack?: string, component?: string, url?: string],
  { success: boolean }
>("log_frontend_error");

let _handlersInstalled = false;

function reportError(error: string, stack?: string, component?: string) {
  logFrontendError(error, stack ?? "", component ?? "", globalThis.location?.href ?? "").catch(
    () => {
      console.error("[DeckController] Failed to report error:", error);
    },
  );
}

function installGlobalErrorHandlers() {
  if (_handlersInstalled) return;
  _handlersInstalled = true;

  globalThis.addEventListener("error", (event: ErrorEvent) => {
    reportError(
      event.message || String(event.error),
      event.error?.stack ?? "",
      "globalThis.onerror",
    );
  });

  globalThis.addEventListener("unhandledrejection", (event: PromiseRejectionEvent) => {
    const reason = event.reason;
    reportError(reason?.message ?? String(reason), reason?.stack ?? "", "unhandledrejection");
  });
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: string | null;
}

class PluginErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error: error.message };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    reportError(error.message, error.stack ?? "", info.componentStack ?? "");
  }

  render() {
    if (this.state.hasError) {
      return <div style={{ padding: "1em" }}>Plugin error: {this.state.error}</div>;
    }
    return this.props.children;
  }
}

export default definePlugin(() => {
  installGlobalErrorHandlers();

  return {
    name: "Deck Controller",
    titleView: <span>Deck Controller</span>,
    content: (
      <PluginErrorBoundary>
        <MainView />
      </PluginErrorBoundary>
    ),
    icon: <FaGamepad />,
    onDismount() {
      _handlersInstalled = false;
    },
  };
});
