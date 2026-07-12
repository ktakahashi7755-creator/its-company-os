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
| scoring | 帯一致率（高/中/除外/flag） | 要 | LLM採点が scoring.md 通りに 足切り・帯分けするか |

## 改善履歴（測定値つき）

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
