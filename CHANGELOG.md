# Changelog

本檔格式依 [Keep a Changelog](https://keepachangelog.com/)，版本依 [Semantic Versioning](https://semver.org/)。

## [Unreleased]

### Added
- M2：`tasks` 待辦接入、三種風險原型、與目標的雙向連結
- M2：D1 季節殘差、D3 比率型偵測器、CPI（需要投入時數的 parser）
- M3：trust ledger 回寫先驗與門檻、90 天回放、`interrupt_only` 損失尺度的正式校準

## [0.2.0] - 2026-08-10

### Added
- **M1 目標偏移**：`sync` → `compute` → `gate` → `dash` 全線打通，
  入口 `python3 -m compute.report`，輸出決策卡 ＋ 每日摘要（純文字）
- `core/` — 參數載入（唯讀、取不到就爆）與資料模型。**新增的第六個模組**（← `AG-008`）
- `sync/` — CSV 載入、每日快照差分還原流量（gap／負差分／基準快照皆標記）、
  Notion 抓取器（獨立執行，不在報表路徑上）、關卡 0 契約檢查與關卡 1 資料體檢
- `compute/` — pace ratio／required rate／run rate／SPI／歷史最佳 P90／靜默間隔；
  bootstrap Monte Carlo；偵測器 **D2 計數、D4 pacing、D5 變點（EWMA／CUSUM／Western Electric）**，
  對應四個觸發：可行性翻轉、趨勢反轉、緩衝耗盡、靜默期
- `gate/` — V 公式（含可救性）、三個不該警示的時刻、同目標與父子去重、配額排擠、冷啟動分級
- `dash/` — 決策卡（含三個選項與「不做」的價格）、每日摘要（被擋掉的與被擋原因）
- `config/params.yaml` — 新增 `gate.interrupt_only_loss_units`／`post_milestone_*`／`overshoot_ratio`、
  `drift.infeasible_multiple`／`pressure_consecutive_days`、`detector.best_rate_window_days`／
  `count.recent_days`／`count.alpha`、`forecast.random_seed`／`extension_horizon_days`、
  `cold_start.min_points.historical_best`、`sync.notion.progress_map`
- `ruff.toml` — 行寬 100、double quotes、first-party import 分組

### Changed
- **D1 與 D3 由 M1 退回 M2**（← `AG-008`）：D1 需 `statsmodels`（M2 依賴）且 42 天門檻套在
  31 天的月目標上永遠在校準中；D3 需漏斗分母，而 `progress.csv` 沒有分母欄位
- **契約檢查 `deadline > start_date` 改為 `deadline ≥ start_date`**：日目標起訖本來同一天，
  原規則會擋掉 M0 自己附的 `apply_daily` 範例
- **資料量門檻的作用範圍**：只擋「該偵測器能不能用」，不擋「這則能不能發」。
  Monte Carlo 不足時卡片照發，但三個選項的機率一律標「—」並寫明還差幾天
- `data/examples/progress.csv` 擴充為整月資料，讓回放跑得出可行性翻轉與可救性歸零兩條路徑

### Fixed
- 快照差分的第一筆不再被當成流量（那是存量，會變成一個假的巨大增量）

## [0.1.1] - 2026-08-07

### Changed
- **專案更名** `alertgate` → `goal-drift-alert`（← `AG-007`）：以現有功能命名而非機制命名。
  不用 `goal-alert` 是因為它會被讀成到期提醒 App，而本專案明確不做提醒功能

## [0.1.0] - 2026-08-07

### Added
- **M0 骨架**：專案立項（← 主線 `D-020`），文件與參數先行、不寫實作程式碼
- `docs/ARCHITECTURE.md` — 系統架構圖、五個模組職責、八步資料流、六個偵測器型錄、
  待辦與目標的雙向連結、技術棧與五個里程碑
- `docs/DATA-CONTRACT.md` — `goals`／`progress`／`tasks`／`snapshots` 四張表的 schema、
  Notion「職缺搜集情況」對應與已知缺口的三種補法、資料品質檢查清單
- `docs/DECISION-FLOW.md` — 核心公式（含**可救性**項）、四個觸發與三個不該警示的時刻、
  待辦與目標的三條連結規則、五道關卡、信任帳本三顆按鈕
- `docs/DASHBOARD.md` — 八個視圖的資訊架構，主視圖為 CCPM fever chart
- `config/params.yaml` — 所有門檻的唯一真相，每個參數附「為什麼是這個值」
- `data/examples/` — `goals.csv`／`progress.csv` 範例，目標數字取自既有 sprint 規劃
- `prepare.md` — AG-000～AG-006 七筆決策
