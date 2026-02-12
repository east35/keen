#!/bin/bash
set -e

cd "$(dirname "$0")/.."

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "==> Generating icons from source assets..."

# Create iconset directory for app icon
mkdir -p AppIcon.iconset

# Generate app icon sizes from source PNG
python3 -c "
from PIL import Image
import os

img = Image.open('assets/app-icon.png')
sizes = [16, 32, 64, 128, 256, 512, 1024]
for size in sizes:
    resized = img.resize((size, size), Image.LANCZOS)
    resized.save(f'AppIcon.iconset/icon_{size}x{size}.png')
    if size <= 512:
        resized_2x = img.resize((size*2, size*2), Image.LANCZOS)
        resized_2x.save(f'AppIcon.iconset/icon_{size}x{size}@2x.png')
print('Generated app icon sizes')
"

# Convert to icns (tracked by git)
iconutil -c icns AppIcon.iconset -o AppIcon.icns
rm -rf AppIcon.iconset
echo "==> Created AppIcon.icns"

# Generate menu bar icons from SVG
python3 -c "
import cairosvg
from PIL import Image
import io

with open('assets/menubar-icon.svg', 'rb') as f:
    svg_data = f.read()

# 22x22 for menu bar
png_data = cairosvg.svg2png(bytestring=svg_data, output_width=22, output_height=22)
img = Image.open(io.BytesIO(png_data))
img.save('iconTemplate.png')

# 44x44 @2x for retina
png_data_2x = cairosvg.svg2png(bytestring=svg_data, output_width=44, output_height=44)
img_2x = Image.open(io.BytesIO(png_data_2x))
img_2x.save('iconTemplate@2x.png')

print('Generated menu bar icons')
"

echo "==> Building app bundle with PyInstaller..."

pyinstaller --noconfirm Keen.spec

echo "==> Build complete: dist/Keen.app"
