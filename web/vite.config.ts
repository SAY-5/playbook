import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The page reads the sample procedures straight from ../procedures at build time, so the browser
// demo and the Python CLI always run the same files and there is no copy to keep in sync.
const web = fileURLToPath(new URL(".", import.meta.url));
const procedures = fileURLToPath(new URL("../procedures", import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@procedures": procedures } },
  server: { fs: { allow: [web, procedures] } },
  build: { target: "es2022", sourcemap: false },
});
