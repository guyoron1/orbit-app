"""
Generate professional app icons for Orbit.

Creates:
  - icon-1024.png  (App Store master)
  - icon-512.png   (PWA)
  - icon-192.png   (PWA)
  - icon-180.png   (iOS touch icon)
  - iOS AppIcon set
  - Android adaptive icon foreground layers
"""

from PIL import Image, ImageDraw, ImageFilter, ImageFont
import math
import os

SIZE = 1024
CENTER = SIZE // 2
OUT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def lerp_color(c1, c2, t):
    """Linear interpolation between two RGB colors."""
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def draw_icon(size=SIZE):
    """Draw the Orbit icon at the given size."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2
    scale = size / 1024.0

    # Background: deep space gradient (radial)
    bg = Image.new("RGB", (size, size))
    bg_draw = ImageDraw.Draw(bg)
    bg_center_color = (22, 18, 48)     # Deep purple-black
    bg_edge_color = (8, 8, 24)         # Near black
    max_dist = math.sqrt(cx * cx + cy * cy)
    for y in range(size):
        for x in range(size):
            dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
            t = min(1.0, dist / max_dist)
            t = t * t  # Quadratic falloff for richer center
            c = lerp_color(bg_center_color, bg_edge_color, t)
            bg_draw.point((x, y), fill=c)

    # Outer subtle glow ring
    glow_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    for r_offset in range(int(40 * scale), 0, -1):
        alpha = int(15 * (1 - r_offset / (40 * scale)))
        r = int(380 * scale) + r_offset
        glow_draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            outline=(108, 92, 231, alpha), width=int(2 * scale)
        )

    # Orbital rings (3 rings at different angles — drawn as ellipses)
    rings_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    ring_params = [
        # (rx, ry, rotation_deg, color, width, alpha)
        (340, 120, -25, (108, 92, 231), 4, 200),   # Main ring - purple
        (300, 95,  15,  (129, 116, 240), 3, 150),   # Secondary ring - lighter
        (260, 80, -50,  (86, 71, 207), 3, 120),     # Tertiary ring - deeper
    ]

    for rx, ry, rot, color, width, alpha in ring_params:
        rx_s, ry_s = int(rx * scale), int(ry * scale)
        w_s = max(2, int(width * scale))
        ring_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ring_draw = ImageDraw.Draw(ring_img)
        ring_draw.ellipse(
            [cx - rx_s, cy - ry_s, cx + rx_s, cy + ry_s],
            outline=(*color, alpha), width=w_s
        )
        ring_img = ring_img.rotate(rot, center=(cx, cy), resample=Image.BICUBIC)
        rings_layer = Image.alpha_composite(rings_layer, ring_img)

    # Central orb with gradient
    orb_r = int(110 * scale)
    orb_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    orb_center = (130, 120, 255)   # Bright purple-blue
    orb_edge = (80, 65, 200)       # Deeper purple
    for r in range(orb_r, 0, -1):
        t = 1 - (r / orb_r)
        t_smooth = t * t * (3 - 2 * t)  # Smoothstep
        c = lerp_color(orb_edge, orb_center, t_smooth)
        alpha = 255 if r < orb_r - 2 else int(255 * (orb_r - r) / 3)
        orb_draw = ImageDraw.Draw(orb_layer)
        orb_draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(*c, min(255, alpha + 200))
        )

    # Inner bright highlight on the orb (specular) — drawn on a separate layer and composited
    spec_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    spec_draw = ImageDraw.Draw(spec_layer)
    highlight_r = int(45 * scale)
    h_offset_x, h_offset_y = int(-25 * scale), int(-30 * scale)
    for r in range(highlight_r, 0, -1):
        t = 1 - (r / highlight_r)
        alpha = int(100 * t * t)
        spec_draw.ellipse(
            [cx + h_offset_x - r, cy + h_offset_y - r,
             cx + h_offset_x + r, cy + h_offset_y + r],
            fill=(220, 215, 255, alpha)
        )
    orb_layer = Image.alpha_composite(orb_layer, spec_layer)

    # Small orbiting dots (like satellites)
    dots_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    dots_draw = ImageDraw.Draw(dots_layer)
    dot_positions = [
        (310, -35, 8, (160, 150, 255, 230)),   # Top-right area
        (-280, 100, 6, (130, 120, 240, 200)),   # Left area
        (180, 260, 5, (108, 92, 231, 180)),     # Bottom-right
    ]
    for dx, dy, dr, color in dot_positions:
        dx_s, dy_s, dr_s = int(dx * scale), int(dy * scale), int(dr * scale)
        # Glow around dot
        for gr in range(dr_s * 3, dr_s, -1):
            ga = int(30 * (1 - (gr - dr_s) / (dr_s * 2)))
            dots_draw.ellipse(
                [cx + dx_s - gr, cy + dy_s - gr, cx + dx_s + gr, cy + dy_s + gr],
                fill=(color[0], color[1], color[2], ga)
            )
        dots_draw.ellipse(
            [cx + dx_s - dr_s, cy + dy_s - dr_s, cx + dx_s + dr_s, cy + dy_s + dr_s],
            fill=color
        )

    # Compose all layers
    result = bg.convert("RGBA")
    result = Image.alpha_composite(result, glow_layer)
    result = Image.alpha_composite(result, rings_layer)
    result = Image.alpha_composite(result, orb_layer)
    result = Image.alpha_composite(result, dots_layer)

    return result


def generate_all():
    print("Generating Orbit app icon (1024x1024)...")
    master = draw_icon(1024)

    # Flatten to RGB (no transparency — required for iOS App Store)
    master_rgb = Image.new("RGB", master.size, (8, 8, 24))
    master_rgb.paste(master, mask=master.split()[3])

    # Save master
    master_path = os.path.join(OUT_DIR, "icon-1024.png")
    master_rgb.save(master_path, "PNG", quality=100)
    print(f"  Saved {master_path}")

    # PWA icons
    for s in [512, 192, 180]:
        resized = master_rgb.resize((s, s), Image.LANCZOS)
        path = os.path.join(OUT_DIR, f"icon-{s}.png")
        resized.save(path, "PNG")
        print(f"  Saved {path}")

    # iOS AppIcon (1024x1024 only needed for modern Xcode)
    ios_dir = os.path.join(OUT_DIR, "ios", "App", "App", "Assets.xcassets", "AppIcon.appiconset")
    if os.path.isdir(ios_dir):
        ios_path = os.path.join(ios_dir, "AppIcon-512@2x.png")
        master_rgb.save(ios_path, "PNG")
        print(f"  Saved iOS icon: {ios_path}")

    # Android adaptive icon foreground (432x432 with safe zone padding)
    android_res = os.path.join(OUT_DIR, "android", "app", "src", "main", "res")
    if os.path.isdir(android_res):
        densities = {
            "mipmap-mdpi": 108,
            "mipmap-hdpi": 162,
            "mipmap-xhdpi": 216,
            "mipmap-xxhdpi": 324,
            "mipmap-xxxhdpi": 432,
        }
        for density, dp_size in densities.items():
            density_dir = os.path.join(android_res, density)
            if not os.path.isdir(density_dir):
                os.makedirs(density_dir, exist_ok=True)

            # Foreground: icon with 18dp safe zone padding (scaled)
            # The foreground canvas is 108dp, icon lives in inner 66dp (72dp visible)
            padding = int(dp_size * 18 / 108)
            icon_area = dp_size - 2 * padding
            fg = Image.new("RGBA", (dp_size, dp_size), (0, 0, 0, 0))
            icon_resized = master.resize((icon_area, icon_area), Image.LANCZOS)
            fg.paste(icon_resized, (padding, padding), icon_resized)
            fg.save(os.path.join(density_dir, "ic_launcher_foreground.png"), "PNG")

            # Legacy icon (square, no alpha)
            legacy = master_rgb.resize((dp_size, dp_size), Image.LANCZOS)
            legacy.save(os.path.join(density_dir, "ic_launcher.png"), "PNG")
            legacy.save(os.path.join(density_dir, "ic_launcher_round.png"), "PNG")

        print(f"  Saved Android icons for all densities")

    print("Done! All icons generated.")


if __name__ == "__main__":
    generate_all()
