#!/bin/bash
set -e

echo "=== Orbit iOS Build ==="

# 1. Sync web assets
echo "Step 1: Syncing web assets..."
npm run cap:sync

# 2. Install CocoaPods
echo "Step 2: Installing CocoaPods dependencies..."
cd ios/App
pod install --repo-update
cd ../..

# 3. Build archive
echo "Step 3: Building archive..."
xcodebuild archive \
  -workspace ios/App/App.xcworkspace \
  -scheme App \
  -archivePath build/ios/Orbit.xcarchive \
  -configuration Release \
  CODE_SIGN_IDENTITY="Apple Distribution" \
  -allowProvisioningUpdates

# 4. Export IPA
echo "Step 4: Exporting IPA..."
xcodebuild -exportArchive \
  -archivePath build/ios/Orbit.xcarchive \
  -exportOptionsPlist ios/App/ExportOptions.plist \
  -exportPath build/ios/ \
  -allowProvisioningUpdates

echo "=== Build complete! ==="
echo "IPA: build/ios/App.ipa"
echo ""
echo "To upload to TestFlight:"
echo "  xcrun altool --upload-app -f build/ios/App.ipa -t ios -u YOUR_APPLE_ID -p YOUR_APP_SPECIFIC_PASSWORD"
echo ""
echo "Or use Transporter.app from the Mac App Store."
