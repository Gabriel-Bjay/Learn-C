// Renders every chart*.html in this folder to ../charts/<name>.png at 1920x1080.
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

(async () => {
  const outDir = path.join(__dirname, "..", "charts");
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  for (const file of fs.readdirSync(__dirname).filter(f => f.startsWith("chart") && f.endsWith(".html")).sort()) {
    await page.goto("file://" + path.join(__dirname, file));
    await page.evaluate(() => document.fonts.ready);
    const out = path.join(outDir, file.replace(".html", ".png"));
    await page.screenshot({ path: out });
    console.log("saved", path.relative(process.cwd(), out));
  }
  await browser.close();
})();
