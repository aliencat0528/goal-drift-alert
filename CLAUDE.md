> 繼承根目錄共用規則（Claude Code 已自動載入，勿重複讀取 ../CLAUDE.md）

# goal-drift-alert 專案規則

## 技術棧

Python 3.11+。**無框架、無前端建置步驟**——dashboard 是 Python 產生的靜態 HTML ＋ inline SVG。

依賴上限：`pandas`／`numpy`／`PyYAML`／`Jinja2`／`notion-client`。
**新增任何統計或 ML 套件前必須先問**（`scipy` 除外，屬預期內）。
`scikit-learn`／`lifelines`／`MAPIE` 是 M2 才會用到的，M1 不裝。

## Commit scopes

`core`（參數載入與資料模型，不含判斷）／`sync`（資料接入與 Notion 同步）／
`compute`（指標、偵測器、預測）／`gate`（決策閘與警示預算）／
`dash`（dashboard 與決策卡輸出）／`config`（參數）／`data`（schema 與範例資料）／`docs`

## 決策記錄

本專案決策記於 `prepare.md`，編號前綴 **`AG-`**。立項與 M1 範圍見主線 `prepare.md` D-020，
更早的題目探索與可行性判斷見主線 `ideas.md` I-011。

## 驗證方式（M1 無自動化測試）

Commit 前必跑：

```bash
ruff check .
python3 -m py_compile $(git ls-files '*.py')
python3 -c "import yaml;yaml.safe_load(open('config/params.yaml'))"

# 冒煙測試＝回放（範例資料，兩個日期各驗一條路徑）
python3 -m compute.report --data-dir data/examples --as-of 2026-08-24 --no-write
python3 -m compute.report --data-dir data/examples --as-of 2026-08-30 --no-write --explain
```

**M1 沒有單元測試是刻意的**——這個階段的正確性靠「回放」驗證（用歷史資料跑一次、
人看警示對不對），不是靠斷言。等決策閘的行為穩定下來才補測試，見 `docs/DECISION-FLOW.md`
的「五道關卡」。

## 本專案的硬邊界

- **repo public，資料不進版控**。`data/` 除了 `data/examples/` 之外全部 gitignore。
  這裡會存個人求職記錄與待辦內容，**一筆真實資料都不能進 public repo**
- **不呼叫任何外部 LLM／分析服務**。全部計算在本機完成（← 同上，資料邊界）
- **v1 不引入任何 ML 模型**。只有統計 ＋ 一個校準器，理由見 `docs/ARCHITECTURE.md`
  「為什麼六個偵測器就夠」——監控場景裡模型越強，越容易把異常學成正常
- **不自動執行任何動作**。系統只產出決策卡，改目標／改期／放棄一律由人做
- **不做提醒功能**。沒有時間點的提醒＝重造行事曆且更爛；本工具只在「風險跨過門檻」時說話
- **警示配額是硬上限**，不是建議值。擠不進去的沉進每日摘要，不得因為「這則很重要」而破例
