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

  // Helper: smooth scroll
  const smoothScroll = (y) => page.evaluate((scrollY) => window.scrollTo({ top: scrollY, behavior: 'smooth' }), y);
  // Helper: wait
  const wait = (ms) => page.waitForTimeout(ms);

  // ═══════════════════════════════════════════════════════
  // ACT 1: THE LANDING
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 1: Landing Page');
  await page.goto(APP_URL);
  await wait(2500);

  // Scroll through all landing page sections
  for (const y of [500, 1000, 1500, 2000, 2500]) {
    await smoothScroll(y);
    await wait(1200);
  }
  await smoothScroll(0);
  await wait(800);

  // ═══════════════════════════════════════════════════════
  // ACT 2: AUTHENTICATION
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 2: Login');
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

  // Dismiss onboarding + daily reward overlays
  await page.evaluate(() => {
    localStorage.setItem('orbit_onboarded', '1');
    const overlay = document.getElementById('onboardingOverlay');
    if (overlay) overlay.remove();
  });
  await wait(500);

  // Close daily reward if showing
  const rewardClose = page.locator('#rewardOverlay.active .btn');
  if (await rewardClose.isVisible().catch(() => false)) {
    await wait(2000);
    await rewardClose.click();
    await wait(500);
  }

  // ═══════════════════════════════════════════════════════
  // ACT 3: DASHBOARD OVERVIEW — Stats, Nudges, Gamification
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 3: Dashboard — Hunter Stats & Gamification');
  await wait(1500);
  // Scroll through dashboard slowly to show everything
  for (const y of [200, 500, 800, 1100, 1400]) {
    await smoothScroll(y);
    await wait(1200);
  }
  await smoothScroll(0);
  await wait(1000);

  // ═══════════════════════════════════════════════════════
  // ACT 4: SEARCH — filter contacts
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 4: Search');
  await page.click('#searchInput');
  await wait(300);
  await page.type('#searchInput', 'family', { delay: 80 });
  await wait(1500);
  await page.fill('#searchInput', '');
  await wait(300);
  await page.type('#searchInput', 'work', { delay: 80 });
  await wait(1500);
  await page.fill('#searchInput', '');
  await wait(800);

  // ═══════════════════════════════════════════════════════
  // ACT 5: ADD 3 CONTACTS — building the orbit
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 5: Adding contacts');

  const newContacts = [
    { first: 'Yuki', last: 'Tanaka', type: 'Friend', freq: 'weekly', notes: 'Met at a hackathon in Tokyo. Loves anime and machine learning.' },
    { first: 'Marcus', last: 'Williams', type: 'Work', freq: 'biweekly', notes: 'Product lead at our partner company. Great strategic thinker.' },
    { first: 'Elena', last: 'Rossi', type: 'Mentor', freq: 'monthly', notes: 'Former CTO, incredible advisor on scaling engineering teams.' },
  ];

  for (const person of newContacts) {
    await page.click('text=Add Person');
    await wait(800);
    await page.fill('#firstName', person.first);
    await wait(150);
    await page.fill('#lastName', person.last);
    await wait(150);
    await page.selectOption('#relationship', person.type);
    await wait(150);
    await page.click(`.form-tag[data-val="${person.freq}"]`);
    await wait(150);
    await page.fill('#personNotes', person.notes);
    await wait(600);
    await page.click('text=Add to Orbit');
    await wait(2500);
  }

  // Scroll to see all contacts
  await smoothScroll(500);
  await wait(1500);
  await smoothScroll(0);
  await wait(1000);

  // ═══════════════════════════════════════════════════════
  // ACT 6: LOG INTERACTIONS — triggers XP + weight learning
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 6: Logging interactions');

  // Interaction 1: In-person meetup
  await page.evaluate(() => { if (typeof openLogInteraction === 'function') openLogInteraction(); });
  await wait(1000);
  // Select first contact in dropdown
  await page.selectOption('#logContact', { index: 1 });
  await wait(300);
  // Select "In Person"
  await page.click('#logTypeTags .form-tag[data-val="in_person"]');
  await wait(200);
  await page.fill('#logDuration', '45');
  await wait(200);
  await page.fill('#logNotes', 'Great coffee catch-up. Talked about startup ideas and weekend plans.');
  await wait(500);
  await page.click('#logSubmitBtn');
  await wait(3000);

  // Interaction 2: Video call
  await page.evaluate(() => { if (typeof openLogInteraction === 'function') openLogInteraction(); });
  await wait(800);
  await page.selectOption('#logContact', { index: 2 });
  await wait(200);
  await page.click('#logTypeTags .form-tag[data-val="video_call"]');
  await wait(200);
  await page.fill('#logDuration', '30');
  await wait(200);
  await page.fill('#logNotes', 'Sprint planning session. Aligned on Q2 goals.');
  await wait(400);
  await page.click('#logSubmitBtn');
  await wait(3000);

  // Interaction 3: Call
  await page.evaluate(() => { if (typeof openLogInteraction === 'function') openLogInteraction(); });
  await wait(800);
  await page.selectOption('#logContact', { index: 3 });
  await wait(200);
  await page.click('#logTypeTags .form-tag[data-val="call"]');
  await wait(200);
  await page.fill('#logDuration', '20');
  await wait(200);
  await page.fill('#logNotes', 'Monthly mentorship call. Got advice on leadership.');
  await wait(400);
  await page.click('#logSubmitBtn');
  await wait(3000);

  // ═══════════════════════════════════════════════════════
  // ACT 7: NUDGES — act on one, snooze another
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 7: Nudges');
  await smoothScroll(300);
  await wait(800);

  const reachOutBtns = page.locator('.nudge-btn.primary');
  if (await reachOutBtns.count() > 0) {
    await reachOutBtns.first().click();
    await wait(2500);
  }

  const laterBtns = page.locator('.nudge-btn.ghost');
  if (await laterBtns.count() > 0) {
    await laterBtns.first().click();
    await wait(1500);
  }
  await smoothScroll(0);
  await wait(1000);

  // ═══════════════════════════════════════════════════════
  // ACT 8: CREATE A PARTY — group hangout
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 8: Creating a Party');
  await smoothScroll(800);
  await wait(800);

  await page.evaluate(() => { if (typeof openCreateParty === 'function') openCreateParty(); });
  await wait(1000);

  // Select "Dinner" activity
  await page.click('#partyActivityTags .form-tag[data-val="dinner"]');
  await wait(300);
  await page.fill('#partyTitle', 'Friday Night Dinner Crew');
  await wait(300);
  await page.fill('#partyLocation', 'Izakaya Tanaka, Downtown');
  await wait(300);
  await page.fill('#partyDesc', 'Bringing the crew together for sushi and sake. Celebrating hitting our milestones!');
  await wait(500);

  // Invite contacts (click checkboxes in invite list)
  const inviteChecks = page.locator('#partyInviteList input[type="checkbox"]');
  const inviteCount = await inviteChecks.count();
  for (let i = 0; i < Math.min(3, inviteCount); i++) {
    await inviteChecks.nth(i).click();
    await wait(200);
  }
  await wait(500);

  await page.click('#partySubmitBtn');
  await wait(3000);

  // ═══════════════════════════════════════════════════════
  // ACT 9: SEND A CHALLENGE — Solo Leveling style
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 9: Sending a Challenge');
  await page.evaluate(() => { if (typeof openCreateChallenge === 'function') openCreateChallenge(); });
  await wait(1000);

  // Select contact
  const challengeContactSelect = page.locator('#challengeContact');
  if (await challengeContactSelect.count() > 0) {
    await challengeContactSelect.selectOption({ index: 1 });
    await wait(300);
  }

  // Select "Hike" activity
  await page.click('#challengeActivityTags .form-tag[data-val="hike"]');
  await wait(300);
  await page.fill('#challengeTitle', 'Summit Challenge: Conquer Mt. Wilson');
  await wait(300);
  await page.fill('#challengeDesc', 'First one to summit gets bragging rights and +100 XP. Let\'s see who the real S-Rank hunter is!');
  await wait(500);

  const challengeSubmit = page.locator('#challengeModal .btn-primary');
  await challengeSubmit.click();
  await wait(3000);

  // ═══════════════════════════════════════════════════════
  // ACT 10: SHADOW EXTRACTION — ARISE!
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 10: Shadow Extraction (ARISE!)');
  await smoothScroll(0);
  await wait(500);

  // Click on a contact to open detail panel
  const contactCards = page.locator('#contactsGrid .contact-card');
  if (await contactCards.count() > 0) {
    await contactCards.first().click();
    await wait(2000);

    // Scroll detail panel to find ARISE button
    await page.evaluate(() => {
      const panel = document.getElementById('detailPanel');
      if (panel) {
        const body = panel.querySelector('.detail-body');
        if (body) body.scrollTo({ top: 400, behavior: 'smooth' });
      }
    });
    await wait(1500);

    // Click the ARISE button if exists
    const ariseBtn = page.locator('button:has-text("ARISE")');
    if (await ariseBtn.isVisible().catch(() => false)) {
      await ariseBtn.click();
      await wait(4000); // Let the extraction animation play
    }

    // Close detail panel
    await page.evaluate(() => { if (typeof closeDetail === 'function') closeDetail(); });
    await wait(1000);
  }

  // ═══════════════════════════════════════════════════════
  // ACT 11: OPEN A GATE (Dungeon)
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 11: Opening a Gate');
  // Create a gate via API directly (no UI form for gate creation yet)
  await page.evaluate(async () => {
    const token = localStorage.getItem('orbit_token');
    if (!token) return;
    try {
      await fetch('/gates', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: 'Social Blitz: Contact 5 people in 24 hours',
          description: 'A D-Rank gate has appeared! Clear it by reaching out to 5 different contacts.',
          gate_rank: 'D-Rank',
          objective_type: 'interactions',
          objective_target: 5,
          time_limit_hours: 24,
        }),
      });
    } catch (e) {}
  });
  await wait(1500);

  // Sync to refresh
  await page.click('button:has-text("Sync")');
  await wait(3000);

  // Scroll to see gates in gamification section
  await smoothScroll(800);
  await wait(2000);
  await smoothScroll(0);
  await wait(1000);

  // ═══════════════════════════════════════════════════════
  // ACT 12: BOSS RAID — Attack!
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 12: Boss Raid');
  // Create a boss raid via API
  await page.evaluate(async () => {
    const token = localStorage.getItem('orbit_token');
    if (!token) return;
    try {
      await fetch('/boss-raids', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: 'Reconnect with 10 old friends',
          description: 'The Shadow Beast of Isolation has appeared!',
          boss_name: 'Shadow Beast of Isolation',
          boss_hp: 50,
          xp_reward: 300,
          time_limit_days: 7,
        }),
      });
    } catch (e) {}
  });
  await wait(1000);

  // Sync + scroll to boss raids
  await page.click('button:has-text("Sync")');
  await wait(3000);
  await smoothScroll(1000);
  await wait(2000);

  // Attack the boss 3 times
  for (let i = 0; i < 3; i++) {
    const attackBtn = page.locator('.boss-attack-btn').first();
    if (await attackBtn.isVisible().catch(() => false)) {
      await attackBtn.click();
      await wait(2000);
    }
  }
  await wait(1000);
  await smoothScroll(0);
  await wait(1000);

  // ═══════════════════════════════════════════════════════
  // ACT 13: STAT ALLOCATION
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 13: Allocating Stats');
  // Allocate stats via API
  await page.evaluate(async () => {
    const token = localStorage.getItem('orbit_token');
    if (!token) return;
    try {
      await fetch('/stats/allocate', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
        body: JSON.stringify({ charisma: 2, empathy: 1, consistency: 1, initiative: 0, wisdom: 1 }),
      });
    } catch (e) {}
  });
  await wait(500);

  // Sync to see updated stats
  await page.click('button:has-text("Sync")');
  await wait(3000);

  // Scroll to hunter stats section
  await smoothScroll(500);
  await wait(2000);
  await smoothScroll(0);
  await wait(1000);

  // ═══════════════════════════════════════════════════════
  // ACT 14: TOGGLE LIGHT MODE
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 14: Theme Toggle');
  const themeBtn = page.locator('#themeToggleBtn');
  if (await themeBtn.isVisible().catch(() => false)) {
    await themeBtn.click();
    await wait(2500);
    // Scroll in light mode
    await smoothScroll(400);
    await wait(1500);
    await smoothScroll(0);
    await wait(1000);
    // Back to dark
    await themeBtn.click();
    await wait(1500);
  }

  // ═══════════════════════════════════════════════════════
  // ACT 15: ORBIT VIEW — animated visualization
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 15: Orbit View');
  await page.click('[data-page="orbit"]');
  await wait(5000);

  // ═══════════════════════════════════════════════════════
  // ACT 16: PEOPLE PAGE — cards with avatars + health
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 16: People Page');
  await page.click('[data-page="contacts"]');
  await wait(2000);
  await smoothScroll(300);
  await wait(1500);
  await smoothScroll(600);
  await wait(1500);
  await smoothScroll(0);
  await wait(1000);

  // Search on people page
  const peopleSearch = page.locator('#page-contacts .search-input');
  if (await peopleSearch.isVisible().catch(() => false)) {
    await peopleSearch.click();
    await peopleSearch.type('mentor', { delay: 80 });
    await wait(1500);
    await peopleSearch.fill('');
    await wait(800);
  }

  // ═══════════════════════════════════════════════════════
  // ACT 17: CONTACT DETAIL PANEL — full feature showcase
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 17: Contact Detail Panel');
  const allCards = page.locator('#page-contacts .contact-card');
  if (await allCards.first().isVisible().catch(() => false)) {
    await allCards.first().click();
    await wait(2500);

    // Scroll through detail panel
    await page.evaluate(() => {
      const body = document.querySelector('#detailPanel .detail-body');
      if (body) body.scrollTo({ top: 200, behavior: 'smooth' });
    });
    await wait(1500);
    await page.evaluate(() => {
      const body = document.querySelector('#detailPanel .detail-body');
      if (body) body.scrollTo({ top: 400, behavior: 'smooth' });
    });
    await wait(1500);
    await page.evaluate(() => {
      const body = document.querySelector('#detailPanel .detail-body');
      if (body) body.scrollTo({ top: 0, behavior: 'smooth' });
    });
    await wait(1000);

    // Close detail
    await page.evaluate(() => { if (typeof closeDetail === 'function') closeDetail(); });
    await wait(800);
  }

  // ═══════════════════════════════════════════════════════
  // ACT 18: NETWORK GRAPH — force-directed visualization
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 18: Network Graph');
  // Use evaluate to navigate — sidebar might be behind overlay
  await page.evaluate(() => {
    if (typeof closeDetail === 'function') closeDetail();
    document.querySelectorAll('.detail-overlay.active, .detail-panel.active').forEach(el => el.classList.remove('active'));
    if (typeof navigateTo === 'function') navigateTo('network');
  });
  await wait(5000); // Let the physics simulation settle

  // ═══════════════════════════════════════════════════════
  // ACT 19: INSIGHTS — AI analysis
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 19: Insights');
  await page.evaluate(() => navigateTo('insights'));
  await wait(3000);
  await smoothScroll(200);
  await wait(1500);

  // ═══════════════════════════════════════════════════════
  // ACT 20: ACTIVITY FEED — social timeline
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 20: Activity Feed');
  await page.evaluate(() => navigateTo('activity'));
  await wait(2000);
  await smoothScroll(300);
  await wait(1500);
  await smoothScroll(0);
  await wait(1000);

  // ═══════════════════════════════════════════════════════
  // ACT 21: WEEKLY REPORT
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 21: Weekly Report');
  await page.evaluate(() => navigateTo('dashboard'));
  await wait(2000);

  // Scroll down to find the report button
  await smoothScroll(1200);
  await wait(1000);

  const reportBtn = page.locator('button:has-text("Weekly Report")');
  if (await reportBtn.isVisible().catch(() => false)) {
    await reportBtn.click();
    await wait(3000);
    // Close report
    await page.click('#reportOverlay .btn');
    await wait(1000);
  }
  await smoothScroll(0);
  await wait(1000);

  // ═══════════════════════════════════════════════════════
  // ACT 22: SYNC + FINAL DASHBOARD STATE
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Act 22: Final Sync & Dashboard');
  await page.evaluate(() => { if (typeof syncData === 'function') syncData(); });
  await wait(3000);

  // Grand tour — scroll through entire final dashboard
  for (const y of [300, 600, 900, 1200, 1500]) {
    await smoothScroll(y);
    await wait(1200);
  }
  await smoothScroll(0);
  await wait(2000);

  // ═══════════════════════════════════════════════════════
  // FINALE
  // ═══════════════════════════════════════════════════════
  console.log('🎬 Demo complete! Saving video...');
  await context.close();
  await browser.close();

  console.log('✅ Video saved to orbit/recordings/');
})();
