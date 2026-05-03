"""Regenerate PNG extension icons (requires Pillow)."""
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    root = Path(__file__).resolve().parent.parent / "browser-agent-extension" / "icons"
    root.mkdir(parents=True, exist_ok=True)

    def make(size: int, path: Path) -> None:
        im = Image.new("RGBA", (size, size), (255, 61, 46, 255))
        draw = ImageDraw.Draw(im)
        pad = max(2, size // 8)
        draw.rounded_rectangle(
            [pad, pad, size - pad, size - pad],
            radius=max(2, size // 8),
            outline=(255, 255, 255, 230),
            width=max(1, size // 16),
        )
        im.save(path)

    make(16, root / "icon16.png")
    make(48, root / "icon48.png")
    make(128, root / "icon128.png")
    print("Wrote icons to", root)


if __name__ == "__main__":
    main()
