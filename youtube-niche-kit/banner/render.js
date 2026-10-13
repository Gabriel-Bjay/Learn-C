// Renders banner.html to a 2560x1440 PNG (and a preview with YouTube's safe-area guides).
// Usage: node render.js
const path = require("path");
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 2560, height: 1440 } });
  await page.goto("file://" + path.join(__dirname, "banner.html"));
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: path.join(__dirname, "work-rewired-banner.png") });
  await page.evaluate(() => document.body.classList.add("guides"));
  await page.screenshot({ path: path.join(__dirname, "preview-with-safe-areas.png") });
  await browser.close();
  console.log("Saved work-rewired-banner.png and preview-with-safe-areas.png");
})();
