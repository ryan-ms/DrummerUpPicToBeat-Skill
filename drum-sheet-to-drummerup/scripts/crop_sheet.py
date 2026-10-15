#!/usr/bin/env python3
"""從截圖／照片裡找出鼓譜區域，裁切放大成方便讀譜的圖片。

用法：
    python crop_sheet.py 圖1.png 圖2.jpg ... -o crops/          # 依參數順序處理，輸出 01-…、02-…
    python crop_sheet.py 圖.png -o crops/ --rows                 # 另外把每一行譜各存一張（密的譜逐行讀）
    python crop_sheet.py 圖.png -o crops/ --debug                # 另存一張標出偵測結果的圖，用來確認有沒有框對

原理：找「很長、很細、上下是白底」的橫線當作譜線（五線譜或單線打擊譜都可以），
把譜線湊成譜表，再往外延伸到白色紙面的邊緣（這樣譜面上方的標題、速度也會包含進來）。

需要 Pillow 和 numpy（Claude、ChatGPT 的程式執行環境都有）。沒有的話會直接說明並結束，
改用目測裁切即可。K L R 這類只有字母、沒有譜線的圖偵測不到，也一樣改用目測裁切。

結束代碼：0 全部找到；3 有圖找不到譜線或讀不到（其他圖照樣輸出）；2 缺少 Pillow／numpy。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageOps
except ImportError:  # pragma: no cover
    print("❌ 這個環境沒有 Pillow／numpy，沒辦法自動裁切。請改用目測找出譜的範圍再裁切（見 SKILL.md）。")
    sys.exit(2)

DARK = 160          # 灰階小於這個值 = 墨水
FAINT = 225         # 淡灰色的譜線（螢幕錄影、反鋸齒常見）：比這個值暗、而且比上下兩列都暗 LINE_CONTRAST 以上
LINE_CONTRAST = 25
PAPER = 200         # 灰階大於這個值、而且不太有顏色 = 紙面
MIN_LINE = 0.25     # 譜線至少要佔圖寬的比例
MIN_WIDTH = 1200    # 裁切結果寬度不足時放大到這個寬度（最多 3 倍）


def long_runs(mask: np.ndarray, min_len: float):
    """每一列裡長度 >= min_len 的連續 True：回傳 [(列, 起點, 終點)]，依列排序。"""
    h, w = mask.shape
    padded = np.zeros((h, w + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    d = np.diff(padded, axis=1)
    rows, starts = np.nonzero(d == 1)
    _, ends = np.nonzero(d == -1)
    keep = (ends - starts) >= min_len
    return list(zip(rows[keep].tolist(), starts[keep].tolist(), ends[keep].tolist()))


def close_gaps(mask: np.ndarray) -> np.ndarray:
    """補上 4 像素以內的小缺口（反鋸齒、壓縮造成的譜線斷點；符頭旁邊常斷 3 像素）。

    橫向的形態學閉運算：先往左右各擴 2 像素再縮回來，線的兩端不會變長。
    """
    grown = mask.copy()
    for k in (1, 2):
        grown |= np.roll(mask, k, axis=1) | np.roll(mask, -k, axis=1)
    closed = grown.copy()
    for k in (1, 2):
        closed &= np.roll(grown, k, axis=1) & np.roll(grown, -k, axis=1)
    return mask | closed


def vertical_run(mask: np.ndarray) -> np.ndarray:
    """每個像素所在的「直向連續 True」有多長。"""
    h = mask.shape[0]
    up = np.zeros(mask.shape, dtype=np.int32)
    down = np.zeros(mask.shape, dtype=np.int32)
    up[0] = mask[0]
    for y in range(1, h):
        up[y] = (up[y - 1] + 1) * mask[y]
    down[-1] = mask[-1]
    for y in range(h - 2, -1, -1):
        down[y] = (down[y + 1] + 1) * mask[y]
    return np.where(mask, up + down - 1, 0)


def find_lines(gray: np.ndarray, paper: np.ndarray):
    """回傳譜線清單：每條 (y上, y下, x起, x終)。"""
    h, w = gray.shape
    # 淡灰色的細線也算：比上下兩列（各隔 2 像素）都明顯暗。很多影片、螢幕錄影的譜線只有 170–190 的灰，
    # 只看 DARK 的話五條線只剩壓著音符的那條找得到
    up = np.empty_like(gray)
    down = np.empty_like(gray)
    up[2:], up[:2] = gray[:-2], 255
    down[:-2], down[-2:] = gray[2:], 255
    faint = (gray < FAINT) & (gray + LINE_CONTRAST < up) & (gray + LINE_CONTRAST < down)
    dark = (gray < DARK) | faint
    # 很高的深色區域（影片的深色背景、深色側欄）不可能是譜線。不先拿掉的話，譜線一碰到紙面邊緣
    # （捲動中的譜、貼齊邊框的譜）就會跟旁邊的背景連成一大塊，整條被當成色塊丟掉
    dark &= vertical_run(dark) <= max(60, round(0.15 * h))
    runs = long_runs(close_gaps(dark), max(MIN_LINE * w, 60))
    max_thick = max(4, round(h * 0.004))

    # 上下相鄰、左右範圍差不多的長橫段併成一組（一條有厚度的線，或一整塊色塊）
    groups: list[list[tuple[int, int, int]]] = []
    open_groups: list[list[tuple[int, int, int]]] = []
    for r, s, e in runs:
        for g in open_groups:
            pr, ps, pe = g[-1]
            if pr == r - 1 and min(e, pe) - max(s, ps) >= 0.8 * min(e - s, pe - ps):
                g.append((r, s, e))
                break
        else:
            g = [(r, s, e)]
            groups.append(g)
            open_groups.append(g)
        open_groups = [g for g in open_groups if g[-1][0] >= r - 1]

    lines = []
    for g in groups:
        if len(g) > max_thick:  # 太粗：色塊、黑色狀態列、深色背景之類
            continue
        y0, y1 = g[0][0], g[-1][0]
        xs = int(np.median([s for _, s, _ in g]))
        xe = int(np.median([e for _, _, e in g]))
        # 譜線上下緊鄰的地方要是紙面（音符會蓋到一部分，所以只要求一半）
        above, below = y0 - 2, y1 + 2
        if above < 0 or below >= h:
            continue
        if paper[above, xs:xe].mean() < 0.5 or paper[below, xs:xe].mean() < 0.5:
            continue
        lines.append((y0, y1, xs, xe))
    lines.sort()
    return lines


def crossings(dark: np.ndarray, line) -> int:
    """有幾個東西（符頭、小節線、符桿）同時蓋到譜線上下兩側。分隔線、底線這種是 0。"""
    y0, y1, xs, xe = line
    off = (y1 - y0) + 3
    if y0 - off < 0 or y1 + off >= dark.shape[0]:
        return 0
    both = dark[y0 - off, xs:xe] & dark[y1 + off, xs:xe]
    return int(np.count_nonzero(np.diff(both.astype(np.int8)) == 1) + (1 if both[:1].any() else 0))


def group_staves(lines, dark: np.ndarray, w: int):
    """把譜線湊成譜表（1–5 條線、間距一致、左右範圍重疊）。"""
    staves = []
    cur = []
    for ln in lines:
        if cur:
            prev = cur[-1]
            gap = ln[0] - prev[1]
            overlap = min(ln[3], prev[3]) - max(ln[2], prev[2])
            span = min(ln[3] - ln[2], prev[3] - prev[2])
            if len(cur) >= 2:
                spacing = cur[1][0] - cur[0][1]
                ok = abs(gap - spacing) <= max(2, 0.35 * spacing)
            else:
                ok = gap <= 0.04 * w
            if ok and overlap >= 0.6 * span and len(cur) < 5:
                cur.append(ln)
                continue
            staves.append(cur)
        cur = [ln]
    if cur:
        staves.append(cur)
    # 至少要有兩個東西跨過譜線（小節線、符頭），排除 App 介面的分隔線
    return [s for s in staves if sum(crossings(dark, ln) for ln in s) >= 2]


def expand(paper: np.ndarray, box, axis: int, direction: int, max_dist: int, tolerance: int = 4) -> int:
    """從框的邊往外走到紙面邊緣，回傳新的邊界。

    遇到整條都不是紙面的線（App 的分隔線、卡片邊框、色塊）就停；
    內容（文字、符頭、符尾橫梁）會讓紙面比例下降，所以連續 tolerance 列（或欄）偏低才算走出紙面。最多走 max_dist。
    """
    x0, y0, x1, y1 = box
    limit = paper.shape[0] if axis == 0 else paper.shape[1]
    edge = (y0 if direction < 0 else y1) if axis == 0 else (x0 if direction < 0 else x1)
    start = edge
    misses = 0
    pos = edge
    while 0 <= pos + direction < limit and abs(pos + direction - start) <= max_dist:
        pos += direction
        strip = paper[pos, x0:x1] if axis == 0 else paper[y0:y1, pos]
        frac = strip.mean() if strip.size else 0.0
        if frac < 0.1:
            break
        if frac >= 0.6:
            misses = 0
            edge = pos
        else:
            misses += 1
            if misses >= tolerance:
                break
    return edge


def upscale(img: Image.Image) -> Image.Image:
    if img.width >= MIN_WIDTH:
        return img
    f = min(3.0, MIN_WIDTH / img.width)
    return img.resize((round(img.width * f), round(img.height * f)), Image.LANCZOS)


def detect(img: Image.Image):
    """找出圖裡的譜：回傳 {"box", "staves", "gray", "paper", "dark"}，找不到譜線回傳 None。

    box 是含標題、速度的整塊譜面 (左, 上, 右, 下)；staves 是每一行譜的譜線清單。video_frames.py 也用這個函式。
    """
    rgb = np.asarray(img)  # uint8：比轉成 int16 再算快很多（影片每張畫面都要跑）
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    gray = (r.astype(np.uint16) + g + b) / 3.0
    chroma = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
    paper = (gray > PAPER) & (chroma < 40)
    dark = gray < DARK
    h, w = gray.shape

    staves = group_staves(find_lines(gray, paper), dark, w)
    if not staves:
        return None

    x0 = min(ln[2] for s in staves for ln in s)
    x1 = max(ln[3] for s in staves for ln in s)
    y0 = staves[0][0][0]
    y1 = staves[-1][-1][1]
    # 往上下最多延伸 1.5 行的距離（夠包含標題、速度、上下加線的音符），只有一行時用圖寬的 1/4
    pitch = float(np.median(np.diff([s[0][0] for s in staves]))) if len(staves) > 1 else 0.0
    reach = round(1.5 * pitch) if pitch else round(0.25 * w)
    # 譜線間距：十六分音符的兩條橫梁加起來常比 4 列厚，往上找標題時要能穿過去
    gaps = [b[0] - a[1] for st in staves for a, b in zip(st, st[1:])]
    tol = max(4, round(1.5 * float(np.median(gaps)))) if gaps else 4
    # 從最外側譜線再往外 3 像素開始找：淡灰色譜線緊鄰的那一列是反鋸齒的灰邊，不是紙面，從那裡開始會一步都走不出去
    y0, y1 = max(0, y0 - 3), min(h - 1, y1 + 3)
    top = expand(paper, (x0, y0, x1, y1), 0, -1, reach, tol)
    bottom = expand(paper, (x0, y0, x1, y1), 0, 1, reach, tol)
    left = expand(paper, (x0, top, x1, bottom), 1, -1, round(0.05 * w))
    right = expand(paper, (x0, top, x1, bottom), 1, 1, round(0.05 * w))
    pad = 4
    box = (max(0, left - pad), max(0, top - pad), min(w, right + pad + 1), min(h, bottom + pad + 1))
    return {"box": box, "staves": staves, "gray": gray, "paper": paper, "dark": dark}


def process(path: Path, idx: int, out_dir: Path, rows: bool, debug: bool,
            img: Image.Image | None = None, stem: str | None = None) -> bool:
    """裁切一張圖。img／stem 給 video_frames.py 用：直接傳入影格、指定輸出檔名開頭。"""
    if img is None:
        try:
            img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        except Exception as e:  # noqa: BLE001
            print(f"❌ {idx:02d} {path.name}：讀不到圖片（{e}）")
            return False
    stem = stem or f"{idx:02d}-{path.stem}"
    found = detect(img)
    if not found:
        print(f"⚠️  {idx:02d} {path.name}：找不到譜線（可能是字母譜、譜太小或太模糊）→ 請改用目測裁切")
        return False
    box, staves = found["box"], found["staves"]

    out = out_dir / f"{stem}-sheet.png"
    upscale(img.crop(box)).save(out)
    kinds = sorted({len(s) for s in staves})
    kind = "、".join("單線譜" if k == 1 else f"{k} 線譜" for k in kinds)
    print(f"✅ {idx:02d} {path.name}：{len(staves)} 行（{kind}），譜面範圍 {box} → {out}")

    if rows:
        tops = [s[0][0] for s in staves]
        bots = [s[-1][1] for s in staves]
        for i in range(len(staves)):
            r0 = box[1] if i == 0 else (bots[i - 1] + tops[i]) // 2
            r1 = box[3] if i == len(staves) - 1 else (bots[i] + tops[i + 1]) // 2
            row_out = out_dir / f"{stem}-row{i + 1}.png"
            upscale(img.crop((box[0], r0, box[2], r1))).save(row_out)
        print(f"   逐行：{stem}-row1.png … row{len(staves)}.png")

    if debug:
        dbg = img.copy()
        draw = ImageDraw.Draw(dbg)
        for s in staves:
            for ln in s:
                draw.rectangle((ln[2], ln[0], ln[3], ln[1]), outline=(0, 160, 255), width=2)
        draw.rectangle(box, outline=(255, 0, 0), width=4)
        dbg_out = out_dir / f"{stem}-debug.png"
        dbg.save(dbg_out)
        print(f"   偵測結果：{dbg_out}（藍 = 譜線，紅 = 裁切範圍）")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+", help="圖片檔，依演奏順序排列")
    ap.add_argument("-o", "--out", default="crops", help="輸出資料夾（預設 crops/）")
    ap.add_argument("--rows", action="store_true", help="每一行譜另外存一張")
    ap.add_argument("--debug", action="store_true", help="另存標出偵測結果的圖")
    a = ap.parse_args()

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    found = [process(Path(p), i, out_dir, a.rows, a.debug) for i, p in enumerate(a.images, start=1)]
    return 0 if all(found) else 3


if __name__ == "__main__":
    sys.exit(main())
