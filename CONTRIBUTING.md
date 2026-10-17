# 維護說明

歡迎開 Issue 回報轉錯的譜（附上原圖和轉出來的 `.dmup` 最好）或送 Pull Request。

## 跟 DrummerUp App 同步

`scripts/build_pattern.py` 產生的檔案必須能被 DrummerUp 匯入，所以下列常數要跟 App 保持一致：

| script 裡的常數 | 意思 | 目前的值 |
|---|---|---|
| `VOICES` | 樂器軌道 | crash, ride, hihat, tom1, tom2, tom3, snare, kick, hihatFoot |
| `SYMBOLS`、`OVERLAY_ALLOWED` | 符號與各標記能用在哪些樂器 | 見 `references/tab-format.md` |
| `MAX_BARS` | 一個模組最多幾小節 | 30 |
| `MAX_GROUP_MEMBERS` | 一個群組最多幾個模組 | 20 |
| `DMUP_VERSION` | `.dmup` 檔的格式版本 | 1 |

App 新增樂器或標記、改小節／群組上限、改 `.dmup` 格式時，要一起更新 script 的這些常數，以及 `references/` 裡的三份說明
（`drummerup-json.md` 是給不能跑程式的 AI 看的格式說明，最容易忘記改）。

## 改完之後

```bash
cd drum-sheet-to-drummerup
python3 scripts/build_pattern.py examples/rock-beat.tab.json -o /tmp/rock.dmup
python3 scripts/build_pattern.py --check /tmp/rock.dmup
```

最後把 `/tmp/rock.dmup` 實際匯入 DrummerUp（儲存旁的 ▾ ▸「匯入模組」）確認一次。

## 發佈新版

在 GitHub 建一個 Release，附上打包好的 skill（檔名固定是 `drum-sheet-to-drummerup.zip`，README 的下載連結指向它）：

```bash
zip -r drum-sheet-to-drummerup.zip drum-sheet-to-drummerup -x '*/__pycache__/*' '*.pyc'
```

zip 裡最上層要是 `drum-sheet-to-drummerup/` 資料夾，`SKILL.md` 在它下面。
