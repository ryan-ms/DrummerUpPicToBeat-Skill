---
name: drum-sheet-to-drummerup
description: 把鼓譜（圖片、截圖、掃描檔或 PDF）轉成 DrummerUp 可以「匯入模組」的 JSON 檔。當使用者上傳鼓譜並要求轉成 DrummerUp、DrummerUpSkill、鼓譜 JSON、練習模組，或想把譜子匯入打鼓練習 App 時使用。Converts drum sheet music images/PDFs into DrummerUp pattern JSON.
---

# 鼓譜 → DrummerUp JSON

目標：產生一個（或多個）`.json` 檔，使用者在 DrummerUp 按「儲存 ▸ 匯入模組」就能直接開啟。

**不要直接手寫 DrummerUp 的 JSON**：它要求每個樂器都有一條跟總格數一樣長的陣列，
手寫很容易數錯一格就整份錯位。一律先寫成「文字格線」（tab JSON），再用
`scripts/build_pattern.py` 轉檔——script 會檢查每小節格數，錯了會精確指出哪一行。

## 流程

1. **讀譜。** 讀 [references/reading-drum-notation.md](references/reading-drum-notation.md)，
   照它把五線譜位置對應到樂器。PDF 先把每頁轉成圖片再看（例如 `pdftoppm -r 150 -png in.pdf page`），
   小節很密的譜就裁切放大逐行讀，不要一次看整頁就下結論。
   先抓出：標題、速度（♩=）、拍號、圖例、有沒有手順、反覆記號。

2. **寫 tab JSON。** 格式見 [references/tab-format.md](references/tab-format.md)，
   範例見 [examples/rock-beat.tab.json](examples/rock-beat.tab.json)。
   - 每小節選夠用的最小 grid（八分音符的律動用 2，有十六分才用 4）。
   - 用空白隔開每一拍，一拍一拍對著譜數。
   - 反覆記號預設展開成實際演奏順序（使用者另外要求才不展開）。

3. **轉檔。**
   ```bash
   python scripts/build_pattern.py song.tab.json -o 歌名.json
   ```
   有錯就照錯誤訊息修 tab 再跑，直到成功。超過 30 小節會自動拆成多個檔。

4. **對照檢查。** script 會印出每小節的文字預覽，拿它**逐小節跟原譜比一次**
   （特別是小節數、每拍第一個音、重音位置、三連音）。發現錯就回第 2 步改。

5. **交付。** 把 `.json` 檔給使用者下載，並簡短說明：
   - 幾個小節、拍號、BPM。
   - 有哪些地方是猜的或換成近似樂器（例如第 4 顆 Tom 併入 Floor Tom、滾奏展開成十六分音符）。
   - 匯入方式：DrummerUp ▸ 儲存選單 ▸「匯入模組」▸ 選這個檔案。

## 沒辦法執行程式的環境

如果這個 AI chat 不能跑 Python，才直接寫最終 JSON，規則見
[references/drummerup-json.md](references/drummerup-json.md)。寫完務必自己逐條核對長度公式，
並提醒使用者：匯入後如果小節內容錯位，就是某條陣列長度數錯了。

## 注意

- 用使用者的語言回覆（中文譜就用繁體中文）。
- 看不清楚、不確定的地方要明講，不要默默猜；整頁都看不清楚就請使用者給更清楚的圖。
- DrummerUp 只有 9 個樂器軌道（crash, ride, hihat, tom1, tom2, tom3, snare, kick, hihatFoot），
  沒有滾奏、力度漸強、音長，這些都要在回覆中說明怎麼近似處理的。
