import { chromium } from 'playwright';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP_URL = process.env.DEMO_URL || 'https://orbit-app-production-fd37.up.railway.app';

(async () => {
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    recordVideo: { dir: path.join(__dirname, 'recordings'), size: { width: 1440, height: 900 } }
  });
  const page = await context.newPage();

  const scroll = (y) => page.evaluate((sy) => window.scrollTo({ top: sy, behavior: 'smooth' }), y);
  const wait = (ms) => page.waitForTimeout(ms);
  const nav = (pg) => page.evaluate((p) => navigateTo(p), pg);
  const safeClick = async (selector) => {
    const el = page.locator(selector);
    if (await el.isVisible().catch(() => false)) { await el.click(); return true; }
    return false;
  };

  // ─────────────────────────────────────────────────────
  // 1. LANDING PAGE — full scroll through all sections
  // ─────────────────────────────────────────────────────
  console.log('1/25 — Landing Page');
  await page.goto(APP_URL);
  await wait(2500);
  for (const y of [400, 800, 1200, 1600, 2000, 2400]) {
    await scroll(y); await wait(1000);
  }
  // Open FAQ items
  const faqItems = page.locator('.faq-item');
  const faqCount = await faqItems.count();
  if (faqCount > 0) {
    await faqItems.first().click(); await wait(800);
    if (faqCount > 1) { await faqItems.nth(1).click(); await wait(800); }
  }
  await scroll(0); await wait(800);

  // ─────────────────────────────────────────────────────
  // 2. LOGIN
  // ─────────────────────────────────────────────────────
  console.log('2/25 — Login');
  await page.click('text=Get Started Free');
  await wait(1000);
  await page.click('a:has-text("Log in")');
  await wait(500);
  await page.fill('#authEmail', 'jordan@example.com');
  await wait(200);
  await page.fill('#authPass', 'orbit2024demo');
  await wait(400);
  await page.click('#authSubmitBtn');
  await wait(5000);

  // Clear overlays
  await page.evaluate(() => {
    localStorage.setItem('orbit_onboarded', '1');
    const ob = document.getElementById('onboardingOverlay'); if (ob) ob.remove();
  });
  await wait(500);

  // Dismiss daily reward if showing
  if (await safeClick('#rewardOverlay.active .btn')) await wait(1000);

  // ─────────────────────────────────────────────────────
  // 3. DASHBOARD — first look at everything
  // ─────────────────────────────────────────────────────
  console.log('3/25 — Dashboard Overview');
  await wait(1500);
  // Slow scroll to show stats, nudges, gamification, contacts
  for (const y of [250, 500, 750, 1000, 1300, 1600]) {
    await scroll(y); await wait(1200);
  }
  await scroll(0); await wait(1000);

  // ─────────────────────────────────────────────────────
  // 4. SEARCH — filter contacts
  // ─────────────────────────────────────────────────────
  console.log('4/25 — Search');
  await page.click('#searchInput');
  await wait(300);
  await page.type('#searchInput', 'family', { delay: 90 });
  await wait(1500);
  await page.fill('#searchInput', '');
  await wait(300);
  await page.type('#searchInput', 'friend', { delay: 90 });
  await wait(1500);
  await page.fill('#searchInput', '');
  await wait(800);

  // ─────────────────────────────────────────────────────
  // 5. ADD PERSON #1
  // ─────────────────────────────────────────────────────
  console.log('5/25 — Add Contact: Yuki Tanaka');
  await page.click('text=Add Person');
  await wait(800);
  await page.fill('#firstName', 'Yuki');
  await wait(150);
  await page.fill('#lastName', 'Tanaka');
  await wait(150);
  await page.selectOption('#relationship', 'Friend');
  await wait(150);
  await page.click('.form-tag[data-val="weekly"]');
  await wait(150);
  await page.fill('#personNotes', 'Met at a hackathon in Tokyo. Loves anime and machine learning.');
  await wait(600);
  await page.click('text=Add to Orbit');
  await wait(3000);

  // ─────────────────────────────────────────────────────
  // 6. ADD PERSON #2
  // ─────────────────────────────────────────────────────
  console.log('6/25 — Add Contact: Marcus Williams');
  await page.click('text=Add Person');
  await wait(800);
  await page.fill('#firstName', 'Marcus');
  await wait(150);
  await page.fill('#lastName', 'Williams');
  await wait(150);
  await page.selectOption('#relationship', 'Work');
  await wait(150);
  await page.click('.form-tag[data-val="biweekly"]');
  await wait(150);
  await page.fill('#personNotes', 'Product lead at partner company. Great strategic thinker.');
  await wait(600);
  await page.click('text=Add to Orbit');
  await wait(3000);

  // ─────────────────────────────────────────────────────
  // 7. LOG INTERACTION — In-person meetup
  // ─────────────────────────────────────────────────────
  console.log('7/25 — Log Interaction: In-Person Meetup');
  await page.evaluate(() => openLogInteraction());
  await wait(1000);
  await page.selectOption('#logContact', { index: 1 });
  await wait(300);
  await page.click('#logTypeTags .form-tag[data-val="in_person"]');
  await wait(200);
  await page.fill('#logDuration', '60');
  await wait(200);
  await page.fill('#logNotes', 'Amazing dinner catch-up. Talked about career goals and travel plans. Really meaningful conversation.');
  await wait(500);
  await page.click('#logSubmitBtn');
  await wait(3000);

  // ─────────────────────────────────────────────────────
  // 8. LOG INTERACTION — Video call
  // ─────────────────────────────────────────────────────
  console.log('8/25 — Log Interaction: Video Call');
  await page.evaluate(() => openLogInteraction());
  await wait(800);
  await page.selectOption('#logContact', { index: 2 });
  await wait(200);
  await page.click('#logTypeTags .form-tag[data-val="video_call"]');
  await wait(200);
  await page.fill('#logDuration', '30');
  await wait(200);
  await page.fill('#logNotes', 'Weekly sync on the joint project. Aligned on roadmap priorities.');
  await wait(400);
  await page.click('#logSubmitBtn');
  await wait(3000);

  // ─────────────────────────────────────────────────────
  // 9. LOG INTERACTION — Quick text
  // ─────────────────────────────────────────────────────
  console.log('9/25 — Log Interaction: Text');
  await page.evaluate(() => openLogInteraction());
  await wait(800);
  await page.selectOption('#logContact', { index: 3 });
  await wait(200);
  await page.click('#logTypeTags .form-tag[data-val="text"]');
  await wait(200);
  await page.fill('#logDuration', '5');
  await wait(200);
  await page.fill('#logNotes', 'Shared a funny meme. Got a laugh back.');
  await wait(400);
  await page.click('#logSubmitBtn');
  await wait(3000);

  // ─────────────────────────────────────────────────────
  // 10. NUDGES — act on one, snooze one
  // ─────────────────────────────────────────────────────
  console.log('10/25 — Nudges');
  await scroll(300);
  await wait(800);
  if (await safeClick('.nudge-btn.primary')) await wait(2500);
  if (await safeClick('.nudge-btn.ghost')) await wait(1500);
  await scroll(0); await wait(800);

  // ─────────────────────────────────────────────────────
  // 11. CREATE A PARTY
  // ─────────────────────────────────────────────────────
  console.log('11/25 — Create Party');
  await scroll(800); await wait(800);
  await page.evaluate(() => openCreateParty());
  await wait(1000);
  await page.click('#partyActivityTags .form-tag[data-val="dinner"]');
  await wait(200);
  await page.fill('#partyTitle', 'Friday Night Sushi Crew');
  await wait(200);
  await page.fill('#partyLocation', 'Nobu Downtown');
  await wait(200);
  await page.fill('#partyDesc', 'Monthly dinner tradition. Great food, better company. Everyone welcome!');
  await wait(400);
  // Invite people
  const invites = page.locator('#partyInviteList input[type="checkbox"]');
  for (let i = 0; i < Math.min(3, await invites.count()); i++) {
    await invites.nth(i).click(); await wait(150);
  }
  await wait(300);
  await page.click('#partySubmitBtn');
  await wait(3000);

  // ─────────────────────────────────────────────────────
  // 12. SEND A CHALLENGE
  // ─────────────────────────────────────────────────────
  console.log('12/25 — Send Challenge');
  await page.evaluate(() => openCreateChallenge());
  await wait(1000);
  const chalContact = page.locator('#challengeContact');
  if (await chalContact.count() > 0) await chalContact.selectOption({ index: 1 });
  await wait(200);
  await page.click('#challengeActivityTags .form-tag[data-val="run"]');
  await wait(200);
  await page.fill('#challengeTitle', '10K Run Challenge');
  await wait(200);
  await page.fill('#challengeDesc', 'Let\'s see who can run 10K faster this week. Loser buys coffee!');
  await wait(400);
  await page.locator('#challengeModal .btn-primary').click();
  await wait(3000);

  // ─────────────────────────────────────────────────────
  // 13. CONTACT DETAIL — open, explore, log from panel
  // ─────────────────────────────────────────────────────
  console.log('13/25 — Contact Detail Panel');
  await scroll(0); await wait(500);
  const dashCards = page.locator('#contactsGrid .contact-card');
  if (await dashCards.first().isVisible().catch(() => false)) {
    await dashCards.first().click();
    await wait(2500);
    // Scroll through detail sections
    for (const y of [150, 300, 450]) {
      await page.evaluate((sy) => {
        const b = document.querySelector('#detailPanel .detail-body');
        if (b) b.scrollTo({ top: sy, behavior: 'smooth' });
      }, y);
      await wait(1200);
    }
    // Log a quick interaction from the detail panel
    await page.evaluate(() => {
      const b = document.querySelector('#detailPanel .detail-body');
      if (b) b.scrollTo({ top: 600, behavior: 'smooth' });
    });
    await wait(1000);
    // Fill quick log via evaluate (button may be outside viewport)
    await page.evaluate(() => {
      const notes = document.getElementById('detailLogNotes');
      if (notes) notes.value = 'Quick check-in call';
    });
    await wait(300);
    await page.evaluate(() => { if (typeof submitDetailLog === 'function') submitDetailLog(); });
    await wait(2500);
    await page.evaluate(() => closeDetail());
    await wait(800);
  }

  // ─────────────────────────────────────────────────────
  // 14. SHADOW EXTRACTION — ARISE!
  // ─────────────────────────────────────────────────────
  console.log('14/25 — Shadow Extraction');
  // Open another contact and try to extract
  if (await dashCards.count() > 1 && await dashCards.nth(1).isVisible().catch(() => false)) {
    await dashCards.nth(1).click();
    await wait(1500);
    await page.evaluate(() => {
      const b = document.querySelector('#detailPanel .detail-body');
      if (b) b.scrollTo({ top: 500, behavior: 'smooth' });
    });
    await wait(1000);
    if (await safeClick('button:has-text("ARISE")')) {
      await wait(4000); // Let the extraction animation play
    }
    await page.evaluate(() => closeDetail());
    await wait(800);
  }

  // ─────────────────────────────────────────────────────
  // 15. GATE / DUNGEON — create and see it
  // ─────────────────────────────────────────────────────
  console.log('15/25 — Open a Gate');
  await page.evaluate(async () => {
    const token = localStorage.getItem('orbit_token');
    if (!token) return;
    await fetch('/gates', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: 'Social Sprint: Reach out to 5 people today',
        description: 'A gate has appeared! Contact 5 people to clear it and earn XP.',
        gate_rank: 'C-Rank', objective_type: 'interactions',
        objective_target: 5, time_limit_hours: 24,
      }),
    });
  });
  await wait(1000);
  await page.evaluate(() => syncData());
  await wait(3000);
  await scroll(600); await wait(2000);
  await scroll(0); await wait(800);

  // ─────────────────────────────────────────────────────
  // 16. BOSS RAID — create + attack
  // ─────────────────────────────────────────────────────
  console.log('16/25 — Boss Raid');
  await page.evaluate(async () => {
    const token = localStorage.getItem('orbit_token');
    if (!token) return;
    await fetch('/boss-raids', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: 'Break the isolation cycle',
        boss_name: 'The Hermit King',
        boss_hp: 60, xp_reward: 250, time_limit_days: 7,
      }),
    });
  });
  await wait(1000);
  await page.evaluate(() => syncData());
  await wait(3000);
  await scroll(1000); await wait(1500);

  // Attack boss 3 times
  for (let i = 0; i < 3; i++) {
    if (await safeClick('.boss-attack-btn')) await wait(2000);
  }
  await wait(1000);

  // ─────────────────────────────────────────────────────
  // 17. STAT ALLOCATION
  // ─────────────────────────────────────────────────────
  console.log('17/25 — Stat Allocation');
  await page.evaluate(async () => {
    const token = localStorage.getItem('orbit_token');
    if (!token) return;
    await fetch('/stats/allocate', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ charisma: 1, empathy: 1, consistency: 1, initiative: 0, wisdom: 0 }),
    }).catch(() => {});
  });
  await wait(500);
  await page.evaluate(() => syncData());
  await wait(3000);
  // Scroll to stats section
  await scroll(500); await wait(2000);
  await scroll(0); await wait(800);

  // ─────────────────────────────────────────────────────
  // 18. STREAK FREEZE
  // ─────────────────────────────────────────────────────
  console.log('18/25 — Streak Freeze');
  await scroll(1200); await wait(1000);
  if (await safeClick('.freeze-btn')) await wait(2000);
  await scroll(0); await wait(800);

  // ─────────────────────────────────────────────────────
  // 19. LIGHT MODE TOGGLE
  // ─────────────────────────────────────────────────────
  console.log('19/25 — Light Mode Toggle');
  if (await safeClick('#themeToggleBtn')) {
    await wait(2000);
    await scroll(400); await wait(1500);
    await scroll(0); await wait(1000);
    // Back to dark
    await safeClick('#themeToggleBtn');
    await wait(1500);
  }

  // ─────────────────────────────────────────────────────
  // 20. ORBIT VIEW
  // ─────────────────────────────────────────────────────
  console.log('20/25 — Orbit View');
  await nav('orbit');
  await wait(5000);

  // ─────────────────────────────────────────────────────
  // 21. PEOPLE PAGE — browse all contacts
  // ─────────────────────────────────────────────────────
  console.log('21/25 — People Page');
  await nav('contacts');
  await wait(2000);
  await scroll(300); await wait(1200);
  await scroll(600); await wait(1200);
  await scroll(0); await wait(800);

  // Search on people page
  const pSearch = page.locator('#page-contacts .search-input');
  if (await pSearch.isVisible().catch(() => false)) {
    await pSearch.click();
    await pSearch.type('work', { delay: 80 });
    await wait(1500);
    await pSearch.fill('');
    await wait(800);
  }

  // ─────────────────────────────────────────────────────
  // 22. NETWORK GRAPH
  // ─────────────────────────────────────────────────────
  console.log('22/25 — Network Graph');
  await nav('network');
  await wait(5000);

  // ─────────────────────────────────────────────────────
  // 23. INSIGHTS PAGE
  // ─────────────────────────────────────────────────────
  console.log('23/25 — Insights');
  await nav('insights');
  await wait(3000);
  await scroll(200); await wait(1500);

  // ─────────────────────────────────────────────────────
  // 24. ACTIVITY FEED
  // ─────────────────────────────────────────────────────
  console.log('24/25 — Activity Feed');
  await nav('activity');
  await wait(2000);
  await scroll(300); await wait(1500);
  await scroll(0); await wait(1000);

  // ─────────────────────────────────────────────────────
  // 25. WEEKLY REPORT + FINAL DASHBOARD TOUR
  // ─────────────────────────────────────────────────────
  console.log('25/25 — Weekly Report + Final Dashboard');
  await nav('dashboard');
  await wait(2000);

  // Weekly report
  await scroll(1200); await wait(1000);
  if (await safeClick('button:has-text("Weekly Report")')) {
    await wait(3000);
    await safeClick('#reportOverlay .btn');
    await wait(1000);
  }

  // Grand final scroll
  await scroll(0); await wait(1000);
  for (const y of [300, 600, 900, 1200, 1500, 1800]) {
    await scroll(y); await wait(1000);
  }
  await scroll(0); await wait(2500);

  // ─────────────────────────────────────────────────────
  console.log('✅ Demo complete! Saving video...');
  await context.close();
  await browser.close();
  console.log('📹 Video saved to recordings/');
})();
