# Local Reading Assistant リファクタリング計画

## 目的

現在の機能、画面、保存形式、LLMへのプロンプト、処理順序を変えずに、コードの責務を整理し、今後の修正を安全に行える構造へ移行する。

今回のリファクタリングでは、以下を互換性維持の対象とする。

- UIの表示内容と操作手順
- `ReadingOrchestrator`、`ReadingMemory`、`LocalLLMClient`などの公開API
- SQLiteの既存スキーマと保存データ
- LLMへ送るプロンプト文字列、JSON Schema、呼び出し順序
- コンテキスト予算、階層統合、再試行の挙動
- 章Markdownと最終レポートのファイル名・見出し構成
- 既存セッションの中断再開

## 現状と優先順位

| 優先度 | ファイル | 行数 | 主な問題 |
|---|---|---:|---|
| 1 | `reading_assistant/ui.py` | 975 | UI構築、依存生成、設定同期、バックグラウンド処理、表示整形が1クラスへ集中 |
| 2 | `reading_assistant/memory.py` | 802 | DBスキーマ、CRUD、集約クエリ、人物状態保存、サニタイズが混在 |
| 3 | `reading_assistant/prompts.py` | 637 | 出力例、JSON Schema、圧縮処理、全種類のプロンプトが混在 |
| 4 | `reading_assistant/orchestrator.py` | 487 | 状態機械、キャプチャ、読解、保存、ページ送り、章処理を統括しすぎている |
| 5 | `reading_assistant/llm_client.py` | 472 | ページスキーマ、OpenAI/Ollama通信、再試行、検出、JSON解析が混在 |
| 6 | `reading_assistant/reports.py` | 410 | 4パス制御、階層統合、キャッシュ、Markdown生成・保存が混在 |

## 基本方針

1. 最初に特性テストを追加し、現在の挙動を固定する。
2. 公開クラスは残し、内部処理を新しいモジュールへ委譲する。
3. 一度に設計を書き換えず、最初はコード移動だけを行う。
4. 各段階を独立したPull Requestにし、テスト成功後に次へ進む。
5. プロンプト、JSON、SQLは文字列・キー順・既定値まで比較する。
6. 新しい外部依存関係は原則追加しない。

## 1. UIの分割

### 現在混在している責務

`ReadingAssistantApp`は次の処理を同時に担当している。

- Tkウィジェットの生成と配置
- `ReadingMemory`、LLMクライアント、Orchestrator等の生成
- Tk変数と`AppConfig`の相互変換
- バックグラウンドスレッドとUIスレッド復帰
- セッション開始・再開・章終了・最終生成の操作
- メトリクス、人物心理、関係性等の表示文字列生成
- 警告、再試行、スキップ等のエラーUI

### 目標構成

```text
reading_assistant/ui/
  app.py                 画面全体の組み立てとイベント接続
  composition.py         DB・LLM・Orchestrator等の生成
  task_runner.py         バックグラウンド実行とUIスレッド復帰
  settings_binding.py    Tk変数とAppConfigの変換
  presenters.py          メトリクス・人物・心理等の表示整形
  panels/
    toolbar.py
    current_page.py
    progress.py
    understanding.py
```

### 安全な実施順

1. `_statement_lines`等の純粋な表示整形関数を`presenters.py`へ移す。
2. `_run_background`と完了・失敗処理を`TkTaskRunner`へ移す。
3. 依存オブジェクト生成を`composition.py`へ移す。
4. 最後に各パネルのウィジェット構築を分割する。

`ReadingAssistantApp`と`run_app()`のimportパスは互換用に維持する。

## 2. 永続化層の分割

### 現在混在している責務

- 約186行のSQLiteスキーマ定義
- 接続、ロック、トランザクション
- セッション・ページ・チャンク・章のCRUD
- `recent_context`や`metrics`等の集約クエリ
- 人物、関係性、予想、重要イベントの保存
- 意味メモの安全性検査とJSON変換

### 目標構成

```text
reading_assistant/persistence/
  schema.py               現在のSCHEMA文字列
  database.py             接続・ロック・transaction
  session_repository.py
  page_repository.py
  summary_repository.py
  entity_repository.py
  read_models.py          recent_context、metrics、全巻素材
  sanitization.py
```

既存コードからは引き続き`ReadingMemory`を利用し、内部でRepositoryへ委譲する。これによりOrchestratorとテストの呼び出しを変更しない。

### 注意事項

- SQLiteスキーマとPRAGMAを変更しない。
- トランザクション境界を変更しない。
- `check_same_thread=False`と現在のロック範囲を維持する。
- 既存DBのコピーを使った再開テストを必須とする。
- `sanitize_semantic_payload`は独立後もDB書き込み前に必ず通す。

## 3. プロンプトとスキーマの整理

JSON Schemaと出力例は現在、`prompts.py`、`llm_client.py`、`memory_schemas.py`に分散している。

### 目標構成

```text
reading_assistant/llm/
  schemas/
    page.py
    chunk.py
    chapter.py
    final_reports.py
  prompts/
    page.py
    chunk.py
    chapter.py
    final_reports.py
  compaction/
    page_context.py
    long_term_memory.py
```

プロンプト内の出力例は、実際のJSON Schemaと区別するため`PAGE_OUTPUT_EXAMPLE`等の名称にする。

### 必須テスト

- リファクタリング前後の各プロンプトが完全一致する。
- `json.dumps`の`ensure_ascii`、`separators`、キー順が一致する。
- 全レスポンススキーマが完全一致する。
- ページコンテキスト圧縮後のサイズと保持項目が一致する。

## 4. ページ処理パイプラインの抽出

`ReadingOrchestrator._process_capture`には、次の処理が集中している。

- 排他ロックと状態変更
- 画面キャプチャ
- 黒画面・重複判定
- 見開き分割
- Vision読解
- DB保存
- チャンク統合
- ページ送りと画面変化待機
- 失敗記録と画像破棄

### 目標構成

```text
reading_assistant/reading/
  orchestrator.py         公開操作とReaderState
  page_pipeline.py        1回のページ読解処理
  capture_service.py      キャプチャ・検査・見開き分割
  page_turn_monitor.py    キー送信と画面変化待機
  chapter_service.py      章終了処理
```

次の公開メソッドは維持する。

- `read_current_page()`
- `read_and_turn()`
- `skip_current_page()`
- `close_chapter()`
- `finalize()`

### 重要な不変条件

- ページ画像は処理後に必ず閉じる。
- 重複ページは新ページとして保存しない。
- 黒画面時に回避処理を実行しない。
- DB保存完了前にページ送りしない。
- 失敗時の状態、失敗数、コールバック順を変えない。

## 5. LLMクライアントの分割

`LocalLLMClient`は公開ファサードとして残し、内部だけを次のように分割する。

```text
reading_assistant/llm/
  client.py               vision_json、text_jsonの公開API
  openai_transport.py     OpenAI互換API
  ollama_transport.py     Ollama APIとThinking制御
  http.py                 urllib、timeout、エラー変換
  retry.py                JSON失敗時の再試行
  parsing.py              extract_json_object
  discovery.py            localhostサーバー検出
```

`vision_json()`と`text_json()`の引数・戻り値を変更しない。再試行回数、temperature変更、timeout、Ollama判定も現状を維持する。

## 6. レポート生成の分割

### 目標構成

```text
reading_assistant/reporting/
  generator.py            ReportGeneratorファサード
  verification.py         Pass 1〜4
  sectional.py            範囲別レポート
  cache.py                JSONキャッシュ
  writer.py               Markdown保存
  definitions.py          ファイル名、タイトル、対象項目
```

4パス検証と7レポート生成の処理順は変更しない。キャッシュキー、キャッシュパス、ファイル名、見出しも互換性を維持する。

`reports.py`、`integrator.py`、`chapter.py`には似た階層統合ループが存在する。将来的には共通の`HierarchicalReducer`へまとめられるが、各処理の特性テストを追加してから最後に実施する。

## 7. 章・チャンク統合の整理

`chapter.py`は章統合、正規化、Markdown出力を分ける。

```text
chapter_integrator.py
chapter_normalization.py
chapter_writer.py
```

`integrator.py`はチャンク統合、コンテキスト予算調整、レスポンス正規化を分ける。

```text
chunk_integrator.py
integration_budget.py
chunk_normalization.py
```

互換モジュールから現在のクラス・関数を再exportし、既存importを壊さない。

## 8. 人物・伏線ID追跡の整理

`entity_tracking.py`には純粋な照合ロジックとSQLite書き込みが混在している。

```text
entities/
  matcher.py              正規化、同一性判定、ID候補検索
  tracker.py              追跡処理の制御
  repository.py           SQLite読み書き
```

ID生成順、既存IDの再利用条件、履歴レコードの生成条件は変更しない。既存の`question_001`等を保持できる回帰テストを追加する。

## 実施フェーズ

### Phase 0: 挙動の固定

- プロンプト全文のゴールデンテスト
- JSON Schemaのスナップショットテスト
- DB既存セッション再開テスト
- ページ処理時のコールバック順序テスト
- レポートファイル構成テスト

### Phase 1: 低リスクなコード移動

- DBスキーマを`schema.py`へ移動
- UI表示整形関数を`presenters.py`へ移動
- JSON Schemaを用途別ファイルへ移動
- レポート定数を`definitions.py`へ移動

### Phase 2: ファサード内部の分割

- `ReadingMemory`からRepositoryへ委譲
- `LocalLLMClient`からtransportへ委譲
- `ReportGenerator`からcache・writerへ委譲
- UIバックグラウンド処理を`TkTaskRunner`へ委譲

### Phase 3: 処理パイプラインの分割

- キャプチャ・画像検査を抽出
- ページ切替待機を抽出
- ページ分析・保存処理を抽出
- 章終了処理を抽出

### Phase 4: 重複ロジックの共通化

- 階層統合ループの共通化
- コンテキスト予算調整の共通化
- 正規化処理の配置統一

## 各Pull Requestの完了条件

- 現在の25テストが無変更で成功する。
- 追加した特性テストが成功する。
- UIスモークテストが成功する。
- 既存SQLiteのコピーから中断再開できる。
- 300ページ耐久テストが成功する。
- 生成プロンプト、JSON Schema、LLM呼び出し順が一致する。
- LLM入力のトークン予算を超えない。
- レポート名、見出し、キャッシュパスが一致する。
- 公開クラスと主要メソッドのimportパスが維持される。

## 今回行わない変更

- ORMの導入
- Tkinterから別GUIフレームワークへの移行
- 全処理のasync化
- 全dictを一括してPydantic等へ置換
- SQLiteスキーマの再設計
- プロンプト文面の改善
- LLMパラメータやtoken予算の変更
- 新しい自動ページ送り機能の追加

## 推奨する最初のPull Request

最初のPRでは、次だけを行う。

1. 特性テストを追加する。
2. `memory.py`の`SCHEMA`を`persistence/schema.py`へ移す。
3. `ui.py`末尾の表示整形関数を`ui/presenters.py`へ移す。
4. 既存モジュールから再exportしてimport互換性を維持する。

この範囲なら主要処理フローへ触れず、分割方法とテスト方針が妥当かを小さな変更で確認できる。
