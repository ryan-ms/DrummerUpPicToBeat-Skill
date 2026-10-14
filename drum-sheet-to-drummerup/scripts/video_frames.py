#!/usr/bin/env python3
"""從影片裡把鼓譜一頁一頁挑出來：找出「譜換頁」的時間點，每一頁存一張最清楚的畫面並裁切。

很多教學影片是「畫面上顯示幾小節譜，過幾秒換成下幾小節」。這個 script 會：
  1. 每秒取幾張畫面（預設 4 張），用 crop_sheet.py 同一套方法找出譜的位置（旁邊的人、鼓、字幕不算）；
  2. 比對譜的內容，內容變了就是換頁（只換一行、一個小節也算）；移動的游標、跟著演奏走的色塊、
     淡入淡出的過場都不算換頁；
  3. 每一頁取「穩定那段時間的正中間」，從影片重新抓一張原始解析度的畫面，依時間順序存成 frames/01_0m01.8s.png …，
     再照 crop_sheet.py 的方式裁出譜面（01_0m01.8s-sheet.png）、逐行（--rows）與偵測結果（--debug）；
  4. 比對相鄰兩頁的每一行，印出「第 1 行 = #03 第 1 行」這種重複（只換了部分的行、或往上捲動時會出現）；
  5. 印出時間軸，並輸出 segments.json（每頁的起訖時間、檔名、重複的行）與 overview.png（所有頁的縮圖，用來確認有沒有漏頁）。

用法：
    python video_frames.py 影片.mp4 -o frames --rows --debug
    python video_frames.py 影片1.mp4 影片2.mov -o frames               # 多支影片依參數順序接續編號
    python video_frames.py 影片.mp4 -o frames --start 0:12 --end 1:30  # 只看一段

畫面一直在動、停不下來的段落（例如整排譜持續往左捲動、整頁往上捲）沒有「一頁」可言，會改成內容每捲過大約
半個畫面就存一張（最久每 --scroll-every 秒一張），標成「捲動」：相鄰兩張一定有重疊，拼接時要靠內容對齊、刪掉重複的小節。

需要 Pillow、numpy，以及 ffmpeg（PATH 裡的 ffmpeg，或 pip 的 imageio-ffmpeg）或 opencv-python 其中之一。
都沒有的話會說明並結束，這時請使用者改成每次換頁後各截一張圖。

結束代碼：0 成功；3 整支影片都找不到譜；2 缺少必要的套件或讀不到影片。
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    print("❌ 這個環境沒有 Pillow／numpy，沒辦法自動分析影片。請使用者改成每次換頁後各截一張圖，照截圖的流程處理（見 SKILL.md）。")
    sys.exit(2)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crop_sheet  # noqa: E402

CHANGE = 0.30        # 譜面任何一塊的內容差異超過這個比例 = 換頁
MIN_DUR = 0.7        # 停留不到這麼久的畫面 = 過場（淡入淡出、模糊），不當成一頁
SCROLL_MIN = 2.5     # 連續這麼久都停不下來 = 捲動式的譜
POOL = 640           # 比對內容時把畫面縮到這個寬度（容忍壓縮雜訊、1–2 像素的晃動）
TILES = 4            # 譜面切成 TILES × TILES 塊分開比對：只換一行、一個小節也抓得到
VOTE = 5             # 前後幾張畫面投票（多數決）：移動的游標、跟著演奏走的標記不算內容
FRAME_MAX_W = 3840   # 存檔的畫面寬度上限（分析時用 --max-width，存檔用原始解析度，讀譜比較清楚）


# ---------------------------------------------------------------- 讀影片

def find_ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


def _read_ppm(stream):
    """從串流讀一張 PPM（P6）。讀完了回傳 None。"""
    tokens = []
    while len(tokens) < 4:  # P6 寬 高 最大值
        tok = b""
        while True:
            c = stream.read(1)
            if not c:
                break
            if c.isspace():
                if tok:
                    break
                continue
            if c == b"#" and not tok:  # 註解行
                stream.readline()
                continue
            tok += c
        if not tok:
            return None
        tokens.append(tok)
    w, h = int(tokens[1]), int(tokens[2])
    data = stream.read(w * h * 3)
    if len(data) < w * h * 3:
        return None
    return Image.frombytes("RGB", (w, h), data)


class Video:
    """讀影片：優先用 ffmpeg（手機直拍的旋轉會自動轉正），沒有才用 opencv。"""

    def __init__(self, path: Path):
        self.path = path
        self.ffmpeg = find_ffmpeg()
        if not self.ffmpeg:
            try:
                import cv2  # type: ignore # noqa: F401
            except ImportError:
                print("❌ 這個環境沒有 ffmpeg（也沒有 imageio-ffmpeg、opencv-python），讀不了影片。\n"
                      "   可以試 `pip install imageio-ffmpeg`；不行的話請使用者在每次換頁後各截一張圖，改走截圖流程。")
                sys.exit(2)

    def frames(self, fps: float, max_w: int, start: float, end: float | None):
        """每秒取 fps 張，產生 (秒數, 畫面)。"""
        if self.ffmpeg:
            yield from self._frames_ffmpeg(fps, max_w, start, end)
        else:
            yield from self._frames_cv2(fps, max_w, start, end)

    def grab(self, t: float, max_w: int = FRAME_MAX_W):
        """抓第 t 秒的一張畫面（存檔用）。"""
        if self.ffmpeg:
            cmd = [self.ffmpeg, "-v", "error", "-ss", f"{t:.3f}", "-i", str(self.path), "-frames:v", "1",
                   "-vf", f"scale='min({max_w},iw)':-2", "-f", "image2pipe", "-vcodec", "ppm", "-"]
            proc = subprocess.run(cmd, capture_output=True)
            return _read_ppm(io.BytesIO(proc.stdout))
        import cv2  # type: ignore

        cap = cv2.VideoCapture(str(self.path))
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, bgr = cap.read()
        cap.release()
        return _fit(Image.fromarray(bgr[:, :, ::-1]), max_w) if ok else None

    def _frames_ffmpeg(self, fps, max_w, start, end):
        cmd = [self.ffmpeg, "-v", "error"]
        if start:
            cmd += ["-ss", f"{start:.3f}"]
        cmd += ["-i", str(self.path)]
        if end is not None:
            cmd += ["-t", f"{max(0.0, end - start):.3f}"]
        cmd += ["-vf", f"fps={fps},scale='min({max_w},iw)':-2", "-f", "image2pipe", "-vcodec", "ppm", "-"]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        n = 0
        try:
            while True:
                img = _read_ppm(proc.stdout)
                if img is None:
                    break
                yield start + n / fps, img
                n += 1
        finally:
            proc.stdout.close()
            err = proc.stderr.read().decode("utf-8", "replace").strip()
            proc.wait()
            if n == 0:
                raise RuntimeError(err.splitlines()[-1] if err else "影片裡沒有畫面")

    def _frames_cv2(self, fps, max_w, start, end):
        import cv2  # type: ignore

        cap = cv2.VideoCapture(str(self.path))
        if not cap.isOpened():
            raise RuntimeError("opencv 打不開這個影片")
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        i, n = 0, 0
        next_t = start
        while cap.grab():
            t = i / src_fps
            i += 1
            if end is not None and t > end:
                break
            if t + 1e-6 < next_t:
                continue
            ok, bgr = cap.retrieve()
            if not ok:
                break
            yield t, _fit(Image.fromarray(bgr[:, :, ::-1]), max_w)
            n += 1
            next_t += 1 / fps
        cap.release()
        if n == 0:
            raise RuntimeError("影片裡沒有畫面")


def _fit(img, max_w: int):
    if img.width <= max_w:
        return img
    return img.resize((max_w, round(img.height * max_w / img.width)), Image.LANCZOS)


# ---------------------------------------------------------------- 比對內容

def _shift_or(m: np.ndarray) -> np.ndarray:
    """往上下左右擴張 1 格。"""
    o = m.copy()
    o[1:] |= m[:-1]
    o[:-1] |= m[1:]
    o[:, 1:] |= m[:, :-1]
    o[:, :-1] |= m[:, 1:]
    return o


def _erode(m: np.ndarray) -> np.ndarray:
    o = m.copy()
    o[1:] &= m[:-1]
    o[:-1] &= m[1:]
    o[:, 1:] &= m[:, :-1]
    o[:, :-1] &= m[:, 1:]
    o[0] = o[-1] = False
    o[:, 0] = o[:, -1] = False
    return o


def signature(found: dict) -> dict:
    """譜面內容的指紋 {"m": 縮小後的墨水位置, "box": 譜面範圍, "k": 縮小倍數}。

    只看譜的範圍、拿掉譜線本身（每頁都一樣）、塗滿的色塊只留外框（深色的高亮、遮罩不會被算成大量內容）。
    """
    dark = found["dark"]
    h, w = dark.shape
    # 裁切範圍外圍多留了幾像素，常會包到影片的深色背景、卡片邊框，那一圈不算內容
    x0, y0, x1, y1 = found["box"]
    inset = 8
    x0, y0, x1, y1 = x0 + inset, y0 + inset, max(x0 + inset, x1 - inset), max(y0 + inset, y1 - inset)
    m = np.zeros_like(dark)
    m[y0:y1, x0:x1] = dark[y0:y1, x0:x1]
    for staff in found["staves"]:
        for ly0, ly1, lxs, lxe in staff:
            m[max(0, ly0 - 1):ly1 + 2, lxs:lxe] = False
    m &= ~_erode(_erode(m))
    k = max(1, -(-w // POOL))
    hh, ww = h // k * k, w // k * k
    pooled = m[:hh, :ww].reshape(hh // k, k, ww // k, k).any(axis=(1, 3))
    return {"m": pooled, "box": (x0 // k, y0 // k, -(-x1 // k), -(-y1 // k)), "k": k}


def ink(sig: dict) -> int:
    return int(sig["m"].sum())


def vote(sigs: list[dict], center: dict) -> dict:
    """多數決：前後幾張畫面裡超過一半都有墨水的位置才算（只留下靜止的內容）。"""
    same = [x["m"] for x in sigs if x["m"].shape == center["m"].shape]
    if len(same) < 3:
        return center
    count = np.sum(same, axis=0)
    return {"m": count * 2 > len(same), "box": center["box"], "k": center["k"]}


def difference(a: dict, b: dict) -> float:
    """兩個指紋差多少：0 = 一樣，1 = 完全不同。

    把兩者的譜面範圍聯集切成 TILES × TILES 塊，每塊算「對不上的墨水比例」（容忍 1 格位移），取最大的一塊；
    墨水太少的塊不算（避免空白處一兩個雜點就被當成換頁）。
    """
    ma, mb = a["m"], b["m"]
    if ma.shape != mb.shape:
        return 1.0
    na, nb = int(ma.sum()), int(mb.sum())
    if na + nb == 0:
        return 0.0
    miss = (ma & ~_shift_or(mb)) | (mb & ~_shift_or(ma))
    both = ma.astype(np.int32) + mb.astype(np.int32)
    x0, y0 = min(a["box"][0], b["box"][0]), min(a["box"][1], b["box"][1])
    x1, y1 = max(a["box"][2], b["box"][2]), max(a["box"][3], b["box"][3])
    xs = np.linspace(x0, x1, TILES + 1).round().astype(int)
    ys = np.linspace(y0, y1, TILES + 1).round().astype(int)
    floor = max(15, 0.02 * (na + nb))
    worst = 0.0
    for i in range(TILES):
        for j in range(TILES):
            tile = (slice(ys[i], ys[i + 1]), slice(xs[j], xs[j + 1]))
            total = int(both[tile].sum())
            if total >= floor:
                worst = max(worst, int(miss[tile].sum()) / total)
    return worst


def sharpness(found: dict) -> float:
    x0, y0, x1, y1 = found["box"]
    g = found["gray"][y0:y1, x0:x1]
    if g.shape[0] < 3 or g.shape[1] < 3:
        return 0.0
    lap = 4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    return float(np.abs(lap).mean())


def _profiles(sig: dict) -> dict:
    """指紋在譜面範圍裡的橫向、直向墨水分布（估計捲動了多少用）。"""
    x0, y0, x1, y1 = sig["box"]
    m = sig["m"][y0:y1, x0:x1]
    return {"cols": m.sum(axis=0).astype(float), "rows": m.sum(axis=1).astype(float)}


def _shift(a: np.ndarray, b: np.ndarray) -> float:
    """b 相對 a 移動了多少（佔長度的比例）：用互相關找最吻合的位移，最多找半個長度。"""
    n = min(len(a), len(b))
    if n < 8:
        return 0.0
    a, b = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
    if not a.any() or not b.any():
        return 0.0
    lags = np.arange(-(n - 1), n)
    corr = np.correlate(b, a, mode="full") / (n - np.abs(lags))  # 依重疊長度平均，不偏向位移 0
    ok = np.abs(lags) <= n // 2
    return abs(int(lags[ok][np.argmax(corr[ok])])) / n


def _moved(a: dict, b: dict) -> float:
    return max(_shift(a["cols"], b["cols"]), _shift(a["rows"], b["rows"]))


def row_bands(found: dict, sig: dict) -> list[tuple[int, int]]:
    """每一行譜在指紋上的上下範圍（行與行之間從中間切開）。"""
    k = sig["k"]
    staves = found["staves"]
    tops = [st[0][0] for st in staves]
    bots = [st[-1][1] for st in staves]
    y0, y1 = sig["box"][1] * k, sig["box"][3] * k
    bands = []
    for i in range(len(staves)):
        r0 = y0 if i == 0 else (bots[i - 1] + tops[i]) // 2
        r1 = y1 if i == len(staves) - 1 else (bots[i] + tops[i + 1]) // 2
        bands.append((r0 // k, -(-r1 // k)))
    return bands


def same_rows(a: dict, b: dict, change: float) -> list[tuple[int, int]]:
    """b 的哪幾行跟 a 的哪一行內容一樣：回傳 [(b 的第幾行, a 的第幾行)]，從 1 起算。行的高度位置可以不同（往上捲也找得到）。"""
    ma, mb = a["sig"]["m"], b["sig"]["m"]
    if ma.shape != mb.shape:
        return []
    out = []
    for bi, (b0, b1) in enumerate(b["bands"], start=1):
        if mb[b0:b1].sum() < 15:
            continue
        for ai, (a0, a1) in enumerate(a["bands"], start=1):
            h = min(b1 - b0, a1 - a0)
            ob, oa = b0 + (b1 - b0 - h) // 2, a0 + (a1 - a0 - h) // 2  # 行高不同時以中間對齊
            ra, rb = ma[oa:oa + h], mb[ob:ob + h]
            na, nb = int(ra.sum()), int(rb.sum())
            if na + nb == 0:
                continue
            miss = int((ra & ~_shift_or(rb)).sum()) + int((rb & ~_shift_or(ra)).sum())
            if miss / (na + nb) <= change / 2:
                out.append((bi, ai))
                break
    return out


# ---------------------------------------------------------------- 分頁

class Segment:
    """畫面上同一頁譜持續出現的一段時間。只記每張畫面的數據，不留畫面本身（最後再從影片抓）。"""

    def __init__(self, t: float, sig: dict):
        self.start = self.end = t
        self.ref = sig          # 這一頁的內容（投票後的指紋），之後的畫面都跟它比
        self.kind = "page"
        # (秒數, 穩定, 清晰度, 墨水量, 投票前的墨水量, 投票前的指紋)
        self.recs: list[tuple[float, bool, float, int, int, dict]] = []

    def add(self, t: float, found: dict, sig: dict, raw: dict) -> None:
        self.end = t
        # 穩定 = 這張畫面本身跟前後幾張的共識一致（不在淡入淡出、模糊、被手擋住的時候）
        self.recs.append((t, difference(raw, sig) <= 0.1, sharpness(found), ink(sig), ink(raw), _profiles(raw)))

    def duration(self, step: float) -> float:
        return self.end - self.start + step

    def absorb(self, other: "Segment") -> None:
        """同一頁被短暫的模糊、遮擋切成兩段時合回一段。"""
        self.end = max(self.end, other.end)
        self.recs += other.recs

    def moving(self, step: float) -> bool:
        """整段的內容一直在動（捲動式的譜）：大部分畫面的墨水撐不過投票（前後幾張的位置都不一樣）。

        游標、高亮只佔一小部分，投票後墨水還在，不會被當成捲動。
        """
        if self.duration(step) < SCROLL_MIN:
            return False
        moved = sum(1 for r in self.recs if r[4] and r[3] < 0.5 * r[4])
        return moved >= 0.6 * len(self.recs)

    def split(self, every: float) -> list["Segment"]:
        """捲動的段落切成幾張：內容捲過大約半個畫面就存一張（相鄰兩張一定有重疊），最久每 every 秒一張。"""
        out: list[Segment] = []
        moved = 0.0
        for i, r in enumerate(self.recs):
            if i:
                moved += _moved(self.recs[i - 1][5], r[5])
            if not out or moved >= 0.5 or r[0] - out[-1].start >= every - 1e-6:
                seg = Segment(r[0], self.ref)
                seg.kind = "scroll"
                out.append(seg)
                moved = 0.0
            out[-1].end = r[0]
            out[-1].recs.append(r)
        return out

    def candidates(self) -> list[float]:
        """存檔用的畫面時間，最適合的排第一。

        捲動畫面：最清楚的（動態模糊最少）。
        一般的頁：穩定的畫面裡，夠清楚（至少是最清楚的 85%）而且音符最多（≥ 97%）的那些，取時間在正中間的；
        音符逐漸出現的影片會選到後段音符最完整的時候。
        """
        if self.kind == "scroll":  # 一定要用切點那一張，才保證跟上一張有重疊
            return [r[0] for r in self.recs]
        recs = self._inner()
        max_sharp = max(r[2] for r in recs)
        max_ink = max(r[3] for r in recs)
        good = [r for r in recs if r[2] >= 0.85 * max_sharp and r[3] >= 0.97 * max_ink] or recs
        mid = (good[0][0] + good[-1][0]) / 2
        return [r[0] for r in sorted(good, key=lambda r: abs(r[0] - mid))]

    def _inner(self) -> list:
        """穩定的畫面，去掉頭尾各 VOTE//2 張：那幾張的投票窗口跨到前後一頁，數據不準。"""
        recs = self.recs
        half = VOTE // 2
        if len(recs) > 2 * half + 2:
            recs = recs[half:-half]
        return [r for r in recs if r[1]] or recs

    def ink_grew(self) -> bool:
        recs = self._inner()
        return recs[0][3] > 0 and max(r[3] for r in recs) > 1.15 * recs[0][3]


def segment_video(frames, fps: float, change: float, min_dur: float, scroll_every: float):
    """回傳 (頁與捲動畫面的清單, 沒有譜的時間段, 分析了幾張畫面)。"""
    step = 1 / fps
    items: list[Segment] = []
    no_sheet: list[list[float]] = []
    run: dict | None = None            # 連續的短暫畫面（過場或捲動）
    cur: Segment | None = None
    total = 0

    def run_is_scroll(r) -> bool:
        return r is not None and r["end"] - r["start"] + step >= SCROLL_MIN

    def flush_run():
        nonlocal run
        if run_is_scroll(run):
            for s in run["keep"]:
                s.kind = "scroll"
                items.append(s)
        run = None

    def close(seg: Segment | None):
        nonlocal run
        if seg is None:
            return
        if seg.moving(step):
            flush_run()
            items.extend(seg.split(scroll_every))
            return
        if seg.duration(step) >= min_dur:
            was_scroll = run_is_scroll(run)
            flush_run()
            prev = items[-1] if items else None
            # 中間只隔了過場的同一頁 → 合併
            if prev and prev.kind == "page" and not was_scroll and difference(prev.ref, seg.ref) <= change \
                    and seg.start - prev.end <= max(3 * min_dur, 2.0):
                prev.absorb(seg)
            else:
                items.append(seg)
        else:
            if run is None:
                run = {"start": seg.start, "end": seg.end, "keep": [], "last": -1e9}
            run["end"] = seg.end
            if seg.start - run["last"] >= scroll_every:
                run["keep"].append(seg)
                run["last"] = seg.start

    def handle(t, found, sig, raw):
        nonlocal cur
        if cur is None or difference(cur.ref, sig) > change:
            close(cur)
            cur = Segment(t, sig)
        cur.add(t, found, sig, raw)

    # 一邊讀一邊處理：只留前後 VOTE 張畫面在記憶體裡
    window: list = []  # [(秒數, found, 指紋)]，found 是 None = 這張沒有譜
    half = VOTE // 2

    def emit(i):
        t, found, sig = window[i]
        if found is None:
            if no_sheet and t - no_sheet[-1][1] <= step * 1.5:
                no_sheet[-1][1] = t
            else:
                no_sheet.append([t, t])
            return
        handle(t, found, vote([w[2] for w in window if w[2] is not None], sig), sig)

    for t, img in frames:
        total += 1
        found = crop_sheet.detect(img)
        if found:  # 只留比對需要的部分，整張畫面不留
            found = {"box": found["box"], "staves": found["staves"], "gray": found["gray"], "dark": found["dark"]}
        window.append((t, found, signature(found) if found else None))
        if len(window) > VOTE:
            window.pop(0)
        if len(window) == VOTE:
            # 第一次湊滿窗口時，前半的畫面也一起處理
            for i in range(half + 1) if total == VOTE else (half,):
                emit(i)
    # 結尾（或整支影片不滿一個窗口）還沒處理的畫面
    for i in range(len(window)) if total < VOTE else range(half + 1, len(window)):
        emit(i)
    close(cur)
    flush_run()
    no_sheet = [s for s in no_sheet if s[1] - s[0] + step >= 1.0]
    return items, no_sheet, total


# ---------------------------------------------------------------- 輸出

def ts(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:04.1f}"


def fname_ts(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m)}m{s:04.1f}s"


def overview(entries: list[dict], out: Path) -> None:
    """所有頁的縮圖排成一張，左上角標編號與時間。"""
    if not entries:
        return
    tw, label_h, gap = 640, 22, 8
    thumbs = []
    for e in entries:
        crop = e["img"].crop(e["found"]["box"])
        thumbs.append((e, crop.resize((tw, max(1, round(crop.height * tw / crop.width))), Image.LANCZOS)))
    H = sum(t.height + label_h + gap for _, t in thumbs) + gap
    sheet = Image.new("RGB", (tw + 2 * gap, H), (235, 235, 235))
    d = ImageDraw.Draw(sheet)
    y = gap
    for e, t in thumbs:
        tag = "SCROLL" if e["kind"] == "scroll" else "PAGE"
        d.text((gap, y + 4), f"#{e['index']:02d}  {tag}  {ts(e['start'])} - {ts(e['end'])}", fill=(0, 0, 0))
        y += label_h
        sheet.paste(t, (gap, y))
        y += t.height + gap
    sheet.save(out)


def secs(v) -> float | None:
    if v is None:
        return None
    parts = [float(x) for x in str(v).split(":")]
    return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("videos", nargs="+", help="影片檔，依演奏順序排列")
    ap.add_argument("-o", "--out", default="frames", help="輸出資料夾（預設 frames/）")
    ap.add_argument("--fps", type=float, default=4.0, help="每秒取幾張畫面分析（預設 4；換頁很快的影片可以調高）")
    ap.add_argument("--change", type=float, default=CHANGE, help=f"內容差異超過多少算換頁（預設 {CHANGE}）")
    ap.add_argument("--min-dur", type=float, default=MIN_DUR, help=f"一頁至少停留幾秒（預設 {MIN_DUR}，更短的當成過場）")
    ap.add_argument("--scroll-every", type=float, default=2.0, help="捲動式的譜最久每隔幾秒存一張（預設 2；捲得快時會自動存得更密）")
    ap.add_argument("--max-width", type=int, default=1920, help="分析時的畫面寬度上限（預設 1920；存檔用原始解析度）")
    ap.add_argument("--start", default="0", help="從第幾秒開始，可寫 75 或 1:15")
    ap.add_argument("--end", default=None, help="到第幾秒結束")
    ap.add_argument("--rows", action="store_true", help="每一行譜另外存一張")
    ap.add_argument("--debug", action="store_true", help="另存標出偵測結果的圖")
    a = ap.parse_args()

    out_dir = Path(a.out)
    frame_dir = out_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    idx = 0
    for vi, vpath in enumerate(map(Path, a.videos), start=1):
        if not vpath.exists():
            print(f"❌ 找不到影片 {vpath}")
            return 2
        label = vpath.name if len(a.videos) > 1 else "影片"
        video = Video(vpath)
        try:
            items, no_sheet, total = segment_video(video.frames(a.fps, a.max_width, secs(a.start) or 0.0, secs(a.end)),
                                                   a.fps, a.change, a.min_dur, a.scroll_every)
        except RuntimeError as e:
            print(f"❌ {vpath.name}：讀不到影片（{e}）")
            return 2
        pages = sum(i.kind == "page" for i in items)
        scrolls = len(items) - pages
        print(f"🎬 {vpath.name}：分析了 {total} 張畫面（每秒 {a.fps:g} 張），找到 {pages} 頁"
              + (f"、{scrolls} 張捲動畫面" if scrolls else ""))
        for s0, s1 in no_sheet:
            print(f"   （{ts(s0)}–{ts(s1 + 1 / a.fps)} 畫面上沒有譜）")

        for seg in items:
            # 從影片抓原始解析度的畫面；萬一那張偵測不到譜（剛好模糊），換下一個候選時間
            img = found = None
            for t in seg.candidates()[:4]:
                img = video.grab(t)
                found = crop_sheet.detect(img) if img is not None else None
                if found:
                    break
            if not found:
                print(f"\n⚠️  {ts(seg.start)}–{ts(seg.end + 1 / a.fps)} 的畫面抓不到清楚的譜，略過；請自己看影片這一段")
                continue
            idx += 1
            end = seg.end + 1 / a.fps
            stem = f"{idx:02d}_{fname_ts(t)}" if len(a.videos) == 1 else f"{idx:02d}_v{vi}_{fname_ts(t)}"
            fpath = frame_dir / f"{stem}.png"
            img.save(fpath)
            sig = signature(found)
            e = {"index": idx, "video": vpath.name, "kind": seg.kind, "start": round(seg.start, 2), "end": round(end, 2),
                 "frame_time": round(t, 2), "frame": str(fpath.relative_to(out_dir)), "sheet": f"{stem}-sheet.png",
                 "rows": len(found["staves"]), "source": f"{label} {ts(seg.start)}–{ts(end)}", "same_rows": [], "notes": [],
                 "img": img, "found": found, "sig": sig, "bands": row_bands(found, sig)}
            if seg.kind == "page" and seg.ink_grew():
                e["notes"].append("這段畫面中音符逐漸變多（逐步出現的譜？），已選音符最完整的時候")
            for old in entries[:-1]:
                if old["video"] == e["video"] and old["kind"] == seg.kind == "page" and difference(old["sig"], sig) <= a.change:
                    e["notes"].append(f"跟 #{old['index']:02d} 是同一頁（影片又回到這頁：反覆演奏？還是只是回顧？要確認）")
                    break
            prev = entries[-1] if entries and entries[-1]["video"] == e["video"] else None
            if prev:
                pairs = same_rows(prev, e, a.change)
                e["same_rows"] = [{"row": r, "same_as": f"#{prev['index']:02d} 第 {o} 行"} for r, o in pairs]
                if pairs and len(pairs) == e["rows"] and seg.kind == "scroll":
                    e["notes"].append("每一行都跟上一張一樣（捲動很慢？），確認後可以略過這張")
                elif pairs:
                    e["notes"].append("、".join(f"第 {r} 行 = #{prev['index']:02d} 第 {o} 行" for r, o in pairs)
                                      + "（跟上一張重複，拼接時只寫一次）")
            entries.append(e)

            kind = "捲動" if seg.kind == "scroll" else "頁"
            print(f"\n#{idx:02d} {kind}  {ts(seg.start)}–{ts(end)}（取 {ts(t)} 的畫面）  → {fpath}")
            crop_sheet.process(fpath, idx, out_dir, a.rows, a.debug, img=img, stem=stem)
            for n in e["notes"]:
                print(f"   ℹ️  {n}")
            print(f"   tab JSON 這一段第一個小節寫 \"source\": \"{e['source']}\"")

    if not entries:
        print("❌ 整支影片都找不到譜線。可能是字母譜、譜太小或太模糊 → 請使用者在每次換頁後截圖，改走截圖流程")
        return 3
    overview(entries, out_dir / "overview.png")
    keep = ("index", "video", "kind", "start", "end", "frame_time", "frame", "sheet", "rows", "source", "same_rows", "notes")
    (out_dir / "segments.json").write_text(
        json.dumps([{k: e[k] for k in keep} for e in entries], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n📋 總覽：{out_dir / 'overview.png'}（每頁縮圖，確認順序、有沒有漏頁或多出過場畫面）")
    print(f"   時間軸：{out_dir / 'segments.json'}")
    if any(e["kind"] == "scroll" for e in entries):
        print("⚠️  有捲動式的段落：相鄰的捲動畫面內容一定重疊，要對齊內容、同一小節只寫一次")
    return 0


if __name__ == "__main__":
    sys.exit(main())
