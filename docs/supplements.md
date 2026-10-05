# 地址補充層

地址補充層把經審查的外部地址座標加入既有門牌資料，但不直接改寫 `roads/`。匯入程序先建立不可變的補充來源，再由物化程序把固定版本的既有資料與所有補充來源合併到獨立候選目錄。

目前程式與合成資料測試已完成。`taiwan-lvr-geodata` 的真實 TGOS 補充資料尚未匯入，因為每個上游資料來源的公開再散布依據仍待確認。

## 資料結構

```txt
supplements/
├── legacy-base.json               # 固定既有 roads/ 與 road.csv 的版本及雜湊
├── manifest.json                  # 已接受補充來源的索引
└── lvr/
    └── {source-id}/
        ├── addresses.csv          # 舊版相容的 14 欄地址資料
        ├── provenance.jsonl       # 每筆補充資料的來源證據
        ├── quarantine.csv         # 未通過轉換規則的資料
        └── manifest.json          # 匯入結果、筆數及檔案雜湊
```

`addresses.csv` 必須完全使用下列欄位順序：

```txt
FULL_ADDR,COUNTY,TOWN,VILLAGE,NEIGHBORHOOD,ROAD,SECTION,LANE,ALLEY,SUB_ALLEY,TONG,NUMBER,X,Y
```

## 匯入經審查的 LVR 地址補充資料

先在 `taiwan-lvr-geodata` 驗證地址補充快照。確認來源權限及發布審查完成後，在本 repo 執行：

```powershell
python scripts\import_lvr_patch.py `
  --snapshot C:\Code\taiwan-lvr-geodata\data\work\address-patch\snapshots\p4-tgos-20261005-001-patch-v3 `
  --supplements supplements `
  --source-id lvr-p4-tgos-20261005-001
```

匯入器會驗證來源 manifest、每個檔案的大小與 SHA-256、Parquet 合約、`patch_id` 唯一性及 provenance 關係。相同來源重跑會回傳既有結果。相同 `source-id` 若指向不同來源，程序會拒絕覆寫。

## 產生合併候選資料

```powershell
python scripts\materialize_addresses.py `
  --base . `
  --supplements supplements `
  --output data\work\address-candidate
```

物化程序會先驗證 `legacy-base.json` 固定的 `roads/` 與 `road.csv`。程序會在獨立暫存目錄合併資料、重建 `road.csv`，並產生 `materialization-manifest.json`。如果相同 `FULL_ADDR` 的其他欄位不同，程序會停止，且不會留下候選目錄。

候選資料通過抽樣、權限及發布審查後，才可取代公開的 `roads/` 與 `road.csv`。本文件不代表真實補充資料已獲准發布。

## 測試

測試只使用合成資料，不會下載或發布真實地址資料：

```powershell
python -m unittest discover -s tests -v
```
