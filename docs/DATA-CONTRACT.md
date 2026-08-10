# 資料契約

> 本檔是所有資料結構的正本。範例檔在 `data/examples/`。
> **真實資料一律不進版控**（repo 是 public，內容是個人求職與待辦記錄）。

## 設計原則

1. **記增量不記累積**（`progress.delta`）——補登、修正、回填都只要加一列，不用改舊資料
2. **記事件不記狀態**——狀態可以從事件推出來，反過來不行。這是整個專案的地基
3. **三欄能解決的不要用五欄**——欄位每多一個，人工補登的機率就低一分

---

## `goals.csv`

一個目標＝一列。支援月／週／日巢狀。

| 欄位 | 型別 | 必填 | 說明 |
|------|------|:---:|------|
| `goal_id` | text | ✓ | 唯一鍵，慣例 `<動作>_<週期>`，如 `apply_202608` |
| `name` | text | ✓ | 顯示名稱 |
| `type` | enum | ✓ | `cumulative`／`rate`／`streak`。**M1 只實作 `cumulative`** |
| `target` | number | ✓ | 目標數字 |
| `start_date` | date | ✓ | ISO `YYYY-MM-DD` |
| `deadline` | date | ✓ | 同上 |
| `unit_value` | number | | 一單位值多少。**留空即走 `interrupt_only`**（無金額場景） |
| `loss_kind` | enum | | `linear_excess`／`opportunity`／`at_risk_stock`／`deadline_miss`／`interrupt_only`。留空時由 `type` 推定 |
| `parent_id` | text | | 上層目標的 `goal_id`。月 → 週 → 日的巢狀靠這欄 |
| `owner` | text | | 個人版固定 `self`，保留給多人版 |

### 從現有 Notion sprint 直接建出來的基線

以下數字全部來自「sprint & action (short-term)」，不是新訂的：

| goal_id | name | target | 週期 | parent_id |
|---|---|---|---|---|
| `apply_202608` | 8 月投遞職缺 | 60 | 月 | — |
| `apply_w32` | 第 32 週投遞 | 15 | 週 | `apply_202608` |
| `apply_daily` | 每日投遞 | 1 | 日 | `apply_w32` |
| `collect_daily` | 每日找職缺 | 4 | 日 | — |
| `leetcode_202608` | 8 月刷題 | 100 | 月 | — |
| `article_202608` | ina 文章更新 | 3 | 月 | — |

> **`target` 取區間的下界**（週投遞寫 15–20 → 取 15）。取上界會讓警示過於頻繁，
> 而目標偏移的價值在「來不及了」而不是「不夠拚」。

---

## `progress.csv`

三欄。每天每個目標一列（沒有進展的日子可以不寫，計算層補 0）。

| 欄位 | 型別 | 必填 | 說明 |
|------|------|:---:|------|
| `date` | date | ✓ | 該增量發生的日期（依 `day_boundary_hour` 歸日） |
| `goal_id` | text | ✓ | |
| `delta` | number | ✓ | **當天增量，不是累積值** |
| `source` | enum | | `notion_diff`／`manual`／`backfill`。用來標記可信度 |

`source` 存在的理由：snapshot 差分還原出來的量與手動補登的量，可信度不同。
漏跑一天後的第一筆差分會把兩天的量記在一起，必須標記出來，否則 run rate 會出現假峰值。

---

## `tasks.csv`（M2）

待辦風險用。**與目標透過 `goal_id` 連結**——這是雙向連結的結構基礎。

| 欄位 | 型別 | 必填 | 說明 |
|------|------|:---:|------|
| `task_id` | text | ✓ | |
| `title` | text | ✓ | |
| `goal_id` | text | | 掛在哪個目標下。留空＝獨立待辦 |
| `created_at` | datetime | ✓ | 用來算 age |
| `due_date` | date | | 有值＝懸崖型候選 |
| `closed_at` | datetime | | 有值＝已結束（完成或放棄） |
| `outcome` | enum | | `done`／`dropped`／`expired` |
| `deferral_count` | int | ✓ | **改期次數，預設 0**。假設中最強的單一預測因子 |
| `last_touched_at` | datetime | | 上次編輯／移動時間 |
| `category` | text | | 用於同類比較（age 百分位要分類別算） |

### 三種風險原型的判定（由計算層推導，不存欄位）

| 原型 | 判定 | 正確動作 |
|------|------|---------|
| **懸崖型 Cliff** | 有 `due_date` | 立刻做第一步 |
| **漂移型 Drift** | 無 `due_date` 但有 `goal_id` | 調目標或加碼 |
| **腐爛型 Rot** | 無 `due_date` 無 `goal_id`，且 age > `task.rot_days` | **提議刪除，不警示** |

---

## `snapshots/YYYY-MM-DD.csv`

每日 23:00 對 Notion 的狀態快照。存在的唯一理由是**還原流量**。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `snapshot_date` | date | |
| `data_source` | text | 來源資料庫識別 |
| `dimension` | text | 維度名，如 `狀態`／`公司`／`求職管道` |
| `value` | text | 維度值，如 `已投遞` |
| `count` | int | 當下該組合的筆數 |

流量還原：`delta(t) = count(t) − count(t-1)`，負數視為修正並記入 `sync` 日誌。

---

## Notion 對應

### 「職缺搜集情況」資料庫

`collection://3b3e6df2-9bcf-8059-b90e-000bba8351f7`

| Notion 欄位 | 型別 | 對應到 |
|------------|------|-------|
| `狀態` | status：**觀望中 → 已投遞 → 有回覆** | ★ 三階漏斗。`已投遞` 計數 → `apply_*` 的 progress；`有回覆` → 漏斗轉換率 |
| `createdTime` | 系統自動 | 可靠的「收集日」，用於 `collect_daily` |
| `Date` | date | **語意待確認**：收集日還是投遞日 |
| `公司`／`求職管道`／`關聯職位` | select／multi_select | 歸因維度 |
| `評估（自評／irene／adam）` | select 四級 | 分層維度，可看「值得優先投遞」那層的達成率 |

### 已知缺口與補法

> **狀態變更沒有時間戳。** 存量拿得到（現在有幾筆已投遞），流量拿不到（今天投了幾筆）——
> 而目標偏移需要的正是流量。

| 補法 | 成本 | 效果 | 採用 |
|------|------|------|:---:|
| a. 在 Notion 加「投遞日期」date 欄位 | 30 秒 | 從加的那天起資料完整、精確 | ✅ 建議 |
| b. 拿現有 `Date` 欄當投遞日 | 0 | 需先確認語意 | 待確認 |
| c. 每日 snapshot 差分 | 一支 script | 還原流量，且**現有資料立刻可用** | ✅ 採用 |

**a + c 並行**：a 讓未來精確，c 讓現在就有序列且能覆蓋 a 上線前的空窗。
兩者同時有值時以 a 為準，差異記入 `sync` 日誌當資料品質指標。

### 「week task tracker」（M2）

每日時間區段是純文字（`11:39-16:39 claude 開發`），需要 parser 才能轉成投入時數。
排 M2，因為它產出的是「投入」不是「產出」，而目標偏移先看產出。

---

## 資料品質檢查（每次 sync 後執行）

| 檢查 | 不過時的行為 |
|------|------------|
| 日期連續性：snapshot 有無斷天 | 標記受影響的 delta，`source` 記為 `notion_diff_gap` |
| `delta` 為負 | 記入日誌，不寫入 progress（視為 Notion 端的修正或刪除） |
| `goal_id` 在 `goals.csv` 存在 | 拒絕寫入並報錯 |
| `deadline ≥ start_date` | 拒絕建立目標。**取 `≥` 不是 `>`**：日目標的起訖本來就同一天，用 `>` 會把 `apply_daily` 這類目標全擋掉（← `prepare.md` AG-008） |
| 累積量 > target 的 150% | 提示「目標可能訂太低」，不是錯誤 |
| 資料量對照 `cold_start.min_points` | 不足者該偵測器停用，dashboard 標「校準中」 |
