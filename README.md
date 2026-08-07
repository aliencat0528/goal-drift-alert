# alertgate - 把警示當預算來管的個人風險決策系統

當你的目標開始偏移、待辦開始腐爛時，它只在「還來得及救」的那一刻說話——而且每天最多三次。

![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Status](https://img.shields.io/badge/status-M0%20骨架-lightgrey.svg)

## 為什麼做這個

監控工具的產業現況是：SOC 團隊每天收到約 3,832 則警示、**62% 被忽略**，其中約 83% 是假警報；
而 Monte Carlo、Anomalo 這類資料可觀測性平台都需要 **4–8 週人工調校**，訊噪比才會轉正。

所有人都在優化「偵測準確率」，但真正的失效發生在**通知之後**。

> **警示不是通知，是一次對人類注意力的支出。**

所以這個系統回答的不是「這個數字奇怪嗎」，而是——**這件事值不值得現在打斷你、
打斷了你該做什麼、不做會賠多少。**

## 功能特色

- **期望損失閘門** — 用「不處理會損失多少」決定要不要說話，不用統計顯著性
- **警示預算** — 每天固定配額，警示之間互相排擠；擠不進去的沉進摘要，不丟掉
- **可救性判定** — 已經數學上做不到的目標**不再提醒你努力**，改成建議調整目標
- **目標偏移偵測** — pace ratio、required run rate、EVM 的 SPI／CPI、EWMA 控制圖
- **待辦風險分型** — 懸崖／漂移／腐爛三種原型，各有不同的正確動作（腐爛型的正確動作是**提議刪除**）
- **待辦 ↔ 目標雙向連結** — 待辦延遲會推高目標的 required rate；目標來不及時指出是哪幾件卡住
- **信任帳本** — 三顆按鈕（已處理／不用理／太晚了），**沒有「已讀」**，因為已讀學不到東西
- **決策卡而非警示** — 症狀、金額、責任、信心、三個選項，**「不做」也標價**

## 快速開始

> M0 階段只有文件與參數骨架，`sync`／`compute` 尚未實作。以下是 M1 完成後的路徑。

```bash
git clone https://github.com/aliencat0528/alertgate.git && cd alertgate
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp data/examples/goals.csv data/goals.csv     # 用範例起步，再改成自己的目標
cp data/examples/progress.csv data/progress.csv

python3 -m compute.report                      # 預期：out/dashboard.html 產生
open out/dashboard.html
```

## 使用方式

### 1. 定義目標

編輯 `data/goals.csv`。一個目標一列，支援月 → 週 → 日巢狀（用 `parent_id`）。
欄位說明見 [`docs/DATA-CONTRACT.md`](docs/DATA-CONTRACT.md)。

### 2. 餵進度

三欄就夠：`date, goal_id, delta`。**delta 是當天增量，不是累積值**——
補登、修正、回填都只要加一列，不用改舊資料。

三種來源：手動補登 CSV、Notion 每日快照差分、未來的 API 接入。

### 3. 讀決策卡

```
【目標】8 月投遞 40 份職缺 · 已過 22 天（71%）
【進度】已投 17 份（43%）· pace ratio = 0.60 · SPI = 0.60
【速率】目前 0.77 份/天；required 2.56 份/天
        你的歷史最佳（P90）是 1.9 份/天
【判定】★ 可行性翻轉 — required 已超過你做過的最快速度
【選項】A 改目標為 30 份 — 需 1.44/天，達成機率 71%
        B 維持 40 份 — 需連續 9 天達到歷史最佳的 135%，機率 8%
        C 延長到 9/10 — 需 1.15/天，機率 84%
```

那句「**required 已超過你做過的最快速度**」是核心——它不是說你不夠努力，
是說這個目標在數學上已經超出你的能力邊界，**而這是只有你自己的歷史資料才講得出來的話**。

### 4. 回饋

每則警示按一顆按鈕。**不用理** 會讓門檻自動升高，連續三次即自動靜音該規則——
這是市面工具那「4–8 週人工調校」的自動化版本，而且訊號來自你的行為而非設定檔。

## 專案結構

```
alertgate/
├── config/params.yaml     # 所有門檻的唯一真相，程式碼不得硬編碼
├── data/                  # 真實資料全部 gitignored，只有 examples/ 進版控
├── docs/
│   ├── ARCHITECTURE.md    # 架構圖、模組職責、資料流、六個偵測器
│   ├── DATA-CONTRACT.md   # schema、Notion 對應、資料品質檢查
│   ├── DECISION-FLOW.md   # 決策公式、四個觸發、五道關卡、信任帳本
│   └── DASHBOARD.md       # 視覺化資訊架構與八個視圖
├── sync/    compute/    gate/    dash/     # M1 起實作
└── out/                   # 產出的 HTML，gitignored
```

模組職責與資料流見 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

## 開發階段

| 階段 | 交付 | 出口條件（不過就停） |
|------|------|--------------------|
| **M0** ✅ | 文件、參數、schema、範例資料 | 本次 |
| **M1** | sync ＋ pace ratio／required rate／SPI ＋ 決策卡 | 跑得出真實數字，且**至少一則讓你覺得「幸好它說了」** |
| **M2** | 待辦三原型、與目標雙向連結 | 可行性翻轉能指出是哪幾件待辦卡住 |
| **M3** | 期望損失、配額排擠、信任帳本、回放 | 回放 90 天，三條門檻策略的挽回曲線分得開 |
| **M4** | Dashboard 全套視圖 | 沒看過的人 3 分鐘內講得出差異化 |
| **M5** | 指標契約、場景模板、LINE 通道 | **前置是 M3 通過**——沒有被證明有效的場景就開放泛用只會得到空殼 |

## 測試

M1 階段沒有單元測試是刻意的——這個階段的正確性靠**回放**驗證
（用歷史資料跑一次、人看警示對不對），不是靠斷言。理由見
[`docs/DECISION-FLOW.md`](docs/DECISION-FLOW.md) 的「五道關卡」。

```bash
ruff check .
python3 -m py_compile $(git ls-files '*.py')
python3 -c "import yaml;yaml.safe_load(open('config/params.yaml'))"
```

## 邊界

- **repo public，資料不進版控。** 這裡會存個人求職記錄與待辦內容，一筆真實資料都不進 repo
- **不呼叫任何外部 LLM 或分析服務**，全部計算在本機
- **v1 不用任何 ML 模型。** 監控場景裡模型越強，越容易把異常學成正常
- **不自動執行任何動作**，系統只產決策卡，改目標／改期／放棄一律由人做
- **不做提醒功能**，只在風險跨過門檻時說話

## 版本歷史

### v0.1.0 (2026-08-07)

- **M0 骨架** — 架構、決策流程、資料契約、Dashboard 設計四份文件與參數總表

## 授權

MIT License
