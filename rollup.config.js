import commonjs from "@rollup/plugin-commonjs";
import json from "@rollup/plugin-json";
import { nodeResolve } from "@rollup/plugin-node-resolve";
import replace from "@rollup/plugin-replace";
import typescript from "@rollup/plugin-typescript";
import importCss from "rollup-plugin-import-css";

export default {
  input: "src/index.tsx",
  output: {
    file: "dist/index.js",
    format: "esm",
    sourcemap: true,
  },
  external: ["react", "react-dom", "@decky/ui", "@decky/api"],
  plugins: [
    typescript(),
    commonjs(),
    nodeResolve(),
    replace({
      preventAssignment: true,
      "process.env.NODE_ENV": JSON.stringify("production"),
    }),
    json(),
    importCss(),
  ],
};
