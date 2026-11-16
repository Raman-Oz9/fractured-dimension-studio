"""Pure-time procedural Fractured Dimension flat-illustration renderer."""
from __future__ import annotations
import math, random, shutil, subprocess, wave
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W,H=540,960
INK=(22,25,34); BLUE=(57,126,157); RED=(193,72,75)
VIOLET=(103,83,132); YELLOW=(232,190,87); PAPER=(232,223,198)
PALETTE=[INK,BLUE,RED,VIOLET,YELLOW,PAPER]

def ease(a,b,t):
    u=max(0,min(1,(t-a)/(b-a))); return u*u*(3-2*u)
def font(n):
    try: return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",n)
    except OSError: return ImageFont.load_default()
def poly(d,p,c,o=INK,w=4):
    d.polygon(p,fill=c)
    if o: d.line(p+[p[0]],fill=o,width=w,joint="curve")
def ln(d,p,c=INK,w=5): d.line(p,fill=c,width=w,joint="curve")

def background(t):
    im=Image.new("RGB",(W,H),PAPER); d=ImageDraw.Draw(im)
    d.rectangle((0,0,W,650),fill=INK)
    poly(d,[(0,0),(140,0),(115,620),(0,650)],VIOLET,w=3)
    poly(d,[(390,0),(540,0),(540,650),(420,620)],BLUE,w=3)
    for x in range(-20,600,115):
        y=150+(x*7%100)
        poly(d,[(x,y),(x+70,y-30),(x+90,625),(x-8,625)],VIOLET if x%2 else BLUE,w=3)
        for wy in range(y+60,570,105):
            for wx in (x+18,x+48): d.rectangle((wx,wy,wx+12,wy+23),fill=YELLOW if (wx+wy)//11%3 else RED)
    for x in (40,410):
        poly(d,[(x,310),(x+130,310),(x+112,355),(x+18,355)],RED,w=3)
        for k in range(4): d.polygon([(x+8+k*31,310),(x+32+k*31,310),(x+24+k*31,355),(x+1+k*31,355)],fill=PAPER)
    for x,y in ((95,130),(450,185),(275,90)):
        sway=math.sin(t*2.3+x)*5
        ln(d,[(x,0),(x+sway,y-18)],YELLOW,2)
        d.ellipse((x+sway-12,y-18,x+sway+12,y+18),fill=YELLOW,outline=INK,width=3)
    d.rectangle((0,625,W,H),fill=INK)
    for r in range(7):
        y=650+r*53
        for x in range(-30+(r%2)*28,W,58):
            d.rounded_rectangle((x,y,x+50,y+34),radius=7,fill=VIOLET if r%2 else BLUE,outline=INK,width=3)
    pulse=abs(math.sin(t*3))
    ln(d,[(0,810),(125,790),(175,835),(290,790),(355,825),(540,770)],RED,2+int(3*pulse))
    return im

def boro(im,x,y,t,pose="normal",s=1.25):
    d=ImageDraw.Draw(im)
    lean={"trip":-.42*ease(0,1,t),"kneel":.08,"assistant":.02}.get(pose,.03*math.sin(t*4))
    arm=math.sin(t*4)*.5 if pose=="normal" else (1 if pose=="trip" else -.7)
    def tr(a,b):
        a*=s; b*=s
        return (x+a*math.cos(lean)-b*math.sin(lean),y+a*math.sin(lean)+b*math.cos(lean))
    def P(ps): return [tr(a,b) for a,b in ps]
    ln(d,P([(-13,55),(-20,87),(-31,93)]),INK,int(8*s))
    ln(d,P([(13,55),(21,86),(34,92)]),INK,int(8*s))
    d.ellipse((x-42*s,y+83*s,x-18*s,y+99*s),fill=RED,outline=INK,width=3)
    d.ellipse((x+21*s,y+83*s,x+46*s,y+99*s),fill=YELLOW,outline=INK,width=3)
    poly(d,P([(-25,-8),(22,-8),(34,57),(15,69),(-22,62),(-35,18)]),VIOLET,w=5)
    poly(d,P([(-4,-2),(8,0),(16,58),(0,63),(-8,18)]),RED,w=2)
    ln(d,P([(-22,4),(-45,16+arm*15),(-54,31+arm*14)]),INK,int(8*s))
    ln(d,P([(22,2),(43,18-arm*12),(52,31-arm*12)]),INK,int(7*s))
    d.ellipse((x-24*s,y-63*s,x+24*s,y-12*s),fill=PAPER,outline=INK,width=4)
    d.ellipse((x-17*s,y-47*s,x-7*s,y-38*s),fill=INK)
    d.ellipse((x+7*s,y-47*s,x+17*s,y-38*s),fill=INK)
    poly(d,P([(-3,-45),(8,-31),(0,-29),(-8,-35)]),YELLOW,w=2)
    ln(d,P([(-15,-25),(-5,-20),(0,-24),(8,-20),(17,-25)]),INK,4)
    d.rectangle((x+2*s,y-21*s,x+8*s,y-16*s),fill=YELLOW)
    poly(d,P([(-31,-65),(27,-65),(21,-83),(-18,-88)]),INK,w=3)
    poly(d,P([(-21,-85),(-15,-124),(13,-128),(22,-85)]),BLUE,w=4)
    ln(d,P([(-14,-125),(0,-135),(18,-123)]),RED,3)

def shadow(im,x,y,t,pose="stand",s=1.45):
    d=ImageDraw.Draw(im); bob=math.sin(t*5)*4*s
    poly(d,[(x-30*s,y-2*s+bob),(x-22*s,y-61*s+bob),(x-12*s,y-94*s+bob),(x+15*s,y-96*s+bob),(x+24*s,y-57*s+bob),(x+34*s,y+8*s)],INK,RED,3)
    poly(d,[(x-23*s,y-91*s+bob),(x-17*s,y-125*s+bob),(x+14*s,y-129*s+bob),(x+24*s,y-91*s+bob)],INK,BLUE,3)
    d.ellipse((x-13*s,y-70*s+bob,x-5*s,y-62*s+bob),fill=BLUE)
    d.ellipse((x+7*s,y-70*s+bob,x+15*s,y-62*s+bob),fill=BLUE)
    ln(d,[(x-8*s,y-48*s+bob),(x+9*s,y-44*s+bob)],RED,3)
    if pose in ("point","bow"):
        ex=x+76*s; ey=y-15*s if pose=="point" else y+15*s
        ln(d,[(x+18*s,y-5*s),(ex,ey)],INK,9)
    else: ln(d,[(x+18*s,y-5*s),(x+42*s,y+20*s)],INK,8)
    ln(d,[(x-12*s,y+5*s),(x-28*s,y+43*s)],INK,9)
    ln(d,[(x+12*s,y+5*s),(x+30*s,y+42*s)],INK,9)

def frame_at(t):
    im=background(t); d=ImageDraw.Draw(im)
    bx=180-60*ease(10,15,t)+110*ease(20,25,t)-40*ease(30,35,t)
    sx=190+180*ease(10,16,t)-15*ease(15,20,t)
    spotlight=.15+.85*ease(13,19,t)
    d.ellipse((sx-110*spotlight,390,sx+110*spotlight,680),outline=YELLOW,width=3)
    if t<10: boro(im,bx,665,t); shadow(im,bx+10,666,t,s=1.25)
    elif t<15: boro(im,bx,665,t); shadow(im,bx+10+(sx-bx-10)*ease(10,15,t),665,t)
    elif t<20: boro(im,bx,665,t,"kneel",1.15); shadow(im,sx,655,t)
    elif t<25: boro(im,bx,665,t,"trip"); shadow(im,sx,655,t)
    elif t<30: boro(im,bx,665,t,"kneel",1.18); shadow(im,sx,655,t,"point")
    else: boro(im,bx,665,t,"assistant",1.18); shadow(im,sx,655,t,"bow")
    ln(d,[(300,720),(370,850)],PAPER,7)
    poly(d,[(360,840),(400,865),(365,875),(345,858)],YELLOW,w=3)
    if t<3.8:
        d.rounded_rectangle((28,55,510,155),radius=8,fill=INK,outline=YELLOW,width=3)
        d.text((48,70),"THE SHADOW",font=font(36),fill=PAPER)
        d.text((48,112),"THAT QUIT",font=font(30),fill=YELLOW)
    captions=["A MAGician. A MIDNIGHT MARKET.","HIS SHADOW DID ALL THE WORK.","TONIGHT, IT WALKED AWAY.","THE SHADOW STOLE THE SHOW.","BORO TRIED TO TAKE IT BACK.","THE SHADOW HAD ONE CONDITION.","ASSISTANT. NOT THE STAR.","THE OVATION WASN'T FOR BORO."]
    ci=min(7,int(t//5))
    d.rounded_rectangle((26,855,514,925),radius=8,fill=INK,outline=YELLOW,width=2)
    cap=captions[ci]
    d.text((270,890),cap,font=font(19),fill=PAPER,anchor="mm")
    d.rectangle((12,12,W-13,H-13),outline=PAPER,width=3)
    rng=random.Random(int(t*30)+1907)
    for _ in range(900):
        px=rng.randrange(18,W-18); py=rng.randrange(18,H-18)
        if rng.random()<.6: d.point((px,py),fill=PALETTE[rng.randrange(6)])
    return im

def render_procedural_story(story: dict, output: str|Path)->Path:
    if shutil.which("ffmpeg") is None: raise RuntimeError("FFmpeg is required")
    out=Path(output); out.parent.mkdir(parents=True,exist_ok=True)
    duration=sum(float(s["duration"]) for s in story["shots"])
    fps=int(story.get("format",{}).get("fps",30)); total=round(duration*fps)
    silent=out.with_name("."+out.stem+"-silent.mp4")
    cmd=["ffmpeg","-y","-f","rawvideo","-pix_fmt","rgb24","-s",f"{W}x{H}","-r",str(fps),"-i","-","-an","-c:v","libx264","-preset","veryfast","-crf","18","-pix_fmt","yuv420p",str(silent)]
    p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for i in range(total):
            t=i/fps
            im=frame_at(t)
            # Time-driven camera choreography: push, lateral reveal, then settle.
            z=1.0+0.12*ease(0,5,t)+0.08*ease(15,20,t)-0.10*ease(30,40,t)
            fx=0.5+0.16*math.sin(t*math.pi/20)
            fy=0.5-0.05*math.sin(t*math.pi/10)
            cw=int(W/z); ch=int(H/z)
            left=max(0,min(W-cw,int(fx*W-cw/2))); top=max(0,min(H-ch,int(fy*H-ch/2)))
            im=im.crop((left,top,left+cw,top+ch)).resize((1080,1920),Image.Resampling.LANCZOS)
            p.stdin.write(im.tobytes())
        p.stdin.close(); code=p.wait()
        if code: raise RuntimeError("FFmpeg procedural render failed; see runner logs.")
    except Exception:
        if p.poll() is None: p.kill(); p.wait()
        raise
    narration=story.get("narration")
    if narration:
        from .voice import generate_voiceover
        voice=out.with_name("."+out.stem+"-voice.wav")
        generate_voiceover(narration,voice)
        with wave.open(str(voice),"rb") as wf: speech=wf.getnframes()/wf.getframerate()
        if speech < duration*.94:
            voice.unlink(missing_ok=True); silent.unlink(missing_ok=True)
            raise RuntimeError(f"Narration QC failed: {speech:.1f}s spoken audio for {duration:.1f}s video. No silent padding will be added.")
        subprocess.run(["ffmpeg","-y","-i",str(silent),"-i",str(voice),"-map","0:v:0","-map","1:a:0","-c:v","copy","-c:a","aac","-b:a","192k","-t",str(duration),"-movflags","+faststart",str(out)],check=True,capture_output=True,text=True)
        voice.unlink(missing_ok=True); silent.unlink(missing_ok=True)
    else: silent.replace(out)
    return out
