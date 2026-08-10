"""共用基礎層：參數載入與資料模型。

這一層刻意不含任何判斷邏輯——`sync`／`compute`／`gate`／`dash` 都會用到它，
若它開始做判斷，模組職責表（`docs/ARCHITECTURE.md`）的分界就會從這裡漏掉。
"""
