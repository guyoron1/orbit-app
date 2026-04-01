"""
Generate splash screen images for Orbit.

Creates splash screens for iOS and Android with the Orbit icon centered
on the app's dark background color.
"""

from PIL import Image
import os

OUT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BG_COLOR = (10, 10, 26)  # #0a0a1a


def generate_splash():
    icon = Image.open(os.path.join(OUT_DIR, "icon-1024.png")).convert("RGBA")

    # Splash screen sizes
    sizes = {
        # (width, height, icon_size, output_path)
        "ios-universal": (2732, 2732, 400, "ios/App/App/Assets.xcassets/Splash.imageset/splash-2732x2732.png"),
        "android-land-hdpi": (800, 480, 200, "android/app/src/main/res/drawable-land-hdpi/splash.png"),
        "android-land-xhdpi": (1280, 720, 280, "android/app/src/main/res/drawable-land-xhdpi/splash.png"),
        "android-land-xxhdpi": (1600, 960, 340, "android/app/src/main/res/drawable-land-xxhdpi/splash.png"),
        "android-port-hdpi": (480, 800, 200, "android/app/src/main/res/drawable-port-hdpi/splash.png"),
        "android-port-xhdpi": (720, 1280, 280, "android/app/src/main/res/drawable-port-xhdpi/splash.png"),
        "android-port-xxhdpi": (960, 1600, 340, "android/app/src/main/res/drawable-port-xxhdpi/splash.png"),
        # Generic splash for both
        "splash-2436": (1125, 2436, 300, "splash-2436.png"),
    }

    for name, (w, h, icon_size, path) in sizes.items():
        full_path = os.path.join(OUT_DIR, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        splash = Image.new("RGB", (w, h), BG_COLOR)
        resized_icon = icon.resize((icon_size, icon_size), Image.LANCZOS)

        # Center the icon
        x = (w - icon_size) // 2
        y = (h - icon_size) // 2
        splash.paste(resized_icon, (x, y), resized_icon)
        splash.save(full_path, "PNG")
        print(f"  {name}: {full_path}")

    # Create iOS Splash imageset Contents.json
    ios_splash_dir = os.path.join(OUT_DIR, "ios", "App", "App", "Assets.xcassets", "Splash.imageset")
    os.makedirs(ios_splash_dir, exist_ok=True)
    contents = """{
  "images": [
    {
      "filename": "splash-2732x2732.png",
      "idiom": "universal",
      "scale": "1x"
    },
    {
      "filename": "splash-2732x2732.png",
      "idiom": "universal",
      "scale": "2x"
    },
    {
      "filename": "splash-2732x2732.png",
      "idiom": "universal",
      "scale": "3x"
    }
  ],
  "info": {
    "author": "xcode",
    "version": 1
  }
}"""
    with open(os.path.join(ios_splash_dir, "Contents.json"), "w") as f:
        f.write(contents)

    print("Done! All splash screens generated.")


if __name__ == "__main__":
    generate_splash()
