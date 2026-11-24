# SILICON SIGNAL — Semiconductor & AI Weekly

半導体、半導体製造装置、半導体材料、AIの週次ニュースサイト。**完全な記事本文は複製せず**、RSSの見出し・短い概要と元記事リンクを掲載する。https://sampe-bot.github.io/silicon-signal/

![Status](https://img.shields.io/badge/deployment-GitHub%20Pages-90e5bb)


## 主な機能

- 4カテゴリー：半導体／製造装置／材料／AI・LLM
- 業界別の本数・今週の注目記事、重要度・日付による並び替え
- 企業名・技術キーワードでの全文検索（掲載データの範囲）
- ブックマーク保存（閲覧ブラウザの localStorage 内だけ）
- 週ごとのアーカイブ（`site/data/editions/`）
- GitHub Actionsによる毎週月曜07:17 JST更新
- 14系統のRSSフィード + 任意のOpenAI APIによる日本語翻訳・要約

## ローカル環境での更新手順

```bash
source .venv/bin/activate
uv run scripts/collect.py --week current
uv run python -m http.server 8000 -d site
```

- `--week previous` は先週、`--week 2026-W46` は指定週を対象とする。
- 同じ週を再収集すると記事IDで既存データを更新し、今回取得できなかった記事も保持する。
- `--limit`（既定44件）は記事数の目安。新規記事は空き枠に追加し、上限を下げても既存記事は削除しない。
- 週の開始は**月曜00:00 JST**、終了は**次の月曜00:00 JST**（終了直前まで）
- 取得元のRSSフィードによって過去記事の保持件数が限られるため、過去週のバックフィルには適していない
- デフォルトでは原文RSSメタデータをそのまま表示する
- 英語記事のタイトルも英語のまま。
## 日本語ダイジェストを自動生成する手順
```bash
export OPENAI_API_KEY='your_api_key_here'
export OPENAI_MODEL='gpt-6-luna'
uv run scripts/collect.py --week current
```
- AI要約に使うLLMサービス（OpenAIなど）のAPIキーは、サーバー側（GitHub Actions）でのみ使用し、公開サイトには含めない。
- AIに渡すのはRSSの**見出しと短い概要**
- 見出し・概要・カテゴリーが変わらない記事は既存の翻訳を再利用し、未翻訳の記事だけ再試行する。
- 原文などが変わった記事は再翻訳する。翻訳が失敗・欠落した場合やAPIキーがない場合は、前回保存した原文と日本語要約をセットで保持し、次回再収集時に再試行する。
- AI要約は自動生成のため、誤りが発生しうる。
- 重要数値や発表内容は必ずソースを確認すること

## カスタマイズ

- ブランド・レイアウト：`site/index.html` / `site/styles.css`
- 表示ロジック：`site/app.js`
- ニュース取得元：`config/feeds.json`（RSS/AtomのURLと優先度を変更）
- 分類と重要度：`scripts/collect.py`（`KEYWORDS`、`score_for`）
- 更新周期：`.github/workflows/weekly.yml`
- 記事データ：`site/data/editions/YYYY-Www.json`

各記事のデータ形式は `id, category, title, titleJa, summary, summaryJa, whyJa, source, publishedAt, url, score, tags, enriched` です。公開側ではHTMLエスケープとURLのプロトコル検証を行います。

## 制約・運用上の注意

- 取得対象はRSS/Atomが存在するニュースに限られます。各社のサイトすべてを網羅するわけではありません（特にJSRやTELの公式発表は初期版に手動掲載）。
- 企業公式発表と報道・Google News検索結果が混在します。`source`で出典を確認してください。
- 自動「重要度」はルールベースの簡易スコアです。信頼性・実際の市場影響度を保証するものではありません。
- Google Newsのリンクは中継URLのままになる場合があります。ニュース配信元の利用規約とRSSの利用条件を守ってください。
- すべてのRSSが失敗した場合は**既存の週次データを上書きしません**。一部の失敗やRSSからの記事脱落は削除とみなさず、既存記事と取得できた記事をマージします。初回収集で記事が0件の場合は公開しません（Actionsログを参照）。
- GitHub Actionsのスケジュールは必ず定刻実行されるとは限らず、非アクティブな公開リポジトリでは無効化される場合があります。
- 本実装はメール配信・ログイン・有料記事本文取得・セマンティック検索を含みません。

## 情報源（例）

Semiconductor Engineering、Semiconductor Digest、EE Times、IEEE Spectrum、SemiAnalysis、Samsung Semiconductor、NVIDIA、OpenAI、Google DeepMind、Google Research、Hugging Face ほか。全リストは `config/feeds.json`。

## 技術構成

Static HTML/CSS/JavaScript + Python標準ライブラリRSS収集 + GitHub Actions + GitHub Pages。無料の静的ホスティングを第一候補にして、要件が固まったらNext.js、DB、認証、API、配信機能へ拡張できます。

## 開発メモ

回帰テスト（外部通信なし）: `uv run python -m unittest discover -s tests -v`

- Gemini APIの利用可に拡張
- 調査範囲に特許と論文データベースを追加する
- 更新日時を西暦表示とする
