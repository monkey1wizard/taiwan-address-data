# 自動更新 Runbook（GitHub Actions）

> 這份文件是 `.github/workflows/monthly-update.yml` 的規格書，也是部署後的除錯依據。
> workflow 檔案本身應該跟這份文件保持一致；兩者不一致時，以這份文件記錄的設計意圖為準，
> 回頭修 workflow，而不是反過來改文件遷就 workflow 的現況。
>
> 本 repo 目前沒有任何 CI 設定（無 `.github/`、無 `.gitlab-ci.yml`），這是第一份自動化流程，
> 沒有既有規範可以沿用。

## 0. 一句話總結

每月 5 號，workflow 自動探測 17 個縣市的資料集有沒有比 `update_log.csv` 記錄的日期新，
只重跑真的有更新的縣市，把結果 commit + push 回 `main`。push 衝突會自動重試，另外有一支
獨立的保活 workflow 防止 GitHub 因為 repo 太久沒動靜而停用排程，**日常運作不需要任何人工
介入**。Actions 頁面的 `workflow_dispatch` 只保留給部署後的第一次驗證、或事後想手動補跑時用。
每次執行（不管是排程、手動、dry-run 還是真的跑）都會開一個 GitHub Issue 記錄本次摘要，
立刻關閉。GitHub 會依你帳號的通知設定，把這個 Issue 寄信到你 GitHub 上的信箱。

## 1. 觸發方式

| 觸發 | 設定 | 用途 |
| --- | --- | --- |
| 排程 | `schedule: cron: '0 2 5 * *'`，`timezone: "Asia/Taipei"` | 每月 5 號台北時間 02:00 自動跑 |
| 手動 | `workflow_dispatch`，帶一個 `dry_run` boolean input（預設 `false`） | 部署後第一次驗證、或除錯時手動重跑 |

`timezone` 欄位是 GitHub Actions 內建支援的 IANA 時區字串，直接寫本地時間即可，不用手算
UTC offset。

## 2. 權限與金鑰

| 項目 | 設定 | 說明 |
| --- | --- | --- |
| `permissions.contents` | `write` | 要 push 回**同一個** repo，用內建 `GITHUB_TOKEN` 就夠，不需要另外申請 PAT |
| `permissions.issues` | `write` | 給每次執行摘要開／關 Issue 用，藉此觸發 GitHub 的信件通知，同樣用內建 `GITHUB_TOKEN` |
| git 身分 | `github-actions[bot]` | commit 的 author，不代表任何真人帳號 |
| 其他 `secrets` | 無 | 資料來源（data.gov.tw / data.nat.gov.tw）都是公開 API；通知也是借 GitHub 自己的 Issue 通知機制，不寄外部 SMTP，不需要金鑰 |

## 3. 整體流程

單一 job，逐步往下：

```text
(start) cron 觸發（每月 5 號 02:00 台北）／或手動 workflow_dispatch
  │
  ▼
[ checkout repo（main，完整可寫）]
  │
  ▼
[ setup-python + pip install requests pyproj openpyxl ]
  │
  ▼
[ python scripts/update_addresses.py --updated-only --dry-run | tee selection.txt ]  @counties_needing_update()
  │  印出「這次會跑哪些縣市、為什麼」，同時存成 selection.txt 供最後寄信摘要引用
  ▼
{ workflow_dispatch 的 dry_run input == true？ }
  ├── 是 ──▶ (end >>|) 只看 log，不下載不寫檔，job 結束
  │
  否（含排程觸發，排程沒有 dry_run 這個選項，恆為否）
  ▼
[ python scripts/update_addresses.py --updated-only ]  @run() 逐縣市寫檔
  │  記下這個指令的 exit code，繼續往下走（不因為它失敗就跳過後面的 commit）
  ▼
[ git add -A；檢查是否有變更 ]
  │
  ▼
{ 有檔案變更？ }
  ├── 否 ──▶ (end >>|) 「本次沒有資料變更」，job 正常結束（綠）
  │
  是
  ▼
[ git commit ]
  │
  ▼
[ git push ]  用 GITHUB_TOKEN 推回 main
  │
  ▼
{ push 被拒絕（main 有新 commit）？ }
  ├── 是 ──▶ [ git fetch + git rebase origin/main，重推 ]  最多重試 3 次
  │             │
  │             ▼
  │           { 3 次都失敗？ }
  │             ├── 是 ──▶ (end ×) job 失敗，這是唯一還留給人的情況——
  │             │           代表 rebase 本身衝突，需要人判斷怎麼合併
  │             └── 否 ──▶ (end √)（回到下面「exit code 是失敗？」判斷）
  │
  否
  ▼
[ 開一個 Issue 記錄本次摘要（模式／updater 結果／有沒有 push／selection.txt 內容），
  立刻關閉 ]  @if: always()，不管前面任何步驟成功失敗都會跑到這一步
  │  GitHub 依你帳號的通知設定，把這個 Issue 的建立寄信到你 GitHub 上的信箱
  ▼
{ 上一步 updater 的 exit code 是失敗？ }
  ├── 否 ──▶ (end √) 全部縣市成功，commit 已推上去，摘要信已寄，job 綠燈
  └── 是 ──▶ (end ×) 已成功的縣市照樣推上去了、摘要信也已經寄出，但 job 故意標記
              失敗（紅燈），提醒要去 log（或剛收到的信）找是哪個縣市出包
```

對照 `scripts/update_addresses.py` 目前的設計：`--updated-only` 內部已經把「單一縣市失敗」
跟「整批失敗」拆開了（per-county `try/except`），所以即使某個縣市那個月探測或下載出錯，
其他已經成功的縣市資料還是會寫進 `roads/`、被這個 workflow commit 上去 —— workflow 這層
只需要「commit 完再看 exit code 決定要不要讓 job 標紅」，不需要自己重做一次容錯。

## 4. workflow 骨架（照這份規格寫 `.github/workflows/monthly-update.yml`）

```yaml
name: Monthly address update

on:
  schedule:
    - cron: '0 2 5 * *'
      timezone: "Asia/Taipei"
  workflow_dispatch:
    inputs:
      dry_run:
        description: "只印會更新哪些縣市，不下載不寫檔"
        type: boolean
        default: false

permissions:
  contents: write
  issues: write

concurrency:
  group: monthly-update
  cancel-in-progress: false

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - run: pip install requests pyproj openpyxl

      - name: Dry-run selection (always logged)
        run: python scripts/update_addresses.py --updated-only --dry-run | tee selection.txt

      - name: Run updater
        if: ${{ github.event.inputs.dry_run != 'true' }}
        id: run_update
        continue-on-error: true
        run: python scripts/update_addresses.py --updated-only

      - name: Check for changes
        if: ${{ github.event.inputs.dry_run != 'true' }}
        id: diff
        run: |
          git add -A
          if git diff --cached --quiet; then
            echo "changed=false" >> "$GITHUB_OUTPUT"
          else
            echo "changed=true" >> "$GITHUB_OUTPUT"
          fi

      - name: Commit and push
        if: ${{ github.event.inputs.dry_run != 'true' && steps.diff.outputs.changed == 'true' }}
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git commit -m "chore(data): monthly auto-update $(date -u +%Y-%m-%d)"
          for attempt in 1 2 3; do
            if git push; then
              exit 0
            fi
            echo "push rejected (attempt $attempt/3) — rebasing onto latest main"
            git fetch origin main
            git rebase origin/main
          done
          echo "::error::push still failing after 3 attempts — needs manual conflict resolution"
          exit 1

      - name: Notify by email (via a GitHub Issue, opened + closed each run)
        if: always()
        env:
          GH_TOKEN: ${{ github.token }}
          MODE: ${{ github.event.inputs.dry_run == 'true' && 'dry-run' || 'full run' }}
          UPDATE_OUTCOME: ${{ steps.run_update.outcome }}
          PUSHED: ${{ steps.diff.outputs.changed }}
        run: |
          {
            echo "模式: $MODE"
            echo "updater 執行結果: ${UPDATE_OUTCOME:-(dry-run 跳過)}"
            echo "是否有 commit 推送: ${PUSHED:-n/a}"
            echo
            echo "### 本次選中的縣市"
            echo '```'
            cat selection.txt 2>/dev/null || echo "(無法讀取 selection.txt)"
            echo '```'
          } > issue_body.md
          number=$(gh issue create \
            --title "monthly-update 執行摘要 $(date -u +%Y-%m-%d)（$MODE）" \
            --body-file issue_body.md \
            | grep -oE '[0-9]+$')
          gh issue close "$number"

      - name: Fail the job if the updater reported per-county errors
        if: ${{ github.event.inputs.dry_run != 'true' && steps.run_update.outcome == 'failure' }}
        run: exit 1
```

`if: always()` 讓這一步不管前面任何步驟成功、失敗、還是被跳過都會執行，才能保證「每次都寄」；
它用 `gh issue create` + `gh issue close` 借 GitHub 自己的 Issue 通知機制寄信，不需要另外設定
SMTP 帳密、也不需要存金鑰。**前提是你 GitHub 帳號的 Settings → Notifications 裡，Issues 的
Email 通知要是開著的**——這份文件假設它是預設開啟，沒有另外去停用過。

## 5. 保活 workflow（防止 60 天自動停用）

獨立於 §4 的 `monthly-update.yml`，另外開一支 `.github/workflows/keepalive.yml`，
只做一件事：讓 repo 不會因為太久沒有新 commit 而被 GitHub 停用排程（§7 的限制）。

不採用「每次跑都硬 commit 一個時間戳」的做法——那樣每個月都會留一筆跟地址資料無關的
noise commit。改用 [`efrecon/gh-action-keepalive`](https://github.com/efrecon/gh-action-keepalive)：
它只在**距離上一次 default branch 有 commit 已經超過 41 天**（`timeout` 參數，預設
3542400 秒，抓在 GitHub 60 天門檻的 2/3 左右當緩衝）時，才會真的寫一個活動標記檔
（預設路徑 `.github/.github_liveness.txt`）並 commit。也就是說，只要 `monthly-update.yml`
當月本來就有推資料更新，這支 workflow 該週就不會做任何事；只有連續好幾個月都沒有任何
縣市有新資料時，它才會介入補一個 commit。

```yaml
name: keepalive

on:
  schedule:
    # 每週日 01:27 UTC 檢查一次；41 天保留緩衝，遠早於 60 天門檻
    - cron: '27 1 * * SUN'

permissions:
  contents: write

jobs:
  keepalive:
    runs-on: ubuntu-latest
    steps:
      - uses: efrecon/gh-action-keepalive@main
```

沒有額外參數需要調整——預設的 41 天 timeout 已經比 `monthly-update.yml` 的月排程週期
（30 天上下）留了足夠緩衝，就算連續兩三個月都真的沒有縣市更新，也會在 60 天門檻前
補上一個活動標記，排程不會被停用。

## 6. 失敗排查表

| 症狀 | 位置 | 排查方式 |
| --- | --- | --- |
| job 整個沒有觸發 | Actions 頁籤看不到任何 run | 先查 §7 的 60 天自動停用；去 Settings → Actions 確認 workflow 是 enabled |
| `Run updater` 步驟紅色，但後面 `Commit and push` 是綠色 | log 裡搜尋 `!! <縣市> aborted` 或 `!! <縣市> failed` | 只有列出的縣市那個月出包，其他縣市的資料已經正常 commit 上去了，不用整批重跑 |
| `Dry-run selection` 印出某縣市是 `probe-failed` 而不是 `no-freshness-api` | 同一步驟的 log | 代表該縣市**有** `dataset_id` 但這次探測失敗（timeout / API 改格式）；連續好幾個月都是這個縣市要留意，可能是探測邏輯該修了，不是預期行為 |
| `Commit and push` 步驟印出多次 `push rejected (attempt N/3)` | 該步驟 log | 正常現象，已自動 `fetch` + `rebase` 重推，通常第 2 次就會成功，不用人介入 |
| `Commit and push` 最終還是紅色（3 次都失敗） | 該步驟 log 的 `::error::` 那行 | 這是文件裡唯一還需要人工處理的情況——代表 rebase 本身有真正的內容衝突（例如剛好有人手動改了同一批 `roads/*.csv`），需要人判斷怎麼合併，再用 `workflow_dispatch` 重跑 |
| 整個 job 每月都選到同一批縣市，從沒變過 | `Dry-run selection` 的 log | 檢查 `update_log.csv` 有沒有被正常 commit 更新到（如果這個檔案沒跟著資料一起進版，下次比對基準就不會動，永遠判定「有更新」） |
| `keepalive` workflow 突然出現一筆 commit | `.github/.github_liveness.txt` 的 commit 訊息 | 正常現象，代表已經連續一段時間沒有縣市資料更新，保活 workflow 補了一個活動標記，不代表 `monthly-update.yml` 有問題 |
| Actions log 顯示 `Notify by email` 是綠色，但收不到信 | GitHub 帳號 Settings → Notifications | 檢查「Issues」那一列的 Email 通知有沒有被關掉；Issue 本身有沒有建立成功可以直接去 repo 的 Issues 分頁（含已關閉的）確認 |
| repo 的 Issues 分頁被每月一筆摘要塞滿 | — | 預期行為，每次執行都會開一個、立刻關閉；想清掉可以到 Issues 分頁按標題排序批次關閉／刪除，不影響 workflow 運作 |

## 7. 已知限制

| 限制 | 說明 |
| --- | --- |
| Public repo 排程 60 天自動停用 | 已由 §5 的 `keepalive.yml` 緩解——只要它自己有正常執行，就不會真的連續 60 天沒有 commit |
| 觸發時間非準點 | GitHub Actions 尖峰負載時 `schedule` 可能延遲，只保證「不早於」設定時間 |
| 只認 default branch | 排程一定是跑 `main` 上最新的 commit，跟哪個分支無關 |
| `keepalive.yml` 本身也受 60 天規則約束 | 它是另一支獨立排程 workflow，理論上也可能被停用；但它自己每週跑一次，每次都會產生一筆 Actions run，這筆 run 本身就會被算進 repo activity，不會出現「兩支排程互相指望對方防呆、結果一起被停用」的情況 |

## 8. 部署後第一次驗證步驟

1. Push `.github/workflows/monthly-update.yml` 和 `.github/workflows/keepalive.yml` 至 GitHub。
2. 至 Actions 頁籤手動打勾 `Run workflow`、`dry_run`，測 `monthly-update.yml`。
3. 觀看 log 的 `Dry-run selection` 那一步，逐一核對印出來的縣市／理由是否合理
   （比對 `update_log.csv` 目前的 `last_updated`）。
4. 確認這次有收到 GitHub 寄來的摘要信（或至少 repo 的 Issues 分頁裡有一筆剛建立又關閉
   的 issue）；沒收到信就照 §6 那一列排查通知設定。
5. 沒問題後，再手動 `Run workflow` 一次、`dry_run` 不打勾，確認 commit 真的推上 `main`，
   且訊息、檔案範圍符合預期，同時又收到一封摘要信。
6. `keepalive.yml` 不用手動驗證內容——預設 41 天內都不會寫入，只要確認它有出現在
   Actions 頁籤、且沒有紅燈即可。
7. 之後就交給兩支排程各自運作；有異常回來查 §6。
