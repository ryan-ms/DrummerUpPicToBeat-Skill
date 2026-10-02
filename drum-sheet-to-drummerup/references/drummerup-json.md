# DrummerUp 模組 JSON 格式（直接手寫用）

**能跑 Python 就不要用這份**，改用 `scripts/build_pattern.py`。這份只給不能執行程式的 AI chat 用。
規則對應 DrummerUp 原始碼的 `sanitizePattern()`（`src/core/pattern.ts`）：不合規則的欄位會在匯入時被默默改掉或清空。

## 完整範例（1 小節 4/4，八分音符 8 Beat）

```json
{
  "name": "8 Beat",
  "bpm": 100,
  "beatsPerBar": 4,
  "bars": 1,
  "resolution": 2,
  "tracks": {
    "crash":     [0,0,0,0,0,0,0,0],
    "ride":      [0,0,0,0,0,0,0,0],
    "hihat":     [1,1,1,1,1,1,1,1],
    "tom1":      [0,0,0,0,0,0,0,0],
    "tom2":      [0,0,0,0,0,0,0,0],
    "tom3":      [0,0,0,0,0,0,0,0],
    "snare":     [0,0,2,0,0,0,2,0],
    "kick":      [1,0,0,0,1,0,0,0],
    "hihatFoot": [0,0,0,0,0,0,0,0]
  },
  "sticking": {
    "crash": ["","","","","","","",""],
    "ride": ["","","","","","","",""],
    "hihat": ["R","R","R","R","R","R","R","R"],
    "tom1": ["","","","","","","",""],
    "tom2": ["","","","","","","",""],
    "tom3": ["","","","","","","",""],
    "snare": ["","","L","","","","L",""],
    "kick": ["","","","","","","",""],
    "hihatFoot": ["","","","","","","",""]
  },
  "trackOrder": ["crash","ride","hihat","tom1","tom2","tom3","snare","kick","hihatFoot"],
  "subdiv": [2,2,2,2],
  "locked": false,
  "timeSigs": [{ "beats": 4, "unit": 4 }]
}
```

## 長度公式（最容易出錯，寫完逐條核對）

- `timeSigs`：長度 = `bars`。每項 `{ beats: 1–16, unit: 1|2|4|8|16 }`。
- `subdiv`：長度 = 所有小節 `beats` 加總（總拍數）。每項 = 那一拍切幾格（1–16）。
- **總格數 = `subdiv` 全部加總**。
- `tracks` 的 9 條、`sticking` 的 9 條、以及有用到的 `rim`/`grace`/`open`/`bell` 的每一條：長度都 = 總格數。
- `bars` ≤ 30，超過就拆成多個檔案。

## 欄位

| 欄位 | 值 |
|---|---|
| `tracks.<樂器>` | 每格 `0` 休息、`1` 一般、`2` 重音、`3` ghost |
| `sticking.<樂器>` | 每格 `""`、`"R"`、`"L"` |
| `open.hihat` | 開踩 Hi-Hat，`true`/`false` 陣列（其他樂器全 `false`） |
| `bell.ride` | Ride Bell |
| `rim.snare` / `rim.tom1..3` | 鼓邊／Cross-stick |
| `grace.<樂器>` | 該音前面有裝飾音（flam/drag） |
| `resolution` | 1/2/4/8，取最常見的每拍格數（只是預設值，`subdiv` 才是準的） |
| `beatsPerBar` | 第一小節的拍數 |
| `bpm` | 四分音符速度（10–500）。6/8 的 `♩. = 80` 要換成 `120` |

`rim`/`grace`/`open`/`bell` 沒用到就整個省略；有用到時 9 個樂器都要列，沒標的填全 `false`。
