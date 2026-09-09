"""
RetinaShield — Synthetic Test Image Generator

Generates synthetic fundus-like test images for pipeline development.
These are NOT real medical images and should never be used for training
or validation of clinical models.

Usage:
    python scripts/generate_test_images.py --count 10 --output ./data/test_images/
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def generate_synthetic_fundus(
    size: int = 512,
    seed: int | None = None,
) -> Image.Image:
    """
    Generate a synthetic fundus-like image.

    NOT a real medical image. For testing pipeline connectivity only.
    """
    rng = np.random.default_rng(seed)

    # Create dark background
    img = np.zeros((size, size, 3), dtype=np.uint8)

    # Create circular fundus field
    center = size // 2
    radius = int(size * 0.42)
    Y, X = np.ogrid[:size, :size]
    dist = np.sqrt((X - center) ** 2 + (Y - center) ** 2)
    fundus_mask = dist < radius

    # Fill with retina-like color (reddish-orange)
    base_r = rng.integers(120, 170)
    base_g = rng.integers(50, 90)
    base_b = rng.integers(20, 50)

    img[fundus_mask, 0] = base_r
    img[fundus_mask, 1] = base_g
    img[fundus_mask, 2] = base_b

    # Add radial gradient (vignette effect)
    gradient = 1.0 - (dist / radius) ** 2
    gradient = np.clip(gradient, 0, 1)
    for c in range(3):
        img[:, :, c] = (img[:, :, c] * gradient).astype(np.uint8)

    # --- Optic Disc ---
    od_x = center + rng.integers(int(radius * 0.3), int(radius * 0.5))
    od_y = center + rng.integers(-int(radius * 0.15), int(radius * 0.15))
    od_radius = rng.integers(int(size * 0.06), int(size * 0.09))

    od_dist = np.sqrt((X - od_x) ** 2 + (Y - od_y) ** 2)
    od_mask = od_dist < od_radius
    od_glow = np.clip(1.0 - (od_dist / (od_radius * 1.5)), 0, 1)

    img[:, :, 0] = np.clip(img[:, :, 0] + (od_glow * 100).astype(np.uint8), 0, 255).astype(np.uint8)
    img[:, :, 1] = np.clip(img[:, :, 1] + (od_glow * 90).astype(np.uint8), 0, 255).astype(np.uint8)
    img[:, :, 2] = np.clip(img[:, :, 2] + (od_glow * 50).astype(np.uint8), 0, 255).astype(np.uint8)

    # --- Crude vessel lines ---
    pil_img = Image.fromarray(img)
    draw = ImageDraw.Draw(pil_img)

    num_vessels = rng.integers(8, 16)
    for _ in range(num_vessels):
        # Start from near optic disc
        start_x = int(od_x + rng.integers(-od_radius, od_radius))
        start_y = int(od_y + rng.integers(-od_radius, od_radius))

        angle = rng.uniform(0, 2 * math.pi)
        length = rng.integers(int(radius * 0.3), int(radius * 0.8))
        width = rng.integers(1, 3)

        points = [(start_x, start_y)]
        x, y = float(start_x), float(start_y)
        for step in range(length // 5):
            angle += rng.uniform(-0.3, 0.3)
            x += 5 * math.cos(angle)
            y += 5 * math.sin(angle)
            if 0 <= x < size and 0 <= y < size and fundus_mask[int(y), int(x)]:
                points.append((int(x), int(y)))

        if len(points) > 2:
            vessel_color = (
                max(0, base_r - 50 - rng.integers(0, 30)),
                max(0, base_g - 30 - rng.integers(0, 20)),
                max(0, base_b - 10),
            )
            draw.line(points, fill=vessel_color, width=width)

    # --- Macula (dark region) ---
    mac_x = center - rng.integers(int(radius * 0.1), int(radius * 0.3))
    mac_y = center + rng.integers(-int(radius * 0.05), int(radius * 0.05))
    mac_radius = rng.integers(int(size * 0.04), int(size * 0.06))

    mac_dist = np.sqrt((X - mac_x) ** 2 + (Y - mac_y) ** 2)
    mac_glow = np.clip(1.0 - (mac_dist / (mac_radius * 2)), 0, 1)

    img_arr = np.array(pil_img)
    for c in range(3):
        img_arr[:, :, c] = np.clip(
            img_arr[:, :, c] - (mac_glow * 30).astype(np.uint8), 0, 255
        ).astype(np.uint8)

    # Apply slight blur for realism
    result = Image.fromarray(img_arr)
    result = result.filter(ImageFilter.GaussianBlur(radius=1))

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic fundus test images (NOT real medical images)"
    )
    parser.add_argument("--count", type=int, default=5, help="Number of images to generate")
    parser.add_argument("--output", type=str, default="./data/test_images/", help="Output directory")
    parser.add_argument("--size", type=int, default=512, help="Image size in pixels")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating {args.count} synthetic fundus images...")
    print("⚠ These are NOT real medical images — for pipeline testing only.")
    print()

    for i in range(args.count):
        img = generate_synthetic_fundus(size=args.size, seed=i)
        path = output_dir / f"synthetic_fundus_{i:04d}.png"
        img.save(path)
        print(f"  [{i+1}/{args.count}] Saved: {path}")

    print(f"\n✓ Done. {args.count} images saved to {output_dir}")


if __name__ == "__main__":
    main()
