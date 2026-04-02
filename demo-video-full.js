const { chromium } = require('playwright');

const BASE = 'https://orbit-app-production-fd37.up.railway.app';
const VIDEO_DIR = 'demo-screenshots/video';
const EMAIL = 'jordan@example.com';
const PASS = 'orbit2024demo';

(async () => {
  console.log('Setting up demo data via API...');

  // Login
  const loginRes = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASS }),
  });
  const loginData = await loginRes.json();
  const token = loginData.access_token;
  if (!token) { console.error('Login failed'); return; }

  const headers = { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' };

  // Start quest chains
  for (const chain of ['reconnection_saga', 'party_animal', 'the_marathon', 'shadow_hunter', 'gate_crawler']) {
    await fetch(`${BASE}/quest-chains/${chain}/start`, { method: 'POST', headers }).catch(() => {});
  }

  // Start a circle if none exist
  const circlesRes = await fetch(`${BASE}/circles`, { headers });
  const circles = await circlesRes.json();
  if (!circles.length || circles.length === 0) {
    await fetch(`${BASE}/circles`, {
      method: 'POST', headers,
      body: JSON.stringify({ name: 'Close Friends', description: 'My inner circle' }),
    }).catch(() => {});
  }

  // Get job advancement info
  const jobRes = await fetch(`${BASE}/gamification/job-advancement`, { headers });
  const jobData = await jobRes.json();
  console.log('Job tier:', jobData.current_tier, '| Can advance:', jobData.can_advance);

  // Get enhanced dashboard
  const enhRes = await fetch(`${BASE}/gamification/enhanced-dashboard`, { headers });
  const enhData = await enhRes.json();
  console.log('Damage preview:', enhData.damage_preview);
  console.log('Active buffs:', enhData.active_buffs?.length || 0);

  await new Promise(r => setTimeout(r, 2000)); // brief pause

  // Now record the video
  console.log('\nLaunching browser with video recording...');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    recordVideo: { dir: VIDEO_DIR, size: { width: 1440, height: 900 } },
  });
  const page = await context.newPage();

  await page.goto(BASE);
  await page.evaluate(({ t, u }) => {
    localStorage.setItem('orbit_token', t);
    localStorage.setItem('orbit_user', JSON.stringify(u));
    localStorage.setItem('orbit_onboarded', '1');
  }, { t: token, u: loginData.user });

  await page.goto(BASE);
  await page.waitForTimeout(7000);

  // Walkthrough
  console.log('Recording walkthrough...');
  await page.waitForTimeout(2500); // Dashboard overview

  // Smooth scroll through entire page
  const totalHeight = await page.evaluate(() => document.body.scrollHeight);
  const step = 300;
  for (let y = 0; y < totalHeight; y += step) {
    await page.evaluate((s) => window.scrollTo({ top: s, behavior: 'smooth' }), y);
    await page.waitForTimeout(800);
  }

  // Back to top
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
  await page.waitForTimeout(2000);

  // Navigate to orbit view
  await page.evaluate(() => { if (typeof navigateTo === 'function') navigateTo('orbit'); });
  await page.waitForTimeout(3000);

  // Navigate to contacts
  await page.evaluate(() => { if (typeof navigateTo === 'function') navigateTo('contacts'); });
  await page.waitForTimeout(2000);

  // Back to dashboard
  await page.evaluate(() => { if (typeof navigateTo === 'function') navigateTo('dashboard'); });
  await page.waitForTimeout(2500);

  // Mobile view
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(2000);

  // Scroll through mobile
  const mobileHeight = await page.evaluate(() => document.body.scrollHeight);
  for (let y = 0; y < mobileHeight; y += 300) {
    await page.evaluate((s) => window.scrollTo({ top: s, behavior: 'smooth' }), y);
    await page.waitForTimeout(600);
  }

  await page.waitForTimeout(1500);

  // Finalize
  console.log('\nFinalizing video...');
  const videoPath = await page.video().path();
  await context.close();
  await browser.close();

  console.log(`Video saved to: ${videoPath}`);
  console.log('Done!');
})();
