import fs from "node:fs/promises";
import { chromium } from "playwright-core";

const [, , inputPath, outputPath, chromePath] = process.argv;

if (!inputPath || !outputPath) {
  console.error("Usage: node render-pdf.mjs <input.html> <output.pdf> [chromePath]");
  process.exit(1);
}

const browser = await chromium.launch({
  executablePath: chromePath || process.env.GOOGLE_CHROME_BIN || "/usr/sbin/google-chrome-stable",
  headless: true,
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});

try {
  const page = await browser.newPage();
  const html = await fs.readFile(inputPath, "utf-8");
  await page.setContent(html, { waitUntil: "networkidle" });
  await page.pdf({
    path: outputPath,
    format: "A4",
    printBackground: true,
    margin: { top: "18mm", right: "12mm", bottom: "18mm", left: "12mm" },
  });
} finally {
  await browser.close();
}
