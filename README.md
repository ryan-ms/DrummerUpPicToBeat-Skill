# 鼓譜 → DrummerUp 轉檔 Skill

把鼓譜的**照片、截圖、PDF，或畫面上會換頁／捲動顯示鼓譜的影片**交給 AI，轉成 [DrummerUp](https://drummerup.com) 可以直接匯入的練習模組（`.dmup` 檔）。

> **DrummerUp 是什麼？** 免費的線上打鼓練習 App（[drummerup.com](https://drummerup.com)）：在瀏覽器裡編輯節奏、播放示範，
> 接上 MIDI 電子鼓（或用鍵盤、觸控模擬）跟著打，打完會有成績單告訴你哪裡搶拍、拖拍、左右手不平均。
> 這個 skill 讓你不用一格一格手動輸入，拍一張譜就能開始練。

[English](#english) ・ [快速開始](#快速開始claudeai) ・ [使用範例](#使用範例) ・ [其他 AI](#其他-ai) ・ [限制與注意事項](#限制與注意事項)

## 能做什麼

- 一張或多張鼓譜圖片（自動依順序接起來，連續截圖重複截到的行只算一次）
- 截圖裡只有一部分是譜也可以（會自動找出譜的位置、裁切放大再讀）
- PDF
- 教學影片：畫面每幾秒換一頁、或整排譜一直往左捲（常見於 Facebook／IG 短片）
- 超過 30 小節的長譜會自動切成好幾個模組，放進同一個群組檔，一次匯入

AI 不是直接寫出 DrummerUp 的檔案（每個樂器一條很長的陣列，數錯一格整份就錯位），
而是先寫成人看得懂的文字格線，再由內附的 script 轉檔並檢查每一小節的格數。

## 快速開始（claude.ai）

適用 claude.ai 網頁版、Claude 桌面版與手機 App。

1. **下載 skill**：到 [Releases](https://github.com/ryan-ms/DrummerUpPicToBeat-Skill/releases/latest) 下載
   [`drum-sheet-to-drummerup.zip`](https://github.com/ryan-ms/DrummerUpPicToBeat-Skill/releases/latest/download/drum-sheet-to-drummerup.zip)。
   **不要解壓縮**，直接上傳這個 zip。
   （請不要用 GitHub 綠色按鈕的「Download ZIP」：那個 zip 多包了一層資料夾，上傳會失敗。）
2. **開啟程式碼執行**：claude.ai 的設定裡，確認「程式碼執行與檔案建立」（Code execution and file creation）已開啟。
3. **上傳 skill**：在設定的 **Skills** 頁面選「上傳 skill」（Upload skill），選剛剛下載的 zip。
   這個頁面的位置會隨介面版本不同，可能在「設定 ▸ 功能（Capabilities）」或「自訂（Customize）▸ Skills」，
   找不到的話請參考 [Claude 官方說明](https://support.claude.com/en/articles/12512180)。
   Team／Enterprise 方案可能要先請管理員開放 skills。
4. **開始使用**：開一個新對話，上傳鼓譜，說「幫我轉成 DrummerUp」。

## 使用範例

> 👤（上傳 3 張截圖）幫我把這首轉成 DrummerUp
>
> 🤖 轉好了：**《歌名》.dmup**（可下載）
> - 共 16 小節，4/4，♩ = 96（譜上標的速度）
> - 圖 1 → 第 1–8 小節、圖 2 → 第 9–12 小節、圖 3 → 第 13–16 小節；圖 3 第一行跟圖 2 最後一行重複，只算一次
> - 第 12 小節的滾奏展開成十六分音符；第 4 顆 Tom 併進 Floor Tom
> - 匯入方式：DrummerUp ▸ 儲存按鈕旁的 ▾ ▸「匯入模組」▸ 選這個檔案

譜上沒寫速度或拍號時，會先用 4/4、90 BPM 並且明講，匯入後可以在 DrummerUp 裡自己調整。

### 匯入到 DrummerUp

1. 打開 [drummerup.com](https://drummerup.com)
2. 按「儲存」按鈕旁邊的 **▾** ▸ **匯入模組**，選 AI 給你的 `.dmup` 檔
   （長譜的群組檔也從這裡匯入，或從模組庫左側的「匯入群組」）
3. 確認預覽視窗後按匯入，模組就會存進你的模組庫，不會蓋掉正在編輯的內容

**匯入後請對照原譜檢查一次**，尤其是小節數、重音和三連音，AI 讀譜不一定百分之百正確。

## 其他 AI

### Claude Code（電腦上）

```bash
git clone https://github.com/ryan-ms/DrummerUpPicToBeat-Skill.git
cp -r DrummerUpPicToBeat-Skill/drum-sheet-to-drummerup ~/.claude/skills/
```

Windows（PowerShell）把第二行換成
`Copy-Item -Recurse DrummerUpPicToBeat-Skill\drum-sheet-to-drummerup $HOME\.claude\skills\`。
只想在某個專案用的話，複製到那個專案的 `.claude/skills/`。

要處理截圖或影片，先裝好：

```bash
pip install pillow numpy
# 影片另外需要 ffmpeg：
winget install Gyan.FFmpeg      # Windows
brew install ffmpeg             # macOS
pip install imageio-ffmpeg      # 或用這個，不需要系統安裝
```

### ChatGPT（自訂 GPT）

建立自訂 GPT 需要 ChatGPT 付費方案。

1. 下載並解壓縮上面的 zip
2. 探索 GPT ▸ 建立 ▸ 設定（Configure）
3. 「指令」貼上 `PORTABLE_PROMPT.md` 的全部內容
4. 「知識」上傳：`scripts/` 裡的四個 `.py`、`references/` 裡的三個 `.md`
5. 「功能」勾選 **程式碼直譯器與資料分析**（讓它能跑 script、產生可下載的檔案）

### Gemini（Gem）

1. Gem 管理工具 ▸ 新增 Gem
2. 「指示」貼上 `PORTABLE_PROMPT.md`
3. 「知識」上傳 `references/` 裡的三個 `.md` 和 `scripts/build_pattern.py`

Gemini 通常不能執行上傳的 script，會改成直接寫 `.dmup` 的內容，長譜比較容易數錯格子。
AI 會把內容放在程式碼區塊裡，請存成副檔名 **`.dmup`** 的檔案再匯入。長的譜建議用 Claude 或 ChatGPT。

### 其他 AI

把 `PORTABLE_PROMPT.md` 當成第一則訊息（或系統提示），再附上 `references/` 的檔案。

### 各環境能處理什麼

| | claude.ai | ChatGPT | Gemini | Claude Code（本機） |
|---|---|---|---|---|
| 圖片、截圖、PDF | ✅ | ✅ | ✅（不能跑 script，長譜較容易出錯） | ✅ |
| 影片 | 看環境有沒有 ffmpeg | 看環境有沒有 ffmpeg | ❌ 請改成每次換頁截一張圖 | ✅（先裝 ffmpeg） |

雲端讀不了影片、或影片太大傳不上去時，AI 會建議兩個做法：改用電腦上的 Claude Code，或在影片每次換頁時各截一張圖上傳。

## 限制與注意事項

- **AI 讀譜可能出錯。** 匯入後請逐小節對照原譜。看不清楚的地方 AI 會說明，譜太模糊時請提供更清楚的圖。
- DrummerUp 的模組有 9 個軌道：Crash、Ride、Hi-Hat（含開鈸）、Tom 1–3（Tom 3 是落地鼓）、小鼓、大鼓、Hi-Hat 腳踩。
  第 4 顆 Tom、Splash、China、Cowbell 等會併到最接近的軌道，AI 會告訴你怎麼處理的。
- 支援重音、ghost note、鼓邊（cross stick）、開鈸、Ride Bell、裝飾音（flam）、手順 R／L、三連音等連音、每小節不同拍號。
- 沒有滾奏、漸強、音長：滾奏會展開成連續的短音符。
- 一個模組最多 30 小節，更長的會切成多個模組放進同一個群組檔（一個群組最多 20 個模組）。
- **著作權**：多數出版的鼓譜與教學影片受著作權保護。請只把轉出來的模組用在個人練習，不要拿來散布別人的譜。
- **隱私**：圖片和影片會上傳到你使用的 AI 服務（Anthropic、OpenAI、Google 等），適用該服務的隱私政策。

## 自己手動用 script

給想自己寫文字格線、或檢查檔案的人。`build_pattern.py` 只用 Python 標準函式庫；其他三個需要 Pillow、numpy（影片還需要 ffmpeg 或 opencv）。

```bash
cd drum-sheet-to-drummerup
python3 scripts/build_pattern.py examples/rock-beat.tab.json -o rock.dmup   # 文字格線 → .dmup
python3 scripts/build_pattern.py --check 某個模組.dmup                       # 檢查現成的 .dmup（模組或群組）
python3 scripts/build_pattern.py --convert 舊模組.json                       # 舊版 DrummerUp .json 模組檔 → .dmup
python3 scripts/crop_sheet.py 截圖1.png 截圖2.png -o crops --rows --debug     # 裁出截圖裡的譜（逐行另存）
python3 scripts/video_frames.py 影片.mp4 -o frames --rows --debug            # 影片：每次換頁存一張並裁切
python3 scripts/scroll_stitch.py 影片.mp4 -o stitch                           # 影片：整排往左捲的譜拼成一條長譜
```

文字格線的寫法見 [`references/tab-format.md`](drum-sheet-to-drummerup/references/tab-format.md)，
範例見 [`examples/rock-beat.tab.json`](drum-sheet-to-drummerup/examples/rock-beat.tab.json)。

<details>
<summary>script 的細節</summary>

- `crop_sheet.py` 偵測五線譜、單線／雙線打擊譜的譜線；只有字母（例如 `K L R`）沒有譜線的圖偵測不到，這時 AI 會改成目測裁切。
- `video_frames.py` 每秒取 4 張畫面，只比對譜面範圍找出換頁時間（旁邊的人、鼓、移動的游標與高亮不算換頁；只換一行也抓得到），
  每頁取最清楚的畫面存成原始解析度，並比對相鄰兩頁哪幾行重複。整排譜持續捲動的段落改成每捲過約半個畫面存一張。
  輸出 `overview.png`（所有頁的縮圖）與 `segments.json`（時間軸、重複的行）。
- `scroll_stitch.py` 處理一整排譜往左捲的影片：找出白底的譜面範圍、每 0.1 秒算一次往左捲了幾 px、遮掉固定不動的播放游標，
  拼成 `panorama.png`（整條長譜），再切成放大、前後重疊的 `read_01.png`… 方便依序讀。1080p 影片每一分鐘約需 40 秒分析。

</details>

## 檔案結構

```
drum-sheet-to-drummerup/          # ← skill 本體（Release 的 zip 就是這個資料夾）
├── SKILL.md                        # Claude Skill 主檔
├── PORTABLE_PROMPT.md              # 給 ChatGPT／Gemini 等其他 AI 的指令
├── scripts/
│   ├── build_pattern.py            # 文字格線 → .dmup，並檢查格數
│   ├── crop_sheet.py               # 從截圖找出譜的位置並裁切放大
│   ├── video_frames.py             # 影片：找出每次換頁的畫面並裁切
│   └── scroll_stitch.py            # 影片：整排往左捲的譜拼成一條長譜
├── references/
│   ├── reading-drum-notation.md    # 讀譜：五線譜位置 → 樂器
│   ├── tab-format.md               # 文字格線格式
│   └── drummerup-json.md           # .dmup 格式（不能跑程式時用）
└── examples/rock-beat.tab.json     # 範例
```

## 回報問題與貢獻

轉錯的譜、用不了的環境都歡迎開 [Issue](https://github.com/ryan-ms/DrummerUpPicToBeat-Skill/issues)（附上原圖與轉出來的檔案最好）。
修改 script 或發佈新版請看 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 授權

[MIT](LICENSE)

---

## English

**Turn drum sheet music into [DrummerUp](https://drummerup.com) practice modules with AI.**
DrummerUp is a free web app for drum practice: edit grooves, play along on a MIDI e-drum kit (or keyboard / touch simulator),
and get a score report on timing and hand balance. This skill lets an AI read a drum chart — photos, screenshots, PDFs, or videos
that page or scroll through a chart — and produce a `.dmup` file you can import directly.

**Quick start (claude.ai)**

1. Download [`drum-sheet-to-drummerup.zip`](https://github.com/ryan-ms/DrummerUpPicToBeat-Skill/releases/latest/download/drum-sheet-to-drummerup.zip)
   from [Releases](https://github.com/ryan-ms/DrummerUpPicToBeat-Skill/releases/latest). Upload it as is — don't unzip it, and don't use GitHub's
   green "Download ZIP" button (that archive has an extra folder level and won't upload).
2. In claude.ai settings, turn on **Code execution and file creation**.
3. Open the **Skills** page in settings (under *Capabilities* or *Customize ▸ Skills* depending on your interface version;
   see [Anthropic's help article](https://support.claude.com/en/articles/12512180)) and upload the zip.
4. In a new chat, upload your sheet music and say "convert this to DrummerUp".
5. In DrummerUp, click **▾** next to **Save** ▸ **Import Module** and pick the `.dmup` file.

**Claude Code:** copy `drum-sheet-to-drummerup/` into `~/.claude/skills/`, then `pip install pillow numpy`
(plus ffmpeg for videos). **ChatGPT / Gemini / others:** use `PORTABLE_PROMPT.md` as the instructions and upload the
`scripts/` and `references/` files as knowledge (see the Chinese sections above for the exact steps).

**Limitations:** AI reading is not perfect, so always check the result against the original chart. DrummerUp has 9 tracks
(crash, ride, hi-hat, 3 toms, snare, kick, hi-hat pedal); extra drums are mapped to the closest track, rolls are written out
as short notes, and one module holds up to 30 bars (longer charts become a group file). Most published drum charts are
copyrighted, so use converted modules for personal practice only. Your images and videos are sent to the AI service you use.
The skill replies in your language; its internal instructions are in Traditional Chinese.

License: [MIT](LICENSE)
