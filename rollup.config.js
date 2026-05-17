import deckyPlugin from "@decky/rollup";
import importCss from "rollup-plugin-import-css";

export default deckyPlugin({
  plugins: [importCss()],
});
