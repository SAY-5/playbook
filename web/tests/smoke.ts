/* Browser smoke test for the built page. Serves dist/ with `vite preview`, loads it in Chrome
   through playwright-core, and fails on a console error, a request to another origin, horizontal
   overflow at either width, or a self-check that does not finish green. Writes the two screenshots
   under docs/ that the READMEs link to.

   npm run smoke
*/
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, type Browser, type Page } from "playwright-core";

const here = dirname(fileURLToPath(import.meta.url));
const web = join(here, "..");
const docs = join(web, "docs");
const PORT = Number(process.env.SMOKE_PORT ?? 4173);
const BASE = `http://127.0.0.1:${PORT}/`;
const WIDE = { width: 1440, height: 900 };
const NARROW = { width: 390, height: 844 };

const failures: string[] = [];
const fail = (message: string) => failures.push(message);

function startPreview() {
  const child = spawn("npx", ["vite", "preview", "--host", "127.0.0.1", "--port", String(PORT), "--strictPort"], {
    cwd: web,
    stdio: "ignore",
  });
  return child;
}

async function waitForServer(): Promise<void> {
  for (let attempt = 0; attempt < 120; attempt++) {
    try {
      const response = await fetch(BASE);
      if (response.ok) return;
    } catch {
      // not listening yet
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`vite preview never answered on ${BASE}`);
}

async function overflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

/* Scroll the whole page so every section reveal fires, then return to the top. A screenshot taken
   before that shows empty sections. */
async function revealEverything(page: Page): Promise<void> {
  await page.evaluate(async () => {
    // The page scrolls smoothly, which would turn each jump below into an animation the next jump
    // interrupts, so nothing would ever come into view.
    const root = document.documentElement;
    const behavior = root.style.scrollBehavior;
    root.style.scrollBehavior = "auto";
    const step = window.innerHeight * 0.8;
    for (let y = 0; y < root.scrollHeight; y += step) {
      window.scrollTo(0, y);
      await new Promise((resolve) => setTimeout(resolve, 80));
    }
    window.scrollTo(0, 0);
    await new Promise((resolve) => setTimeout(resolve, 80));
    root.style.scrollBehavior = behavior;
  });
  await page.waitForFunction(() => document.querySelectorAll(".reveal:not(.reveal--in)").length === 0, null, {
    timeout: 30_000,
  });
}

/* The hero counters animate on mount, so wait until the figures stop moving before capturing
   them: a screenshot of a counter in flight shows a number the page never reports. */
async function settleCounters(page: Page): Promise<string> {
  let previous = "";
  for (let attempt = 0; attempt < 40; attempt++) {
    const current = (await page.locator(".hero__stats").innerText()).replace(/\s+/g, " ").trim();
    if (current && current === previous) return current;
    previous = current;
    await page.waitForTimeout(150);
  }
  fail("hero counters never settled");
  return previous;
}

async function run(browser: Browser): Promise<void> {
  const context = await browser.newContext({ viewport: WIDE, deviceScaleFactor: 1 });
  const page = await context.newPage();
  page.on("console", (message) => {
    if (message.type() === "error") fail(`console error: ${message.text()}`);
  });
  page.on("pageerror", (error) => fail(`page error: ${error.message}`));
  page.on("request", (request) => {
    if (!request.url().startsWith(BASE) && !request.url().startsWith("data:")) fail(`off-origin request: ${request.url()}`);
  });

  await page.goto(BASE, { waitUntil: "networkidle" });
  const title = await page.title();
  if (!title.startsWith("Playbook")) fail(`unexpected title: ${title}`);
  const wide = await overflow(page);
  if (wide > 0) fail(`horizontal overflow at ${WIDE.width}px: ${wide}px`);
  console.log(`hero stats at ${WIDE.width}px: ${await settleCounters(page)}`);

  await page.getByRole("button", { name: "Run", exact: true }).click();
  await page.getByRole("button", { name: "Skip" }).click();
  const verdict = page.locator(".run__verdict");
  await verdict.waitFor({ state: "visible", timeout: 60_000 });
  const text = (await verdict.textContent())?.trim() ?? "";
  const match = /^(\d+)\/(\d+) assertions passed$/.exec(text);
  if (!match) fail(`self-check verdict unreadable: ${text}`);
  else if (match[1] !== match[2]) fail(`self-check failed: ${text}`);
  else console.log(`self-check in the page: ${text}`);

  mkdirSync(docs, { recursive: true });
  await revealEverything(page);
  await page.screenshot({ path: join(docs, "desktop.png"), fullPage: true });

  await page.setViewportSize(NARROW);
  await page.goto(BASE, { waitUntil: "networkidle" });
  const narrow = await overflow(page);
  if (narrow > 0) fail(`horizontal overflow at ${NARROW.width}px: ${narrow}px`);
  await settleCounters(page);
  await revealEverything(page);
  await page.screenshot({ path: join(docs, "mobile.png"), fullPage: true });

  await context.close();
}

async function main(): Promise<void> {
  const preview = startPreview();
  let browser: Browser | null = null;
  try {
    await waitForServer();
    browser = await chromium.launch({ channel: "chrome" });
    await run(browser);
  } finally {
    await browser?.close();
    preview.kill();
  }
  if (failures.length) {
    for (const message of failures) console.error(`FAIL ${message}`);
    process.exit(1);
  }
  console.log(`smoke passed at ${WIDE.width}px and ${NARROW.width}px; screenshots written to web/docs`);
}

await main();
