import { readFile } from "node:fs/promises";
import { fileURLToPath, URL } from "node:url";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { parse } from "yaml";

// The page reads the sample procedures straight from ../procedures at build time, so the browser
// demo and the Python CLI always run the same files and there is no copy to keep in sync.
const web = fileURLToPath(new URL(".", import.meta.url));
const procedures = fileURLToPath(new URL("../procedures", import.meta.url));

// The rubrics and scenario sets are parsed here instead of in the browser, so the page ships JSON
// and `yaml` stays a development dependency. `?raw` imports are left alone.
function yamlAsJson(): Plugin {
  return {
    name: "playbook-yaml",
    enforce: "pre",
    async load(id) {
      const [file, query] = id.split("?");
      if (!file.endsWith(".yaml") || query === "raw") return null;
      return `export default ${JSON.stringify(parse(await readFile(file, "utf8")))};`;
    },
  };
}

export default defineConfig({
  plugins: [react(), yamlAsJson()],
  resolve: { alias: { "@procedures": procedures } },
  server: { fs: { allow: [web, procedures] } },
  build: { target: "es2022", sourcemap: false },
});
