/**
 * Orbit Native Bridge
 * Initializes Capacitor plugins when running in a native context.
 * This file is a no-op when running in a web browser.
 */
(function() {
  'use strict';

  // Only run in native Capacitor context
  if (!window.Capacitor || !window.Capacitor.isNativePlatform()) {
    console.log('[Orbit] Running in web browser mode');
    return;
  }

  console.log('[Orbit] Running in native mode — initializing plugins');

  // Wait for Capacitor to be fully ready
  document.addEventListener('DOMContentLoaded', async () => {

    // ── Status Bar ──
    try {
      const { StatusBar } = await import('@capacitor/status-bar');
      await StatusBar.setStyle({ style: 'DARK' });
      await StatusBar.setBackgroundColor({ color: '#0a0a1a' });
      console.log('[Orbit] StatusBar configured');
    } catch (e) {
      console.warn('[Orbit] StatusBar not available:', e.message);
    }

    // ── Push Notifications ──
    try {
      const { PushNotifications } = await import('@capacitor/push-notifications');

      // Request permission
      const permResult = await PushNotifications.requestPermissions();
      if (permResult.receive === 'granted') {
        await PushNotifications.register();
        console.log('[Orbit] Push notifications registered');
      }

      // Handle registration success — send token to backend
      PushNotifications.addListener('registration', async (token) => {
        console.log('[Orbit] Push token:', token.value);
        const authToken = localStorage.getItem('orbit_token');
        if (authToken) {
          try {
            await fetch('https://orbit-app-production-fd37.up.railway.app/auth/push-token', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + authToken,
              },
              body: JSON.stringify({
                token: token.value,
                platform: window.Capacitor.getPlatform(),
              }),
            });
          } catch (e) {
            console.warn('[Orbit] Failed to register push token:', e.message);
          }
        }
      });

      // Handle push notification received while app is open
      PushNotifications.addListener('pushNotificationReceived', (notification) => {
        console.log('[Orbit] Push received:', notification.title);
        // Show as an in-app toast
        if (typeof showToast === 'function') {
          showToast(notification.title + ': ' + (notification.body || ''), 'info');
        }
      });

      // Handle push notification tap — navigate to relevant page
      PushNotifications.addListener('pushNotificationActionPerformed', (action) => {
        const data = action.notification.data;
        if (data && data.page && typeof navigateTo === 'function') {
          navigateTo(data.page);
        }
      });

    } catch (e) {
      console.warn('[Orbit] Push notifications not available:', e.message);
    }

    // ── Haptics ──
    try {
      const { Haptics, ImpactStyle } = await import('@capacitor/haptics');
      // Expose haptic feedback globally for UI interactions
      window.orbitHaptic = async (style) => {
        try {
          await Haptics.impact({ style: style || ImpactStyle.Light });
        } catch (e) { /* ignore */ }
      };
      console.log('[Orbit] Haptics ready');
    } catch (e) {
      // No-op in web
      window.orbitHaptic = () => {};
    }

    // ── Sign In With Apple (native) ──
    try {
      const mod = await import('@nicedigital/capacitor-sign-in-with-apple');
      if (mod?.SignInWithApple) {
        window.Capacitor.Plugins.SignInWithApple = mod.SignInWithApple;
        console.log('[Orbit] Sign In With Apple ready');
      }
    } catch (e) {
      console.log('[Orbit] Sign In With Apple plugin not available');
    }

    // ── Google Auth (native) ──
    try {
      const mod = await import('@nicedigital/capacitor-google-auth');
      if (mod?.GoogleAuth) {
        await mod.GoogleAuth.initialize();
        window.Capacitor.Plugins.GoogleAuth = mod.GoogleAuth;
        console.log('[Orbit] Google Auth ready');
      }
    } catch (e) {
      console.log('[Orbit] Google Auth plugin not available');
    }

    // ── Splash Screen ──
    try {
      const { SplashScreen } = await import('@capacitor/splash-screen');
      // Hide splash after app is loaded
      setTimeout(() => SplashScreen.hide(), 500);
      console.log('[Orbit] Splash screen hidden');
    } catch (e) {
      console.warn('[Orbit] SplashScreen not available:', e.message);
    }

  });
})();
