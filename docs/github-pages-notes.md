# GitHub Pages公開・運用メモ

SILICON SIGNALの公開設定と、週次の収集・翻訳・要約を運用するための備忘録。

## 現在の設定

| 項目 | 設定 |
| --- | --- |
| 公開元 | `main` ブランチの `site/` をGitHub Actionsで公開 |
| ワークフロー | `Publish SILICON SIGNAL Weekly` |
| 定期実行 | 毎週月曜 07:17 JST（UTC日曜22:17） |
| 定期実行の対象 | 前週分（`previous`） |
| LLMサービス | OpenRouter |
| モデル | `nvidia/nemotron-3.5-super-vl:free` |
| 接続先 | `https://openrouter.ai/api/v1/responses` |
| GitHub Secret名 | `OPENAI_API_KEY` |

設定の正本は [weekly.yml](../.github/workflows/weekly.yml)。ローカル実行時のデフォルト値は [collect.py](../scripts/collect.py) の `enrich_with_openai` にあり、環境変数で上書きできる。GitHub Actionsではworkflowの `env` で指定している。

## GitHub Pagesの初期設定

1. GitHubにリポジトリを作り、コードを `main` ブランチにpushする。
2. リポジトリの **Settings → Pages** を開く。
3. **Build and deployment → Source** を **GitHub Actions** にする。
4. **Actions → Publish SILICON SIGNAL Weekly** で、pushによる公開処理が成功しているか確認する。

通常のプロジェクトサイトのURLは `https://<USERNAME>.github.io/<REPOSITORY>/`。現在のリポジトリでは `https://sampe-bot.github.io/silicon-signal/`。公開URLは **Settings → Pages** でも確認できる。リンクは相対パスを使用しているため、プロジェクトサイトに対応している。公開可否やActionsの権限はGitHubアカウント・リポジトリの設定に従う。

## OpenRouterのAPIキーを登録

1. [OpenRouterのAPIキー画面](https://openrouter.ai/keys)でキーを作成する。
2. GitHubリポジトリの **Settings → Secrets and variables → Actions** を開く。
3. **New repository secret** をクリックする。
4. 次の内容で登録する。

| 入力欄 | 値 |
| --- | --- |
| Name | `OPENAI_API_KEY` |
| Secret | OpenRouterで発行したAPIキー |

変数名は `OPENAI_API_KEY` だが、現在はOpenRouterのキーを入れる。workflowが参照するSecret名も同じなので、`OPENROUTER_API_KEY` という名前で登録しても現在の設定では読み込まれない。

キーはリポジトリのファイルや公開サイトに含めず、GitHub Actionsの収集処理で使用する。未登録でも収集・公開は動作するが、新しく収集する記事はRSSの原文タイトル・概要で表示される。API呼び出しに失敗した場合も、そのバッチは原文を残して処理を続ける。

## 初回・任意の週を手動実行

[ワークフロー画面を開く](https://github.com/sampe-bot/silicon-signal/actions/workflows/weekly.yml)。

1. 実行履歴一覧の右上にある **Run workflow ▾** をクリックする。
2. **Branch** は `main` を選ぶ。
3. **previous / current / YYYY-Www** の入力欄に対象週を指定する。
4. メニュー内の **Run workflow** をクリックする。

| 入力値 | 対象 |
| --- | --- |
| `current` | 今週分。初回の動作確認に使用 |
| `previous` | 前週分。定期実行と同じ対象 |
| `2026-W46` など | 指定したISO週 |

週の開始は月曜00:00 JST、終了は次の月曜00:00 JST（終了直前まで）。同じ週を再実行すると、その週のデータは再取得した結果で更新される。RSSには過去記事の保持件数の制限があるため、古い週の記事をすべて取得できるとは限らない。

**mainへのpushだけでは、新しい記事の収集・翻訳は実行されない。** `site/**`、`scripts/**`、`config/**`、workflowファイルへの変更を含むpushでは、保存済みデータを使って公開する。READMEやこのメモだけの変更では、このworkflowは起動しない。

## 実行結果の確認

実行履歴の対象を開き、`build-and-deploy` の各ステップを確認する。

| ステップ | 確認内容 |
| --- | --- |
| Collect weekly news | RSS収集後に `[OK] Japanese enrichment ...` が出ていること。`[WARN] AI enrichment failed ...` があれば、そのバッチの翻訳は失敗 |
| Commit new edition to history | 変更があれば `site/data/` のデータをコミット・push |
| Deploy GitHub Pages | 公開処理が成功していること |

緑のチェックはworkflow全体の成功を示すが、翻訳に失敗して原文のまま公開された場合も成功扱いになる。翻訳の成功は収集ログと記事データの `enriched: true`、`titleJa`、`summaryJa` で確認する。

ページでは「今週のピックアップ」と「記事を探す」に日本語タイトル・要約が表示される。各記事カードの出典の横に「AI要約」が付く。ページを開いたままの場合は再読み込みする。

## 週次実行の設定

```yaml
schedule:
  - cron: '17 22 * * 0'
```

毎週月曜07:17 JSTに、前週分の収集 → 日本語翻訳・要約 → データ保存 → サイト公開を実行する。初期設定後は毎週手動実行する必要はない。スケジュール実行には遅延が生じる場合があり、非アクティブな公開リポジトリでは無効化される場合もある。

実行日時・モデルを変更する場合は `weekly.yml` を編集して `main` にpushする。Secretの値はGitHubの設定画面で更新する。

## エラー時のメモ

| ログ・症状 | 確認すること |
| --- | --- |
| `No OPENAI_API_KEY` | Secret名が `OPENAI_API_KEY` で登録されているか |
| `401 Unauthorized` | OpenRouterのキーが有効か、接続先がOpenRouterになっているか |
| `429` | 無料枠の回数・トークン制限や混雑。時間を置いて再実行 |
| 空応答・JSONの途中切れ | 出力上限と推論設定。現在は1回5件・最大8,000トークンで、指定のNemotron無料モデルでは推論を無効化 |
| 特定RSSの解析エラー | そのフィードを取得できていない。他の取得元からは収集を続ける |
| 収集記事が0件 | 既存の週次データを上書きせず、処理を失敗として終了 |

[READMEに戻る](../README.md)
