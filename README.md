# 臺灣門牌地址查詢

本專案提供以道路分檔的政府門牌座標資料，供程式依地址查詢座標。資料有縣市代碼、道路及門牌欄位，詳細格式見[資料格式](docs/data-format.md)。程式碼採 BSD License。

## 使用

`roads/` 存放道路 CSV，`road.csv` 是查詢用道路索引。可直接下載本專案檔案，供自己的程式離線讀取。欄位說明見[資料格式](docs/data-format.md)。

既有查詢頁面使用 `address.html`、`address.js` 和行政區 CSV。在專案目錄執行 `python -m http.server` 後，開啟 [本機查詢頁面](http://localhost:8000/address.html)。頁面會讀取本機 CSV，但 jQuery 和 Bootstrap 仍從外部網站載入，需要網路。

政府資料公布日期與本專案執行下載的日期不同。`update_log.csv` 的 `last_updated` 是本機執行日期，不能代表政府資料產製日期。自動更新支援範圍與操作限制見[政府資料更新](docs/automated-update.md)。

## 資料來源與限制

資料來自政府開放資料集。目前路檔涵蓋 22 個縣市，更新器支援其中 17 個縣市。臺中市、宜蘭縣、南投縣、連江縣與嘉義市的路檔不經過更新器。其中宜蘭縣、南投縣與臺中市的缺字，以 `scripts/fix_static_roads.py` 直接修正路檔。支援清單見[政府資料更新](docs/automated-update.md)。

輸出 `X` 是經度，`Y` 是緯度，固定為小數 9 位。更新器預設來源座標為 EPSG:3826。澎湖縣與金門縣的來源使用 119 度分帶，設定為 EPSG:3825。

政府匯出檔會把系統無法儲存的字寫成「?」「■」或「？」。本專案以 `char_fixes.csv` 還原這些字，並以 `rare_chars.csv` 統一罕用字的字碼。輸出使用標準 Unicode，部分字在擴充 B 區，例如「𨻶」，有些字型無法顯示。規則見[資料格式](docs/data-format.md)。

更新會重建縣市路檔。新路檔先寫到暫存目錄，全部寫完才替換舊檔，替換失敗時會還原舊檔。檢查與限制見政府資料更新說明。每個門牌只保留一列，規則見[資料格式](docs/data-format.md)。目前限制請先看[已知問題](docs/known-issues.md)。

`taiwan-lvr-geodata` 寫入的更新暫不處理。既有 `supplements/` 與[相關文件](docs/supplements.md)先保留，不屬於目前政府資料更新步驟。

## 文件

- [資料格式](docs/data-format.md)
- [政府資料更新](docs/automated-update.md)
- [已知問題](docs/known-issues.md)
- [文件整理紀錄](docs/records/2026-10-12-文件整理.md)
- [新竹、澎湖、金門重跑紀錄](docs/records/2026-10-13-新竹澎湖金門重跑.md)
- [缺字還原紀錄](docs/records/2026-10-13-缺字還原.md)
- [全縣市缺字紀錄](docs/records/2026-10-13-全縣市缺字.md)
- [門牌與村里紀錄](docs/records/2026-10-14-門牌與村里.md)
