import math, os
out = os.path.expanduser("~/Software/recall/docs/logo-varianten")

def tile(theme, inner, grad):
    if theme == "dark":
        bg = ('<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1b1c36"/>'
              '<stop offset="1" stop-color="#0d0e1c"/></linearGradient>')
        glow = '<filter id="glow" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="10" result="b"/><feColorMatrix in="b" type="matrix" values="1 0 0 0 0 0 1 0 0 0 0 0 1 0 0 0 0 0 .55 0"/><feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
    else:
        bg = ('<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffffff"/>'
              '<stop offset="1" stop-color="#eceef6"/></linearGradient>')
        glow = '<filter id="glow"><feMerge><feMergeNode in="SourceGraphic"/></feMerge></filter>'
    a, b = grad[theme]
    fg = f'<linearGradient id="fg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient>'
    cut = "#121326" if theme == "dark" else "#ffffff"
    border = '' if theme == "dark" else '<rect x="1.5" y="1.5" width="509" height="509" rx="111" fill="none" stroke="#d9dce8" stroke-width="3"/>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">'
            f'<defs>{bg}{fg}{glow}</defs><rect width="512" height="512" rx="112" fill="url(#bg)"/>{border}'
            f'<g filter="url(#glow)">{inner.replace("CUT", cut)}</g></svg>')

def pt(cx, cy, r, deg):
    t = math.radians(deg)
    return cx + r * math.cos(t), cy + r * math.sin(t)

# A – „Zurück-Kreis“: Pfeil läuft gegen den Uhrzeigersinn zum gemerkten Punkt in der Mitte
cx, cy, r = 256, 262, 138
s = pt(cx, cy, r, 25); e = pt(cx, cy, r, -255)  # = 105°
# Pfeilspitze am Ende (Bewegung gegen den Uhrzeigersinn: Tangente (sin θ, -cos θ))
th = math.radians(105); tx, ty = math.sin(th), -math.cos(th); nx, ny = math.cos(th), math.sin(th)
tip = (e[0] + tx * 46, e[1] + ty * 46)
w1 = (e[0] + nx * 46, e[1] + ny * 46); w2 = (e[0] - nx * 46, e[1] - ny * 46)
A = (f'<path d="M {s[0]:.1f} {s[1]:.1f} A {r} {r} 0 1 0 {e[0]:.1f} {e[1]:.1f}" fill="none" stroke="url(#fg)" stroke-width="44" stroke-linecap="round"/>'
     f'<path d="M {w1[0]:.1f} {w1[1]:.1f} L {tip[0]:.1f} {tip[1]:.1f} L {w2[0]:.1f} {w2[1]:.1f} Z" fill="url(#fg)" stroke="url(#fg)" stroke-width="10" stroke-linejoin="round"/>'
     f'<circle cx="{cx}" cy="{cy}" r="40" fill="url(#fg)"/>')

# B – „Lesezeichen“: Band mit ausgeschnittenem Zurück-Pfeil
B = ('<path d="M 150 132 Q 150 100 182 100 L 330 100 Q 362 100 362 132 L 362 416 L 256 348 L 150 416 Z" fill="url(#fg)" stroke="url(#fg)" stroke-width="12" stroke-linejoin="round"/>'
     '<path d="M 300 288 L 300 236 Q 300 196 260 196 L 226 196" fill="none" stroke="CUT" stroke-width="30" stroke-linecap="round" stroke-linejoin="round"/>'
     '<path d="M 238 160 L 196 196 L 238 232" fill="none" stroke="CUT" stroke-width="30" stroke-linecap="round" stroke-linejoin="round"/>')

# C – „Position“: Schiene, aktueller Knopf unten, gemerkte Position oben als Ring, Bogen-Pfeil zurück
C = ('<line x1="206" y1="128" x2="206" y2="384" stroke="url(#fg)" stroke-width="18" stroke-linecap="round" opacity=".35"/>'
     '<circle cx="206" cy="160" r="40" fill="none" stroke="url(#fg)" stroke-width="22"/>'
     '<circle cx="206" cy="352" r="46" fill="url(#fg)"/>'
     '<path d="M 270 352 Q 366 352 366 256 Q 366 170 302 160" fill="none" stroke="url(#fg)" stroke-width="30" stroke-linecap="round"/>'
     '<path d="M 322 122 L 284 158 L 324 194" fill="none" stroke="url(#fg)" stroke-width="30" stroke-linecap="round" stroke-linejoin="round"/>')

variants = {
    "a-zurueck-kreis": (A, {"dark": ("#6ee7d8", "#3b9dff"), "light": ("#0fb5a4", "#2563eb")}),
    "b-lesezeichen": (B, {"dark": ("#ffc069", "#ff6b6b"), "light": ("#f59e0b", "#e8484f")}),
    "c-position": (C, {"dark": ("#b4a6ff", "#6d7cff"), "light": ("#7c5cff", "#4153e0")}),
}
for name, (inner, grad) in variants.items():
    for theme in ("light", "dark"):
        with open(f"{out}/{name}-{theme}.svg", "w") as f:
            f.write(tile(theme, inner, grad))
labels = {"a-zurueck-kreis": "A · Zurück-Kreis", "b-lesezeichen": "B · Lesezeichen", "c-position": "C · Position"}
cells = ""
for name in variants:
    cells += (f'<div class="col"><div class="row light"><img src="{name}-light.svg"><img class="sm" src="{name}-light.svg"></div>'
              f'<div class="row dark"><img src="{name}-dark.svg"><img class="sm" src="{name}-dark.svg"></div><p>{labels[name]}</p></div>')
html = f'''<!doctype html><html><head><meta charset="utf-8"><style>
body{{margin:0;font-family:-apple-system,Helvetica,sans-serif;background:#fff}}
.wrap{{display:flex;gap:28px;padding:36px}}
.col{{display:flex;flex-direction:column;gap:0;border-radius:20px;overflow:hidden;box-shadow:0 2px 10px #0002}}
.row{{display:flex;align-items:center;gap:22px;padding:26px}}
.light{{background:#f3f4f8}} .dark{{background:#111318}}
img{{width:180px;height:180px}} img.sm{{width:48px;height:48px}} .row{{justify-content:center}}
p{{margin:0;padding:14px;text-align:center;font-size:20px;font-weight:600;background:#fff}}
h1{{margin:30px 36px 0;font-size:26px}}
</style></head><body><h1>Recall – Logo-Varianten (oben HA hell, unten HA dunkel; groß + 48 px)</h1><div class="wrap">{cells}</div></body></html>'''
open(f"{out}/vergleich.html", "w").write(html)
