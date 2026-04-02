const { chromium } = require('playwright');

const BASE = 'https://orbit-app-production-fd37.up.railway.app';
const VIDEO_DIR = 'demo-screenshots/video';
const EMAIL = 'jordan@example.com';
const PASS = 'orbit2024demo';

(async () => {
  console.log('Launching browser with video recording...');
  const browser = await chromium.launch({ headless: true });

  // Create context WITH video recording
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    recordVideo: {
      dir: VIDEO_DIR,
      size: { width: 1440, height: 900 },
    },
  });

  const page = await context.newPage();

  // Login via API
  console.log('Logging in...');
  const loginRes = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASS }),
  });
  const loginData = await loginRes.json();
  if (!loginData.access_token) {
    console.error('Login failed:', loginData);
    await browser.close();
    return;
  }

  // Set auth in localStorage
  await page.goto(BASE);
  await page.evaluate(({ t, u }) => {
    localStorage.setItem('orbit_token', t);
    localStorage.setItem('orbit_user', JSON.stringify(u));
    localStorage.setItem('orbit_onboarded', '1');
  }, { t: loginData.access_token, u: loginData.user });

  // Load dashboard
  console.log('Loading dashboard...');
  await page.goto(BASE);
  await page.waitForTimeout(6000);

  // ── DEMO WALKTHROUGH ──

  // 1. Dashboard overview - pause to show
  console.log('1. Dashboard overview');
  await page.waitForTimeout(2000);

  // 2. Scroll to XP / Job Advancement section
  console.log('2. XP & Job Advancement');
  await scrollToSection(page, '#xpSection');
  await page.waitForTimeout(2500);

  // 3. Hunter Stats + Damage Preview
  console.log('3. Hunter Stats & Damage Preview');
  await scrollToSection(page, '#hunterStatsSection');
  await page.waitForTimeout(2500);

  // 4. Active Gates
  console.log('4. Active Gates');
  await scrollToSection(page, '#gatesSection');
  await page.waitForTimeout(2000);

  // 5. Daily Quests
  console.log('5. Daily Quests');
  await scrollToSection(page, '#questsSection');
  await page.waitForTimeout(2000);

  // 6. Quest Chains
  console.log('6. Quest Chains');
  await scrollToSection(page, '#questChainsSection');
  await page.waitForTimeout(2500);

  // 7. Parties
  console.log('7. Parties');
  await scrollToSection(page, '#partiesSection');
  await page.waitForTimeout(1500);

  // 8. Achievements
  console.log('8. Achievements');
  await scrollToSection(page, '#achievementsSection');
  await page.waitForTimeout(2000);

  // 9. Skill Tree (with prerequisites!)
  console.log('9. Skill Tree with Prerequisites');
  await scrollToSection(page, '#skillTreeSection');
  await page.waitForTimeout(3000);

  // 10. Circles / Guilds
  console.log('10. Circles / Guilds');
  await scrollToSection(page, '#circlesSection');
  await page.waitForTimeout(2000);

  // 11. Boss Raids
  console.log('11. Boss Raids');
  await scrollToSection(page, '#bossRaidsSection');
  await page.waitForTimeout(2000);

  // 12. Leaderboard
  console.log('12. Leaderboard');
  await scrollToSection(page, '#leaderboardSection');
  await page.waitForTimeout(2000);

  // 13. Scroll back to top for overview
  console.log('13. Back to top');
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
  await page.waitForTimeout(2000);

  // 14. Navigate to Orbit view
  console.log('14. Orbit View');
  await page.evaluate(() => { if (typeof navigateTo === 'function') navigateTo('orbit'); });
  await page.waitForTimeout(2000);

  // 15. Contacts page
  console.log('15. Contacts');
  await page.evaluate(() => { if (typeof navigateTo === 'function') navigateTo('contacts'); });
  await page.waitForTimeout(2000);

  // 16. Back to dashboard
  console.log('16. Back to Dashboard');
  await page.evaluate(() => { if (typeof navigateTo === 'function') navigateTo('dashboard'); });
  await page.waitForTimeout(2000);

  // 17. Mobile view
  console.log('17. Mobile view');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(2500);

  // 18. Scroll through mobile
  await page.evaluate(() => window.scrollBy({ top: 400, behavior: 'smooth' }));
  await page.waitForTimeout(1500);
  await page.evaluate(() => window.scrollBy({ top: 400, behavior: 'smooth' }));
  await page.waitForTimeout(1500);
  await page.evaluate(() => window.scrollBy({ top: 400, behavior: 'smooth' }));
  await page.waitForTimeout(1500);

  // 19. Back to desktop
  console.log('18. Back to desktop');
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.evaluate(() => { if (typeof navigateTo === 'function') navigateTo('dashboard'); });
  await page.waitForTimeout(3000);

  // Done - close context to finalize video
  console.log('\nFinalizing video...');
  const videoPath = await page.video().path();
  await context.close();
  await browser.close();

  console.log(`\nVideo saved to: ${videoPath}`);
  console.log('Done!');
})();

async function scrollToSection(page, selector) {
  const exists = await page.$(selector);
  if (!exists) {
    console.log(`  (section ${selector} not found, skipping)`);
    return;
  }
  const visible = await exists.evaluate(e => {
    const s = getComputedStyle(e);
    return s.display !== 'none' && e.offsetParent !== null;
  });
  if (!visible) {
    console.log(`  (section ${selector} hidden, skipping)`);
    return;
  }
  await exists.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(500);
}
