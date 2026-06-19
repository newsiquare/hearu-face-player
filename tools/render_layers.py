#!/usr/bin/env python3
# Bake layered sprite assets for the pygame runtime player.
# Per talking emotion: screen base (bg+ambient+cheeks+symbol), brows, eyes(open/closed),
# and an 8-step mouth set. Glow is baked in (same look as the approved APNGs).
import math, os
from PIL import Image, ImageDraw, ImageFilter

W, H = 800, 480
OUT = "/mnt/user-data/outputs/pideploy/assets/sprites"
os.makedirs(OUT, exist_ok=True)

def hx(h):
    h=h.lstrip("#"); return tuple(int(h[i:i+2],16) for i in (0,2,4))

EMO = {
    "happy":   {"face":"#ffe9b0","glow":"#ffd36e","brow":"happy","cheek":0.60,"sym":"spark","eye":"happy"},
    "sad":     {"face":"#cfe2ff","glow":"#8fb8ff","brow":"sad",  "cheek":0.0, "sym":"tear", "eye":"open"},
    "dejected":{"face":"#ded6ef","glow":"#a99bc4","brow":"dejected","cheek":0.0,"sym":"sweat","eye":"open"},
    "angry":   {"face":"#ffd9d0","glow":"#ff9a8a","brow":"angry","cheek":0.70,"sym":"anger","eye":"open"},
    "speaking":{"face":"#d6f4ee","glow":"#7fe3d4","brow":None,   "cheek":0.0, "sym":None,  "eye":"open"},
}
MOUTH_STEPS = 8

# geometry (800x480)
LEX,REX,EYEY = 314,486,200
EW,EH,ERAD = 84,112,40
MX = 400
S_M = 172/84.0
def mk(x,y): return (400+(x-160)*S_M, 200+(y-141)*S_M)
MOUTHS_M = {"happy":(26,210,221,18),"sad":(22,224,210,12),"angry":(22,222,213,14),
            "dejected":(15,219,215,8),"speaking":(18,214,214,16)}

def quad(p0,p1,p2,n=42):
    o=[]
    for i in range(n+1):
        t=i/n
        o.append(((1-t)**2*p0[0]+2*(1-t)*t*p1[0]+t*t*p2[0],
                  (1-t)**2*p0[1]+2*(1-t)*t*p1[1]+t*t*p2[1]))
    return o
def seg(p0,p1,n=26):
    return [(p0[0]+(p1[0]-p0[0])*i/n, p0[1]+(p1[1]-p0[1])*i/n) for i in range(n+1)]
def stroke(d,pts,w,col):
    r=w/2
    for (x,y) in pts: d.ellipse([x-r,y-r,x+r,y+r],fill=col)

def make_bg(glow):
    import numpy as np
    yy,xx=np.mgrid[0:H,0:W].astype(np.float32)
    cx,cy=W/2,H*0.42
    r=np.clip(np.sqrt(((xx-cx)/(W*0.62))**2+((yy-cy)/(H*0.62))**2),0,1)[...,None]
    a=np.array([0x25,0x1d,0x36],np.float32); b=np.array([0x10,0x0c,0x1a],np.float32)
    base=a*(1-r)+b*r
    ar=(np.clip(1-np.sqrt(((xx-cx)/(W*0.46))**2+((yy-cy)/(H*0.5))**2),0,1)**2)[...,None]
    base=base+(np.array(hx(glow),np.float32)-base)*(ar*0.16)
    return Image.fromarray(base.clip(0,255).astype("uint8"),"RGB").convert("RGBA")

def layer(draw_fn, glow_c, face_c, blur=15):
    glow=Image.new("RGBA",(W,H),(0,0,0,0)); sharp=Image.new("RGBA",(W,H),(0,0,0,0))
    draw_fn(ImageDraw.Draw(glow),glow_c, ImageDraw.Draw(sharp),face_c)
    gb=glow.filter(ImageFilter.GaussianBlur(blur))
    out=Image.new("RGBA",(W,H),(0,0,0,0))
    out=Image.alpha_composite(out,gb); out=Image.alpha_composite(out,gb)
    out=Image.alpha_composite(out,sharp)
    return out

# ---- mouth ----
def mouth_pts(key,open_):
    w,corner,mid,depth=MOUTHS_M[key]; cx=160; L=cx-w; R=cx+w
    low=mid+max(open_*depth,2.5); Cup=2*mid-corner; Clow=2*low-corner
    top=quad((L,corner),(cx,Cup),(R,corner),24); bot=quad((R,corner),(cx,Clow),(L,corner),24)
    return [mk(x,y) for (x,y) in top+bot]
def draw_mouth(key,open_):
    pts=mouth_pts(key,open_)
    return lambda gd,gc,sd,fc:(gd.polygon(pts,fill=gc), sd.polygon(pts,fill=fc))

# ---- eyes ----
def draw_eyes_open(mode):
    def fn(gd,gc,sd,fc):
        if mode=="happy":
            for cx in (LEX,REX):
                stroke(gd,quad((cx-38,EYEY+12),(cx,EYEY-26),(cx+38,EYEY+12)),18,gc)
                stroke(sd,quad((cx-38,EYEY+12),(cx,EYEY-26),(cx+38,EYEY+12)),18,fc)
        else:
            for cx in (LEX,REX):
                box=[cx-EW/2,EYEY-EH/2,cx+EW/2,EYEY+EH/2]
                gd.rounded_rectangle(box,radius=ERAD,fill=gc)
                sd.rounded_rectangle(box,radius=ERAD,fill=fc)
                sd.ellipse([cx-18-10,EYEY-24-10,cx-18+10,EYEY-24+10],fill=(255,255,255,235))
    return fn
def draw_eyes_closed():
    def fn(gd,gc,sd,fc):
        for cx in (LEX,REX):
            stroke(gd,quad((cx-36,EYEY-2),(cx,EYEY+16),(cx+36,EYEY-2)),14,gc)
            stroke(sd,quad((cx-36,EYEY-2),(cx,EYEY+16),(cx+36,EYEY-2)),14,fc)
    return fn

# ---- brows ----
def brow_endpoints(mode):
    return {"happy":(((278,122),(350,116)),((450,116),(522,122))),
            "sad":  (((278,140),(350,116)),((450,116),(522,140))),
            "angry":(((282,116),(350,142)),((450,142),(522,116))),
            "dejected":(((282,150),(350,150)),((450,150),(522,150)))}.get(mode)
def draw_brows(mode):
    eps=brow_endpoints(mode)
    def fn(gd,gc,sd,fc):
        for a,b in eps:
            stroke(gd,seg(a,b,24),16,gc); stroke(sd,seg(a,b,24),16,fc)
    return fn

# ---- symbols + cheeks baked into screen base ----
def add_cheeks(img,glow,alpha):
    if alpha<=0: return img
    c=Image.new("RGBA",(W,H),(0,0,0,0)); d=ImageDraw.Draw(c)
    col=hx(glow)+(int(255*alpha),)
    for cx in (250,550): d.ellipse([cx-40,242,cx+40,302],fill=col)
    return Image.alpha_composite(img,c.filter(ImageFilter.GaussianBlur(10)))
def symbol_layer(kind):
    def fn(gd,gc,sd,fc):
        if kind=="spark":
            for (cx,cy,s) in [(176,214,22),(616,150,16)]:
                star=[(cx,cy-s),(cx+0.28*s,cy-0.28*s),(cx+s,cy),(cx+0.28*s,cy+0.28*s),
                      (cx,cy+s),(cx-0.28*s,cy+0.28*s),(cx-s,cy),(cx-0.28*s,cy-0.28*s)]
                gd.polygon(star,fill=(255,227,154)); sd.polygon(star,fill=(255,227,154))
        elif kind=="tear":
            for d_ in (gd,sd): d_.ellipse([300-11,300-11,300+11,300+11],fill=(190,224,255))
        elif kind=="sweat":
            for d_ in (gd,sd):
                d_.ellipse([536,158,556,180],fill=(190,230,255))
                d_.polygon([(546,144),(538,164),(554,164)],fill=(190,230,255))
        elif kind=="anger":
            cxp,cyp=540,112; L=16
            for ang in (0,60,120,180,240,300):
                a=math.radians(ang)
                pts=seg((cxp,cyp),(cxp+L*math.cos(a),cyp+L*math.sin(a)),6)
                stroke(gd,pts,6,(255,138,120)); stroke(sd,pts,6,(255,138,120))
    return fn

def save(img,name): img.save(f"{OUT}/{name}.png"); return name

def main():
    manifest={}
    for e,cfg in EMO.items():
        gc,fc=hx(cfg["glow"]),hx(cfg["face"])
        # screen base = bg + cheeks + symbol (opaque)
        bg=make_bg(cfg["glow"])
        bg=add_cheeks(bg,cfg["glow"],cfg["cheek"])
        if cfg["sym"]:
            bg=Image.alpha_composite(bg, layer(symbol_layer(cfg["sym"]),gc,fc,blur=10))
        save(bg.convert("RGB"), f"screen_{e}")
        # brows
        if cfg["brow"]:
            save(layer(draw_brows(cfg["brow"]),gc,fc,blur=12), f"brows_{e}")
        # eyes
        save(layer(draw_eyes_open(cfg["eye"]),gc,fc), f"eyes_open_{e}")
        if cfg["eye"]!="happy":
            save(layer(draw_eyes_closed(),gc,fc), f"eyes_closed_{e}")
        # mouth steps
        for k in range(MOUTH_STEPS):
            save(layer(draw_mouth(e,k/(MOUTH_STEPS-1)),gc,fc), f"mouth_{e}_{k}")
        manifest[e]=cfg
        print("baked", e)
    print("done ->", OUT)

if __name__=="__main__":
    main()
