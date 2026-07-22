# 精度評価ハーネス（eval）

SESマッチングの「精度を上げる」を**計測可能**にする土台。ラベル付きの合成データに対して
パイプラインを走らせ、数値（precision/recall/F1・帯一致率）で評価する。
**評価→改善→再評価** を回して精度を上げるための実行体。**すべてダミー**（実在人物ではない）。

## 実行

```bash
cd automation/ses-matching
python eval/run_eval.py                 # 段階①プレフィルタ（決定論・APIキー不要）
python eval/run_eval.py --stage draft   # 下書き安全網 validate_draft（決定論・APIキー不要）
python eval/run_eval.py --stage scoring # 段階②LLM採点の帯一致（要 OPENAI/ANTHROPIC キー）
python eval/run_eval.py --stage all
```

決定論の段（prefilter / draft）に失敗があると **exit 1**（退行検知＝CIでゲートできる）。

## 何を測るか

| 段 | 指標 | キー | 目的 |
|---|---|---|---|
| prefilter | precision / recall / F1 | 不要 | 両刀プレフィルタの誤通過（純NWの混入）・誤除外を潰す |
| draft | 違反検知の正解率 | 不要 | 生成下書きのガードレール違反（REOorGA混入・From違反・署名欠落）を確実に捕捉 |
| contact | 宛先抽出の正解率 | 不要 | 宛先(To)自動抽出が担当アドレスを拾い、REOorGA/noreply/曖昧は「要確認」にするか |
| dedup | 重複検知の正解率 | 不要 | 既提案の 案件×要員 に重複フラグが立つか |
| watermark | 新着フィルタの正解率 | 不要 | イベント駆動の新着UID判定（取りこぼし/再採点コスト暴発）を潰す |
| reconcile | 自己整合化の正解率 | 不要 | score＝内訳合計・帯導出・score<60候補の除外（『内訳≠score』『0点候補の下書き漏れ』を根絶） |
| pickup | 本命判定の正解率 | 不要 | **85+×両刀根拠×代表確認なし**の本命だけを自動下書き/トラッカーに回すか（`is_pickup`・digest/Notionの本命/参考分割） |
| scoring | 帯一致率＋本命一致率 | 要 | LLM採点が scoring.md 通りに 足切り・帯分けするか＋**本命(85+)の一致**（**reconcile後**を計測＝本番と一致） |

## 改善履歴（測定値つき）

- **2026-07-22 R8｜案件スコープ改定（NW×Sec → サーバ×NW両刀＋情シス/PL）に精度を追随**：
  - クライアントの正式版（遊技機 情シスインフラPL）に合わせ、**両刀ゲートを「NW×セキュリティ」から「サーバ×NW」へ転換**。
    `PREFILTER_GROUPS` をサーバ群（Windows Server/AD/VMware/Hyper-V/Linux/仮想 等）×NW群（Cisco/多拠点/VPN/SD-WAN 等）に差し替え。
    **セキュリティ(EDR初動)は必須→歓迎(加点)へ移動。** 情シス目線・2〜5名PL/進捗品質管理は `scoring.md` の必須内訳で重み付け。
  - **fixtures を新スコープへ全面作り直し**：`fixtures_prefilter.jsonl`（27件＝サーバ×NW両刀の pass/純サーバ・純NWの fail/語境界の
    FP誤爆トラップ 'plan'∈lan・'broadband'∈ad 等）、`fixtures_scoring.jsonl`（11件＝本命/中/除外/年齢flag、単価アンカー支払92万以下）。
    `run_eval.py` の本命判定テスト（`two_sided`/`nw_only`）もサーバ×NWへ更新。
  - **測定**：段階①プレフィルタ **27件で precision 1.00・recall 1.00・F1 1.00**（純サーバ/純NWの片刀を確実に足切り、語境界の誤爆ゼロ）。
    本命ピックアップ **20/20**。→ **決定論15ステージ全緑（`--stage all`・exit 0）**。段階②(LLM帯一致)はCI（キー有）で実測。

- **2026-07-20 R7｜本命(85+)ピックアップ＝面談依頼が確実に来る母集団に絞る**：
  - **ピックアップ基準を score 85以上に引き上げ**（`PICKUP_MIN`・既定85）。sales@自動下書き・Notion送信トラッカー投入を
    **本命（85+）だけ**に限定し、60-84は「参考」として可視化のみ（自動アクションなし）。→ 面談依頼が来る確度を最優先。
  - **本命の二重ガード**（precision）：85+でも `reason`／`summary` に NW証拠語×Sec証拠語 が揃わなければ本命から外す
    （＝当て馬の自動下書きを止める）。年齢/国籍等の**代表確認フラグ付きは本命から除外**（客都合で弾かれ得るため参考へ）。
  - **ルーブリック**：`scoring.md`／SYSTEM_PROMPT に「本命（85+）」節と 高だが本命でない例（A'）を追加。
    「単価・商流・稼働・両刀根拠のどれか一つでも要確認が残るなら 80-84 に留める（迷ったら85未満へ）」を明文化。
  - **eval**：決定論ステージ `pickup`（**20/20**）を新設＝閾値・両刀ゲート・代表確認除外・digest/Notionの本命/参考分割を回帰。
    `scoring` fixtures に `expect_pickup` と 高だが本命でない S06/S11 を追加し、**本命(85+)一致率**も同時計測（CI・非ゲート）。
    → **決定論15ステージ全緑（`--stage all`・exit 0）**。

- **2026-07-14 R6｜精度＆マッチング率の総合強化（世界最高峰化）**：
  - **段階①recall**：両刀同義語を拡充（NW: VPN/WAN/LAN/BGP/OSPF/SD-WAN/ルーター/無線 等、Sec: EDR/XDR/SIEM/SOAR/
    ゼロトラスト/サイバー/インシデント 等）。旧語彙では取りこぼしていた「VPN/SD-WAN×EDR/SIEM」等の真の両刀を捕捉。
    群がある時は広いOR門を**バイパス**（群がヒットする語を門で落とさない）。→ **27ケースで precision 1.00・recall 1.00・F1 1.00**。
  - **段階②precision（採点の自己整合化 `reconcile`）**：各軸を配点上限でクランプ→**score＝内訳合計**に確定（『内訳≠score』根絶）、
    帯を score から決定論導出、**score<60 のジャンク候補を candidates から除外**（本番で起きた『0/100・低の下書き漏れ』を根絶）。
    決定論ステージ `reconcile`（11/11）で回帰。
  - **ルーブリック**：`scoring.md` に 必須30の内訳（両刀ハードゲート）・帯閾値・**キャリブレーション・アンカー**（採点例A〜E）を追加。
    SYSTEM_PROMPT にも両刀根拠の明記とアンカーを内蔵＝LLM採点のブレを低減。scoring fixtures を 7→10 に拡充。
  - ※段階②の帯一致（`--stage scoring`）はキー要のため本環境では未実走。**CI（ワークフロー）ではキーがあり毎回実測**される（非ゲート）。

- **2026-07-12 R1｜プレフィルタ誤爆の修正**：ASCII短語（soc/ids/ips 等）の substring 誤爆で
  純NW案件が「両刀成立」で誤通過していた（`soc`∈associate, `ips`∈tips 等）。語境界一致に変更。
  → **precision 0.67→1.00・F1 0.80→1.00**（recall 1.00維持＝標準語 SOC/IDS/IPS は引き続き成立）。
- **2026-07-12 R2｜下書き安全網**：`validate_draft` を追加し、From違反・REOorGA混入・宛先ドメイン・
  署名欠落を決定論で検知（6/6）。`make_draft.py` は違反時に一度作り直し、残れば送信不可表示。
- **2026-07-12 R3｜採点の監査可能化**：LLM採点に7軸 breakdown を必須化。内訳計とscoreのズレを
  ダイジェストで⚠️表示（説明可能なスコア）。※LLM段はキーが要るため本環境では未実走（設定済み）。
- **2026-07-12 R4｜宛先自動化＋重複防止**：`extract_contact`（宛先6/6）で担当アドレスを保守的に抽出し、
  REOorGA/noreply/複数ドメインは「要・宛先確認」に倒す。`backfill_contacts` はLLMがreorga宛を入れても
  データ層で安全化。`flag_duplicates`（2/2）で既提案の再掲を警告。プレフィルタは境界・件名一致・大文字
  混在を追加し **18ケースで F1 1.00 維持**。eval gate を `--stage all` に統一。

## フィクスチャの足し方

`fixtures_prefilter.jsonl` / `fixtures_scoring.jsonl` に1行1ケースで追記（合成データのみ）。
実運用で「見送り」が出たら、その匿名化パターンをフィクスチャに足す＝`scoring.md` の重み・足切りを
回帰付きで調整できる（`../README.md` のKPIループ）。個人情報・実アドレスは入れない。
