/**
 * Orbit — Final Comprehensive Demo
 * Showcases every feature end-to-end with screenshots
 */
import { chromium } from 'playwright';
import { join } from 'path';

const BASE = 'https://orbit-app-production-fd37.up.railway.app';
const DIR = join(process.cwd(), 'demo-screenshots', 'final');
let shotNum = 0;

async function dismissOverlays(page) {
  await page.evaluate(() => {
    // Dismiss reward overlay
    const reward = document.getElementById('rewardOverlay');
    if (reward && reward.classList.contains('active')) {
      reward.classList.remove('active');
    }
    // Dismiss onboarding overlay
    const onboard = document.getElementById('onboardingOverlay');
    if (onboard) onboard.remove();
    // Dismiss any modal overlays
    document.querySelectorAll('.modal-overlay.active').forEach(m => m.classList.remove('active'));
    // Dismiss any toast
    document.querySelectorAll('.toast').forEach(t => t.remove());
  });
  await page.waitForTimeout(300);
}

async function shot(page, name, delay = 600) {
  await page.waitForTimeout(delay);
  shotNum++;
  const file = join(DIR, `${String(shotNum).padStart(2, '0')}-${name}.png`);
  await page.screenshot({ path: file, fullPage: false });
  console.log(`  [${shotNum}] ${name}`);
}

async function nav(page, pageName) {
  await dismissOverlays(page);
  // Click the first visible nav button for this page
  const btns = page.locator(`[data-page="${pageName}"]`);
  for (const btn of await btns.all()) {
    if (await btn.isVisible()) {
      await btn.click();
      return;
    }
  }
  // Fallback: use JS navigation
  await page.evaluate((p) => { if (typeof navigateTo === 'function') navigateTo(p); }, pageName);
}

(async () => {
  const { mkdirSync } = await import('fs');
  mkdirSync(DIR, { recursive: true });

  const browser = await chromium.launch({ headless: false, slowMo: 60 });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  const email = `demo-${Date.now()}@orbit.app`;
  const password = 'OrbitDemo2026!';

  console.log('\n======================================');
  console.log('  ORBIT — FINAL FEATURE SHOWCASE');
  console.log('======================================\n');

  // =======================================
  // 1. LANDING PAGE
  // =======================================
  console.log('-- Landing Page --');
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  await shot(page, 'landing-hero');

  await page.evaluate(() => {
    const el = document.querySelector('.landing-features');
    if (el) el.scrollIntoView({ behavior: 'instant' });
  });
  await shot(page, 'landing-features', 800);

  // =======================================
  // 2. SIGNUP FLOW
  // =======================================
  console.log('-- Signup --');
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(300);

  // Click "Get Started Free" button
  await page.locator('text=Get Started Free').first().click();
  await page.waitForSelector('#authModal.active', { timeout: 5000 });
  await page.waitForTimeout(500);
  await shot(page, 'signup-modal');

  await page.fill('#authName', 'Alex Rivera');
  await page.fill('#authEmail', email);
  await page.fill('#authPass', password);
  await shot(page, 'signup-filled');

  await page.click('#authSubmitBtn');
  await page.waitForTimeout(3500);

  // Handle onboarding overlay — screenshot it then dismiss
  const onboarding = page.locator('#onboardingOverlay');
  if (await onboarding.isVisible({ timeout: 3000 }).catch(() => false)) {
    await shot(page, 'onboarding-welcome');
    // Click through a couple steps for screenshots
    const nextBtn = page.locator('button', { hasText: 'Next' }).first();
    if (await nextBtn.isVisible()) {
      await nextBtn.click();
      await page.waitForTimeout(500);
      await shot(page, 'onboarding-step2');
    }
    // Skip the rest
    await page.evaluate(() => { if (typeof finishOnboarding === 'function') finishOnboarding(); });
    await page.waitForTimeout(500);
  }

  await shot(page, 'dashboard-fresh');

  // =======================================
  // 3. ADD CONTACTS
  // =======================================
  console.log('-- Adding Contacts --');
  const contacts = [
    { first: 'Sarah', last: 'Chen', type: 'Friend', freq: 'weekly', notes: 'Best friend, designer at Figma, loves hiking' },
    { first: 'Mom', last: '', type: 'Family', freq: 'weekly', notes: 'Book club Thursdays, planning garden for spring' },
    { first: 'Marcus', last: 'Williams', type: 'Friend', freq: 'biweekly', notes: 'College roommate, PM at Google, expecting first child' },
    { first: 'David', last: 'Park', type: 'Mentor', freq: 'monthly', notes: 'VP Eng at Datadog, career mentor' },
    { first: 'Priya', last: 'Patel', type: 'Friend', freq: 'biweekly', notes: 'Yoga class friend, training for marathon' },
    { first: 'Emma', last: 'Kim', type: 'Family', freq: 'weekly', notes: 'Sister, finishing grad school in May' },
  ];

  for (let i = 0; i < contacts.length; i++) {
    const c = contacts[i];
    // Click "Add Person" button
    await dismissOverlays(page);
    const addBtn = page.locator('button', { hasText: 'Add Person' }).first();
    await addBtn.click();
    await page.waitForSelector('#addModal.active', { timeout: 3000 });
    await page.waitForTimeout(300);

    await page.fill('#firstName', c.first);
    await page.fill('#lastName', c.last);
    await page.selectOption('#relationship', c.type);

    // Click the frequency tag
    await page.click(`#frequencyTags .form-tag[data-val="${c.freq}"]`);
    await page.fill('#personNotes', c.notes);

    if (i === 0) await shot(page, 'add-contact-sarah');

    // Click "Add to Orbit"
    await page.locator('button', { hasText: 'Add to Orbit' }).click();
    await page.waitForTimeout(2000);
  }
  await shot(page, 'six-contacts-added');

  // =======================================
  // 4. LOG INTERACTIONS (multiple via API)
  // =======================================
  console.log('-- Logging Interactions --');
  const token = await page.evaluate(() => localStorage.getItem('orbit_token'));
  const contactsData = await page.evaluate(async () => {
    const res = await fetch('/contacts', { headers: { 'Authorization': 'Bearer ' + localStorage.getItem('orbit_token') } });
    return res.json();
  });

  // Log interactions via API for speed
  for (const c of contactsData.slice(0, 4)) {
    const types = ['call', 'text', 'in_person', 'video_call'];
    for (let j = 0; j < 3; j++) {
      await page.evaluate(async ({ cid, itype, dur }) => {
        await fetch('/interactions', {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + localStorage.getItem('orbit_token'), 'Content-Type': 'application/json' },
          body: JSON.stringify({ contact_id: cid, interaction_type: itype, duration_minutes: dur, initiated_by_user: true }),
        });
      }, { cid: c.id, itype: types[j % types.length], dur: 10 + j * 15 });
    }
  }

  // Now use the UI to log one interaction for the screenshot
  // Navigate to dashboard first to find the Log Interaction button
  await dismissOverlays(page);
  await nav(page, 'dashboard');
  await page.waitForTimeout(1500);

  // Open log modal via JS since button location may vary
  await page.evaluate(() => {
    if (typeof openLogModal === 'function') openLogModal();
    else document.getElementById('logModal')?.classList.add('active');
  });
  await page.waitForTimeout(800);

  // Select contact in dropdown
  const logContactSelect = page.locator('#logContact');
  if (await logContactSelect.isVisible()) {
    // Select first option that has a value
    await page.evaluate(() => {
      const sel = document.getElementById('logContact');
      if (sel && sel.options.length > 1) sel.selectedIndex = 1;
    });
  }

  // Click "Video" tag
  await page.click('#logTypeTags .form-tag[data-val="video_call"]');
  await page.fill('#logDuration', '30');
  await page.fill('#logNotes', 'Career advice session - discussed switching to product management');
  await shot(page, 'log-interaction-modal');

  await page.click('#logSubmitBtn');
  await page.waitForTimeout(2500);

  // Reload dashboard to reflect all interactions
  await nav(page, 'dashboard');
  await page.waitForTimeout(3000);
  await shot(page, 'dashboard-with-interactions');

  // =======================================
  // 5. CONTACT DETAIL PANEL
  // =======================================
  console.log('-- Contact Detail Panel --');
  await nav(page, 'contacts');
  await page.waitForTimeout(1500);

  const firstCard = page.locator('.contact-card').first();
  if (await firstCard.isVisible()) {
    await firstCard.click();
    await page.waitForTimeout(2000);
    await shot(page, 'contact-detail-health');

    // Scroll detail body to see AI starters
    await page.evaluate(() => {
      const panel = document.querySelector('.detail-body');
      if (panel) panel.scrollTop = 200;
    });
    await shot(page, 'contact-detail-ai-starters', 500);

    // Scroll to bottom for edit/delete
    await page.evaluate(() => {
      const panel = document.querySelector('.detail-body');
      if (panel) panel.scrollTop = panel.scrollHeight;
    });
    await shot(page, 'contact-detail-manage', 500);

    // Try opening edit modal
    const editBtn = page.locator('button', { hasText: 'Edit' }).first();
    if (await editBtn.isVisible()) {
      await editBtn.click();
      await page.waitForTimeout(600);
      await shot(page, 'edit-contact-modal');
      // Close edit modal
      const cancelBtn = page.locator('button', { hasText: 'Cancel' }).first();
      if (await cancelBtn.isVisible()) await cancelBtn.click();
      await page.waitForTimeout(300);
    }

    await page.click('.detail-close');
    await page.waitForTimeout(300);
  }

  // =======================================
  // 6. DASHBOARD — FULL VIEW
  // =======================================
  console.log('-- Dashboard Full --');
  await nav(page, 'dashboard');
  await page.waitForTimeout(2500);
  await shot(page, 'dashboard-stats');

  // Scroll to nudges
  await page.evaluate(() => window.scrollBy(0, 500));
  await shot(page, 'dashboard-nudges', 600);

  // =======================================
  // 7. ORBIT VISUALIZATION
  // =======================================
  console.log('-- Orbit View --');
  await nav(page, 'orbit');
  await page.waitForTimeout(2500);
  await shot(page, 'orbit-visualization');

  // =======================================
  // 8. INSIGHTS
  // =======================================
  console.log('-- Insights --');
  await nav(page, 'insights');
  await page.waitForTimeout(2000);
  await shot(page, 'insights-report');

  // =======================================
  // 9. ACTIVITY FEED
  // =======================================
  console.log('-- Activity --');
  await nav(page, 'activity');
  await page.waitForTimeout(1500);
  await shot(page, 'activity-feed');

  // =======================================
  // 10. NETWORK GRAPH
  // =======================================
  console.log('-- Network --');
  await nav(page, 'network');
  await page.waitForTimeout(2500);
  await shot(page, 'network-graph');

  // =======================================
  // 11. GAMIFICATION — SOLO LEVELING
  // =======================================
  console.log('-- Gamification --');
  await nav(page, 'dashboard');
  await page.waitForTimeout(2000);

  // Scroll to gamification section
  await page.evaluate(() => {
    const sections = document.querySelectorAll('.section-title, h2, h3');
    for (const s of sections) {
      if (s.textContent.includes('Hunter') || s.textContent.includes('Rank') || s.textContent.includes('Quest')) {
        s.scrollIntoView({ behavior: 'instant', block: 'start' });
        return;
      }
    }
    window.scrollBy(0, 800);
  });
  await page.waitForTimeout(600);
  await shot(page, 'gamification-rank-stats');

  await page.evaluate(() => window.scrollBy(0, 450));
  await shot(page, 'gamification-quests', 500);

  await page.evaluate(() => window.scrollBy(0, 450));
  await shot(page, 'gamification-achievements', 500);

  // =======================================
  // 12. SETTINGS PAGE
  // =======================================
  console.log('-- Settings --');
  await nav(page, 'settings');
  await page.waitForTimeout(1000);
  await shot(page, 'settings-profile');

  await page.evaluate(() => window.scrollBy(0, 350));
  await shot(page, 'settings-password-change', 500);

  await page.evaluate(() => window.scrollBy(0, 400));
  await shot(page, 'settings-data-export');

  await page.evaluate(() => window.scrollBy(0, 300));
  await shot(page, 'settings-danger-zone', 500);

  // =======================================
  // 13. LIGHT MODE
  // =======================================
  console.log('-- Light Mode --');
  await nav(page, 'dashboard');
  await page.waitForTimeout(1500);

  await page.click('#themeToggleBtn');
  await page.waitForTimeout(800);
  await shot(page, 'light-mode-dashboard');

  await nav(page, 'contacts');
  await page.waitForTimeout(1000);
  await shot(page, 'light-mode-contacts');

  await nav(page, 'orbit');
  await page.waitForTimeout(2000);
  await shot(page, 'light-mode-orbit');

  // Back to dark
  await page.click('#themeToggleBtn');
  await page.waitForTimeout(500);

  // =======================================
  // 14. MOBILE RESPONSIVE
  // =======================================
  console.log('-- Mobile View --');
  await page.setViewportSize({ width: 390, height: 844 });

  await nav(page, 'dashboard');
  await page.waitForTimeout(2000);
  await shot(page, 'mobile-dashboard');

  await page.evaluate(() => window.scrollBy(0, 400));
  await shot(page, 'mobile-dashboard-scroll', 500);

  // Navigate to contacts on mobile
  await nav(page, 'contacts');
  await page.waitForTimeout(1500);
  await shot(page, 'mobile-contacts');

  // Tap a card
  const mobCard = page.locator('.contact-card').first();
  if (await mobCard.isVisible()) {
    await mobCard.click();
    await page.waitForTimeout(1500);
    await shot(page, 'mobile-detail-panel');
    await page.click('.detail-close');
    await page.waitForTimeout(300);
  }

  // Mobile orbit
  await nav(page, 'orbit');
  await page.waitForTimeout(2000);
  await shot(page, 'mobile-orbit-view');

  // Reset
  await page.setViewportSize({ width: 1440, height: 900 });

  // =======================================
  // CLEANUP
  // =======================================
  console.log('-- Cleanup --');
  await page.evaluate(async () => {
    const t = localStorage.getItem('orbit_token');
    if (t) await fetch('/auth/account', {
      method: 'DELETE',
      headers: { 'Authorization': 'Bearer ' + t, 'Content-Type': 'application/json' },
    });
  });
  console.log('  Test account deleted');

  console.log('\n======================================');
  console.log(`  DONE — ${shotNum} screenshots captured`);
  console.log(`  ${DIR}`);
  console.log('======================================\n');

  await browser.close();
})();
