// Render the generated local artifact in an isolated, headless browser.
// node scripts/capture_cp22_gallery.cjs <playwright-module-path> <chrome-executable>
// Uses existing installations; never downloads a browser or opens a user profile.
const path = require('node:path');
const fs = require('node:fs');
const { pathToFileURL } = require('node:url');
if (!process.argv[2] || !process.argv[3]) {
  console.error('Provide the installed Playwright module path and Chrome executable.');
  process.exit(2);
}
const { chromium } = require(process.argv[2]);
const root = path.resolve(__dirname, '..', 'docs', 'cp22-gallery');
(async () => {
  const browser = await chromium.launch({ executablePath: process.argv[3], headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1200 }, deviceScaleFactor: 1 });
    await page.goto(pathToFileURL(path.join(root, 'index.html')).href);
    await page.locator('article').first().waitFor();
    const names = await page.locator('article').evaluateAll(nodes => nodes.map(node => node.id));
    if (names.length !== 31 || names.some(name => !/^(caption|image)-[a-z-]+$/.test(name))) {
      throw new Error('Expected the 20 captions and 11 image options from the gallery generator.');
    }
    const output = path.join(root, 'screenshots');
    fs.mkdirSync(output, { recursive: true });
    for (const name of names) {
      await page.locator('#' + name).screenshot({ path: path.join(output, name + '.png') });
    }
    await page.screenshot({ path: path.join(output, 'gallery-overview.png') });
    console.log('Captured 31 style cards plus overview.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
