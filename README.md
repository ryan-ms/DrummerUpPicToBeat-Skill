# 鼓譜 → DrummerUp 轉檔 Skill

上傳鼓譜圖片（可以多張、可以是只有一部分是譜的截圖）或 PDF，讓 AI 轉成 DrummerUp「匯入模組」可以直接開的 `.dmup` 檔。

```
drum-sheet-to-drummerup/          # ← skill 本體，安裝時用這個資料夾
├── SKILL.md                        # Claude Skill 主檔
├── PORTABLE_PROMPT.md              # 給 ChatGPT / Gemini 等其他 AI 用的指令
├── scripts/build_pattern.py        # tab JSON → DrummerUp .dmup（純 Python 標準函式庫）
├── scripts/crop_sheet.py           # 從截圖找出譜的位置並裁切放大（需要 Pillow、numpy）
├── references/
│   ├── reading-drum-notation.md    # 讀譜：五線譜位置 → 樂器
│   ├── tab-format.md               # 中間格式說明
│   └── drummerup-json.md           # DrummerUp .dmup 格式（不能跑程式時用）
└── examples/rock-beat.tab.json     # 範例
```

AI 不直接手寫 DrummerUp 的模組（每個樂器一條跟總格數一樣長的陣列，數錯一格整份就錯位），
而是先寫成人看得懂的文字格線，再由 script 轉檔＋檢查格數。

## 安裝

### Claude（claude.ai／Claude 桌面版／手機版）

1. 把 `drum-sheet-to-drummerup/` 資料夾壓成 zip（zip 裡最上層要是這個資料夾）：
   ```bash
   zip -r drum-sheet-to-drummerup.zip drum-sheet-to-drummerup
   ```
2. claude.ai ▸ 設定 ▸ Capabilities（功能）▸ 確認「程式碼執行與檔案建立」已開啟
3. 同一頁的 Skills ▸ 上傳 skill ▸ 選 zip
4. 之後在任何對話上傳鼓譜，說「轉成 DrummerUp」就會自動套用

### Claude Code

把資料夾複製到 `~/.claude/skills/`（所有專案可用）或專案的 `.claude/skills/`。

### ChatGPT（自訂 GPT）

1. 探索 GPT ▸ 建立 ▸ 設定（Configure）
2. 「指令」貼上 `PORTABLE_PROMPT.md` 的全部內容
3. 「知識」上傳：`scripts/build_pattern.py`、`scripts/crop_sheet.py`、`references/` 裡的三個 `.md`
4. 「功能」勾選 **程式碼直譯器與資料分析**（讓它能跑 script、產生可下載的檔案）

### Gemini（Gem）

1. Gem 管理工具 ▸ 新增 Gem
2. 「指示」貼上 `PORTABLE_PROMPT.md`
3. 「知識」上傳 `references/` 裡的三個 `.md`（加上 `build_pattern.py`）

Gemini 通常不能執行上傳的 script，會改走「直接寫 .dmup 內容」的路線，長譜比較容易數錯格子；
長的譜建議用 Claude 或 ChatGPT。

### 其他 AI

把 `PORTABLE_PROMPT.md` 當成第一則訊息（或系統提示），再附上 `references/` 的檔案。

## 自己手動用 script

```bash
python3 scripts/build_pattern.py examples/rock-beat.tab.json -o rock.dmup   # 轉檔
python3 scripts/build_pattern.py --check 某個模組.dmup                       # 檢查現成的 .dmup 檔（模組或群組）
python3 scripts/build_pattern.py --convert 舊模組.json                       # 舊版 .json 模組檔 → .dmup
python3 scripts/crop_sheet.py 截圖1.png 截圖2.png -o crops --rows --debug     # 裁出截圖裡的譜（逐行另存）
```

`crop_sheet.py` 偵測五線譜、單線／雙線打擊譜的譜線；只有字母（例如 `K L R`）沒有譜線的圖偵測不到，
這時 AI 會改成目測裁切。

## 維護

`build_pattern.py` 的檢查規則對應 [DrummerUpSkill](https://github.com/ryan-ms/DrummerUpSkill) 的
`sanitizePattern()`（`src/core/pattern.ts`）與樂器清單 `INSTRUMENTS`（`src/core/drumMap.ts`）。App 新增樂器、疊加標記或改小節上限
（`MAX_PATTERN_BARS`）時，要一起更新 script 的 `VOICES`、`SYMBOLS`、`MAX_BARS` 和 references。
輸出的 `.dmup` 標頭對應 `src/core/dmup.ts`（`DMUP_VERSION`）與 `src/core/importFile.ts`（`parseImportFile()`、`buildPatternFile()`／`buildGroupFile()`），
App 改格式、加 `DMUP_VERSION` 或改群組上限（`MAX_GROUP_MEMBERS`）時，script 的 `DMUP_VERSION`、`MAX_GROUP_MEMBERS` 與 `drummerup-json.md` 要一起改。
