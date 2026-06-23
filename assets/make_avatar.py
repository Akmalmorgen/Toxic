"""Аватар бота «NEXT» для анонимного общения.
Качество: рендер в 3x + сглаживание (LANCZOS), неоновое свечение, диагональный градиент.
Тема: маска инкогнито (шляпа + очки) в пузыре чата.
"""
import glob
from PIL import Image, ImageDraw, ImageFont, ImageFilter

OUT = 640
S = 3                      # супер-сэмплинг
W = OUT * S
k = S                      # координаты задаём в 640-пространстве, умножаем на k

# Палитра
C_TOP = (26, 16, 64)       # глубокий индиго
C_BOT = (146, 51, 215)     # насыщенный фиолетовый
ACCENT = (190, 120, 255)   # неон для свечения
WHITE = (255, 255, 255)
MASK = (40, 22, 92)        # цвет маски на белом пузыре


def R(*coords):
    """Масштабирование координат из 640-пространства в рабочее."""
    return tuple(c * k for c in coords)


# ---------- 1. Диагональный градиент (через маленькое изображение + ресайз) ----------
small = Image.new("RGB", (64, 64))
sp = small.load()
for y in range(64):
    for x in range(64):
        t = (x + y) / 126
        sp[x, y] = (
            int(C_TOP[0] + (C_BOT[0] - C_TOP[0]) * t),
            int(C_TOP[1] + (C_BOT[1] - C_TOP[1]) * t),
            int(C_TOP[2] + (C_BOT[2] - C_TOP[2]) * t),
        )
img = small.resize((W, W), Image.BILINEAR)

# Радиальная подсветка по центру-верху (глубина)
glow_bg = Image.new("L", (W, W), 0)
gd = ImageDraw.Draw(glow_bg)
gd.ellipse(R(140, 60, 500, 420), fill=90)
glow_bg = glow_bg.filter(ImageFilter.GaussianBlur(W * 0.06))
img = Image.composite(Image.new("RGB", (W, W), (175, 130, 255)), img, glow_bg)

# Виньетка по краям
vig = Image.new("L", (W, W), 0)
vd = ImageDraw.Draw(vig)
vd.ellipse(R(-80, -80, 720, 720), fill=255)
vig = vig.filter(ImageFilter.GaussianBlur(W * 0.05))
dark = Image.new("RGB", (W, W), (12, 7, 30))
img = Image.composite(img, dark, vig)

draw = ImageDraw.Draw(img)

# ---------- 2. Неоновое свечение под пузырём ----------
glow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
gdr = ImageDraw.Draw(glow)
gdr.rounded_rectangle(R(150, 108, 490, 372), radius=58 * k, fill=ACCENT + (255,))
glow = glow.filter(ImageFilter.GaussianBlur(W * 0.035))
img.paste(Image.new("RGB", (W, W), ACCENT), (0, 0), glow.split()[3].point(lambda a: int(a * 0.55)))
draw = ImageDraw.Draw(img)

# ---------- 3. Белый пузырь чата ----------
draw.rounded_rectangle(R(150, 108, 490, 372), radius=58 * k, fill=WHITE)
draw.polygon([(206 * k, 360 * k), (206 * k, 430 * k), (266 * k, 362 * k)], fill=WHITE)

# ---------- 4. Маска инкогнито ----------
# Шляпа — корона
draw.rounded_rectangle(R(262, 158, 378, 236), radius=22 * k, fill=MASK)
# Поля шляпы
draw.ellipse(R(214, 220, 426, 266), fill=MASK)
# Лента (светлая)
draw.rectangle(R(262, 214, 378, 230), fill=(150, 120, 220))
# Очки
draw.rounded_rectangle(R(250, 290, 312, 344), radius=18 * k, fill=MASK)
draw.rounded_rectangle(R(328, 290, 390, 344), radius=18 * k, fill=MASK)
draw.rectangle(R(312, 302, 328, 314), fill=MASK)
draw.rectangle(R(236, 300, 250, 312), fill=MASK)
draw.rectangle(R(390, 300, 404, 312), fill=MASK)

# ---------- 5. Текст NEXT (с подсветкой) ----------
font_path = (glob.glob("/usr/share/fonts/**/NotoSans*[wght]*.ttf", recursive=True) +
             glob.glob("/usr/share/fonts/**/NotoSans*.ttf", recursive=True))[0]
font = ImageFont.truetype(font_path, 104 * k)
try:
    font.set_variation_by_axes([900])
except Exception:
    pass

text = "NEXT"
spacing = 16 * k
widths = [draw.textlength(ch, font=font) for ch in text]
total = sum(widths) + spacing * (len(text) - 1)
tx = (W - total) / 2
ty = 432 * k

# слой подсветки текста
tglow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
tg = ImageDraw.Draw(tglow)
x = tx
for ch, w in zip(text, widths):
    tg.text((x, ty), ch, font=font, fill=ACCENT + (255,))
    x += w + spacing
tglow = tglow.filter(ImageFilter.GaussianBlur(W * 0.012))
img.paste(Image.new("RGB", (W, W), ACCENT), (0, 0), tglow.split()[3])

draw = ImageDraw.Draw(img)
x = tx
for ch, w in zip(text, widths):
    draw.text((x, ty), ch, font=font, fill=WHITE)
    x += w + spacing

# ---------- финал: уменьшение со сглаживанием ----------
img = img.resize((OUT, OUT), Image.LANCZOS)
img.save("/projects/sandbox/Toxic/assets/avatar.png", "PNG")
print("avatar.png обновлён, размер", img.size)
