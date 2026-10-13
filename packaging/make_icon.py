"""Draw assets/dictado.ico. Run once when the icon changes."""

from pathlib import Path

from PIL import Image, ImageDraw


def draw(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    margin = max(1, size // 16)
    pen.ellipse((margin, margin, size - margin, size - margin), fill=(47, 158, 68, 255))
    body_left = int(size * 0.40)
    body_right = int(size * 0.60)
    body_top = int(size * 0.24)
    body_bottom = int(size * 0.56)
    radius = max(2, size // 10)
    pen.rounded_rectangle(
        (body_left, body_top, body_right, body_bottom),
        radius=radius,
        fill=(255, 255, 255, 255),
    )
    pen.arc(
        (int(size * 0.30), int(size * 0.40), int(size * 0.70), int(size * 0.78)),
        20,
        160,
        fill=(255, 255, 255, 255),
        width=max(2, size // 16),
    )
    stem_x = size // 2
    pen.line(
        (stem_x, int(size * 0.72), stem_x, int(size * 0.82)),
        fill=(255, 255, 255, 255),
        width=max(2, size // 18),
    )
    return image


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    destination = root / "assets" / "dictado.ico"
    destination.parent.mkdir(parents=True, exist_ok=True)
    image = draw(256)
    image.save(destination, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])
    print(destination)


if __name__ == "__main__":
    main()
