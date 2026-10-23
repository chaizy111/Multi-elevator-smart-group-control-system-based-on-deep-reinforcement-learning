import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { existsSync } from "node:fs";
const root = resolve(fileURLToPath(new URL(".", import.meta.url)), "..");
const python =
  process.env.ELEVATOR_PYTHON ??
  (existsSync(resolve(root, ".venv/bin/python"))
    ? resolve(root, ".venv/bin/python")
    : "python");
export default defineConfig({
  testDir: "tests/e2e",
  testMatch: "*.spec.ts",
  workers: 1,
  timeout: 45000,
  use: {
    baseURL: "http://127.0.0.1:8765",
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  reporter: [["list"], ["json", { outputFile: "../reports/playwright.json" }]],
  outputDir: "test-results",
  webServer: {
    command: `"${python}" -m elevator_control.cli serve --host 127.0.0.1 --port 8765`,
    cwd: root,
    url: "http://127.0.0.1:8765/api/v1/health",
    reuseExistingServer: false,
    env: {
      PYTHONPATH: `${root}/src`,
      PYTHONDONTWRITEBYTECODE: "1",
      MPLCONFIGDIR: `${root}/.cache/matplotlib`,
      XDG_CACHE_HOME: `${root}/.cache`,
      TMPDIR: `${root}/.cache/tmp`,
    },
  },
});
