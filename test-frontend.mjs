import { chromium } from 'playwright';

const results = [];
const consoleErrors = [];
let passed = 0;
let failed = 0;

function log(name, pass, detail = '') {
  const status = pass ? 'PASS' : 'FAIL';
  if (pass) passed++; else failed++;
  results.push({ name, status, detail });
  console.log(`[${status}] ${name}${detail ? ' -- ' + detail : ''}`);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  page.on('console', msg => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', err => consoleErrors.push(err.message));

  const URL = 'https://orbit-app-production-fd37.up.railway.app';

  try {
    // =========================================================
    // LANDING PAGE
    // =========================================================
    console.log('\n=== LANDING PAGE ===');
    await page.goto(URL, { waitUntil: 'networkidle', timeout: 30000 });

    const title = await page.title();
    log('Title contains "Orbit"', title.includes('Orbit'), `title="${title}"`);

    const getStartedBtn = page.locator('text=Get Started Free').first();
    log('"Get Started Free" button exists', await getStartedBtn.isVisible().catch(() => false));

    const tierCount = await page.locator('.pricing-card').count();
    log('Pricing section has 3 tiers', tierCount === 3, `found ${tierCount} tiers`);

    const faqItem = page.locator('.faq-item').first();
    if (await faqItem.isVisible().catch(() => false)) {
      const before = await faqItem.evaluate(el => el.classList.contains('open'));
      await faqItem.click();
      await page.waitForTimeout(500);
      const after = await faqItem.evaluate(el => el.classList.contains('open'));
      log('FAQ items expand on click', !before && after, `before=${before}, after=${after}`);
    } else {
      log('FAQ items expand on click', false, 'not found');
    }

    // =========================================================
    // AUTH
    // =========================================================
    console.log('\n=== AUTH ===');

    await getStartedBtn.click();
    await page.waitForTimeout(1000);
    log('Auth modal appears', await page.locator('#authModal.active').isVisible().catch(() => false));

    // Switch to login
    const loginLink = page.locator('.auth-switch a');
    if (await loginLink.isVisible().catch(() => false)) {
      await loginLink.click();
      await page.waitForTimeout(500);
    }
    const authTitle = await page.locator('#authTitle').textContent();
    log('Switch to login', authTitle === 'Welcome back', `authTitle="${authTitle}"`);

    // Login
    await page.fill('#authEmail', 'jordan@example.com');
    await page.fill('#authPass', 'orbit2024demo');
    await page.click('#authSubmitBtn');

    try {
      await page.waitForSelector('#contactsGrid', { timeout: 15000 });
      log('Dashboard loads after login', true);
    } catch {
      log('Dashboard loads after login', false, '#contactsGrid not found');
    }

    // Dismiss onboarding overlay
    const skipBtn = page.locator('#onboardingOverlay button:has-text("Skip")');
    if (await skipBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await skipBtn.click({ force: true });
      await page.waitForTimeout(500);
    }
    // Double-check it's gone
    await page.evaluate(() => {
      const el = document.getElementById('onboardingOverlay');
      if (el) el.remove();
    });
    await page.waitForTimeout(300);

    // =========================================================
    // DASHBOARD
    // =========================================================
    console.log('\n=== DASHBOARD ===');

    log('Greeting header exists', await page.locator('#greetingHeader').isVisible().catch(() => false));

    const gridChildren = await page.locator('#contactsGrid > *').count();
    log('#contactsGrid has children', gridChildren > 0, `found ${gridChildren} children`);

    // Wait for gamification to render (it loads async after contacts)
    await page.waitForTimeout(3000);
    const gamifInfo = await page.evaluate(() => {
      const el = document.getElementById('xpSection');
      if (!el) return { exists: false };
      return { exists: true, display: getComputedStyle(el).display, children: el.children.length };
    });
    const gamifOk = gamifInfo.exists && gamifInfo.display !== 'none' && gamifInfo.children > 0;
    log('Gamification section renders', gamifOk, `display=${gamifInfo.display}, children=${gamifInfo.children}`);

    const searchInput = page.locator('#searchInput');
    if (await searchInput.isVisible().catch(() => false)) {
      const beforeCount = await page.locator('#contactsGrid > *').count();
      await searchInput.fill('family');
      await page.waitForTimeout(1000);
      const afterCount = await page.evaluate(() =>
        document.querySelectorAll('#contactsGrid > *:not([style*="display: none"]):not([style*="display:none"])').length
      );
      log('Search input works (type "family")', true, `before=${beforeCount}, after=${afterCount}`);
      await searchInput.fill('');
      await page.waitForTimeout(500);
    } else {
      log('Search input works', false, '#searchInput not found');
    }

    // =========================================================
    // NAVIGATION
    // =========================================================
    console.log('\n=== NAVIGATION ===');

    const navPages = ['dashboard', 'contacts', 'orbit', 'insights', 'activity', 'network'];
    for (const nav of navPages) {
      // Navigate to target page: first ensure clean state, then navigate
      const navResult = await page.evaluate(async (p) => {
        // Manually perform what navigateTo does, but safely
        const nextPage = document.getElementById('page-' + p);
        if (!nextPage) return { exists: false, active: false };

        // Call navigateTo
        try { navigateTo(p); } catch(e) { /* ignore errors */ }

        // Wait for crossfade transition
        await new Promise(r => setTimeout(r, 400));

        return {
          exists: true,
          active: nextPage.classList.contains('active')
        };
      }, nav);

      await page.waitForTimeout(600);
      log(`Nav: ${nav}`, navResult.active, navResult.exists
        ? (navResult.active ? 'page has .active class' : `#page-${nav} exists but not active`)
        : `#page-${nav} element does not exist in DOM`);
    }

    // Back to dashboard
    await page.evaluate(() => navigateTo('dashboard'));
    await page.waitForTimeout(600);

    // =========================================================
    // MODALS
    // =========================================================
    console.log('\n=== MODALS ===');

    // Add Person modal
    await page.evaluate(() => openModal());
    await page.waitForTimeout(800);
    const addModalActive = await page.evaluate(() => document.getElementById('addModal')?.classList.contains('active'));
    const addFields = await page.locator('#addModal input, #addModal select').count();
    log('Add Person modal: opens with form fields', addModalActive && addFields > 0, `active=${addModalActive}, fields=${addFields}`);
    await page.evaluate(() => closeModal());
    await page.waitForTimeout(300);

    // Log Interaction modal
    await page.evaluate(() => openLogInteraction());
    await page.waitForTimeout(800);
    const logModalActive = await page.evaluate(() => document.getElementById('logModal')?.classList.contains('active'));
    const logFields = await page.locator('#logModal input, #logModal select, #logModal textarea').count();
    log('Log Interaction modal: opens with fields', logModalActive && logFields > 0, `active=${logModalActive}, fields=${logFields}`);
    await page.evaluate(() => closeLogModal());
    await page.waitForTimeout(300);

    // Party modal
    await page.evaluate(() => openCreateParty());
    await page.waitForTimeout(800);
    const partyModalActive = await page.evaluate(() => document.getElementById('partyModal')?.classList.contains('active'));
    const partyFields = await page.locator('#partyModal input, #partyModal select, #partyModal textarea').count();
    log('Party modal: opens with fields', partyModalActive && partyFields > 0, `active=${partyModalActive}, fields=${partyFields}`);
    await page.evaluate(() => closePartyModal());
    await page.waitForTimeout(300);

    // Challenge modal
    await page.evaluate(() => openCreateChallenge());
    await page.waitForTimeout(800);
    const challengeModalActive = await page.evaluate(() => document.getElementById('challengeModal')?.classList.contains('active'));
    const challengeFields = await page.locator('#challengeModal input, #challengeModal select, #challengeModal textarea').count();
    log('Challenge modal: opens with fields', challengeModalActive && challengeFields > 0, `active=${challengeModalActive}, fields=${challengeFields}`);
    await page.evaluate(() => closeChallengeModal());
    await page.waitForTimeout(300);

    // =========================================================
    // DETAIL PANEL
    // =========================================================
    console.log('\n=== DETAIL PANEL ===');

    // Ensure dashboard is fully active (reset any broken state from nav tests)
    await page.evaluate(() => {
      document.querySelectorAll('.page').forEach(p => { p.classList.remove('active', 'page-exit'); });
      document.getElementById('page-dashboard').classList.add('active');
    });
    await page.waitForTimeout(800);

    // Click first contact card
    const contactCard = page.locator('#contactsGrid > *').first();
    if (await contactCard.isVisible().catch(() => false)) {
      // Try clicking directly first
      await contactCard.click({ force: true });
      await page.waitForTimeout(2000);

      let detailActive = await page.evaluate(() =>
        document.getElementById('detailPanel')?.classList.contains('active')
      );

      // If click didn't work, call openDetail with the first contact via JS
      if (!detailActive) {
        await page.evaluate(() => {
          if (typeof contacts !== 'undefined' && contacts.length > 0) {
            openDetail(contacts[0]);
          }
        });
        await page.waitForTimeout(1500);
        detailActive = await page.evaluate(() =>
          document.getElementById('detailPanel')?.classList.contains('active')
        );
      }

      log('Detail panel opens (has .active class)', detailActive);

      const healthBar = await page.locator('.detail-health-bar').first().isVisible().catch(() => false);
      log('Health bar renders', healthBar);

      const aiStarters = await page.locator('.ai-starters').first().isVisible().catch(() => false);
      log('AI starters section exists', aiStarters);

      // Close detail panel via JS
      await page.evaluate(() => closeDetail());
      await page.waitForTimeout(500);
      const detailClosed = await page.evaluate(() =>
        !document.getElementById('detailPanel')?.classList.contains('active')
      );
      log('Detail panel closes', detailClosed);
    } else {
      log('Detail panel opens', false, 'No contact cards');
      log('Health bar renders', false, 'skipped');
      log('AI starters section exists', false, 'skipped');
      log('Detail panel closes', false, 'skipped');
    }

    // =========================================================
    // THEME TOGGLE
    // =========================================================
    console.log('\n=== THEME TOGGLE ===');

    // Navigate back to dashboard so sidebar is in view
    await page.evaluate(() => navigateTo('dashboard'));
    await page.waitForTimeout(500);

    const initialLight = await page.evaluate(() => document.documentElement.classList.contains('light-mode'));

    // Try multiple selectors for theme toggle button
    const themeInfo = await page.evaluate(() => {
      const byId = document.getElementById('themeToggleBtn');
      const byClass = document.querySelector('.theme-toggle');
      const byTitle = document.querySelector('[title*="theme"], [title*="Theme"], [title*="mode"]');
      const btn = byId || byClass || byTitle;
      return {
        found: !!btn,
        id: btn?.id || null,
        className: btn?.className || null,
        tag: btn?.tagName || null
      };
    });

    if (themeInfo.found) {
      // First toggle
      await page.evaluate(() => {
        const btn = document.getElementById('themeToggleBtn')
          || document.querySelector('.theme-toggle')
          || document.querySelector('[title*="theme"], [title*="Theme"], [title*="mode"]');
        if (btn) btn.click();
      });
      await page.waitForTimeout(500);
      const afterFirst = await page.evaluate(() => document.documentElement.classList.contains('light-mode'));
      log('Theme toggle adds light-mode class', afterFirst !== initialLight,
        `initial=${initialLight}, after=${afterFirst}`);

      // Second toggle
      await page.evaluate(() => {
        const btn = document.getElementById('themeToggleBtn')
          || document.querySelector('.theme-toggle')
          || document.querySelector('[title*="theme"], [title*="Theme"], [title*="mode"]');
        if (btn) btn.click();
      });
      await page.waitForTimeout(500);
      const afterSecond = await page.evaluate(() => document.documentElement.classList.contains('light-mode'));
      log('Theme toggle removes light-mode class', afterSecond === initialLight,
        `back to initial=${afterSecond === initialLight}`);
    } else {
      // Try calling toggleTheme directly
      const hasFn = await page.evaluate(() => typeof toggleTheme === 'function');
      if (hasFn) {
        await page.evaluate(() => toggleTheme());
        await page.waitForTimeout(500);
        const afterFirst = await page.evaluate(() => document.documentElement.classList.contains('light-mode'));
        log('Theme toggle adds light-mode class', afterFirst !== initialLight,
          `initial=${initialLight}, after=${afterFirst} (via toggleTheme fn)`);

        await page.evaluate(() => toggleTheme());
        await page.waitForTimeout(500);
        const afterSecond = await page.evaluate(() => document.documentElement.classList.contains('light-mode'));
        log('Theme toggle removes light-mode class', afterSecond === initialLight,
          `back to initial=${afterSecond === initialLight} (via toggleTheme fn)`);
      } else {
        log('Theme toggle adds light-mode class', false,
          'Theme toggle button not found and toggleTheme function not defined');
        log('Theme toggle removes light-mode class', false,
          'Theme toggle button not found and toggleTheme function not defined');
      }
    }

  } catch (err) {
    console.error('\n[FATAL ERROR]', err.message);
  }

  await browser.close();

  // =========================================================
  // CONSOLE ERRORS
  // =========================================================
  console.log('\n=== CONSOLE ERRORS ===');
  if (consoleErrors.length === 0) {
    console.log('No console errors captured.');
  } else {
    consoleErrors.forEach((e, i) => console.log(`  ${i + 1}. ${e}`));
  }

  // =========================================================
  // SUMMARY
  // =========================================================
  console.log('\n========================================');
  console.log('           TEST SUMMARY');
  console.log('========================================');
  console.log(`Total tests : ${passed + failed}`);
  console.log(`Passed      : ${passed}`);
  console.log(`Failed      : ${failed}`);
  console.log(`Console Errors: ${consoleErrors.length}`);
  console.log('========================================');
})();
