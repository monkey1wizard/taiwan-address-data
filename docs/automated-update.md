# 政府資料更新

本文件說明更新器目前設定的政府門牌資料來源、本機命令、缺字修正和 GitHub Actions 流程。來源平台的現行規則與資料發布頻率沒有外查，表內只列程式設定。

## 更新器設定

[更新器](../scripts/update_addresses.py)設定 18 個縣市。以下資料集編號、格式和下載頁取自程式設定，不代表本次已確認外部頁面仍可用。除基隆市與臺中市外，程式使用 `data.gov.tw` 或 `data.nat.gov.tw` 的資料集 API。基隆市從市府頁面擷取 CSV 連結。臺中市見表後說明。

| 縣市 | 資料集編號或來源 | 程式讀取格式 | 來源座標 |
| --- | --- | --- | --- |
| 臺北市 | `155472` | CSV | EPSG:3826 |
| 新北市 | `168887` | CSV | EPSG:3826 |
| 桃園市 | `157689` | CSV | EPSG:3826 |
| 臺南市 | `120044` | CSV | EPSG:3826 |
| 高雄市 | `172400` | CSV | EPSG:3826 |
| 新竹縣 | `172380` | XLSX | EPSG:3826 |
| 苗栗縣 | `176511` | CSV | EPSG:3826 |
| 彰化縣 | `170727` | CSV | EPSG:3826 |
| 嘉義縣 | `172873` | CSV | EPSG:3826 |
| 屏東縣 | `170847` | CSV | EPSG:3826 |
| 臺東縣 | `165619` | CSV | EPSG:3826 |
| 花蓮縣 | `175221` | CSV | EPSG:3826 |
| 澎湖縣 | `170852` | CSV | EPSG:3825 |
| 新竹市 | `157547` | CSV，多個分區檔 | EPSG:3826 |
| 雲林縣 | `166201` | XLSX，多個分檔 | EPSG:3826 |
| 金門縣 | `171571` | XLSX | EPSG:3825 |
| 基隆市 | 市府頁面：[基隆市民政處](https://www.klcg.gov.tw/tw/civil/2209-292163.html) | 從頁面擷取 CSV | EPSG:3826 |
| 臺中市 | `169806` | 清單 CSV，再從 Google Drive 下載每月門牌 CSV | EPSG:3826 |

新竹縣改讀 XLSX，因為同一版的 Big5 CSV 把「鄰／巷／弄／號」寫成 `D-`／`G-`／`H-`／`I-`，也把 Big5 以外的字寫成「?」。澎湖縣與金門縣的來源使用 119 度分帶，以 121 度分帶換算會使經度偏東 2 度。測試 `tests/test_update_addresses.py` 鎖定各縣市的分帶，新增縣市若用其他分帶必須同時修改測試。

臺中市的資料集檔案是一張清單，列出每月的門牌 CSV，檔案放在 Google Drive。更新器從清單挑出最新一筆「臺中市1xx年x月GIS門牌號碼」，先取得 Google Drive 的確認頁讀出 `uuid`，再向 `drive.usercontent.google.com/download` 下載。如果拿到的是網頁而不是檔案，臺中市更新失敗，現有路檔不變。是否有新資料仍依資料集 169806 的 `modifiedDate` 判斷。

程式透過 `https://{網域}/api/v2/rest/dataset/{資料集編號}` 取得下載資訊，並在設定的政府平台間嘗試查詢。表內編號不是直接下載網址。

現有路檔涵蓋 22 個縣市。宜蘭縣、南投縣、連江縣與嘉義市有既有路檔，但不在這個更新器的設定中，都是 2016 年匯入的資料。未設定更新器不代表政府沒有提供資料。

## 本機更新

安裝 Python 套件：

```bash
pip install requests pyproj openpyxl
```

`openpyxl` 用於 XLSX 資料。以下第一個命令只列出本機設定，不連線、不寫檔。其餘三個會下載資料並改寫檔案：

```bash
python scripts/update_addresses.py --list
python scripts/update_addresses.py 新北市
python scripts/update_addresses.py --updated-only
python scripts/update_addresses.py --all
```

`--list` 列出更新器設定。指定縣市只處理該縣市。`--all` 依設定逐縣市更新，遇到錯誤會停止。`--updated-only` 先查更新資訊，再逐縣市處理，單一縣市的錯誤會記錄後繼續。

`--updated-only` 將政府 API 的 `modifiedDate` 與 `update_log.csv` 的本機執行日期比較。更新資訊查詢失敗，或縣市沒有可用的更新日期時，該縣市仍會被選取。選取理由包括 `new`、`updated`、`probe-failed` 和 `no-freshness-api`。

如需先看選取結果，可執行 `python scripts/update_addresses.py --updated-only --dry-run`。它不下載地址檔，但會連線查詢更新資訊。`--dry-run` 只在 `--updated-only` 分支生效，不能用來保護指定縣市或 `--all` 的更新。

更新器先下載並處理資料，再執行現有檢查。通過後，新路檔先寫到 `roads/.staging-{縣市代碼}/`。全部寫完後，才把舊路檔移到 `roads/.old-{縣市代碼}/`，再把新檔移入 `roads/`，最後刪除兩個暫存目錄。移動過程失敗時，會刪除已移入的新檔並還原舊檔。替換完成後才更新道路索引及更新紀錄。若程序在移動檔案的那幾秒內被強制終止，仍可能留下部分成果，要依暫存目錄的內容判斷。

替換路檔前的主要檢查如下，這些檢查不能證明政府資料完整或每筆座標正確：

- 新資料處理後為 0 列時停止。
- 舊資料超過 1,000 列，且新資料少於舊資料的 60% 時停止。
- 舊路檔超過 10 個，新資料卻只產生至多 1 個道路群組時停止。
- 新資料超過 1,000 列，且超過 70% 沒有路名時停止。

通過檢查後，更新器才對每個門牌去重，規則見[資料格式](data-format.md)的「一個門牌一列」。檢查使用去重前的列數，`update_log.csv` 記錄去重後的列數。要對現有路檔套用去重與座標位數而不重新下載，可執行 `python scripts/normalize_roads.py 63 65`。這個腳本的 `--all` 只處理 `update_log.csv` 裡的縣市，不含臺中、宜蘭、南投、連江與嘉義市，處理這些縣市要直接列出代碼。

在 Windows 執行時，Git 追蹤但檔名含 Windows 不允許字元的路檔不會出現在工作樹。更新器刪不到這類舊檔，重建的 `road.csv` 也會少列。目前追蹤的路檔已沒有這類檔名。日後若再出現，要以 `git rm --cached --sparse` 移除舊檔，並以 Git 追蹤的檔案清單重建 `road.csv`。

座標固定寫成小數 9 位，所以 Windows 與 Linux 重跑同一份來源會得到相同的座標文字。

## 缺字修正

更新器在查村里代碼前套用 `char_fixes.csv` 與 `rare_chars.csv`，欄位規則見[資料格式](data-format.md)。處理後會列出套用數、刪除列數，以及仍含「?」「■」「？」或私用區字元的欄位數。殘留只會警告，不會停止更新。

新增對照時，先產生候選再人工審查。候選不會自動寫入對照表：

```bash
python scripts/char_fix_candidates.py 彰化縣 屏東縣 --out data/work/charfix
python scripts/char_fix_candidates.py 彰化縣 --legacy --out data/work/charfix
```

第一個命令下載來源，並與國土測繪中心村里清單、戶政司路名清單比對。只有同鄉鎮唯一相符時才標為 `unique`。「?」位置的字必須不在 Big5，「■」與「？」位置只排除私用區字元。第二個命令改以 2016 年路檔同位置比對，證據較弱，只在擁有者接受時使用。

不經過更新器的宜蘭縣與南投縣，以下列命令把對照表直接套用到路檔：

```bash
python scripts/fix_static_roads.py 10002 10008
```

此腳本從 Git `HEAD` 讀取路檔，依修正後的路名重新分檔，並移除舊檔。執行後要重建 `road.csv`。

修改對照表後先執行測試，通過後才提交：

```bash
python -m unittest discover -s tests
```

`tests/test_supplements.py` 需要 `pyarrow`。

## GitHub Actions

設定位於 [monthly-update.yml](../.github/workflows/monthly-update.yml) 與 [keepalive.yml](../.github/workflows/keepalive.yml)。每月更新 workflow 設定在每月 5 日執行，並可手動觸發。排程是否準時執行依賴 GitHub Actions。本文件沒有查證 GitHub 目前的排程政策或執行限制。

workflow 先執行 `--updated-only --dry-run`，記下預計更新的縣市。若手動執行時勾選 `dry_run`，會跳過正式更新及提交，但仍會嘗試建立摘要 Issue。沒有勾選時，才會執行 `--updated-only`。正式更新會重新查詢，因此可能與前一步列出的縣市不同。

更新步驟設為 `continue-on-error`，讓摘要 Issue 仍會建立。只要有一個縣市失敗，更新器就以非零結束碼退出，workflow 不檢查差異也不提交，已完成縣市的成果一併捨棄，下次執行再重試。最後一步會使工作標示失敗。

通知內容中的 `PUSHED` 取自是否偵測到檔案差異，不是 push 成功證明。更新器失敗時沒有檢查差異，摘要顯示為 n/a。推送失敗時 workflow 會嘗試抓取遠端提交、rebase 後重推，最多嘗試推送 3 次。rebase 若失敗會中止，需要檢查失敗原因。

workflow 也會嘗試建立並關閉一筆 Issue 作為摘要。這不保證使用者會收到電子郵件。每週保活設定使用第三方 Action，設定來源見 YAML。本次未查證其外部行為或 GitHub 平台規則。

## 失敗時

- 查閱 Actions 執行記錄中的選取理由、更新器輸出及最後失敗步驟。
- 若更新器失敗，先確認路檔、`road.csv`、`update_log.csv` 是否只完成部分更新，再決定如何處理。
- 若推送失敗，確認遠端分支狀態後再安排重跑或人工處理。不要假設失敗縣市以外的檔案沒有變更。

2026-10-13 在本機重跑過多個縣市，命令、雜湊與結果見各份[執行紀錄](records/)。GitHub workflow、通知與發布沒有在本機執行。已知問題見[已知問題](known-issues.md)。
