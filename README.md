# goal-drift-alert - 把警示當預算來管的個人風險決策系統

當你的目標開始偏移、待辦開始腐爛時，它只在「還來得及救」的那一刻說話——而且每天最多三次。

![Version](https://img.shields.io/badge/version-0.2.0-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Status](https://img.shields.io/badge/status-M1%20目標偏移-blue.svg)

## 為什麼做這個

監控工具的產業現況是：SOC 團隊每天收到約 3,832 則警示、**62% 被忽略**，其中約 83% 是假警報；
而 Monte Carlo、Anomalo 這類資料可觀測性平台都需要 **4–8 週人工調校**，訊噪比才會轉正。

所有人都在優化「偵測準確率」，但真正的失效發生在**通知之後**。

> **警示不是通知，是一次對人類注意力的支出。**

所以這個系統回答的不是「這個數字奇怪嗎」，而是——**這件事值不值得現在打斷你、
打斷了你該做什麼、不做會賠多少。**

## 功能特色

已可用（v0.2.0 / M1）：

- **期望損失閘門** — 用「不處理會損失多少」決定要不要說話，不用統計顯著性
- **警示預算** — 每天固定配額，警示之間互相排擠；擠不進去的沉進摘要，不丟掉
- **可救性判定** — 已經數學上做不到的目標**不再提醒你努力**，改成建議調整目標
- **目標偏移偵測** — pace ratio、required run rate、EVM 的 SPI、EWMA／CUSUM 控制圖
- **決策卡而非警示** — 症狀、缺口、信心、三個選項，**「不做」也標價**
- **冷啟動分級** — 觀察期只收不發 → 影子模式 → 分級發布，讓誤報在便宜的時候暴露

還沒做（見開發階段）：

- **待辦風險分型**（M2）— 懸崖／漂移／腐爛三種原型，腐爛型的正確動作是**提議刪除**
- **待辦 ↔ 目標雙向連結**（M2）— 待辦延遲推高目標 required rate；目標來不及時指出哪幾件卡住
- **信任帳本**（M3）— 三顆按鈕（已處理／不用理／太晚了），**沒有「已讀」**，因為已讀學不到東西
- **CPI**（M2）— 需要「投入時數」，而它在 Notion 裡還是純文字的時間區段，要 parser

## 快速開始

```bash
git clone https://github.com/aliencat0528/goal-drift-alert.git && cd goal-drift-alert
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 先拿範例資料跑一次，看它會說什麼（不用先準備自己的資料）
python3 -m compute.report --data-dir data/examples --as-of 2026-08-24 --no-write

# 換成自己的
cp data/examples/goals.csv data/goals.csv     # 目標可以直接沿用，數字本來就是你訂的
cp data/examples/progress.csv data/progress.csv   # 這份要清空改成自己的
python3 -m compute.report                      # 決策卡印在終端機，同時寫進 out/decision-cards.md
```

M1 的輸出是**決策卡與每日摘要**（純文字）。Dashboard 的 HTML 與 fever chart 排在 M4；
`--explain` 會附上 V 的完整推導，`--as-of <日期>` 是回放（只用那天以前的資料重跑）。

## 使用方式

### 1. 定義目標

編輯 `data/goals.csv`。一個目標一列，支援月 → 週 → 日巢狀（用 `parent_id`）。
欄位說明見 [`docs/DATA-CONTRACT.md`](docs/DATA-CONTRACT.md)。

### 2. 餵進度

三欄就夠：`date, goal_id, delta`。**delta 是當天增量，不是累積值**——
補登、修正、回填都只要加一列，不用改舊資料。

三種來源：手動補登 CSV、Notion 每日快照差分、未來的 API 接入。

```bash
# Notion 快照（Notion 的 status 變更沒有時間戳，靠每日快照的差分還原流量）
NOTION_TOKEN=secret_xxx python3 -m sync.notion --data-dir data     # 建議掛 cron，每天 23:00
```

**這支不在報表路徑上**：報表要能在沒有網路、沒有 token 的情況下用既有快照跑完。
漏跑一天的第一筆差分會把兩天的量記在一起，`source` 會標成 `notion_diff_gap` 並在摘要說明。

### 3. 讀決策卡

以下是拿 `data/examples` 跑 `--as-of 2026-08-24` 的**實際輸出**（節錄）：

```
■ 2026-08-24｜影子模式（寫進報表但不推播）｜系統第 24 天｜今日配額 3｜發出 1 則

【目標】8 月投遞職缺 · 已過 24 天（77%） · 剩 8 天
【進度】36／60（60%） · pace ratio = 0.78 · SPI = 0.78
【速率】目前 1.29／天；required 3.00／天
        你的歷史最佳（P90）是 2.29／天
【判定】★ 可行性翻轉 — required 已超過你做過的最快速度
【證據】required 3.00／天 > 歷史最佳 P90 2.29／天（131%）
        首次超過是 2026-08-22，已持續 3 天
        就算從今天起維持歷史最佳，也要 11 天，但只剩 8 天
        D2 佐證：近 7 天產出 4，基線期望 13.2（Poisson exact，單尾 p=0.003）
        同時觸發｜緩衝耗盡：壓力係數 2.33 ≥ 黃燈 1.5，已連續 3 天
【選項】A 改目標為 45 — 需 1.12／天，達成機率 —
        B 維持 60 — 需 3.00／天，等於連續 11 天做到歷史最佳的 131%，機率 —
        C 延長到 9/11 — 需 1.26／天，達成機率 —
        三個機率都是「—」：校準中，還差 6 天（已有 24／需要 30）
【不做】目前缺 24，剩 8 天；預測校準中，還差 6 天（已有 24／需要 30）
        這則的期望損失 V = 0.77（打斷成本已扣）
【回饋】[ 已處理 ]  [ 不用理 ]  [ 太晚了 ]　　※ 沒有「已讀」，已讀學不到東西

■ 今日摘要：算出來但沒說的
  · 8 月刷題｜期望損失未過門檻｜V=-0.52｜V = -0.52 未超過門檻 0.00
```

那句「**required 已超過你做過的最快速度**」是核心——它不是說你不夠努力，
是說這個目標在數學上已經超出你的能力邊界。

三個機率都標「—」也是刻意的：Monte Carlo 的資料量還沒到，**這時給一個數字比不給更糟**，
因為它會被當成真的。門檻擋的是「這個偵測器能不能用」，不是「這則能不能發」。

### 4. 回饋（M3）

每則警示按一顆按鈕。**不用理** 會讓門檻自動升高，連續三次即自動靜音該規則——
這是市面工具那「4–8 週人工調校」的自動化版本，而且訊號來自你的行為而非設定檔。
M1 的卡片已經印出三顆按鈕，但**回寫先驗的 trust ledger 排在 M3**。

## 專案結構

```
goal-drift-alert/
├── config/params.yaml     # 所有門檻的唯一真相，程式碼不得硬編碼
├── data/                  # 真實資料全部 gitignored，只有 examples/ 進版控
├── docs/
│   ├── ARCHITECTURE.md    # 架構圖、模組職責、資料流、六個偵測器
│   ├── DATA-CONTRACT.md   # schema、Notion 對應、資料品質檢查
│   ├── DECISION-FLOW.md   # 決策公式、四個觸發、五道關卡、信任帳本
│   └── DASHBOARD.md       # 視覺化資訊架構與八個視圖（M4）
├── core/                  # 參數載入、資料模型（不做任何判斷）
├── sync/                  # CSV／Notion 接入、快照差分、關卡 0／1 檢查
├── compute/               # 指標、預測、偵測器、report 入口
├── gate/                  # V 公式、可救性、三個不該警示的時刻、配額排擠
├── dash/                  # 決策卡、每日摘要
└── out/                   # 產出，gitignored
```

模組職責與資料流見 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

## 開發階段

| 階段 | 交付 | 出口條件（不過就停） |
|------|------|--------------------|
| **M0** ✅ | 文件、參數、schema、範例資料 | 已通過 |
| **M1** ✅ | sync ＋ pace ratio／required rate／SPI ＋ 決策卡 | 程式跑得出數字（範例資料已驗），**「幸好它說了」要接上真實資料才算數** |
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

# 冒煙測試＝回放。兩個日期各驗一條路徑：
python3 -m compute.report --data-dir data/examples --as-of 2026-08-24 --no-write  # 影子模式、預測校準中
python3 -m compute.report --data-dir data/examples --as-of 2026-08-30 --no-write --explain  # 分級發布、可救性歸零
```

## 邊界

- **repo public，資料不進版控。** 這裡會存個人求職記錄與待辦內容，一筆真實資料都不進 repo
- **不呼叫任何外部 LLM 或分析服務**，全部計算在本機
- **v1 不用任何 ML 模型。** 監控場景裡模型越強，越容易把異常學成正常
- **不自動執行任何動作**，系統只產決策卡，改目標／改期／放棄一律由人做
- **不做提醒功能**，只在風險跨過門檻時說話

## 版本歷史

### v0.2.0 (2026-08-10)

- **M1 目標偏移** — `sync` ＋ `compute` ＋ `gate` ＋ `dash` 全線打通，
  `python3 -m compute.report` 產出決策卡與每日摘要
- 偵測器上線 D2／D4／D5；D1 與 D3 退回 M2（理由見 `prepare.md` AG-008）

### v0.1.0 (2026-08-07)

- **M0 骨架** — 架構、決策流程、資料契約、Dashboard 設計四份文件與參數總表

## 授權

MIT License
