#!/bin/bash
set -e

echo "=== Orbit Android Build ==="

# 1. Sync web assets
echo "Step 1: Syncing web assets..."
npm run cap:sync

# 2. Build AAB (Android App Bundle)
echo "Step 2: Building release AAB..."
cd android
./gradlew bundleRelease
cd ..

echo "=== Build complete! ==="
echo "AAB: android/app/build/outputs/bundle/release/app-release.aab"
echo ""
echo "To upload to Play Console:"
echo "  1. Go to https://play.google.com/console"
echo "  2. Select your app > Testing > Internal testing"
echo "  3. Create a new release and upload the AAB"
echo ""
echo "Or use fastlane:"
echo "  fastlane android beta"
