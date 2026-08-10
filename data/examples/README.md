# 範例資料

**這是 repo 裡唯一進版控的資料。** 真實資料一律 gitignored（← `AG-000`）。

| 檔案 | 用途 |
|------|------|
| `goals.csv` | 六個目標，數字取自既有 sprint 規劃（月投遞 60／週 15／日 1／找職缺 4／刷題 100／文章 3） |
| `progress.csv` | 2026 年 8 月整月的假進度，用來回放驗證整條管線 |

## 拿它跑一次

```bash
python3 -m compute.report --data-dir data/examples --as-of 2026-08-24 --no-write
python3 -m compute.report --data-dir data/examples --as-of 2026-08-30 --no-write --explain
```

兩個日期是刻意挑的，各驗一條路徑：

| `--as-of` | 會看到什麼 |
|-----------|-----------|
| `2026-08-24` | 系統第 24 天＝**影子模式**（寫進報表不推播）；「8 月投遞」可行性翻轉，但 Monte Carlo 還差 6 天 → 三個選項的機率標「—」 |
| `2026-08-30` | 系統第 30 天＝**分級發布**（配額只剩 1）；同一個目標的可救性已歸零 → 卡片變成「建議改目標」，其餘沉進摘要 |

`progress.csv` 的走勢是設計過的：前兩週約 2／天，第三週起掉到 0.5／天。
**每一天都還在正常範圍內，累積起來卻到不了**——這正是異常偵測結構上抓不到、
而本專案要抓的那一類（← `AG-007` 為什麼叫 `drift`）。

## 開始用自己的資料

```bash
cp data/examples/goals.csv data/goals.csv
cp data/examples/progress.csv data/progress.csv
```

然後把 `progress.csv` 清空、改成自己的。`goals.csv` 可以直接沿用——
那些數字本來就是你自己訂的。

## 為什麼 `target` 取區間下界

週投遞原本寫「15–20」，這裡取 15。取上界會讓警示過於頻繁，
而目標偏移的價值在「**來不及了**」，不在「不夠拚」。
