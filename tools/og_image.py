from PIL import Image, ImageDraw, ImageFont, ImageFilter
W,H=1200,630
NAVY=(10,16,36); GOLD=(231,206,142); GOLD2=(201,162,75); CREAM=(243,234,215); MUTED=(185,178,163)
img=Image.new("RGB",(W,H),NAVY)
# alone dorato tenue in alto al centro
glow=Image.new("L",(W,H),0); g=ImageDraw.Draw(glow)
g.ellipse((W/2-420,-260,W/2+420,330),fill=70)
glow=glow.filter(ImageFilter.GaussianBlur(120))
img=Image.composite(Image.new("RGB",(W,H),(46,40,40)),img,glow)
d=ImageDraw.Draw(img)
# cornice
d.rectangle((26,26,W-27,H-27),outline=(110,92,52),width=2)
def font(path,size,w):
    f=ImageFont.truetype(path,size)
    try: f.set_variation_by_axes([w] if "Cormorant" in path else [14,w] if False else [w])
    except Exception:
        try: f.set_variation_by_axes([w])
        except Exception: pass
    return f
def inter(size,w):
    f=ImageFont.truetype("/w/Inter.ttf",size)
    try:
        axes=f.get_variation_axes()
        vals=[]
        for a in axes:
            n=a.get("name",b"")
            n=n.decode() if isinstance(n,bytes) else str(n)
            vals.append(w if "eight" in n else max(a["minimum"],min(a["maximum"],size)))
        f.set_variation_by_axes(vals)
    except Exception: pass
    return f
def corm(size,w):
    f=ImageFont.truetype("/w/Cormorant.ttf",size)
    try: f.set_variation_by_axes([w])
    except Exception: pass
    return f
# bilancia (dal favicon, viewBox 32) centrata
s=4.4; ox=W/2-16*s; oy=58
def P(x,y): return (ox+x*s, oy+y*s)
lw=int(1.7*s)
d.line([P(16,8.5),P(16,24)],fill=GOLD,width=lw)
d.line([P(10,24),P(22,24)],fill=GOLD,width=lw)
d.line([P(6.5,11.5),P(25.5,11.5)],fill=GOLD,width=lw)
for cx in (6.5,25.5):
    d.line([P(cx,11.5),P(cx-2.6,16.9)],fill=GOLD,width=max(2,lw-2))
    d.line([P(cx,11.5),P(cx+2.6,16.9)],fill=GOLD,width=max(2,lw-2))
    x0,y0=P(cx-2.6,14.3); x1,y1=P(cx+2.6,19.5)
    d.chord((x0,y0,x1,y1),0,180,fill=(70,62,48),outline=GOLD,width=max(2,lw-2))
x,y=P(16,9); r=1.6*s; d.ellipse((x-r,y-r,x+r,y+r),fill=GOLD)
def centra(t,f,y,col,spacing=0):
    if spacing:
        larg=sum(d.textlength(c,font=f) for c in t)+spacing*(len(t)-1)
        x=(W-larg)/2
        for c in t:
            d.text((x,y),c,font=f,fill=col); x+=d.textlength(c,font=f)+spacing
    else:
        x=(W-d.textlength(t,font=f))/2; d.text((x,y),t,font=f,fill=col)
centra("SUPER AVOKATI",corm(112,600),190,GOLD,spacing=10)
# filetto con punto
d.line([(W/2-120,338),(W/2-14,338)],fill=GOLD2,width=2); d.line([(W/2+14,338),(W/2+120,338)],fill=GOLD2,width=2)
d.ellipse((W/2-5,333,W/2+5,343),fill=GOLD2)
centra("Beteja fitohet para se të nisë.",corm(48,500),368,CREAM)
centra("La battaglia si vince prima che inizi.",inter(27,300),432,MUTED)
centra("AVOKATË · PROKURORË · NOTERË",inter(20,500),520,GOLD2,spacing=4)
centra("LIGJI SHQIPTAR  &  DIRITTO ITALIANO",inter(17,400),556,(150,135,100),spacing=4)
img.save("/w/og-image.png",optimize=True)
print("ok",img.size)
