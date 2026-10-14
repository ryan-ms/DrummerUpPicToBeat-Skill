# DrummerUp 模組檔（.dmup）格式（直接手寫用）

**能跑 Python 就不要用這份**，改用 `scripts/build_pattern.py`。這份只給不能執行程式的 AI chat 用。
規則對應 DrummerUp 原始碼的 `src/core/dmup.ts`、`src/core/importFile.ts`（`parseImportFile()`）與
`sanitizePattern()`（`src/core/pattern.ts`）：不合規則的欄位會在匯入時被默默改掉或清空。

## 檔案本身

- **副檔名一定要是 `.dmup`**（例如 `8 Beat.dmup`）。DrummerUp 2026-10 起只收 `.dmup`，`.json`、`.txt` 會被拒絕：
  「只能匯入 DrummerUp 的 .dmup 檔」。
- 內容是 JSON，最外層一定要有標頭 `"format": "drummerup"`、`"version": 1`、`"kind"`，模組放在 `pattern` 裡。
  沒有標頭（以前直接把模組當整份 JSON 的寫法）一樣會被拒絕。
- 模組裡**不要寫 `id`**。

## 完整範例（1 小節 4/4，八分音符 8 Beat）

```json
{
  "format": "drummerup",
  "version": 1,
  "kind": "pattern",
  "pattern": {
    "name": "8 Beat",
    "bpm": 100,
    "beatsPerBar": 4,
    "bars": 1,
    "resolution": 2,
    "tracks": {
      "hihat": [1,1,1,1,1,1,1,1],
      "snare": [0,0,2,0,0,0,2,0],
      "kick":  [1,0,0,0,1,0,0,0]
    },
    "sticking": {
      "hihat": ["R","R","R","R","R","R","R","R"],
      "snare": ["","","L","","","","L",""]
    },
    "trackOrder": ["crash","ride","hihat","tom1","tom2","tom3","snare","kick","hihatFoot"],
    "subdiv": [2,2,2,2],
    "locked": false,
    "timeSigs": [{ "beats": 4, "unit": 4 }]
  }
}
```

**沒用到的樂器、手順、標記可以整條省略**（跟 App 自己匯出的精簡格式一樣，匯入時會補回空的）：
上例只寫了 hihat／snare／kick，其他 6 個樂器沒有音符就不寫。`tracks` 本身一定要有（至少 `{}`），`bpm` 一定要是數字。

## 長度公式（最容易出錯，寫完逐條核對）

- `timeSigs`：長度 = `bars`。每項 `{ beats: 1–16, unit: 1|2|4|8|16 }`。
- `subdiv`：長度 = 所有小節 `beats` 加總（總拍數）。每項 = 那一拍切幾格（1–16）。
- **總格數 = `subdiv` 全部加總**。
- 有寫出來的每一條 `tracks.<樂器>`、`sticking.<樂器>`、`rim`/`grace`/`open`/`bell` 的 `.<樂器>`：長度都 = 總格數。
- `bars` ≤ 30，超過就切成多個模組，放進一個群組檔（見下面）。

## 欄位

| 欄位 | 值 |
|---|---|
| `tracks.<樂器>` | 每格 `0` 休息、`1` 一般、`2` 重音、`3` ghost |
| `sticking.<樂器>` | 每格 `""`、`"R"`、`"L"`（沒標手順就整個省略） |
| `open.hihat` | 開踩 Hi-Hat，`true`/`false` 陣列 |
| `bell.ride` | Ride Bell |
| `rim.snare` / `rim.tom1..3` | 鼓邊／Cross-stick |
| `grace.<樂器>` | 該音前面有裝飾音（flam/drag） |
| `resolution` | 1/2/4/8，取最常見的每拍格數（只是預設值，`subdiv` 才是準的） |
| `beatsPerBar` | 第一小節的拍數 |
| `bpm` | 四分音符速度（10–500）。6/8 的 `♩. = 80` 要換成 `120` |

樂器只有 9 個：`crash`, `ride`, `hihat`, `tom1`, `tom2`, `tom3`, `snare`, `kick`, `hihatFoot`。
`rim`/`grace`/`open`/`bell` 沒用到就整個省略；有用到時只寫有標記的那幾個樂器。

## 超過 30 小節：群組檔

一個群組檔可以放最多 20 個模組，使用者匯入一次就全部進模組庫（同一個入口「匯入模組」，或模組庫的「匯入群組」）：

```json
{
  "format": "drummerup",
  "version": 1,
  "kind": "group",
  "groupName": "歌名",
  "patterns": [
    { "name": "歌名 (1/2)", "bpm": 100, "bars": 30, "...": "跟上面 pattern 裡的欄位一樣" },
    { "name": "歌名 (2/2)", "bpm": 100, "bars": 12, "...": "..." }
  ]
}
```

`patterns` 裡每一個都是完整的模組（不帶 `id`），長度公式各自核對。
