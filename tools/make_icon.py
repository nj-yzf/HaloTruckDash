"""Rebuild the original truck/pixel-bar icon with Pillow (development only)."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
assets = ROOT / 'assets'
assets.mkdir(exist_ok=True)
SCALE = 4
image = Image.new('RGBA', (256 * SCALE, 256 * SCALE))
draw = ImageDraw.Draw(image)
def rounded(box, radius, color):
    draw.rounded_rectangle(tuple(round(value * SCALE) for value in box), radius=radius * SCALE, fill=color)
def rect(box, color):
    draw.rectangle(tuple(round(value * SCALE) for value in box), fill=color)
rounded((4, 4, 252, 252), 52, '#101b2d')
rounded((40, 45, 216, 162), 22, '#55d5f4')
rounded((56, 59, 200, 111), 10, '#101b2d')
rect((122, 60, 134, 111), '#55d5f4')
rounded((55, 127, 86, 143), 5, '#f5fbff')
rounded((170, 127, 201, 143), 5, '#f5fbff')
rounded((99, 129, 157, 141), 5, '#1b536f')
rounded((55, 155, 84, 177), 7, '#55d5f4')
rounded((172, 155, 201, 177), 7, '#55d5f4')
rounded((29, 187, 227, 223), 10, '#23374a')
for column in range(10):
    rounded((40 + column * 18, 197, 50 + column * 18, 213), 3,
            '#69edbe' if column < 7 else '#386078')
image = image.resize((256, 256), Image.Resampling.LANCZOS)
image.save(assets / 'HaloTruckDash.png')
image.save(assets / 'HaloTruckDash.ico', sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
<rect x="4" y="4" width="248" height="248" rx="52" fill="#101b2d"/>
<g fill="#55d5f4"><rect x="40" y="45" width="176" height="117" rx="22"/>
<rect x="55" y="155" width="29" height="22" rx="7"/><rect x="172" y="155" width="29" height="22" rx="7"/></g>
<rect x="56" y="59" width="144" height="52" rx="10" fill="#101b2d"/>
<path d="M122 60h12v51h-12z" fill="#55d5f4"/>
<g fill="#f5fbff"><rect x="55" y="127" width="31" height="16" rx="5"/><rect x="170" y="127" width="31" height="16" rx="5"/></g>
<rect x="99" y="129" width="58" height="12" rx="5" fill="#1b536f"/>
<rect x="29" y="187" width="198" height="36" rx="10" fill="#23374a"/>
'''
for column in range(10):
    color = '#69edbe' if column < 7 else '#386078'
    svg += f'<rect x="{40 + column * 18}" y="197" width="10" height="16" rx="3" fill="{color}"/>\n'
svg += '</svg>\n'
(assets / 'HaloTruckDash.svg').write_text(svg, encoding='utf-8')
print('Generated original HaloTruckDash SVG, PNG and 9-size ICO.')
