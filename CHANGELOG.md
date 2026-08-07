# Changelog

本檔格式依 [Keep a Changelog](https://keepachangelog.com/)，版本依 [Semantic Versioning](https://semver.org/)。

## [Unreleased]

### Added
- M1：`sync` Notion 接入與每日 snapshot 差分
- M1：`compute` pace ratio／required run rate／SPI／CPI
- M1：決策卡輸出

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
