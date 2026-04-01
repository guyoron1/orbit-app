/**
 * Orbit — Complete PWA Demo
 * Comprehensive showcase of every feature, integration, and mobile PWA experience
 * Captures screenshots in both desktop and mobile viewports
 */
import { chromium } from 'playwright';
import { join } from 'path';

const BASE = 'https://orbit-app-production-fd37.up.railway.app';
const DIR = join(process.cwd(), 'demo-screenshots', 'complete');
let shotNum = 0;

async function dismissOverlays(page) {
  await page.evaluate(() => {
    const reward = document.getElementById('rewardOverlay');
    if (reward && reward.classList.contains('active')) reward.classList.remove('active');
    const onboard = document.getElementById('onboardingOverlay');
    if (onboard) onboard.remove();
    document.querySelectorAll('.modal-overlay.active').forEach(m => m.classList.remove('active'));
    document.querySelectorAll('.toast').forEach(t => t.remove());
  });
  await page.waitForTimeout(200);
}

async function shot(page, name, delay = 600) {
  await page.waitForTimeout(delay);
  shotNum++;
  const file = join(DIR, `${String(shotNum).padStart(2, '0')}-${name}.png`);
  await page.screenshot({ path: file, fullPage: false });
  console.log(`  📸 [${shotNum}] ${name}`);
}

async function nav(page, pageName) {
  await dismissOverlays(page);
  const btns = page.locator(`[data-page="${pageName}"]`);
  for (const btn of await btns.all()) {
    if (await btn.isVisible()) { await btn.click(); return; }
  }
  await page.evaluate((p) => { if (typeof navigateTo === 'function') navigateTo(p); }, pageName);
}

(async () => {
  const { mkdirSync } = await import('fs');
  mkdirSync(DIR, { recursive: true });

  const browser = await chromium.launch({ headless: false, slowMo: 50 });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  const email = `pwa-demo-${Date.now()}@orbit.app`;
  const password = 'OrbitPWA2026!';

  console.log('\n╔══════════════════════════════════════════════╗');
  console.log('║   ORBIT — COMPLETE PWA DEMO & SHOWCASE       ║');
  console.log('║   All features, integrations & mobile PWA     ║');
  console.log('╚══════════════════════════════════════════════╝\n');

  // ═══════════════════════════════════════════════
  // SECTION 1: LANDING PAGE & FIRST IMPRESSION
  // ═══════════════════════════════════════════════
  console.log('━━ 1. LANDING PAGE ━━');
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  await shot(page, '01-landing-hero');

  // Scroll to features section
  await page.evaluate(() => {
    const el = document.querySelector('.landing-features') || document.querySelector('.feature-grid');
    if (el) el.scrollIntoView({ behavior: 'instant' });
  });
  await shot(page, '01-landing-features', 800);

  // Scroll to stats/social proof
  await page.evaluate(() => {
    const el = document.querySelector('.landing-stats');
    if (el) el.scrollIntoView({ behavior: 'instant' });
    else window.scrollTo(0, document.body.scrollHeight);
  });
  await shot(page, '01-landing-stats', 600);

  // ═══════════════════════════════════════════════
  // SECTION 2: AUTH — SIGNUP WITH SOCIAL OPTIONS
  // ═══════════════════════════════════════════════
  console.log('━━ 2. AUTH FLOW ━━');
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(300);

  await page.locator('text=Get Started Free').first().click();
  await page.waitForSelector('#authModal.active', { timeout: 5000 });
  await page.waitForTimeout(600);
  await shot(page, '02-auth-signup-modal');

  // Show social login buttons (Apple + Google)
  const socialBtns = page.locator('.social-btn');
  const socialCount = await socialBtns.count();
  console.log(`    Social login buttons visible: ${socialCount}`);

  // Fill signup form
  await page.fill('#authName', 'Jordan Hunter');
  await page.fill('#authEmail', email);
  await page.fill('#authPass', password);
  await shot(page, '02-auth-signup-filled');

  await page.click('#authSubmitBtn');
  await page.waitForTimeout(3500);

  // Handle onboarding
  const onboarding = page.locator('#onboardingOverlay');
  if (await onboarding.isVisible({ timeout: 3000 }).catch(() => false)) {
    await shot(page, '02-onboarding-welcome');
    const nextBtn = page.locator('button', { hasText: 'Next' }).first();
    if (await nextBtn.isVisible()) {
      await nextBtn.click();
      await page.waitForTimeout(500);
      await shot(page, '02-onboarding-step2');
      if (await nextBtn.isVisible()) {
        await nextBtn.click();
        await page.waitForTimeout(500);
        await shot(page, '02-onboarding-step3');
      }
    }
    await page.evaluate(() => { if (typeof finishOnboarding === 'function') finishOnboarding(); });
    await page.waitForTimeout(500);
  }
  await dismissOverlays(page);
  await shot(page, '02-dashboard-fresh-account');

  // ═══════════════════════════════════════════════
  // SECTION 3: ADD CONTACTS (BUILD THE ORBIT)
  // ═══════════════════════════════════════════════
  console.log('━━ 3. ADDING CONTACTS ━━');
  const contacts = [
    { first: 'Sarah', last: 'Chen', type: 'Friend', freq: 'weekly', notes: 'Best friend, designer at Figma, loves hiking and pottery' },
    { first: 'Mom', last: '', type: 'Family', freq: 'weekly', notes: 'Book club on Thursdays, planning spring garden together' },
    { first: 'Marcus', last: 'Williams', type: 'Friend', freq: 'biweekly', notes: 'College roommate, PM at Google, expecting first child in June' },
    { first: 'David', last: 'Park', type: 'Mentor', freq: 'monthly', notes: 'VP Eng at Datadog, career mentor since 2022' },
    { first: 'Priya', last: 'Patel', type: 'Friend', freq: 'biweekly', notes: 'Yoga class friend, training for Tokyo marathon' },
    { first: 'Emma', last: 'Kim', type: 'Family', freq: 'weekly', notes: 'Sister, finishing grad school in May, needs moving help' },
    { first: 'Jake', last: 'Torres', type: 'Work', freq: 'monthly', notes: 'Tech lead on Platform team, great at system design' },
    { first: 'Aisha', last: 'Rahman', type: 'Friend', freq: 'biweekly', notes: 'Neighbor, has a golden retriever named Mochi, movie buff' },
  ];

  for (let i = 0; i < contacts.length; i++) {
    const c = contacts[i];
    await dismissOverlays(page);
    const addBtn = page.locator('button', { hasText: 'Add Person' }).first();
    await addBtn.click();
    await page.waitForSelector('#addModal.active', { timeout: 3000 });
    await page.waitForTimeout(300);

    await page.fill('#firstName', c.first);
    await page.fill('#lastName', c.last);
    await page.selectOption('#relationship', { label: c.type });
    await page.click(`#frequencyTags .form-tag[data-val="${c.freq}"]`);
    await page.fill('#personNotes', c.notes);

    if (i === 0) await shot(page, '03-add-contact-form');

    await page.locator('button', { hasText: 'Add to Orbit' }).click();
    await page.waitForTimeout(1800);
  }
  await dismissOverlays(page);
  console.log(`    Added ${contacts.length} contacts`);

  // ═══════════════════════════════════════════════
  // SECTION 4: LOG INTERACTIONS (API + UI)
  // ═══════════════════════════════════════════════
  console.log('━━ 4. LOGGING INTERACTIONS ━━');
  const token = await page.evaluate(() => localStorage.getItem('orbit_token'));
  const contactsData = await page.evaluate(async () => {
    const res = await fetch('/contacts', { headers: { 'Authorization': 'Bearer ' + localStorage.getItem('orbit_token') } });
    return res.json();
  });

  // Bulk log via API to build up data
  const interactionTypes = ['call', 'text', 'in_person', 'video_call', 'social_media'];
  const notes = [
    'Caught up over coffee, discussed career moves',
    'Quick check-in, shared a funny meme',
    'Dinner at the new Italian place downtown',
    'Video call to plan weekend trip',
    'Liked their vacation photos, left a comment',
    'Deep conversation about life goals',
    'Helped them move furniture',
    'Birthday celebration at the park',
  ];

  for (let ci = 0; ci < Math.min(contactsData.length, 6); ci++) {
    const c = contactsData[ci];
    for (let j = 0; j < 4; j++) {
      await page.evaluate(async ({ cid, itype, dur, note, initiated }) => {
        await fetch('/interactions', {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + localStorage.getItem('orbit_token'), 'Content-Type': 'application/json' },
          body: JSON.stringify({ contact_id: cid, interaction_type: itype, duration_minutes: dur, initiated_by_user: initiated, notes: note }),
        });
      }, { cid: c.id, itype: interactionTypes[j % interactionTypes.length], dur: 10 + j * 20, note: notes[(ci + j) % notes.length], initiated: j % 2 === 0 });
    }
  }
  console.log(`    Logged ${Math.min(contactsData.length, 6) * 4} interactions via API`);

  // UI log interaction
  await dismissOverlays(page);
  await nav(page, 'dashboard');
  await page.waitForTimeout(1500);

  await page.evaluate(() => {
    if (typeof openLogInteraction === 'function') openLogInteraction();
    else if (typeof openLogModal === 'function') openLogModal();
    else document.getElementById('logModal')?.classList.add('active');
  });
  await page.waitForTimeout(800);

  const logContactSelect = page.locator('#logContact');
  if (await logContactSelect.isVisible()) {
    await page.evaluate(() => {
      const sel = document.getElementById('logContact');
      if (sel && sel.options.length > 1) sel.selectedIndex = 1;
    });
  }
  await page.click('#logTypeTags .form-tag[data-val="video_call"]').catch(() => {});
  await page.fill('#logDuration', '45');
  await page.fill('#logNotes', 'Career coaching session — discussed transitioning to product management, great insights on PM interviews');
  await shot(page, '04-log-interaction-ui');

  await page.click('#logSubmitBtn');
  await page.waitForTimeout(2500);

  // ═══════════════════════════════════════════════
  // SECTION 5: DASHBOARD — FULL OVERVIEW
  // ═══════════════════════════════════════════════
  console.log('━━ 5. DASHBOARD ━━');
  await dismissOverlays(page);
  await nav(page, 'dashboard');
  await page.waitForTimeout(3000);
  await shot(page, '05-dashboard-stats-overview');

  // Scroll to nudges section
  await page.evaluate(() => window.scrollBy(0, 500));
  await shot(page, '05-dashboard-nudges', 600);

  // Scroll to gamification section
  await page.evaluate(() => {
    const sections = document.querySelectorAll('.section-title, h2, h3');
    for (const s of sections) {
      if (s.textContent.includes('Hunter') || s.textContent.includes('Rank') || s.textContent.includes('Level') || s.textContent.includes('Quest')) {
        s.scrollIntoView({ behavior: 'instant', block: 'start' });
        return;
      }
    }
    window.scrollBy(0, 400);
  });
  await page.waitForTimeout(500);
  await shot(page, '05-dashboard-gamification-rank');

  // Scroll to quests
  await page.evaluate(() => window.scrollBy(0, 400));
  await shot(page, '05-dashboard-quests', 500);

  // Scroll to achievements
  await page.evaluate(() => window.scrollBy(0, 400));
  await shot(page, '05-dashboard-achievements', 500);

  // ═══════════════════════════════════════════════
  // SECTION 6: CONTACTS PAGE & DETAIL PANEL
  // ═══════════════════════════════════════════════
  console.log('━━ 6. CONTACTS & DETAIL ━━');
  await nav(page, 'contacts');
  await page.waitForTimeout(2000);
  await shot(page, '06-contacts-grid');

  // Open detail for first contact
  await dismissOverlays(page);
  const firstCard = page.locator('.contact-card').first();
  if (await firstCard.isVisible().catch(() => false)) {
    await firstCard.click();
    await page.waitForTimeout(2000);
    await shot(page, '06-contact-detail-top');

    // Scroll detail to see AI conversation starters
    await page.evaluate(() => {
      const panel = document.querySelector('.detail-body');
      if (panel) panel.scrollTop = 250;
    });
    await shot(page, '06-contact-detail-ai-starters', 800);

    // Scroll to interaction history
    await page.evaluate(() => {
      const panel = document.querySelector('.detail-body');
      if (panel) panel.scrollTop = 500;
    });
    await shot(page, '06-contact-detail-history', 500);

    // Scroll to bottom — edit/delete
    await page.evaluate(() => {
      const panel = document.querySelector('.detail-body');
      if (panel) panel.scrollTop = panel.scrollHeight;
    });
    await shot(page, '06-contact-detail-manage', 500);

    // Open edit modal
    const editBtn = page.locator('.detail-panel button', { hasText: 'Edit' }).first();
    if (await editBtn.isVisible().catch(() => false)) {
      await editBtn.click();
      await page.waitForTimeout(600);
      await shot(page, '06-edit-contact-modal');
      const cancelBtn = page.locator('button', { hasText: 'Cancel' }).first();
      if (await cancelBtn.isVisible().catch(() => false)) await cancelBtn.click();
      await page.waitForTimeout(300);
    }

    const closeBtn = page.locator('.detail-close').first();
    if (await closeBtn.isVisible().catch(() => false)) {
      await closeBtn.click();
    } else {
      await page.evaluate(() => { if (typeof closeDetail === 'function') closeDetail(); });
    }
    await page.waitForTimeout(300);
  } else {
    console.log('    (no contact cards visible, skipping detail panel)');
  }

  // Search contacts
  const searchInput = page.locator('#searchInput, [placeholder*="Search"]').first();
  if (await searchInput.isVisible()) {
    await searchInput.fill('Sarah');
    await page.waitForTimeout(800);
    await shot(page, '06-contacts-search');
    await searchInput.fill('');
    await page.waitForTimeout(500);
  }

  // ═══════════════════════════════════════════════
  // SECTION 7: ORBIT VISUALIZATION
  // ═══════════════════════════════════════════════
  console.log('━━ 7. ORBIT VISUALIZATION ━━');
  await nav(page, 'orbit');
  await page.waitForTimeout(3000);
  await shot(page, '07-orbit-network-view');

  // ═══════════════════════════════════════════════
  // SECTION 8: INSIGHTS & ANALYTICS
  // ═══════════════════════════════════════════════
  console.log('━━ 8. INSIGHTS ━━');
  await nav(page, 'insights');
  await page.waitForTimeout(2000);
  await shot(page, '08-insights-overview');

  // Scroll down for more insight cards
  await page.evaluate(() => window.scrollBy(0, 400));
  await shot(page, '08-insights-details', 500);

  // ═══════════════════════════════════════════════
  // SECTION 9: ACTIVITY FEED & LEADERBOARD
  // ═══════════════════════════════════════════════
  console.log('━━ 9. ACTIVITY FEED ━━');
  await nav(page, 'activity');
  await page.waitForTimeout(2000);
  await shot(page, '09-activity-feed');

  // Scroll to leaderboard section
  await page.evaluate(() => window.scrollBy(0, 400));
  await shot(page, '09-leaderboard', 500);

  // ═══════════════════════════════════════════════
  // SECTION 10: NETWORK GRAPH
  // ═══════════════════════════════════════════════
  console.log('━━ 10. NETWORK GRAPH ━━');
  await nav(page, 'network');
  await page.waitForTimeout(3000);
  await shot(page, '10-network-graph');

  // ═══════════════════════════════════════════════
  // SECTION 11: PARTIES & CHALLENGES (DASHBOARD SECTIONS)
  // ═══════════════════════════════════════════════
  console.log('━━ 11. PARTIES & CHALLENGES ━━');
  await dismissOverlays(page);
  await nav(page, 'dashboard');
  await page.waitForTimeout(2000);

  // Scroll to parties section
  await page.evaluate(() => {
    const sections = document.querySelectorAll('.section-title, h2, h3');
    for (const s of sections) {
      if (s.textContent.includes('Part') || s.textContent.includes('Group')) {
        s.scrollIntoView({ behavior: 'instant', block: 'start' });
        return;
      }
    }
    // If no section found, scroll far down
    window.scrollTo(0, document.body.scrollHeight - 1200);
  });
  await page.waitForTimeout(500);
  await shot(page, '11-parties-section');

  // Scroll to challenges
  await page.evaluate(() => {
    const sections = document.querySelectorAll('.section-title, h2, h3');
    for (const s of sections) {
      if (s.textContent.includes('Challenge')) {
        s.scrollIntoView({ behavior: 'instant', block: 'start' });
        return;
      }
    }
    window.scrollBy(0, 400);
  });
  await page.waitForTimeout(500);
  await shot(page, '11-challenges-section');

  // ═══════════════════════════════════════════════
  // SECTION 13: SETTINGS PAGE
  // ═══════════════════════════════════════════════
  console.log('━━ 13. SETTINGS ━━');
  await nav(page, 'settings');
  await page.waitForTimeout(1000);
  await shot(page, '13-settings-profile');

  await page.evaluate(() => window.scrollBy(0, 350));
  await shot(page, '13-settings-notifications', 500);

  await page.evaluate(() => window.scrollBy(0, 350));
  await shot(page, '13-settings-data-export', 500);

  await page.evaluate(() => window.scrollBy(0, 300));
  await shot(page, '13-settings-danger-zone', 500);

  // ═══════════════════════════════════════════════
  // SECTION 14: LIGHT MODE TOGGLE
  // ═══════════════════════════════════════════════
  console.log('━━ 14. LIGHT MODE ━━');
  await nav(page, 'dashboard');
  await page.waitForTimeout(1500);

  const themeBtn = page.locator('#themeToggleBtn');
  if (await themeBtn.isVisible().catch(() => false)) {
    await themeBtn.click();
    await page.waitForTimeout(800);
    await shot(page, '14-light-mode-dashboard');

    await nav(page, 'contacts');
    await page.waitForTimeout(1000);
    await shot(page, '14-light-mode-contacts');

    await nav(page, 'orbit');
    await page.waitForTimeout(2000);
    await shot(page, '14-light-mode-orbit');

    // Back to dark
    await themeBtn.click();
    await page.waitForTimeout(500);
  }

  // ═══════════════════════════════════════════════
  // SECTION 15: PRIVACY & TERMS (LEGAL PAGES)
  // ═══════════════════════════════════════════════
  console.log('━━ 15. LEGAL PAGES ━━');
  await page.goto(`${BASE}/privacy`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  await shot(page, '15-privacy-policy');

  await page.goto(`${BASE}/terms`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  await shot(page, '15-terms-of-service');

  // Go back to app
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);

  // ═══════════════════════════════════════════════
  // SECTION 16: QUEST COMPLETION & XP REWARD
  // ═══════════════════════════════════════════════
  console.log('━━ 16. QUEST COMPLETION ━━');
  await dismissOverlays(page);
  await nav(page, 'dashboard');
  await page.waitForTimeout(2000);

  // Try completing a quest
  const questCompleteBtn = page.locator('button', { hasText: /Complete|Claim/i }).first();
  if (await questCompleteBtn.isVisible().catch(() => false)) {
    await questCompleteBtn.click();
    await page.waitForTimeout(2000);
    await shot(page, '16-xp-reward-toast');
  }

  // ═══════════════════════════════════════════════
  // SECTION 17: NUDGE ACTIONS
  // ═══════════════════════════════════════════════
  console.log('━━ 17. NUDGE ACTIONS ━━');
  await dismissOverlays(page);
  await nav(page, 'dashboard');
  await page.waitForTimeout(2000);

  // Scroll to nudges
  await page.evaluate(() => {
    const nudgeSection = document.querySelector('.nudges');
    if (nudgeSection) nudgeSection.scrollIntoView({ behavior: 'instant', block: 'start' });
    else window.scrollBy(0, 500);
  });
  await page.waitForTimeout(500);

  // Act on a nudge
  const nudgeActBtn = page.locator('.nudge-card button, .nudge-card .btn').first();
  if (await nudgeActBtn.isVisible().catch(() => false)) {
    await shot(page, '17-nudge-before-action');
    await nudgeActBtn.click();
    await page.waitForTimeout(2000);
    await shot(page, '17-nudge-after-action');
  }

  // ═══════════════════════════════════════════════
  // SECTION 18: MOBILE PWA EXPERIENCE
  // ═══════════════════════════════════════════════
  console.log('━━ 18. MOBILE PWA EXPERIENCE ━━');
  await page.setViewportSize({ width: 390, height: 844 }); // iPhone 14

  await dismissOverlays(page);
  await nav(page, 'dashboard');
  await page.waitForTimeout(2500);
  await shot(page, '18-mobile-dashboard');

  // Show bottom nav with active indicator
  await shot(page, '18-mobile-bottom-nav');

  // Scroll dashboard on mobile
  await page.evaluate(() => window.scrollBy(0, 400));
  await shot(page, '18-mobile-dashboard-scroll', 500);

  // Scroll more to gamification
  await page.evaluate(() => window.scrollBy(0, 600));
  await shot(page, '18-mobile-gamification', 500);

  // Mobile contacts
  console.log('    Mobile contacts...');
  await nav(page, 'contacts');
  await page.waitForTimeout(1500);
  await shot(page, '18-mobile-contacts');

  // Mobile detail panel (slides in from right)
  const mobileCard = page.locator('.contact-card').first();
  if (await mobileCard.isVisible()) {
    await mobileCard.click();
    await page.waitForTimeout(1500);
    await shot(page, '18-mobile-contact-detail');
    await page.click('.detail-close');
    await page.waitForTimeout(300);
  }

  // Mobile orbit visualization
  console.log('    Mobile orbit...');
  await nav(page, 'orbit');
  await page.waitForTimeout(2500);
  await shot(page, '18-mobile-orbit');

  // Mobile insights
  console.log('    Mobile insights...');
  await nav(page, 'insights');
  await page.waitForTimeout(1500);
  await shot(page, '18-mobile-insights');

  // Mobile activity
  console.log('    Mobile activity...');
  await nav(page, 'activity');
  await page.waitForTimeout(1500);
  await shot(page, '18-mobile-activity');

  // Mobile settings
  console.log('    Mobile settings...');
  await nav(page, 'settings');
  await page.waitForTimeout(1000);
  await shot(page, '18-mobile-settings');

  // ═══════════════════════════════════════════════
  // SECTION 19: MOBILE LIGHT MODE
  // ═══════════════════════════════════════════════
  console.log('━━ 19. MOBILE LIGHT MODE ━━');
  const mobileTheme = page.locator('#themeToggleBtn');
  if (await mobileTheme.isVisible().catch(() => false)) {
    await mobileTheme.click();
    await page.waitForTimeout(600);

    await nav(page, 'dashboard');
    await page.waitForTimeout(1500);
    await shot(page, '19-mobile-light-dashboard');

    await nav(page, 'contacts');
    await page.waitForTimeout(1000);
    await shot(page, '19-mobile-light-contacts');

    // Back to dark
    await mobileTheme.click();
    await page.waitForTimeout(500);
  }

  // ═══════════════════════════════════════════════
  // SECTION 20: TABLET VIEW
  // ═══════════════════════════════════════════════
  console.log('━━ 20. TABLET VIEW ━━');
  await page.setViewportSize({ width: 820, height: 1180 }); // iPad

  await nav(page, 'dashboard');
  await page.waitForTimeout(2000);
  await shot(page, '20-tablet-dashboard');

  await nav(page, 'contacts');
  await page.waitForTimeout(1500);
  await shot(page, '20-tablet-contacts');

  await nav(page, 'orbit');
  await page.waitForTimeout(2000);
  await shot(page, '20-tablet-orbit');

  // ═══════════════════════════════════════════════
  // SECTION 21: SECURITY — RATE LIMITING & CSP
  // ═══════════════════════════════════════════════
  console.log('━━ 21. SECURITY CHECKS ━━');
  await page.setViewportSize({ width: 1440, height: 900 });

  // Check CSP header
  const response = await page.goto(BASE, { waitUntil: 'networkidle' });
  const headers = response.headers();
  const csp = headers['content-security-policy'] || 'not set';
  const permissions = headers['permissions-policy'] || 'not set';
  console.log(`    CSP header: ${csp.substring(0, 80)}...`);
  console.log(`    Permissions-Policy: ${permissions.substring(0, 80)}...`);

  // Test rate limiting by hitting login endpoint
  console.log('    Testing rate limiting...');
  let rateLimited = false;
  for (let i = 0; i < 12; i++) {
    const res = await page.evaluate(async () => {
      const r = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: 'test@test.com', password: 'wrong' }),
      });
      return r.status;
    });
    if (res === 429) {
      rateLimited = true;
      console.log(`    Rate limited after ${i + 1} requests (429 Too Many Requests)`);
      break;
    }
  }
  if (!rateLimited) console.log('    Rate limiting threshold not reached in 12 attempts');

  // Test input sanitization
  const sanitizeResult = await page.evaluate(async () => {
    const t = localStorage.getItem('orbit_token');
    const res = await fetch('/contacts', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + t, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        first_name: '<script>alert("xss")</script>Test',
        last_name: '<img onerror=alert(1)>User',
        relationship_type: 'Friend',
        contact_frequency: 'weekly',
      }),
    });
    const data = await res.json();
    return { status: res.status, name: data.first_name || data.name || 'unknown' };
  });
  console.log(`    Sanitization test: input "<script>..." → stored as "${sanitizeResult.name}"`);

  // ═══════════════════════════════════════════════
  // SECTION 22: OFFLINE / SERVICE WORKER
  // ═══════════════════════════════════════════════
  console.log('━━ 22. SERVICE WORKER & OFFLINE ━━');
  await page.waitForTimeout(1500);
  await dismissOverlays(page);

  // Check SW registration
  const swStatus = await page.evaluate(async () => {
    const reg = await navigator.serviceWorker?.getRegistration?.();
    return reg ? `active (scope: ${reg.scope})` : 'not registered';
  });
  console.log(`    Service Worker: ${swStatus}`);

  // Check cached assets
  const cachedAssets = await page.evaluate(async () => {
    const cache = await caches.open('orbit-v4');
    const keys = await cache.keys();
    return keys.map(k => new URL(k.url).pathname);
  });
  console.log(`    Cached assets: ${cachedAssets.join(', ')}`);

  // Simulate offline
  await ctx.setOffline(true);
  await page.waitForTimeout(500);
  await shot(page, '22-offline-indicator');
  await ctx.setOffline(false);
  await page.waitForTimeout(500);

  // ═══════════════════════════════════════════════
  // SECTION 23: PWA MANIFEST VERIFICATION
  // ═══════════════════════════════════════════════
  console.log('━━ 23. PWA MANIFEST ━━');
  const manifest = await page.evaluate(async () => {
    const res = await fetch('/manifest.json');
    return res.json();
  });
  console.log(`    App name: ${manifest.name}`);
  console.log(`    Display: ${manifest.display}`);
  console.log(`    Orientation: ${manifest.orientation}`);
  console.log(`    Icons: ${manifest.icons.length}`);
  console.log(`    Shortcuts: ${manifest.shortcuts?.length || 0}`);
  console.log(`    Categories: ${manifest.categories?.join(', ')}`);

  // ═══════════════════════════════════════════════
  // SECTION 24: DATA EXPORT
  // ═══════════════════════════════════════════════
  console.log('━━ 24. DATA EXPORT ━━');
  await dismissOverlays(page);
  await nav(page, 'settings');
  await page.waitForTimeout(1000);

  // Scroll to export section
  await page.evaluate(() => {
    const buttons = document.querySelectorAll('button');
    for (const b of buttons) {
      if (b.textContent.includes('Export') || b.textContent.includes('CSV') || b.textContent.includes('JSON')) {
        b.scrollIntoView({ behavior: 'instant', block: 'center' });
        return;
      }
    }
    window.scrollBy(0, 400);
  });
  await shot(page, '24-data-export-options', 500);

  // ═══════════════════════════════════════════════
  // SECTION 25: LOGIN FLOW (EXISTING ACCOUNT)
  // ═══════════════════════════════════════════════
  console.log('━━ 25. LOGIN FLOW ━━');
  // Logout first
  await page.evaluate(() => {
    if (typeof logout === 'function') logout();
  });
  await page.waitForTimeout(1000);

  // Login as seed user
  await page.locator('text=Sign In').first().click().catch(async () => {
    await page.locator('text=Get Started Free').first().click();
  });
  await page.waitForSelector('#authModal.active', { timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(500);

  // Switch to login tab if needed
  const loginTab = page.locator('text=Sign In').first();
  if (await loginTab.isVisible().catch(() => false)) {
    await loginTab.click();
    await page.waitForTimeout(300);
  }

  await page.fill('#authEmail', 'jordan@example.com');
  await page.fill('#authPass', 'orbit2024demo');
  await shot(page, '25-login-form');

  await page.click('#authSubmitBtn');
  await page.waitForTimeout(3000);
  await dismissOverlays(page);

  // ═══════════════════════════════════════════════
  // SECTION 26: SEED DATA — FULL POPULATED APP
  // ═══════════════════════════════════════════════
  console.log('━━ 26. SEED DATA SHOWCASE ━━');
  await nav(page, 'dashboard');
  await page.waitForTimeout(3000);
  await shot(page, '26-seed-dashboard-full');

  await page.evaluate(() => window.scrollBy(0, 500));
  await shot(page, '26-seed-nudges-populated', 500);

  await nav(page, 'contacts');
  await page.waitForTimeout(2000);
  await shot(page, '26-seed-contacts-12');

  await nav(page, 'orbit');
  await page.waitForTimeout(3000);
  await shot(page, '26-seed-orbit-populated');

  await nav(page, 'activity');
  await page.waitForTimeout(1500);
  await shot(page, '26-seed-activity-history');

  // ═══════════════════════════════════════════════
  // CLEANUP
  // ═══════════════════════════════════════════════
  console.log('\n━━ CLEANUP ━━');
  // Delete test account (not the seed account)
  await page.evaluate(() => {
    if (typeof logout === 'function') logout();
  });
  await page.waitForTimeout(500);

  // Re-login as test user to delete
  const deleteResult = await page.evaluate(async ({ em, pw }) => {
    try {
      const loginRes = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: em, password: pw }),
      });
      if (!loginRes.ok) return 'login-failed';
      const { access_token } = await loginRes.json();
      const delRes = await fetch('/auth/account', {
        method: 'DELETE',
        headers: { 'Authorization': 'Bearer ' + access_token },
      });
      return delRes.ok ? 'deleted' : 'delete-failed';
    } catch (e) { return 'error: ' + e.message; }
  }, { em: email, pw: password });
  console.log(`  Test account (${email}): ${deleteResult}`);

  // Also clean up the XSS test contact
  await page.evaluate(async () => {
    try {
      const loginRes = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: 'jordan@example.com', password: 'orbit2024demo' }),
      });
      if (loginRes.ok) {
        const { access_token } = await loginRes.json();
        const contacts = await (await fetch('/contacts', { headers: { 'Authorization': 'Bearer ' + access_token } })).json();
        for (const c of contacts) {
          if (c.first_name?.includes('Test') || c.name?.includes('Test')) {
            await fetch(`/contacts/${c.id}`, { method: 'DELETE', headers: { 'Authorization': 'Bearer ' + access_token } });
          }
        }
      }
    } catch {}
  });

  console.log('\n╔══════════════════════════════════════════════╗');
  console.log(`║   COMPLETE — ${shotNum} screenshots captured`);
  console.log(`║   Output: ${DIR}`);
  console.log('╠══════════════════════════════════════════════╣');
  console.log('║   Features Demonstrated:                     ║');
  console.log('║   • Landing page & hero animation             ║');
  console.log('║   • Auth (signup, login, social buttons)      ║');
  console.log('║   • Onboarding flow                           ║');
  console.log('║   • Contact management (add, edit, search)    ║');
  console.log('║   • Interaction logging (UI + API)            ║');
  console.log('║   • Dashboard (stats, nudges, gamification)   ║');
  console.log('║   • Orbit visualization                       ║');
  console.log('║   • Insights & analytics                      ║');
  console.log('║   • Activity feed & leaderboard               ║');
  console.log('║   • Network graph                             ║');
  console.log('║   • Parties & challenges                      ║');
  console.log('║   • Settings & data export                    ║');
  console.log('║   • Light/dark mode toggle                    ║');
  console.log('║   • Privacy policy & terms                    ║');
  console.log('║   • Quest completion & XP rewards             ║');
  console.log('║   • Nudge actions                             ║');
  console.log('║   • Mobile PWA (iPhone 14 viewport)           ║');
  console.log('║   • Tablet view (iPad viewport)               ║');
  console.log('║   • Mobile light mode                         ║');
  console.log('║   • Security (CSP, rate limiting, sanitize)   ║');
  console.log('║   • Service worker & offline mode             ║');
  console.log('║   • PWA manifest & shortcuts                  ║');
  console.log('║   • Seed data showcase (12 contacts)          ║');
  console.log('╚══════════════════════════════════════════════╝\n');

  await browser.close();
})();
