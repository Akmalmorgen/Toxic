"""Генерирует аватар бота: анонимное общение (маска инкогнито + пузырь чата + NEXT)."""
import glob
from PIL import Image, ImageDraw, ImageFont

W = H = 640
PURPLE_TOP = (36, 22, 84)      # глубокий индиго
PURPLE_BOT = (124, 58, 237)    # яркий фиолетовый
WHITE = (255, 255, 255)
MASK = (32, 20, 78)            # цвет маски на белом пузыре

img = Image.new("RGB", (W, H), PURPLE_TOP)
px = img.load()
# вертикальный градиент
for y in range(H):
    t = y / (H - 1)
    r = int(PURPLE_TOP[0] + (PURPLE_BOT[0] - PURPLE_TOP[0]) * t)
    g = int(PURPLE_TOP[1] + (PURPLE_BOT[1] - PURPLE_TOP[1]) * t)
    b = int(PURPLE_TOP[2] + (PURPLE_BOT[2] - PURPLE_TOP[2]) * t)
    for x in range(W):
        px[x, y] = (r, g, b)

d = ImageDraw.Draw(img)

# --- Белый пузырь чата ---
d.rounded_rectangle((150, 95, 490, 360), radius=52, fill=WHITE)
# хвостик пузыря (внизу слева)
d.polygon([(205, 350), (205, 420), (262, 352)], fill=WHITE)

# --- Маска инкогнито (на белом пузыре, фиолетовая) ---
# Шляпа: корона
d.rounded_rectangle((258, 150, 382, 232), radius=20, fill=MASK)
# Поля шляпы
d.ellipse((212, 214, 428, 262), fill=MASK)
# Лента на шляпе (белая полоска)
d.rectangle((258, 210, 382, 226), fill=WHITE)

# Очки (под полями)
d.rounded_rectangle((250, 286, 314, 342), radius=16, fill=MASK)   # левая линза
d.rounded_rectangle((326, 286, 390, 342), radius=16, fill=MASK)   # правая линза
d.rectangle((314, 298, 326, 312), fill=MASK)                      # переносица
# дужки
d.rectangle((236, 296, 250, 308), fill=MASK)
d.rectangle((390, 296, 404, 308), fill=MASK)

# --- Текст NEXT ---
font_path = None
for p in glob.glob("/usr/share/fonts/**/NotoSans*[wght]*.ttf", recursive=True) + \
         glob.glob("/usr/share/fonts/**/NotoSans*.ttf", recursive=True):
    font_path = p
    break
font = ImageFont.truetype(font_path, 96)
try:
    font.set_variation_by_axes([800])  # жирный, если вариативный
except Exception:
    pass

text = "NEXT"
# трекинг между буквами
spacing = 14
widths = [d.textlength(ch, font=font) for ch in text]
total = sum(widths) + spacing * (len(text) - 1)
x = (W - total) / 2
y = 430
for ch, w in zip(text, widths):
    d.text((x, y), ch, font=font, fill=WHITE)
    x += w + spacing

img.save("/projects/sandbox/Toxic/assets/avatar.png", "PNG")
print("avatar.png сохранён")
