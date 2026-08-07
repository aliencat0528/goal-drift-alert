# 範例資料

**這是 repo 裡唯一進版控的資料。** 真實資料一律 gitignored（← `AG-000`）。

| 檔案 | 用途 |
|------|------|
| `goals.csv` | 六個目標，數字取自既有 sprint 規劃（月投遞 60／週 15／日 1／找職缺 4／刷題 100／文章 3） |
| `progress.csv` | 一週的假進度，用來驗證計算層跑得起來 |

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
