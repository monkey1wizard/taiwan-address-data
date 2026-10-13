# 臺灣門牌地址查詢

本專案提供以道路分檔的政府門牌座標資料，供程式依地址查詢座標。資料有縣市代碼、道路及門牌欄位，詳細格式見[資料格式](docs/data-format.md)。程式碼採 BSD License。

## 使用

`roads/` 存放道路 CSV，`road.csv` 是查詢用道路索引。可直接下載本專案檔案，供自己的程式離線讀取。欄位說明見[資料格式](docs/data-format.md)。

既有查詢頁面使用 `address.html`、`address.js` 和行政區 CSV。在專案目錄執行 `python -m http.server` 後，開啟 [本機查詢頁面](http://localhost:8000/address.html)。頁面會讀取本機 CSV，但 jQuery 和 Bootstrap 仍從外部網站載入，需要網路。本次只核對程式，沒有執行瀏覽器查詢測試。

政府資料公布日期與本專案執行下載的日期不同。`update_log.csv` 的 `last_updated` 是本機執行日期，不能代表政府資料產製日期。自動更新支援範圍與操作限制見[政府資料更新](docs/automated-update.md)。

## 資料來源與限制

資料來自政府開放資料集。目前路檔涵蓋 22 個縣市，更新器支援其中 17 個縣市。支援清單見[政府資料更新](docs/automated-update.md)。更新器預設 EPSG:3826，但不能據此判定每一份政府原始檔的座標系統。輸出 `X` 是經度，`Y` 是緯度。

更新會重建縣市路檔，現有檢查及中斷限制見政府資料更新說明。失敗不保證完整復原，也可能留下部分成果。新竹縣地址格式及澎湖、金門座標的舊稽核結果仍待處理，請先看已知問題。

`taiwan-lvr-geodata` 寫入的更新暫不處理，等該專案成功後再考慮。既有 `supplements/` 與[相關文件](docs/supplements.md)先保留，不屬於目前政府資料更新步驟。

## 文件

- [資料格式](docs/data-format.md)
- [政府資料更新](docs/automated-update.md)
- [已知問題](docs/known-issues.md)
- [本次文件更新企劃](docs/plans/文件更新企劃.md)
- [文件整理紀錄與歷史文件](docs/records/2026-10-12-文件整理.md)
