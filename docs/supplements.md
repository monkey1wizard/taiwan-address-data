# 地址補充層

來自 `taiwan-lvr-geodata` 的地址補充匯入目前暫停，不屬於政府資料更新步驟。既有程式與 `supplements/` 保留，本頁不提供可直接執行的真實資料匯入命令。

截至 2026-10-14，本機 `supplements/manifest.json` 的 `sources` 為空。`legacy-base.json` 固定的是提交 `02887978ef19c1067e339787bae976a72d4723af`，其中 `license_status` 為 `pending_upstream_evidence`。這些設定不能證明目前工作樹可作為補充資料的基底，也不能證明資料已獲准公開。

## 保留的用途與結構

匯入器原先用來建立不可覆寫的補充來源。物化程序則將固定版本的基底與補充來源合併到獨立候選目錄，不直接改寫公開的 `roads/`。

| 檔案 | 用途 |
| --- | --- |
| `supplements/legacy-base.json` | 記錄固定基底的提交、路檔數與雜湊。 |
| `supplements/manifest.json` | 記錄已接受的補充來源。 |
| `supplements/lvr/{source-id}/addresses.csv` | 保存轉換後的地址資料。 |
| `supplements/lvr/{source-id}/provenance.jsonl` | 保存逐筆來源證據。 |
| `supplements/lvr/{source-id}/quarantine.csv` | 保存未通過轉換規則的資料。 |
| `supplements/lvr/{source-id}/manifest.json` | 記錄匯入結果、筆數與檔案雜湊。 |

上表的來源子目錄是保留的設計，不表示已有真實來源。地址 CSV 的 14 欄順序以[資料格式](data-format.md#路檔欄位)為準。

原說明記載，匯入器會驗證來源清單、大小、SHA-256、Parquet 契約、`patch_id` 唯一性及來源證據關係。同一 `source-id` 指向不同來源時拒絕覆寫，匯入與物化共用寫入鎖。

物化程序原設計會先核對固定基底，再合併並建立道路索引與 `materialization-manifest.json`。相同 `FULL_ADDR` 的其他欄位有衝突時停止。上述行為保留供重新啟用時核對，本次沒有執行匯入、物化或測試。

## 重新啟用前的條件

1. 確認擁有者要重新啟用的範圍，以及當時有效的上游輸入契約。
2. 核對每個來源的公開再散布依據，不能以程式或合成資料測試完成代替來源權限。
3. 重新選定並核對基底版本、輸入清冊與雜湊，不直接沿用舊路徑或舊快照。
4. 先驗證合成資料，再驗證真實候選資料。記錄衝突、拒絕項目與抽樣結果。
5. 候選資料完成權限與發布審查後，才決定是否替換公開路檔與道路索引。

## 歷史操作說明

重寫前的[地址補充層原文](archive/supplements-before-2026-10-14.md)保留舊目錄結構、快照路徑、命令與測試說明。它是歷史資料，不是目前可用來源的證明，也不是執行或發布授權。
