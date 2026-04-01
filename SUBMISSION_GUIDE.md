# Orbit - App Store Submission Guide

## Prerequisites

### One-time Setup

1. **Apple Developer Account** ($99/year)
   - Enroll at https://developer.apple.com/enroll
   - Note your Team ID from Membership page

2. **Google Play Developer Account** ($25 one-time)
   - Register at https://play.google.com/console/signup
   - Create your app listing

3. **Install Tools** (macOS)
   ```bash
   # Xcode (from Mac App Store)
   xcode-select --install

   # CocoaPods
   sudo gem install cocoapods

   # fastlane
   brew install fastlane

   # Android Studio (for SDK & JDK)
   brew install --cask android-studio

   # After Android Studio install, accept licenses:
   yes | sdkmanager --licenses
   ```

---

## iOS: TestFlight Submission

### Step 1: Configure Signing

1. Open Xcode: `npm run cap:ios`
2. Select the **App** target > **Signing & Capabilities**
3. Set your Team (your Apple Developer account)
4. Ensure Bundle ID is `io.orbitapp.app`
5. Enable these capabilities:
   - Push Notifications
   - Sign in with Apple
6. Xcode will auto-create provisioning profiles

### Step 2: Create App in App Store Connect

1. Go to https://appstoreconnect.apple.com
2. My Apps > "+" > New App
3. Fill in:
   - Platform: iOS
   - Name: **Orbit - Relationship Keeper**
   - Primary Language: English (U.S.)
   - Bundle ID: `io.orbitapp.app`
   - SKU: `orbit-ios-001`

### Step 3: Build & Upload

**Option A: Using fastlane (recommended)**
```bash
# Set environment variables
export APPLE_ID="your@apple.id"
export APPLE_TEAM_ID="YOUR_TEAM_ID"

# Build and upload
fastlane ios beta
```

**Option B: Manual**
```bash
npm run build:ios
# Then use Transporter.app to upload the IPA
```

**Option C: Xcode**
1. `npm run cap:ios` (opens Xcode)
2. Product > Archive
3. Distribute App > App Store Connect > Upload

### Step 4: TestFlight Setup

1. In App Store Connect > TestFlight
2. The build appears after processing (~15 min)
3. Add internal testers (your team)
4. Add external testers (up to 10,000)
5. Fill in test information:
   - Beta App Description: "Test the latest Orbit features"
   - Contact: your email
   - Privacy URL: https://orbit-app-production-fd37.up.railway.app/privacy

### Step 5: Submit for App Review

1. In App Store Connect > App Store tab
2. Fill in all fields using `store-listing/metadata.json`
3. Upload screenshots from `store-listing/screenshots/ios-*.png`
4. Set pricing (Free)
5. App Review Information:
   - Demo account: jordan@example.com / orbit2024demo
   - Notes: "This app requires an internet connection."
6. Submit for Review

---

## Android: Play Console Submission

### Step 1: Create Signing Key

```bash
cd android

# Generate release signing key
keytool -genkey -v \
  -keystore orbit-release-key.jks \
  -keyalg RSA -keysize 2048 \
  -validity 10000 \
  -alias orbit \
  -storepass YOUR_STORE_PASSWORD \
  -keypass YOUR_KEY_PASSWORD

# Create keystore.properties
cp keystore.properties.example keystore.properties
# Edit keystore.properties with your passwords

cd ..
```

### Step 2: Create App in Play Console

1. Go to https://play.google.com/console
2. Create App
3. Fill in:
   - App name: **Orbit - Relationship Keeper**
   - Default language: English (United States)
   - App or Game: App
   - Free or Paid: Free

### Step 3: Build

**Option A: Using fastlane**
```bash
# Set up Play Store API key (for automated upload)
# See: https://docs.fastlane.tools/actions/supply/#setup

fastlane android beta
```

**Option B: Manual**
```bash
npm run build:android
# AAB will be at: android/app/build/outputs/bundle/release/app-release.aab
```

### Step 4: Upload to Play Console

1. Go to Testing > Internal testing
2. Create new release
3. Upload `app-release.aab`
4. Add release notes from `fastlane/metadata/en-US/release_notes.txt`
5. Save and roll out

### Step 5: Complete Store Listing

1. Main store listing:
   - Use description from `fastlane/metadata/en-US/description.txt`
   - Upload screenshots from `store-listing/screenshots/android-*.png`
   - Upload icon from `icon-512.png`
   - Feature graphic: create a 1024x500 banner
2. Content rating questionnaire
3. Data safety questionnaire:
   - Data collected: Email, Name, Contacts (optional), Location (optional)
   - Data shared: None
   - Encryption: Yes (HTTPS)
4. Set up pricing (Free)

### Step 6: Submit for Review

1. Go to Publishing overview
2. Send changes for review
3. Review typically takes 1-3 days

---

## Environment Variables Reference

### Railway (Backend)
```
JWT_SECRET=<generated-secret>
SENTRY_DSN=<optional-sentry-dsn>
RESEND_API_KEY=<for-email-sending>
FIREBASE_CREDENTIALS_JSON=<for-push-notifications>
CRON_API_KEY=<for-scheduled-nudges>
APPLE_CLIENT_ID=io.orbitapp.app
GOOGLE_CLIENT_ID=<from-google-cloud-console>
ALLOWED_ORIGINS=https://orbit-app-production-fd37.up.railway.app,capacitor://localhost,http://localhost
```

### Local Build
```
APPLE_ID=your@apple.id
APPLE_TEAM_ID=XXXXXXXXXX
ITC_TEAM_ID=XXXXXXXXXX
PLAY_STORE_JSON_KEY=play-store-key.json
```

---

## Checklist

### Before Submission
- [ ] Privacy Policy accessible at /privacy
- [ ] Terms of Service accessible at /terms
- [ ] Email verification working
- [ ] Forgot password working
- [ ] Sign in with Apple configured in Apple Developer portal
- [ ] Google Sign In configured in Google Cloud Console
- [ ] Push notifications tested (FCM key in Railway)
- [ ] App icon looks good at small sizes (29x29)
- [ ] Screenshots are current and accurate
- [ ] Demo account works: jordan@example.com / orbit2024demo

### iOS Specific
- [ ] App ID registered in Apple Developer portal
- [ ] Push Notifications capability enabled
- [ ] Sign in with Apple capability enabled
- [ ] App created in App Store Connect
- [ ] Build uploaded and processed
- [ ] TestFlight testers added

### Android Specific
- [ ] Release signing key generated and backed up securely
- [ ] keystore.properties configured
- [ ] App created in Play Console
- [ ] Content rating questionnaire completed
- [ ] Data safety form completed
- [ ] AAB uploaded to internal testing track
