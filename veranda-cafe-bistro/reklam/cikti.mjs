// reklam.html'i iki formatta PNG/JPG olarak dışa aktarır.
// Kullanım: node cikti.mjs   (reklam/ klasöründe, veranda-render.jpg hazır olmalı)
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const dir = path.dirname(fileURLToPath(import.meta.url));

const formats = [
  { name: "yatay", width: 1920, height: 1080 },
  { name: "dikey", width: 1080, height: 1350 },
];

const browser = await chromium.launch();
for (const f of formats) {
  const page = await browser.newPage({ viewport: { width: f.width, height: f.height } });
  await page.goto(`file://${dir}/reklam.html?format=${f.name}`);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() => document.getElementById("render").complete);
  await page.waitForTimeout(300);
  const out = path.join(dir, `veranda-reklam-${f.name}.jpg`);
  await page.locator("#ad").screenshot({ path: out, type: "jpeg", quality: 92 });
  console.log("YAZILDI", out);
  await page.close();
}
await browser.close();
