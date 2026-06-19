#!/usr/bin/env python3
# Generate one looping APNG per companion-robot face state, 800x480.
import math, os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 800, 480
OUT = "/mnt/user-data/outputs/apng"
os.makedirs(OUT, exist_ok=True)

FONT_Z = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)

def hx(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

# state color config (face = bright core, glow = halo / ambient accent)
STATES = {
    "boot":      dict(zh="開機",  en="BOOT",   face="#cfeee9", glow="#7fe3d4"),
    "idle":      dict(zh="待機",  en="IDLE",   face="#e3faf5", glow="#7fe3d4"),
    "listening": dict(zh="聆聽中", en="LISTEN", face="#e6f1ff", glow="#8fb8ff"),
    "thinking":  dict(zh="思考中", en="THINK",  face="#fff0cf", glow="#ffd36e"),
    "speaking":  dict(zh="說話中", en="SPEAK",  face="#e3faf5", glow="#7fe3d4"),
    "happy":     dict(zh="開心",  en="HAPPY",  face="#fff0c2", glow="#ffd36e"),
    "sad":       dict(zh="難過",  en="SAD",    face="#dcebff", glow="#8fb8ff"),
    "dejected":  dict(zh="沮喪",  en="DOWN",   face="#e6def5", glow="#a99bc4"),
    "angry":     dict(zh="生氣",  en="ANGRY",  face="#ffe0d8", glow="#ff9a8a"),
    "sleep":     dict(zh="休眠",  en="SLEEP",  face="#c2c9e6", glow="#6f6790"),
    "error":     dict(zh="異常",  en="ERROR",  face="#ffd2c9", glow="#ff6b6b"),
}

# ---- geometry (800x480) ----
LEX, REX, EYEY = 314, 486, 200          # eye centers
EW, EH = 84, 112                         # eye box
ERAD = 40
HLX = (-18, -24)                         # highlight offset from eye center
MX, MY = 400, 330                        # mouth center

# ---------- drawing helpers ----------
def quad(p0, p1, p2, n=42):
    out = []
    for i in range(n + 1):
        t = i / n
        x = (1-t)**2*p0[0] + 2*(1-t)*t*p1[0] + t*t*p2[0]
        y = (1-t)**2*p0[1] + 2*(1-t)*t*p1[1] + t*t*p2[1]
        out.append((x, y))
    return out

def seg(p0, p1, n=30):
    return [(p0[0]+(p1[0]-p0[0])*i/n, p0[1]+(p1[1]-p0[1])*i/n) for i in range(n+1)]

def stroke(d, pts, width, color):
    r = width / 2.0
    for (x, y) in pts:
        d.ellipse([x-r, y-r, x+r, y+r], fill=color)

def make_bg(glow):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    cx, cy = W/2, H*0.42
    r = np.sqrt(((xx-cx)/(W*0.62))**2 + ((yy-cy)/(H*0.62))**2)
    r = np.clip(r, 0, 1)[..., None]
    a = np.array([0x25, 0x1d, 0x36], np.float32)
    b = np.array([0x10, 0x0c, 0x1a], np.float32)
    base = a*(1-r) + b*r
    ar = np.sqrt(((xx-cx)/(W*0.46))**2 + ((yy-cy)/(H*0.5))**2)
    ar = (np.clip(1-ar, 0, 1)**2)[..., None]
    acc = np.array(hx(glow), np.float32)
    base = base + (acc-base)*(ar*0.16)
    return Image.fromarray(base.clip(0, 255).astype("uint8"), "RGB")

def scale_alpha(im, f):
    r, g, b, a = im.split()
    return Image.merge("RGBA", (r, g, b, a.point(lambda v: int(v*f))))

# ---------- mouth shapes ----------
def mouth_curve(state):
    m = {
        "idle":     (quad((340,322),(400,360),(460,322)), 16),
        "boot":     (seg((372,330),(428,330)), 12),
        "listening":(quad((348,323),(400,352),(452,323)), 16),
        "thinking": (quad((372,331),(404,326),(436,331)), 14),
        "sad":      (quad((340,348),(400,316),(460,348)), 16),
        "dejected": (quad((352,340),(400,333),(452,346)), 14),
        "angry":    (quad((350,346),(400,316),(450,346)), 16),
        "sleep":    (quad((378,331),(400,342),(422,331)), 12),
        "error":    ([(356,334),(376,324),(396,336),(416,324),(436,336),(444,332)], 12),
    }
    return m.get(state)

def happy_mouth_poly():
    top = quad((338,318),(400,332),(462,318), 30)
    bot = quad((462,318),(400,378),(338,318), 30)
    return top + bot

# ---- talking mouth (emotion-flavored), mapped from the approved 320-space mockup ----
TALK_KEYS = {"happy", "sad", "angry", "dejected", "speaking"}
S_M = 172/84.0                                   # mockup(320) -> render(800) scale
def mk(x, y):
    return (400 + (x-160)*S_M, 200 + (y-141)*S_M)
MOUTHS_M = {                                     # (half_width, cornerY, upper-lip Y, open depth)
    "happy":    (26, 210, 221, 18),
    "sad":      (22, 224, 210, 12),
    "angry":    (22, 222, 213, 14),
    "dejected": (15, 219, 215, 8),
    "speaking": (18, 214, 214, 16),
}
def talk_mouth_pts(key, open_):
    w, corner, mid, depth = MOUTHS_M[key]
    cx = 160; L = cx-w; R = cx+w
    low = mid + max(open_*depth, 2.5)            # keep a thin emotional mouth when "closed"
    Cup  = 2*mid - corner
    Clow = 2*low - corner
    top = quad((L, corner), (cx, Cup),  (R, corner), 24)
    bot = quad((R, corner), (cx, Clow), (L, corner), 24)
    return [mk(x, y) for (x, y) in top + bot]

# one shared slow talking rhythm (~300ms per beat); shape carries the emotion, not the speed
TALK_KF = [(0.00,0.0),(0.14,0.72),(0.29,0.22),(0.43,0.95),
           (0.57,0.32),(0.71,0.62),(0.86,0.12),(1.00,0.0)]
def talk_open(frac):
    for j in range(len(TALK_KF)-1):
        a, b = TALK_KF[j], TALK_KF[j+1]
        if a[0] <= frac <= b[0]:
            t = (frac-a[0])/(b[0]-a[0]) if b[0] > a[0] else 0.0
            t = t*t*(3-2*t)                       # smoothstep glide
            return a[1] + (b[1]-a[1])*t
    return 0.0

# ---------- eyes ----------
def draw_eye_open(feat, cx, squash):
    h = EH*squash
    box = [cx-EW/2, EYEY-h/2, cx+EW/2, EYEY+h/2]
    rad = min(ERAD, h/2)
    feat(lambda d, c: d.rounded_rectangle(box, radius=rad, fill=c))

def draw_eye_happy(feat, cx):
    feat(lambda d, c: stroke(d, quad((cx-38,EYEY+12),(cx,EYEY-26),(cx+38,EYEY+12)), 18, c))

def draw_eye_closed(feat, cx):
    feat(lambda d, c: stroke(d, quad((cx-36,EYEY-2),(cx,EYEY+16),(cx+36,EYEY-2)), 14, c))

def draw_eye_x(feat, cx):
    feat(lambda d, c: stroke(d, seg((cx-26,EYEY-26),(cx+26,EYEY+26)), 13, c))
    feat(lambda d, c: stroke(d, seg((cx+26,EYEY-26),(cx-26,EYEY+26)), 13, c))

# ---------- brows ----------
def brow_pts(mode):
    if mode == "happy":
        return ((278,122),(350,116)), ((450,116),(522,122))
    if mode == "sad":
        return ((278,140),(350,116)), ((450,116),(522,140))
    if mode == "angry":
        return ((282,116),(350,142)), ((450,142),(522,116))
    if mode == "dejected":
        return ((282,150),(350,150)), ((450,150),(522,150))
    return None

# ---------- master compose ----------
def compose(cfg, P):
    glow_c = hx(cfg["glow"]); face_c = hx(cfg["face"])
    bg = P["_bg"].copy().convert("RGBA")
    glowL = Image.new("RGBA", (W, H), (0,0,0,0))
    sharpL = Image.new("RGBA", (W, H), (0,0,0,0))
    gd, sd = ImageDraw.Draw(glowL), ImageDraw.Draw(sharpL)

    ox = P.get("glitch_dx", 0)
    oy = P.get("dy", 0)
    def feat(fn):                      # draw on both layers, offset applied
        fn(_Off(gd, ox, oy), glow_c)
        fn(_Off(sd, ox, oy), face_c)

    # cheeks (own soft layer)
    ca = P.get("cheeks", 0.0)
    if ca > 0:
        cheek = Image.new("RGBA", (W, H), (0,0,0,0))
        cdd = ImageDraw.Draw(cheek)
        col = glow_c + (int(255*ca),)
        for cx in (250, 550):
            cdd.ellipse([cx-40, 272-30+oy, cx+40, 272+30+oy], fill=col)
        cheek = cheek.filter(ImageFilter.GaussianBlur(10))
        bg = Image.alpha_composite(bg, cheek)

    # brows
    bm = P.get("brow")
    if bm and brow_pts(bm):
        for (a, b) in brow_pts(bm):
            feat(lambda d, c, a=a, b=b: stroke(d, seg(a, b, 24), 16, c))

    # eyes
    em = P.get("eye", "open")
    gx, gy = P.get("gx", 0), P.get("gy", 0)
    if em == "open":
        sq = P.get("squash", 1.0)
        for cx in (LEX, REX):
            h = EH*sq
            box = [cx-EW/2+ox+gx, EYEY-h/2+oy+gy, cx+EW/2+ox+gx, EYEY+h/2+oy+gy]
            rad = min(ERAD, h/2)
            gd.rounded_rectangle(box, radius=rad, fill=glow_c)
            sd.rounded_rectangle(box, radius=rad, fill=face_c)
            if sq > 0.6:
                hx_, hy_ = cx+HLX[0]+ox+gx, EYEY+HLX[1]+oy+gy
                sd.ellipse([hx_-10, hy_-10, hx_+10, hy_+10], fill=(255,255,255,235))
    elif em == "happy":
        for cx in (LEX, REX):
            feat(lambda d, c, cx=cx: stroke(
                d, quad((cx-38,EYEY+12),(cx,EYEY-26),(cx+38,EYEY+12)), 18, c))
    elif em == "closed":
        for cx in (LEX, REX):
            feat(lambda d, c, cx=cx: stroke(
                d, quad((cx-36,EYEY-2),(cx,EYEY+16),(cx+36,EYEY-2)), 14, c))
    elif em == "x":
        for cx in (LEX, REX):
            feat(lambda d, c, cx=cx: stroke(d, seg((cx-26,EYEY-26),(cx+26,EYEY+26)), 13, c))
            feat(lambda d, c, cx=cx: stroke(d, seg((cx+26,EYEY-26),(cx-26,EYEY+26)), 13, c))

    # mouth
    st = P["state"]
    if st in TALK_KEYS:
        pts = [(x+ox, y+oy) for (x, y) in talk_mouth_pts(st, P.get("mouth_open", 0.0))]
        gd.polygon(pts, fill=glow_c); sd.polygon(pts, fill=face_c)
    else:
        mc = mouth_curve(st)
        if mc:
            pts = [(x+ox, y+oy) for (x, y) in mc[0]]
            feat(lambda d, c, pts=pts, w=mc[1]: stroke(d, pts, w, c))

    # ---- symbols (drawn into glow+sharp so they glow) ----
    sym = P.get("sym", {})
    if "tear" in sym:
        t = sym["tear"]; y = 252 + t*92
        col = (190, 224, 255)
        feat(lambda d, c, y=y, col=col: d.ellipse([300-11, y-11, 300+11, y+11], fill=col))
    if "sweat" in sym:
        t = sym["sweat"]; y = 150 + t*14
        feat(lambda d, c, y=y: (
            d.ellipse([536, y+8, 556, y+30], fill=(190,230,255)),
            d.polygon([(546, y-6), (538, y+14), (554, y+14)], fill=(190,230,255))))
    if "anger" in sym:
        s = sym["anger"]; cxp, cyp = 540, 112; L = 16*s
        col = (255, 138, 120)
        for ang in (0, 60, 120, 180, 240, 300):
            a = math.radians(ang)
            feat(lambda d, c, a=a: stroke(
                d, seg((cxp, cyp), (cxp+L*math.cos(a), cyp+L*math.sin(a)), 6), 6, col))
    if "spark" in sym:
        t = sym["spark"]
        for (cxp, cyp, ph) in [(176, 214, 0.0), (616, 150, 0.5)]:
            s = 8 + 16*(0.5+0.5*math.sin(2*math.pi*(t+ph)))
            star = [(cxp,cyp-s),(cxp+0.28*s,cyp-0.28*s),(cxp+s,cyp),(cxp+0.28*s,cyp+0.28*s),
                    (cxp,cyp+s),(cxp-0.28*s,cyp+0.28*s),(cxp-s,cyp),(cxp-0.28*s,cyp-0.28*s)]
            feat(lambda d, c, star=star: d.polygon(star, fill=(255,227,154)))
    if "dots" in sym:
        ph = sym["dots"]
        for i, dx in enumerate((470, 510, 550)):
            up = 8*max(0, math.sin(math.pi*(ph - i*0.18)))
            feat(lambda d, c, dx=dx, up=up: d.ellipse(
                [dx-9, 116-up, dx+9, 134-up], fill=c))
    if "bang" in sym:
        s = sym["bang"]
        col = (255, 138, 120)
        feat(lambda d, c: d.rounded_rectangle([394, 70, 406, 104], radius=6, fill=col))
        feat(lambda d, c: d.ellipse([394, 110, 406, 122], fill=col))

    # ---- composite glow + sharp ----
    glow_blur = glowL.filter(ImageFilter.GaussianBlur(15))
    out = bg
    out = Image.alpha_composite(out, glow_blur)
    out = Image.alpha_composite(out, glow_blur)
    fa = P.get("face_alpha", 1.0)
    if fa < 1.0:
        out = Image.alpha_composite(out, scale_alpha(glow_blur, fa*0.6))
        out = Image.alpha_composite(out, scale_alpha(sharpL, fa))
    else:
        out = Image.alpha_composite(out, sharpL)

    # ---- overlays drawn directly (rings / scan / zzz) ----
    if "rings" in P:
        ov = Image.new("RGBA", (W, H), (0,0,0,0))
        od = ImageDraw.Draw(ov)
        for fr in P["rings"]:
            a = int(150*(1-fr))
            rx, ry = 150+fr*300, 95+fr*180
            od.ellipse([400-rx, 210-ry, 400+rx, 210+ry], outline=glow_c+(a,), width=4)
        out = Image.alpha_composite(out, ov)
    if "scan_y" in P:
        ov = Image.new("RGBA", (W, H), (0,0,0,0))
        od = ImageDraw.Draw(ov)
        y = P["scan_y"]
        od.rectangle([0, y-26, W, y+26], fill=glow_c+(70,))
        ov = ov.filter(ImageFilter.GaussianBlur(12))
        out = Image.alpha_composite(out, ov)
    if "zzz" in P:
        ov = Image.new("RGBA", (W, H), (0,0,0,0))
        od = ImageDraw.Draw(ov)
        for (x, y, sz, al) in P["zzz"]:
            f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(sz))
            od.text((x, y), "Z", font=f, fill=(180, 190, 220, int(al*255)))
        out = Image.alpha_composite(out, ov)

    return out.convert("RGB")


class _Off:
    """Wrap an ImageDraw so geometry helpers that already bake offsets are bypassed.
    Used only for stroke()/polygon paths that don't get ox/oy elsewhere."""
    def __init__(self, d, ox, oy): self.d, self.ox, self.oy = d, ox, oy
    def ellipse(self, box, **k):
        b = [box[0]+self.ox, box[1]+self.oy, box[2]+self.ox, box[3]+self.oy]
        self.d.ellipse(b, **k)
    def polygon(self, pts, **k):
        self.d.polygon([(x+self.ox, y+self.oy) for (x, y) in pts], **k)
    def rounded_rectangle(self, box, **k):
        b = [box[0]+self.ox, box[1]+self.oy, box[2]+self.ox, box[3]+self.oy]
        self.d.rounded_rectangle(b, **k)


# ---------- per-state frame plans ----------
def blink_squash(i, at, span=3):
    # returns squash 1.0 normally, dipping near frame `at`
    d = abs(i - at)
    if d == 0: return 0.08
    if d == 1: return 0.4
    return 1.0

def frames_for(state):
    cfg = STATES[state]
    bg = make_bg(cfg["glow"])
    P0 = dict(state=state, _bg=bg)
    fr, dl = [], []

    if state == "idle":
        N = 36
        for i in range(N):
            P = dict(P0, dy=8*math.sin(2*math.pi*i/N),
                     squash=blink_squash(i, 31))
            fr.append(compose(cfg, P)); dl.append(70)

    elif state == "listening":
        N = 30
        for i in range(N):
            f1 = (i/N); f2 = ((i/N)+0.5) % 1.0
            P = dict(P0, dy=5*math.sin(2*math.pi*i/N), squash=blink_squash(i, 27),
                     cheeks=0.30, rings=[f1, f2])
            fr.append(compose(cfg, P)); dl.append(80)

    elif state == "thinking":
        N = 30
        for i in range(N):
            P = dict(P0, dy=3*math.sin(2*math.pi*i/N), gx=14, gy=-6,
                     sym={"dots": (i/N)*2.0})
            fr.append(compose(cfg, P)); dl.append(90)

    elif state == "speaking":
        N = 28
        for i in range(N):
            P = dict(P0, dy=4*math.sin(2*math.pi*i/N), squash=blink_squash(i, 24),
                     mouth_open=talk_open(i/N))
            fr.append(compose(cfg, P)); dl.append(78)

    elif state == "happy":
        N = 28
        for i in range(N):
            P = dict(P0, dy=8*math.sin(2*math.pi*i/N), eye="happy", brow="happy",
                     cheeks=0.6, sym={"spark": i/N}, mouth_open=talk_open(i/N))
            fr.append(compose(cfg, P)); dl.append(75)

    elif state == "sad":
        N = 28
        for i in range(N):
            P = dict(P0, dy=4*math.sin(2*math.pi*i/N), squash=0.78, gy=6,
                     brow="sad", sym={"tear": (i % 14)/14}, mouth_open=talk_open(i/N))
            fr.append(compose(cfg, P)); dl.append(78)

    elif state == "dejected":
        N = 28
        for i in range(N):
            P = dict(P0, dy=4+3*math.sin(2*math.pi*i/N), squash=0.6, gy=8,
                     brow="dejected", sym={"sweat": 0.5+0.5*math.sin(2*math.pi*i/N)},
                     mouth_open=talk_open(i/N))
            fr.append(compose(cfg, P)); dl.append(80)

    elif state == "angry":
        N = 28
        for i in range(N):
            P = dict(P0, dy=2*math.sin(4*math.pi*i/N), squash=0.85, brow="angry",
                     cheeks=0.7, sym={"anger": 0.85+0.3*(0.5+0.5*math.sin(2*math.pi*i/N))},
                     mouth_open=talk_open(i/N))
            fr.append(compose(cfg, P)); dl.append(76)

    elif state == "sleep":
        N = 40
        for i in range(N):
            zzz = []
            for k in range(3):
                t = ((i/N) + k/3.0) % 1.0
                zzz.append((512+k*14, 120-t*34, 18+t*14, max(0.0, 1-abs(t*2-0.6))))
            P = dict(P0, dy=5*math.sin(2*math.pi*i/N), eye="closed", zzz=zzz)
            fr.append(compose(cfg, P)); dl.append(95)

    elif state == "boot":
        N = 28
        for i in range(N):
            P = dict(P0, face_alpha=min(1.0, i/10.0),
                     scan_y=(i/N)*540-20, squash=1.0)
            fr.append(compose(cfg, P)); dl.append(70)

    elif state == "error":
        N = 18
        for i in range(N):
            gd = (-5 if i % 2 else 5) + (12 if i in (4, 5) else 0)
            P = dict(P0, eye="x", glitch_dx=gd, face_alpha=(0.78 if i % 4 == 0 else 1.0),
                     sym={"bang": 0.8+0.3*math.sin(2*math.pi*i/N)})
            fr.append(compose(cfg, P)); dl.append(70)

    return fr, dl


def main():
    paths = []
    for state in STATES:
        frames, delays = frames_for(state)
        p = f"{OUT}/{state}.png"
        frames[0].save(p, save_all=True, append_images=frames[1:],
                       duration=delays, loop=0, format="PNG")
        sz = os.path.getsize(p)/1024
        print(f"{state:10s} {len(frames):2d} frames  {sz:6.0f} KB  -> {p}")
        paths.append(p)
    return paths


if __name__ == "__main__":
    main()
