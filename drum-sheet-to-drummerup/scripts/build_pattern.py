#!/usr/bin/env python3
"""把「鼓譜文字格線」(drum tab JSON) 轉成 DrummerUp 可以直接「匯入模組」的 JSON 檔。

用法：
    python build_pattern.py tab.json                 # 輸出 <name>.json（超過 30 小節自動分成多個檔）
    python build_pattern.py tab.json -o out.json     # 指定輸出檔名
    python build_pattern.py --check pattern.json     # 檢查一份已經是 DrummerUp 格式的 JSON

只用 Python 標準函式庫，任何有程式執行環境的 AI chat（Claude、ChatGPT 程式碼直譯器等）都能直接跑。
輸入格式見 ../references/tab-format.md；輸出欄位規則跟 DrummerUp 的 sanitizePattern()
（src/core/pattern.ts）一致，所以輸出檔匯入時不會被默默改掉內容。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 跟 src/core/drumMap.ts 的 INSTRUMENTS 同順序（編輯器由上到下）
VOICES = ["crash", "ride", "hihat", "tom1", "tom2", "tom3", "snare", "kick", "hihatFoot"]

# 方便 AI 照譜面常見名稱寫，統一轉成 DrummerUp 的 VoiceId
ALIASES = {
    "cr": "crash", "crash": "crash", "cc": "crash", "cymbal": "crash",
    "rd": "ride", "ride": "ride", "rc": "ride",
    "hh": "hihat", "hihat": "hihat", "hi-hat": "hihat", "hat": "hihat",
    "t1": "tom1", "tom1": "tom1", "hightom": "tom1", "ht": "tom1",
    "t2": "tom2", "tom2": "tom2", "midtom": "tom2", "mt": "tom2",
    "t3": "tom3", "tom3": "tom3", "floortom": "tom3", "ft": "tom3", "lowtom": "tom3",
    "sn": "snare", "sd": "snare", "snare": "snare",
    "bd": "kick", "kick": "kick", "bass": "kick", "bassdrum": "kick", "kk": "kick",
    "hf": "hihatFoot", "hihatfoot": "hihatFoot", "hhf": "hihatFoot", "hhpedal": "hihatFoot", "pedal": "hihatFoot",
}

RIM_VOICES = {"snare", "tom1", "tom2", "tom3"}
OPEN_VOICES = {"hihat"}
BELL_VOICES = {"ride"}

MAX_BARS = 30            # 編輯器單一模組小節數上限（MAX_PATTERN_BARS）
MAX_BEATS = 16           # 每小節拍數上限
MAX_SUBDIV = 16          # 每拍格數上限
VALID_UNITS = {1, 2, 4, 8, 16}
VALID_RESOLUTIONS = {1, 2, 4, 8}

# 符號 → (cell, 疊加標記)。cell：0 無聲、1 一般、2 重音、3 ghost
SYMBOLS = {
    "-": (0, None), ".": (0, None),
    "x": (1, None), "X": (2, None), "g": (3, None),
    "o": (1, "open"), "O": (2, "open"),
    "b": (1, "bell"), "B": (2, "bell"),
    "r": (1, "rim"), "R": (2, "rim"),
    "f": (1, "grace"), "F": (2, "grace"),
}
OVERLAY_ALLOWED = {"open": OPEN_VOICES, "bell": BELL_VOICES, "rim": RIM_VOICES, "grace": set(VOICES)}
IGNORED = set(" |/")


class TabError(ValueError):
    pass


def norm_voice(name: str) -> str:
    key = re.sub(r"[\s_]", "", name).lower()
    if key in ALIASES:
        return ALIASES[key]
    raise TabError(f"不認得的樂器名稱「{name}」，可用：{', '.join(VOICES)}")


def parse_time(t, prev):
    if t is None:
        return prev
    if isinstance(t, str):
        m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", t)
        if not m:
            raise TabError(f"拍號格式錯誤「{t}」，請寫成像 \"4/4\"、\"6/8\"")
        beats, unit = int(m.group(1)), int(m.group(2))
    else:
        beats, unit = int(t["beats"]), int(t["unit"])
    if not 1 <= beats <= MAX_BEATS:
        raise TabError(f"拍號分子 {beats} 超出範圍 1–{MAX_BEATS}")
    if unit not in VALID_UNITS:
        raise TabError(f"拍號分母 {unit} 不支援，只能是 1/2/4/8/16")
    return beats, unit


def clean(s: str) -> str:
    return "".join(ch for ch in s if ch not in IGNORED)


def build(tab: dict) -> list[dict]:
    name = str(tab.get("name") or "未命名")[:200]
    bpm = int(tab.get("bpm") or 90)
    if not 10 <= bpm <= 500:
        raise TabError(f"bpm {bpm} 超出範圍 10–500")
    bars_in = tab.get("bars")
    if not isinstance(bars_in, list) or not bars_in:
        raise TabError("缺少 bars 陣列（至少要一個小節）")

    default_grid = tab.get("grid", 4)
    time = parse_time(tab.get("time", "4/4"), None)
    grid_prev = default_grid

    tracks = {v: [] for v in VOICES}
    sticking = {v: [] for v in VOICES}
    marks = {k: {v: [] for v in VOICES} for k in OVERLAY_ALLOWED}
    used_marks: set[str] = set()
    subdiv: list[int] = []
    time_sigs: list[dict] = []
    mute: list[bool] = []
    bar_steps: list[int] = []  # 每小節格數，給分檔用
    bar_beats: list[int] = []

    for bi, bar in enumerate(bars_in, start=1):
        where = f"第 {bi} 小節"
        if not isinstance(bar, dict):
            raise TabError(f"{where}：每個小節必須是物件")
        time = parse_time(bar.get("time"), time)
        beats, unit = time
        grid = bar.get("grid", grid_prev)
        grid_prev = grid
        per_beat = [int(grid)] * beats if not isinstance(grid, list) else [int(g) for g in grid]
        if len(per_beat) != beats:
            raise TabError(f"{where}：grid 陣列有 {len(per_beat)} 拍，但拍號 {beats}/{unit} 是 {beats} 拍")
        for g in per_beat:
            if not 1 <= g <= MAX_SUBDIV:
                raise TabError(f"{where}：每拍格數 {g} 超出範圍 1–{MAX_SUBDIV}")
        steps = sum(per_beat)

        notes = bar.get("notes", {k: v for k, v in bar.items() if k not in ("time", "grid", "sticking", "muteMetronome", "comment")})
        bar_cells = {v: [0] * steps for v in VOICES}
        bar_marks = {k: {v: [False] * steps for v in VOICES} for k in OVERLAY_ALLOWED}
        for raw_voice, line in notes.items():
            v = norm_voice(raw_voice)
            s = clean(str(line))
            if len(s) != steps:
                raise TabError(
                    f"{where} {v}：寫了 {len(s)} 格，但這小節應該是 {steps} 格"
                    f"（{beats}/{unit}，每拍 {per_beat} 格）。原字串：{line!r}"
                )
            for i, ch in enumerate(s):
                if ch not in SYMBOLS:
                    raise TabError(f"{where} {v} 第 {i + 1} 格：不認得的符號「{ch}」")
                cell, mark = SYMBOLS[ch]
                if mark and v not in OVERLAY_ALLOWED[mark]:
                    raise TabError(f"{where} {v} 第 {i + 1} 格：「{ch}」({mark}) 不能用在 {v} 上")
                if cell and bar_cells[v][i]:
                    raise TabError(f"{where} {v} 第 {i + 1} 格重複定義")
                bar_cells[v][i] = cell
                if mark:
                    bar_marks[mark][v][i] = True
                    used_marks.add(mark)

        bar_stick = {v: [""] * steps for v in VOICES}
        for raw_voice, line in (bar.get("sticking") or {}).items():
            v = norm_voice(raw_voice)
            s = clean(str(line))
            if len(s) != steps:
                raise TabError(f"{where} 手順 {v}：寫了 {len(s)} 格，應該是 {steps} 格。原字串：{line!r}")
            for i, ch in enumerate(s):
                if ch in "RL":
                    if not bar_cells[v][i]:
                        raise TabError(f"{where} 手順 {v} 第 {i + 1} 格標了 {ch}，但那格沒有音符")
                    bar_stick[v][i] = ch
                elif ch not in "-.":
                    raise TabError(f"{where} 手順 {v} 第 {i + 1} 格：只能用 R / L / -")

        for v in VOICES:
            tracks[v] += bar_cells[v]
            sticking[v] += bar_stick[v]
            for k in OVERLAY_ALLOWED:
                marks[k][v] += bar_marks[k][v]
        subdiv += per_beat
        time_sigs.append({"beats": beats, "unit": unit})
        mute.append(bool(bar.get("muteMetronome", False)))
        bar_steps.append(steps)
        bar_beats.append(beats)

    # 依 MAX_BARS 切成多個模組
    out = []
    n_bars = len(time_sigs)
    chunks = [(s, min(s + MAX_BARS, n_bars)) for s in range(0, n_bars, MAX_BARS)]
    for ci, (b0, b1) in enumerate(chunks, start=1):
        st0, st1 = sum(bar_steps[:b0]), sum(bar_steps[:b1])
        be0, be1 = sum(bar_beats[:b0]), sum(bar_beats[:b1])
        sub = subdiv[be0:be1]
        counts = {}
        for u in sub:
            counts[u] = counts.get(u, 0) + 1
        common = [u for u, _ in sorted(counts.items(), key=lambda kv: -kv[1]) if u in VALID_RESOLUTIONS]
        p = {
            "name": name if len(chunks) == 1 else f"{name} ({ci}/{len(chunks)})",
            "bpm": bpm,
            "beatsPerBar": time_sigs[b0]["beats"],
            "bars": b1 - b0,
            "resolution": common[0] if common else 4,
            "tracks": {v: tracks[v][st0:st1] for v in VOICES},
            "sticking": {v: sticking[v][st0:st1] for v in VOICES},
        }
        for k in ("rim", "grace", "open", "bell"):
            if k in used_marks:
                p[k] = {v: marks[k][v][st0:st1] for v in VOICES}
        p["trackOrder"] = list(VOICES)
        p["subdiv"] = sub
        p["locked"] = False
        p["timeSigs"] = time_sigs[b0:b1]
        if any(mute[b0:b1]):
            p["metronomeMuteBars"] = mute[b0:b1]
        out.append(p)
    return out


def check(p: dict) -> list[str]:
    """檢查一份 DrummerUp JSON；回傳問題清單（空 = 沒問題）。規則對照 sanitizePattern()。"""
    errs = []
    if not isinstance(p.get("tracks"), dict):
        errs.append("缺少 tracks 物件（匯入會直接失敗）")
    if not isinstance(p.get("bpm"), (int, float)):
        errs.append("bpm 必須是數字（匯入會直接失敗）")
    if errs:
        return errs
    bars = p.get("bars")
    if not isinstance(bars, int) or not 1 <= bars <= MAX_BARS:
        errs.append(f"bars 必須是 1–{MAX_BARS} 的整數，目前是 {bars!r}")
        return errs
    bpb = p.get("beatsPerBar", 4)
    res = p.get("resolution", 4)
    if res not in VALID_RESOLUTIONS:
        errs.append(f"resolution 只能是 1/2/4/8，目前是 {res!r}")
    ts = p.get("timeSigs")
    if ts is not None:
        if not isinstance(ts, list) or len(ts) != bars:
            errs.append(f"timeSigs 長度必須等於 bars ({bars})")
            return errs
        beats_per = []
        for i, t in enumerate(ts):
            if not isinstance(t, dict) or not 1 <= t.get("beats", 0) <= MAX_BEATS or t.get("unit") not in VALID_UNITS:
                errs.append(f"timeSigs[{i}] 不合法：{t!r}")
            beats_per.append(t.get("beats", bpb) if isinstance(t, dict) else bpb)
    else:
        beats_per = [bpb] * bars
    total_beats = sum(beats_per)
    sd = p.get("subdiv")
    if sd is None:
        sd = [res] * total_beats
    elif not isinstance(sd, list) or len(sd) != total_beats:
        errs.append(f"subdiv 長度必須等於總拍數 {total_beats}，目前是 {len(sd) if isinstance(sd, list) else sd!r}")
        return errs
    if any(not isinstance(u, int) or not 1 <= u <= MAX_SUBDIV for u in sd):
        errs.append(f"subdiv 每一項必須是 1–{MAX_SUBDIV} 的整數")
    steps = sum(sd)
    for v, arr in p["tracks"].items():
        if v not in VOICES:
            errs.append(f"tracks.{v} 不是合法樂器（會被丟掉），合法：{', '.join(VOICES)}")
            continue
        if not isinstance(arr, list) or len(arr) != steps:
            errs.append(f"tracks.{v} 長度必須是 {steps}，目前是 {len(arr) if isinstance(arr, list) else arr!r}")
        elif any(c not in (0, 1, 2, 3) for c in arr):
            errs.append(f"tracks.{v} 只能包含 0/1/2/3")
    for v, arr in (p.get("sticking") or {}).items():
        if v in VOICES and (not isinstance(arr, list) or len(arr) != steps or any(s not in ("", "R", "L") for s in arr)):
            errs.append(f"sticking.{v} 長度必須是 {steps}，且只能是 \"\" / \"R\" / \"L\"")
    for k, allowed in OVERLAY_ALLOWED.items():
        for v, arr in (p.get(k) or {}).items():
            if v in VOICES and (not isinstance(arr, list) or len(arr) != steps or any(not isinstance(b, bool) for b in arr)):
                errs.append(f"{k}.{v} 長度必須是 {steps} 的 true/false 陣列")
            elif v in VOICES and any(arr) and v not in allowed:
                errs.append(f"{k}.{v}：這種標記不能用在 {v}（會被編輯器忽略）")
    return errs


def preview(p: dict) -> str:
    """把模組畫回文字格線，方便跟原始譜面對照。"""
    sd = p["subdiv"]
    lines = []
    beat = 0
    step = 0
    for bi, t in enumerate(p["timeSigs"], start=1):
        per_beat = sd[beat:beat + t["beats"]]
        n = sum(per_beat)
        lines.append(f"── 第 {bi} 小節  {t['beats']}/{t['unit']}  每拍格數 {per_beat}")
        for v in VOICES:
            cells = p["tracks"][v][step:step + n]
            if not any(cells):
                continue
            chars = []
            for i, c in enumerate(cells):
                j = step + i
                mark = next((k for k in ("open", "bell", "rim", "grace") if p.get(k, {}).get(v, [False] * (j + 1))[j]), None)
                ch = {0: "-", 1: "x", 2: "X", 3: "g"}[c]
                if c and mark:
                    ch = {"open": "o", "bell": "b", "rim": "r", "grace": "f"}[mark]
                    ch = ch.upper() if c == 2 else ch
                chars.append(ch)
            pos = 0
            groups = []
            for u in per_beat:
                groups.append("".join(chars[pos:pos + u]))
                pos += u
            stick = "".join(s or "-" for s in p["sticking"][v][step:step + n])
            extra = f"   手順 {stick}" if stick.strip("-") else ""
            lines.append(f"   {v:<9} |{'|'.join(groups)}|{extra}")
        beat += t["beats"]
        step += n
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="輸出檔名（多個模組時會加上 -1、-2 …）")
    ap.add_argument("--check", action="store_true", help="只檢查一份 DrummerUp JSON")
    ap.add_argument("--quiet", action="store_true", help="不印文字預覽")
    a = ap.parse_args()

    data = json.loads(Path(a.input).read_text(encoding="utf-8"))
    if a.check:
        errs = check(data)
        if errs:
            print("❌ 有問題：")
            for e in errs:
                print("  -", e)
            return 1
        print("✅ 格式正確，可以匯入 DrummerUp")
        if not a.quiet and "timeSigs" in data and "subdiv" in data:
            print(preview(data))
        return 0

    try:
        patterns = build(data)
    except TabError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    base = Path(a.output) if a.output else Path(re.sub(r'[\\/:*?"<>|]', "_", patterns[0]["name"].split(" (")[0]) + ".json")
    for i, p in enumerate(patterns, start=1):
        errs = check(p)
        if errs:  # 理論上不會發生；發生代表 build() 有 bug
            print("❌ 內部檢查失敗：", errs, file=sys.stderr)
            return 2
        path = base if len(patterns) == 1 else base.with_name(f"{base.stem}-{i}{base.suffix}")
        path.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ 已輸出 {path}（{p['bars']} 小節）")
        if not a.quiet:
            print(preview(p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
