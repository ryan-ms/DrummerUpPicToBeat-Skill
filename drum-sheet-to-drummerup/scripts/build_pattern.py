#!/usr/bin/env python3
"""把「鼓譜文字格線」(drum tab JSON) 轉成 DrummerUp 可以直接「匯入模組」的 .dmup 檔。

用法：
    python build_pattern.py tab.json                  # 輸出 <name>.dmup（超過 30 小節輸出成一個群組檔）
    python build_pattern.py tab.json -o out.dmup      # 指定輸出檔名（副檔名一律改成 .dmup）
    python build_pattern.py tab.json --separate       # 超過 30 小節時改成每段一個模組檔（-1、-2 …）
    python build_pattern.py --check song.dmup         # 檢查一份 .dmup 檔（模組或群組）
    python build_pattern.py --convert old.json        # 把舊版 DrummerUp 模組 JSON 轉成 .dmup

只用 Python 標準函式庫，任何有程式執行環境的 AI chat（Claude、ChatGPT 程式碼直譯器等）都能直接跑。
輸入格式見 ../references/tab-format.md；輸出欄位規則跟 DrummerUp 的 sanitizePattern()
（src/core/pattern.ts）一致，所以輸出檔匯入時不會被默默改掉內容。

.dmup 檔格式對應 DrummerUp 的 src/core/dmup.ts 與 src/core/importFile.ts（2026-10 起只收 .dmup，舊的 .json 不再支援）：
    模組：{ "format": "drummerup", "version": 1, "kind": "pattern", "pattern": { …模組… } }
    群組：{ "format": "drummerup", "version": 1, "kind": "group", "groupName": "…", "patterns": [ … ] }
模組本身用跟 App 匯出相同的精簡格式（compactPattern：拿掉整條空的軌道、手順與標記陣列，App 匯入時會補回）。
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
MAX_GROUP_MEMBERS = 20   # 一個群組最多幾個模組（storage.ts 的 MAX_GROUP_MEMBERS）
DMUP_FORMAT = "drummerup"
DMUP_VERSION = 1         # dmup.ts 的 DMUP_VERSION；App 讀到比自己新的版本會拒絕匯入
DMUP_EXT = ".dmup"
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


BAR_KEYS = ("time", "grid", "sticking", "muteMetronome", "comment", "source")


def build(tab: dict) -> tuple[list[dict], list[dict]]:
    """回傳 (DrummerUp 模組清單, 每小節的附帶資訊 [{source, sig}])。"""
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
    bar_info: list[dict] = []  # 每小節來自哪張圖、內容指紋（找截圖重疊用）
    source = None

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

        if bar.get("source") is not None:
            source = str(bar["source"])
        notes = bar.get("notes", {k: v for k, v in bar.items() if k not in BAR_KEYS})
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
        bar_info.append({
            "source": source,
            "sig": (time, tuple(per_beat), tuple(tuple(bar_cells[v]) for v in VOICES),
                    tuple(tuple(bar_stick[v]) for v in VOICES),
                    tuple(tuple(bar_marks[k][v]) for k in OVERLAY_ALLOWED for v in VOICES)),
        })

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
    return out, bar_info


def defaults_used(tab: dict) -> list[str]:
    """譜上沒寫、用了預設值的設定，回覆時要告訴使用者。"""
    used = []
    if not tab.get("bpm"):
        used.append("速度用預設 90 BPM")
    bars = tab.get("bars") or [{}]
    if tab.get("time") is None and not (isinstance(bars[0], dict) and bars[0].get("time")):
        used.append("拍號用預設 4/4")
    return used


def overlap_warnings(bar_info: list[dict]) -> list[str]:
    """相鄰兩張圖：前一張最後 k 小節跟下一張開頭 k 小節一模一樣 → 很可能是截圖重疊。"""
    warns = []
    n = len(bar_info)
    sigs = [x["sig"] for x in bar_info]
    i = 1
    while i < n:
        a, b = bar_info[i - 1]["source"], bar_info[i]["source"]
        if a is None or b is None or a == b:
            i += 1
            continue
        p0 = i
        while p0 > 0 and bar_info[p0 - 1]["source"] == a:
            p0 -= 1
        n1 = i
        while n1 < n and bar_info[n1]["source"] == b:
            n1 += 1
        def span(s0, s1):
            return f"第 {s0} 小節" if s0 == s1 else f"第 {s0}–{s1} 小節"
        for k in range(min(i - p0, n1 - i), 0, -1):
            if sigs[i - k:i] == sigs[i:i + k]:
                warns.append(
                    f"「{a}」最後 {k} 小節（{span(i - k + 1, i)}）跟「{b}」開頭 {k} 小節（{span(i + 1, i + k)}）"
                    "完全一樣：如果是截圖重疊，刪掉其中一份再轉一次；譜上本來就重複演奏就保留"
                )
                break
        i += 1
    return warns


MARK_KEYS = ("rim", "grace", "open", "bell")


def compact(p: dict) -> dict:
    """跟 App 的 compactPattern() 一樣：拿掉整條都空的軌道、手順、標記陣列（tracks 至少留空物件）。"""
    def keep_used(rec, used):
        return {v: arr for v, arr in (rec or {}).items() if any(used(x) for x in arr)}

    out = {}
    for k, val in p.items():
        if k == "tracks":
            out[k] = keep_used(val, bool)
        elif k == "sticking" or k in MARK_KEYS:
            kept = keep_used(val, (lambda x: x in ("R", "L")) if k == "sticking" else (lambda x: x is True))
            if kept:
                out[k] = kept
        else:
            out[k] = val
    return out


def dmup_pattern(p: dict) -> dict:
    return {"format": DMUP_FORMAT, "version": DMUP_VERSION, "kind": "pattern", "pattern": compact(p)}


def dmup_group(name: str, patterns: list[dict]) -> dict:
    return {"format": DMUP_FORMAT, "version": DMUP_VERSION, "kind": "group", "groupName": name[:200],
            "patterns": [compact(p) for p in patterns]}


def unwrap(data) -> tuple[str, list[dict]]:
    """拆開 .dmup 檔，回傳 (kind, 模組清單)；不是 .dmup 格式就丟 TabError（規則同 importFile.ts 的 parseImportFile）。"""
    if not isinstance(data, dict) or data.get("format") != DMUP_FORMAT or not isinstance(data.get("version"), (int, float)):
        if isinstance(data, dict) and "tracks" in data:
            raise TabError("這是舊版的 DrummerUp 模組 JSON（沒有 .dmup 標頭），App 已經不收；"
                           "用 --convert 轉成 .dmup")
        raise TabError("不是 DrummerUp 的 .dmup 檔（缺少 \"format\": \"drummerup\" 標頭）")
    if data["version"] > DMUP_VERSION:
        raise TabError(f"檔案格式版本 {data['version']} 比這個 script 認得的 {DMUP_VERSION} 新，請更新 script")
    kind = data.get("kind")
    if kind == "pattern":
        p = data.get("pattern")
        if not isinstance(p, dict):
            raise TabError("kind 是 pattern，但缺少 pattern 物件")
        return kind, [p]
    if kind == "group":
        ps = data.get("patterns")
        if not isinstance(ps, list) or not ps or not all(isinstance(p, dict) for p in ps):
            raise TabError("kind 是 group，但 patterns 不是非空的模組陣列")
        if len(ps) > MAX_GROUP_MEMBERS:
            raise TabError(f"群組最多 {MAX_GROUP_MEMBERS} 個模組（App 會丟掉多的），目前 {len(ps)} 個")
        if not isinstance(data.get("groupName"), str) or not data["groupName"].strip():
            raise TabError("群組缺少 groupName（App 會改用預設名稱）")
        return kind, ps
    raise TabError(f"kind 只能是 pattern 或 group，目前是 {kind!r}")


def dmup_path(path: Path) -> Path:
    """App 只收副檔名 .dmup 的檔案。"""
    return path if path.suffix.lower() == DMUP_EXT else path.with_suffix(DMUP_EXT)


def write_dmup(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
    # App 匯出的檔案可能有自訂軌道（customVoices，id 是 c_ 開頭）
    known = set(VOICES) | {c.get("id") for c in (p.get("customVoices") or []) if isinstance(c, dict)}
    for v, arr in p["tracks"].items():
        if v not in known:
            errs.append(f"tracks.{v} 不是合法樂器（會被丟掉），合法：{', '.join(VOICES)}")
            continue
        if not isinstance(arr, list) or len(arr) != steps:
            errs.append(f"tracks.{v} 長度必須是 {steps}，目前是 {len(arr) if isinstance(arr, list) else arr!r}")
        elif any(c not in (0, 1, 2, 3) for c in arr):
            errs.append(f"tracks.{v} 只能包含 0/1/2/3")
    for v, arr in (p.get("sticking") or {}).items():
        if v in known and (not isinstance(arr, list) or len(arr) != steps or any(s not in ("", "R", "L") for s in arr)):
            errs.append(f"sticking.{v} 長度必須是 {steps}，且只能是 \"\" / \"R\" / \"L\"")
    for k, allowed in OVERLAY_ALLOWED.items():
        for v, arr in (p.get(k) or {}).items():
            if v in known and (not isinstance(arr, list) or len(arr) != steps or any(not isinstance(b, bool) for b in arr)):
                errs.append(f"{k}.{v} 長度必須是 {steps} 的 true/false 陣列")
            elif v in VOICES and any(arr) and v not in allowed:
                errs.append(f"{k}.{v}：這種標記不能用在 {v}（會被編輯器忽略）")
    return errs


def preview(p: dict, sources: list | None = None, first_bar: int = 0) -> str:
    """把模組畫回文字格線，方便跟原始譜面對照。

    sources：每小節來自哪張圖（可省略）；first_bar：分檔時前面檔案的小節數，讓小節編號接續全曲。
    """
    sd = p["subdiv"]
    lines = []
    beat = 0
    step = 0
    for bi, t in enumerate(p["timeSigs"], start=1):
        per_beat = sd[beat:beat + t["beats"]]
        n = sum(per_beat)
        src = sources[bi - 1] if sources and bi - 1 < len(sources) else None
        new_src = src is not None and (bi == 1 or sources[bi - 2] != src)
        lines.append(f"── 第 {bi + first_bar} 小節  {t['beats']}/{t['unit']}  每拍格數 {per_beat}" + (f"   ◀ {src}" if new_src else ""))
        for v in VOICES:
            cells = p["tracks"].get(v, [0] * (step + n))[step:step + n]
            if not any(cells):
                continue
            chars = []
            for i, c in enumerate(cells):
                j = step + i
                mark = next((k for k in ("open", "bell", "rim", "grace") if (p.get(k) or {}).get(v, [False] * (j + 1))[j]), None)
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
            stick = "".join(s or "-" for s in (p.get("sticking") or {}).get(v, [""] * (step + n))[step:step + n])
            extra = f"   手順 {stick}" if stick.strip("-") else ""
            lines.append(f"   {v:<9} |{'|'.join(groups)}|{extra}")
        beat += t["beats"]
        step += n
    return "\n".join(lines)


def run_check(data: dict, quiet: bool) -> int:
    try:
        kind, patterns = unwrap(data)
    except TabError as e:
        print(f"❌ {e}")
        return 1
    bad = False
    for i, p in enumerate(patterns, start=1):
        label = f"第 {i} 個模組「{p.get('name', '')}」" if kind == "group" else "模組"
        errs = check(p)
        if errs:
            bad = True
            print(f"❌ {label}有問題：")
            for e in errs:
                print("  -", e)
        elif not quiet and isinstance(p.get("timeSigs"), list) and isinstance(p.get("subdiv"), list):
            print(f"── {label}（{p['bars']} 小節）")
            print(preview(p))
    if bad:
        return 1
    what = f"群組「{data['groupName']}」，{len(patterns)} 個模組" if kind == "group" else "模組"
    print(f"✅ 格式正確（{what}），可以匯入 DrummerUp")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="輸出檔名（副檔名一律是 .dmup；多個檔時會加上 -1、-2 …）")
    ap.add_argument("--check", action="store_true", help="只檢查一份 .dmup 檔")
    ap.add_argument("--convert", action="store_true", help="把舊版 DrummerUp 模組 JSON 轉成 .dmup")
    ap.add_argument("--separate", action="store_true", help="超過 30 小節時輸出成多個模組檔，而不是一個群組檔")
    ap.add_argument("--quiet", action="store_true", help="不印文字預覽")
    a = ap.parse_args()

    data = json.loads(Path(a.input).read_text(encoding="utf-8"))
    if a.check:
        return run_check(data, a.quiet)

    if a.convert:
        if not isinstance(data, dict) or "tracks" not in data:
            print("❌ 這不是舊版的 DrummerUp 模組 JSON（要有 tracks 欄位）", file=sys.stderr)
            return 1
        errs = check(data)
        if errs:
            print("❌ 舊檔本身有問題，先修好再轉：")
            for e in errs:
                print("  -", e)
            return 1
        p = {k: v for k, v in data.items() if k not in ("id", "visibleVoices")}  # 同 App 匯出：不帶 id
        path = dmup_path(Path(a.output) if a.output else Path(a.input))
        write_dmup(path, dmup_pattern(p))
        print(f"✅ 已輸出 {path}")
        return 0

    try:
        patterns, bar_info = build(data)
    except TabError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    name = str(data.get("name") or "未命名")[:200]
    base = Path(a.output) if a.output else Path(re.sub(r'[\\/:*?"<>|]', "_", name) + DMUP_EXT)
    if base.suffix.lower() != DMUP_EXT:
        print(f"ℹ️  DrummerUp 只收 .dmup 檔，輸出檔名改成 {dmup_path(base).name}")
        base = dmup_path(base)

    for p in patterns:
        errs = check(p)
        if errs:  # 理論上不會發生；發生代表 build() 有 bug
            print("❌ 內部檢查失敗：", errs, file=sys.stderr)
            return 2

    def numbered(i: int, n: int) -> Path:
        return base if n == 1 else base.with_name(f"{base.stem}-{i}{base.suffix}")

    # 要寫出的檔案：[(路徑, .dmup 內容, 這個檔裡的模組)]
    files = []
    if len(patterns) == 1 or a.separate:
        for i, p in enumerate(patterns, start=1):
            files.append((numbered(i, len(patterns)), dmup_pattern(p), [p]))
    else:
        # 超過 30 小節：整首放進一個群組檔，匯入一次就全部進模組庫（群組最多 20 個模組，再多才拆檔）
        chunks = [patterns[k:k + MAX_GROUP_MEMBERS] for k in range(0, len(patterns), MAX_GROUP_MEMBERS)]
        for i, chunk in enumerate(chunks, start=1):
            gname = name if len(chunks) == 1 else f"{name} ({i}/{len(chunks)})"
            files.append((numbered(i, len(chunks)), dmup_group(gname, chunk), chunk))

    first_bar = 0
    for path, content, ps in files:
        # 寫出去之前，照 App 匯入的規則再拆開檢查一次
        kind, back = unwrap(json.loads(json.dumps(content)))
        assert len(back) == len(ps) and not any(check(x) for x in back), "內部檢查失敗"
        write_dmup(path, content)
        bars = sum(p["bars"] for p in ps)
        what = f"群組「{content['groupName']}」，{len(ps)} 個模組、共 {bars} 小節" if kind == "group" else f"{bars} 小節"
        print(f"✅ 已輸出 {path}（{what}）")
        for p in ps:
            if not a.quiet:
                if kind == "group":
                    print(f"── 模組「{p['name']}」")
                print(preview(p, [x["source"] for x in bar_info[first_bar:first_bar + p["bars"]]], first_bar))
            first_bar += p["bars"]
    for note in defaults_used(data):
        print(f"ℹ️  譜上沒寫，{note}（回覆時要告訴使用者）")
    for w in overlap_warnings(bar_info):
        print(f"⚠️  {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
