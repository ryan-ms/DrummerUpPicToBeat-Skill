#!/usr/bin/env python3
"""橫向捲動的鼓譜影片 → 拼成一張長譜（再切成好讀的放大段落）。

用法：python scroll_stitch.py 影片.mp4 -o stitch [--band 280:520] [--fps 10] [--start 0:00 --end 0:24]
輸出：stitch/panorama.png（整條長譜）、stitch/read_01.png…（放大、每段約 1000px 寬、前後重疊，依序讀）、
      stitch/band.png（自動偵測的譜面範圍，紅框；框錯就用 --band 指定 y 範圍重跑）
需要 Pillow、numpy，以及 ffmpeg（PATH 或 pip 的 imageio-ffmpeg）。
"""
import argparse, io, shutil, subprocess, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw


def ffmpeg_exe():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("❌ 這個環境沒有 ffmpeg，先試 `pip install imageio-ffmpeg`。")


def tsec(s):
    if s is None:
        return None
    p = [float(x) for x in str(s).split(":")]
    return p[0] * 60 + p[1] if len(p) == 2 else p[0]


def read_frames(path, fps, start, end):
    ff = ffmpeg_exe()
    cmd = [ff, "-v", "error"]
    if start is not None:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(path)]
    if end is not None:
        cmd += ["-t", str(end - (start or 0))]
    cmd += ["-vf", f"fps={fps}", "-f", "image2pipe", "-vcodec", "png", "-"]
    data = subprocess.run(cmd, capture_output=True).stdout
    frames = []
    sig = b"\x89PNG\r\n\x1a\n"
    parts = data.split(sig)[1:]
    for p in parts:
        try:
            frames.append(np.asarray(Image.open(io.BytesIO(sig + p)).convert("L"), dtype=np.float32))
        except Exception:
            pass
    return frames


def detect_band(frames):
    med = np.median(np.stack(frames[:: max(1, len(frames) // 30)]), axis=0)
    h, w = med.shape
    x0, x1 = int(w * 0.1), int(w * 0.9)
    bright = (np.percentile(med[:, x0:x1], 25, axis=1) > 215)   # 譜面列：大部分是白底
    # 譜線、符桿橫梁那幾列會整列偏暗：短於 h/40 的暗列空隙補起來
    gap = max(4, h // 40); y = 0
    while y < h:
        if not bright[y]:
            e = y
            while e < h and not bright[e]:
                e += 1
            if y > 0 and e < h and e - y <= gap:
                bright[y:e] = True
            y = e
        else:
            y += 1
    best, cur, s = (0, 0), 0, 0
    for y, b in enumerate(bright):
        if b:
            if cur == 0:
                s = y
            cur += 1
            if cur > best[1] - best[0]:
                best = (s, y + 1)
        else:
            cur = 0
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("-o", "--out", default="stitch")
    ap.add_argument("--band", help="譜面的 y 範圍（原始畫面像素），例如 280:520")
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--max-shift", type=int, default=0, help="每格最多捲動幾 px（預設畫面寬的 1/4）")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    frames = read_frames(a.video, a.fps, tsec(a.start), tsec(a.end))
    if len(frames) < 2:
        sys.exit("❌ 讀不到影片畫面")
    H, W = frames[0].shape
    if a.band:
        y0, y1 = map(int, a.band.split(":"))
    else:
        y0, y1 = detect_band(frames)
        if y1 - y0 < 40:
            sys.exit("❌ 找不到白底的譜面範圍，請看畫面後用 --band y0:y1 指定")
    dbg = Image.fromarray(frames[len(frames) // 2].astype(np.uint8)).convert("RGB")
    ImageDraw.Draw(dbg).rectangle([0, y0, W - 1, y1], outline=(255, 0, 0), width=4)
    dbg.save(out / "band.png")

    strips = [f[y0:y1] for f in frames]
    # 過場、淡入淡出：亮度跟中位數差很多的畫面不用
    lum = np.array([s.mean() for s in strips]); medlum = np.median(lum)
    keep = [i for i in range(len(strips)) if abs(lum[i] - medlum) < 20]
    strips = [strips[i] for i in keep]
    # 固定不動的直線（播放游標、捲軸）遮掉：時間上幾乎不變、又偏暗的欄
    stack = np.stack(strips)
    colmean = stack.mean(axis=1)                       # (T, W)
    static = (colmean.std(axis=0) < 6) & (colmean.mean(axis=0) < np.median(colmean) - 8)
    static = np.convolve(static.astype(float), np.ones(9), "same") > 0
    edge = int(W * 0.04)
    valid = ~static; valid[:edge] = False; valid[W - edge:] = False

    maxs = a.max_shift or W // 4
    offs, prev_d, steps = [0], None, []
    for i in range(1, len(strips)):
        p, q = strips[i - 1], strips[i]
        errs = []
        for d in range(0, maxs + 1):
            m = valid[d:] & valid[: W - d]
            if m.sum() < W * 0.3:
                errs.append(1e9); continue
            errs.append(np.abs(p[:, d:][:, m] - q[:, : W - d][:, m]).mean())
        errs = np.array(errs); d = int(errs.argmin())
        if prev_d is not None and d == maxs:          # 打到上限多半是過場或對錯，沿用上一步
            d = prev_d
        offs.append(offs[-1] + d); steps.append(d)
        if d > 0:
            prev_d = d
    if a.debug:
        print("steps:", steps)
    total = offs[-1] + W
    pan = np.full((y1 - y0, total), 255, np.float32)
    lo, hi = edge, W - edge
    for s, o in zip(strips, offs):
        seg = s[:, lo:hi].copy()
        st = static[lo:hi]
        tgt = pan[:, o + lo:o + hi]
        seg[:, st] = tgt[:, st]                        # 游標的位置保留之前的內容
        pan[:, o + lo:o + hi] = seg
    img = Image.fromarray(pan.clip(0, 255).astype(np.uint8))
    img.save(out / "panorama.png")

    # 切成好讀的段落：每段原始 500px 寬、重疊 60px，放大 2 倍，每張圖疊 4 段
    seg_w, ov, sc = 500, 60, 2
    segs = [img.crop((x, 0, min(x + seg_w, total), img.height)) for x in range(0, total, seg_w - ov)]
    n = 0
    for k in range(0, len(segs), 4):
        group = segs[k:k + 4]
        sh = img.height * sc
        m = Image.new("L", (seg_w * sc, (sh + 12) * len(group)), 128)
        for j, g in enumerate(group):
            m.paste(g.resize((g.width * sc, sh)), (0, j * (sh + 12)))
        n += 1; m.save(out / f"read_{n:02d}.png")
    print(f"✅ {len(strips)} 張畫面（捨棄 {len(frames) - len(strips)} 張過場），譜面 y={y0}:{y1}，"
          f"捲動 {offs[-1]}px，長譜 {total}px 寬")
    print(f"   {out/'band.png'}：確認紅框框住整條譜（含手順字母）；框錯用 --band 重跑")
    print(f"   {out/'panorama.png'}：整條長譜")
    print(f"   {out/'read_01.png'} … read_{n:02d}.png：依序讀，每段跟下一段重疊約 {ov}px（同一個音符不要讀兩次）")
    print("   拼接偶爾會在開頭／結尾或淡入時錯位：開頭幾小節、跟 video_frames.py 的單張畫面對一下")


if __name__ == "__main__":
    main()
