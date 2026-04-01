"""
Generate App Store / Play Store screenshots with captions.

Creates properly sized screenshots with marketing captions for store listings.
iPhone 6.5" (1242x2688) and Android (1080x1920).
"""

from PIL import Image, ImageDraw, ImageFont
import os

OUT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOTS_DIR = os.path.join(OUT_DIR, "demo-screenshots")
STORE_DIR = os.path.join(OUT_DIR, "store-listing", "screenshots")
os.makedirs(STORE_DIR, exist_ok=True)

# App Store: 6.5" iPhone = 1242x2688
IOS_W, IOS_H = 1242, 2688
# Play Store: phone = 1080x1920
ANDROID_W, ANDROID_H = 1080, 1920

BG_COLOR = (10, 10, 26)  # #0a0a1a
ACCENT = (108, 92, 231)  # #6c5ce7
TEXT_COLOR = (255, 255, 255)
SUB_COLOR = (180, 175, 210)

# Screenshots to use with their captions
SCREENSHOTS = [
    ("40-mobile-dashboard.png", "Your Relationship\nCommand Center", "See health scores, streaks,\nand AI insights at a glance"),
    ("46-mobile-orbit.png", "Visualize Your\nSocial Universe", "See all your connections\nmapped in orbit view"),
    ("47-mobile-people.png", "Everyone Has\nTheir Place", "Track friends, family,\nand colleagues"),
    ("42-mobile-quests.png", "Level Up Your\nSocial Skills", "Complete quests and earn XP\nto climb the ranks"),
    ("43-mobile-parties.png", "Plan Hangouts\nThat Happen", "Create parties and track\nwho's coming"),
    ("45-mobile-achievements.png", "Unlock\nAchievements", "Earn badges for being\na great friend"),
]


def try_font(size):
    """Try to load a nice font, falling back to default."""
    font_paths = [
        "/System/Library/Fonts/SFPro-Bold.otf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def create_store_screenshot(screenshot_file, headline, subtitle, index, target_w, target_h):
    """Create a single store screenshot with caption above the screenshot."""
    canvas = Image.new("RGB", (target_w, target_h), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    # Load screenshot
    ss_path = os.path.join(SCREENSHOTS_DIR, screenshot_file)
    if not os.path.exists(ss_path):
        print(f"  WARNING: {screenshot_file} not found, skipping")
        return None

    ss = Image.open(ss_path).convert("RGB")

    # Calculate layout
    caption_zone_h = int(target_h * 0.28)  # Top 28% for captions
    ss_zone_h = target_h - caption_zone_h

    # Resize screenshot to fit the bottom zone
    ss_ratio = ss.width / ss.height
    zone_ratio = target_w / ss_zone_h
    if ss_ratio > zone_ratio:
        new_w = int(target_w * 0.88)
        new_h = int(new_w / ss_ratio)
    else:
        new_h = int(ss_zone_h * 0.92)
        new_w = int(new_h * ss_ratio)

    ss_resized = ss.resize((new_w, new_h), Image.LANCZOS)

    # Add rounded corners to screenshot
    mask = Image.new("L", (new_w, new_h), 0)
    mask_draw = ImageDraw.Draw(mask)
    corner_r = int(new_w * 0.04)
    mask_draw.rounded_rectangle([0, 0, new_w, new_h], corner_r, fill=255)

    ss_with_corners = Image.new("RGB", (new_w, new_h), BG_COLOR)
    ss_with_corners.paste(ss_resized, (0, 0), mask)

    # Center screenshot in bottom zone
    ss_x = (target_w - new_w) // 2
    ss_y = caption_zone_h + (ss_zone_h - new_h) // 2
    canvas.paste(ss_with_corners, (ss_x, ss_y))

    # Draw subtle accent line under caption
    line_y = caption_zone_h - int(target_h * 0.02)
    line_margin = int(target_w * 0.3)
    draw.line(
        [(line_margin, line_y), (target_w - line_margin, line_y)],
        fill=(*ACCENT, 150), width=3
    )

    # Draw headline
    headline_size = int(target_w * 0.068)
    sub_size = int(target_w * 0.032)
    headline_font = try_font(headline_size)
    sub_font = try_font(sub_size)

    # Center headline vertically in caption zone
    headline_bbox = draw.multiline_textbbox((0, 0), headline, font=headline_font)
    headline_h = headline_bbox[3] - headline_bbox[1]
    sub_bbox = draw.multiline_textbbox((0, 0), subtitle, font=sub_font)
    sub_h = sub_bbox[3] - sub_bbox[1]

    total_text_h = headline_h + int(target_h * 0.02) + sub_h
    text_start_y = (caption_zone_h - total_text_h) // 2

    draw.multiline_text(
        (target_w // 2, text_start_y), headline,
        font=headline_font, fill=TEXT_COLOR, anchor="ma", align="center"
    )
    draw.multiline_text(
        (target_w // 2, text_start_y + headline_h + int(target_h * 0.02)), subtitle,
        font=sub_font, fill=SUB_COLOR, anchor="ma", align="center"
    )

    return canvas


def generate_all():
    print("Generating store screenshots...")

    for i, (ss_file, headline, subtitle) in enumerate(SCREENSHOTS):
        # iOS version
        ios = create_store_screenshot(ss_file, headline, subtitle, i + 1, IOS_W, IOS_H)
        if ios:
            ios_path = os.path.join(STORE_DIR, f"ios-{i+1:02d}.png")
            ios.save(ios_path, "PNG")
            print(f"  iOS #{i+1}: {ios_path}")

        # Android version
        android = create_store_screenshot(ss_file, headline, subtitle, i + 1, ANDROID_W, ANDROID_H)
        if android:
            android_path = os.path.join(STORE_DIR, f"android-{i+1:02d}.png")
            android.save(android_path, "PNG")
            print(f"  Android #{i+1}: {android_path}")

    # Copy to fastlane
    fastlane_dir = os.path.join(OUT_DIR, "fastlane", "screenshots", "en-US")
    os.makedirs(fastlane_dir, exist_ok=True)
    import shutil
    for f in os.listdir(STORE_DIR):
        if f.startswith("ios-"):
            shutil.copy2(os.path.join(STORE_DIR, f), os.path.join(fastlane_dir, f))

    print("Done! Store screenshots generated.")


if __name__ == "__main__":
    generate_all()
