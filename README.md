# State Graffito

文字のベクトルパスを編集・保存し、パスの統計値を管理するツールです。

## ディレクトリ構成

```text
.
├── assets/
│   ├── generate_char_path/   # Next.js UI・API・DBスキーマ・run.sh
│   ├── fetch_cabinet_info/   # 歴代総理大臣・閣僚情報の取得サービス・run.sh
│   ├── fetch_cabinet_wiki/   # 歴代内閣のWikipedia本文取得サービス・run.sh
│   ├── fetch_diet_bills/     # 国会議案情報の取得サービス・run.sh
│   ├── map_cabinet_diet_bills/ # 内閣と国会議案の対応表作成サービス・run.sh
│   └── create_prime_minister_mart/ # 総理大臣マート作成サービス・run.sh
├── services/
│   ├── cabinet_llm/          # 内閣マートのLLM分析サービス・run.sh
│   └── cabinet_score/        # cabinet_llm.json の項目別スコア計算サービス・run.sh
├── docker-compose.yml        # Webアプリと共有MySQL
├── exports/                  # DBテーブルごとのCSV出力先
└── README.md
```

## 起動

Docker Engine / Compose、Node.js / npm が必要です（ホストでは依存関係の導入に利用し、アプリは Node.js 22 コンテナで動作します）。

```sh
./assets/generate_char_path/run.sh
```

`generate_char_path/run.sh` はサービスの `node_modules` をホスト上でインストールし、そのディレクトリをコンテナ内の `/app/node_modules` にマウントしてMySQLとNext.jsを起動します。DB起動後、各テーブルのCSVを `exports/` に出力します。初回起動後は <http://localhost:3000> を開いてください。MySQL はホストの `localhost:3306` で利用できます。他のコンテナからは Docker ネットワーク `state-graffito` に接続し、ホスト名 `state-graffito-db`、ポート `3306` を指定してください。

CSVは `character_paths.csv`、`prime_ministers.csv`、`cabinet_members.csv` のようにテーブル単位で出力します。Excelで開きやすいUTF-8 BOM付きです。

MySQL の初期ユーザーとパスワードは開発用です。共有環境では `.env` を作成し、`MYSQL_ROOT_PASSWORD`、`MYSQL_DATABASE`、`MYSQL_USER`、`MYSQL_PASSWORD` を変更してください。データは `mysql-data` ボリュームに保存されます。

## 歴代内閣情報の取得

`fetch_cabinet_info` は首相官邸の歴代内閣ページから指定した代数の範囲を取得し、総理大臣情報と閣僚名簿をMySQLに保存します。かなからローマ字への変換には pykakasi の Passport 式ヘボン式を使います。既存のローマ字データは、次回スクレイピング時に更新されます。スクリプトはMySQL起動時とスクレイピング完了後に各テーブルのCSVを `exports/` へ出力します。

```sh
./assets/fetch_cabinet_info/run.sh --from-number 1 --to-number 104
```

`--from-number` は省略時に `1` です。範囲内に存在する代数の情報だけを取得します。1つの閣僚が複数の役職を兼任する場合、役職ごとに別の閣僚名簿行として保存します。

## 歴代内閣のWikipedia本文取得

`fetch_cabinet_wiki` はWikipediaの「日本国歴代内閣」一覧から内閣ページと総理大臣の代数を動的に取得し、各内閣ページのHTML本文を `cabinet_wiki` テーブルへ保存します。同じ代に複数の内閣ページがある場合、`cabinet_name` と `wiki_body` をそれぞれ空白行で連結します。CSSやページヘッダーは含めず、実行時点で一覧にある最新の代まで取得します。取得したテーブルは `exports/cabinet_wiki.csv` に出力されます。

```sh
./assets/fetch_cabinet_wiki/run.sh
```

範囲を指定する場合は `--from-number` と `--to-number` を利用できます。終了代数を省略すると、一覧から検出した最新代までを対象にします。

## 国会議案情報の取得

`fetch_diet_bills` は衆議院の議案情報から指定した国会回次の閣法・条約・予算・決議を取得し、1件取得するごとにMySQLの `diet_bills` テーブルへ保存します。経過情報ページにある最新日付を西暦と和暦で記録します。本文情報がある議案は、リンク先HTMLの `body` と、その本文情報ページにある「照会できる情報の一覧」の各リンク先の `body` を保存します。実行後、国会回次ごとにヘッダー付きのCSVを `exports/diet_bills/diet_bills-1.csv` の形式で出力します。

```sh
./assets/fetch_diet_bills/run.sh --from-number 140 --to-number 142
```

`--from-number` は省略時に `1` です。取得範囲は国会回次の両端を含みます。

## 内閣と国会議案の対応表

`map_cabinet_diet_bills` は、`prime_ministers` の在職期間と `diet_bills.date_gregorian` を照合し、期間内の日付に該当する議案のキーを `cabinet_diet_bills` テーブルへ保存します。指定した内閣番号の範囲だけを再作成し、対応表は `exports/cabinet_diet_bills.csv` に出力します。元データの取得後に実行してください。

```sh
./assets/map_cabinet_diet_bills/run.sh --from-number 1 --to-number 104
```

`--from-number` は省略時に `1` です。国会回次ごとに `date_gregorian` の最新日を求め、その日が在職期間（開始日・終了日を含む）に入る内閣へ、同じ回次のすべての議案を対応づけます。複数の内閣に該当する場合は新しい代を採用します。最新日が `NULL`（日付のある議案がない回次）の場合や、どの内閣期間にも入らない場合は対応づけません。

## 総理大臣マートの作成

`create_prime_minister_mart` は `prime_ministers` を基準に、`cabinet_wiki` と `cabinet_diet_bills` 経由の `diet_bills` を結合して `prime_minister_mart` を全件再作成します。議案は `diet_bills` の全列を含むJSON配列 `diet` に格納し、議案がない総理大臣は空配列になります。Wikipedia本文がない場合は空文字です。作成後、総理大臣の代数ごとにUTF-8 BOM付きCSVを `exports/mart/cabinet-<代数>.csv`（例: `cabinet-1.csv`）として出力します。

```sh
./assets/create_prime_minister_mart/run.sh
```

## 内閣マートのLLM分析

`cabinet_llm` サービスは `services/cabinet_llm/` にあります。`works/<work_name>/<work_version>/config.yaml`
で指定された内閣の行を `prime_minister_mart` から読み込み、Geminiで重要議案の抽出と個別評価を行います。
最終スコアの集計は行わず、2段階のLLMレスポンスを `works/<work_name>/<work_version>/cabinet_llm.json` に保存します。
JSONには内閣番号・氏名・ローマ字名・在職期間（開始日・終了日・日数）・使用モデル名と、Task 1/Task 2の結果が含まれます。
議案の `policy_score` と歴史イベントの `event_score` は連続値ではなく、正方向を `1`、負方向を `-1` とする二値です。中間値や `0` は出力しません。
各段階のレスポンスは入力・モデル・プロンプトが同一なら、作品ディレクトリ内の `.cache/cabinet_llm/` から再利用します。

各作品・バージョンごとに `works/<work_name>/<work_version>/config.yaml` を作成し、`common` の下に
対象となる内閣番号を1以上の整数で指定します。Geminiのモデル名（バージョンを含む）も `gemini_model` で指定できます。
省略時は `gemini-2.5-flash` を使用します。設定例:

```yaml
common:
  cabinet_number: 42
  gemini_model: emini-3.8-flash
```

`cabinet_number` の代わりに、DBの列名と同じ `prime_minister_number` も指定できます。両方を書く場合は同じ値にしてください。
指定したモデル名はキャッシュの識別と出力JSONの `model` にも反映されます。

```sh
bash services/cabinet_llm/run.sh works/<work_name>/<work_version>/config.yaml
```

Google Cloud Vertex AIを利用する場合は `GOOGLE_GENAI_USE_VERTEXAI=true`、
`GOOGLE_CLOUD_PROJECT`、`GOOGLE_CLOUD_LOCATION` を設定し、Application Default Credentialsを
利用できるようにしてください。`run.sh` は標準の gcloud ADC ファイル
（`~/.config/gcloud/application_default_credentials.json`）を見つけた場合、コンテナに読み取り専用で
渡します。Gemini Developer APIを利用する場合は `GEMINI_API_KEY` を設定してください。

## 項目別スコアの計算

`cabinet_score` は作品の `config.yaml` を引数に受け取り、同じディレクトリにある固定名の
`cabinet_llm.json` の Task 2 の結果から5項目の合計と正規化スコアを計算し、
同じ作品・バージョンの `cabinet_score.json` に保存します。`cabinet_llm.json` の内閣番号、氏名、
ローマ字名、在職期間、モデル名も結果に引き継ぎます。先に `cabinet_llm` を実行してください。

```sh
bash services/cabinet_score/run.sh works/<work_name>/<work_version>/config.yaml
```

議案の審議結果ウェイトは、成立 `1.0`、修正成立 `0.7`、閉会中審査 `0.2`、未了・撤回・否決 `0.0` です。
GOVERNANCEには、持ち越しでない未了または撤回1件につき `-0.5`、否決1件につき `-1.0` を加算します。
持ち越し法案は `diet_number` と `submission_session` の違いから `cabinet_llm` が判定し、
持ち越しの未了はペナルティ対象外です。不信任・問責等の決議は可決 `-2.0`、否決・未了 `-1.0` です。

各項目の素点合計を `X`、在任日数を `D` とし、`alpha = 3.0 × max(1.0, (D / 365) ** 0.35)`、
`final_score = round(tanh(X / alpha), 2)` で正規化します。結果JSONには `alpha`、項目別の `raw_sums`、
`final_scores` が含まれます。未了議案の持ち越し判定がない古い `cabinet_llm.json` は、
新しいスキーマで `cabinet_llm` を再実行してから集計してください。

## 文字パスの仕様

- 各文字はカテゴリと名前の組で識別し、この組み合わせを一意にします。
- 保存済み一覧から既存の文字を再編集でき、確認後に削除できます。
- 1つの文字は複数の線を持てます。線は始点、中点（0個以上）、終点の順で構成します。
- 中点のない線は直線、中点がある線は各点を通る三次ベジェ曲線を滑らかにつないで描画します。制御点は隣接点から接線を導出して計算し、描画と統計値計算で同じ曲線を使います。
- 線の総本数はそのまま保持し、各線を水平・垂直・斜線・曲線に分類して本数と割合を計算します。中点のない直線は始点と終点の位置関係で分類し、中点を持つ線は曲線として分類します。始点と終点が同じ座標の直線は方向分類から除外し、割合の母数は4分類の本数合計です。母数が0の場合、各割合は0です。
- 17×17グリッドの中心を `(0, 0)` とし、座標は `-8〜8` の整数です。Y軸は画面上で上から下へ正に増加するため、上端が `-8`、下端が `8` です。描画曲線のバウンディングボックスは `minY` が上端、`maxY` が下端です。重心は全線の始点・中点・終点の座標平均を四捨五入した整数です。底の点数は入力されたベクトル点群のBBox下辺（点のY座標の最大値）にある点を座標単位で重複なく数えます。中点数と中点以外（始点・終点）の数も、それぞれの分類内で座標単位に重複を除いて集計します。曲線がベクトル点より下へ膨らむ場合でも、底の点数はベクトル点群を基準にします。統計値は曲線をサンプリングして計算し、充填率は「総延長距離 / バウンディングボックス面積」です。
- 以前の `0〜16` 座標で保存された文字は、初回読み込み時に中心原点の座標へ自動移行します。
- 曲線アルゴリズムの更新時は、初回読み込み時に保存済み文字の統計値も再計算します。

## データベーススキーマ

MySQLの初期化DDLは `assets/generate_char_path/db/init.sql`、`assets/fetch_cabinet_info/db/init.sql`、`assets/fetch_cabinet_wiki/db/init.sql`、`assets/fetch_diet_bills/db/init.sql`、`assets/map_cabinet_diet_bills/db/init.sql`、`assets/create_prime_minister_mart/db/init.sql` にあります。各サービスは既存のDBボリュームでも実行時に自分のテーブルを作成します。DBの全テーブルスキーマを以下に記載します。

### `character_paths`（generate_char_path）

```sql
CREATE TABLE IF NOT EXISTS character_paths (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  category VARCHAR(120) NOT NULL,
  name VARCHAR(120) NOT NULL,
  strokes JSON NOT NULL,
  metrics JSON NOT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_character_paths_category_name (category, name)
);
```

### `prime_ministers`（fetch_cabinet_info）

```sql
CREATE TABLE IF NOT EXISTS prime_ministers (
  prime_minister_number SMALLINT UNSIGNED NOT NULL,
  name VARCHAR(120) NOT NULL,
  name_kana VARCHAR(120) NOT NULL,
  name_romaji VARCHAR(240) NOT NULL,
  birth_date DATE NOT NULL,
  birth_place VARCHAR(120) NOT NULL,
  tenure_start_date DATE NOT NULL,
  tenure_end_date DATE NOT NULL,
  tenure_start_date_era VARCHAR(32) NOT NULL,
  tenure_end_date_era VARCHAR(32) NOT NULL,
  appointment_age TINYINT UNSIGNED NULL,
  tenure_days INT UNSIGNED NULL,
  cumulative_tenure_days INT UNSIGNED NULL,
  PRIMARY KEY (prime_minister_number)
);
```

### `cabinet_members`（fetch_cabinet_info）

```sql
CREATE TABLE IF NOT EXISTS cabinet_members (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  prime_minister_number SMALLINT UNSIGNED NOT NULL,
  cabinet_name VARCHAR(200) NOT NULL,
  position VARCHAR(255) NOT NULL,
  name VARCHAR(120) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_cabinet_members_prime_minister_number (prime_minister_number),
  KEY idx_cabinet_members_cabinet_name (cabinet_name),
  CONSTRAINT fk_cabinet_members_prime_minister
    FOREIGN KEY (prime_minister_number)
    REFERENCES prime_ministers (prime_minister_number)
    ON DELETE CASCADE
);
```

`cabinet_members` は総理大臣の代数を外部キーとして保持します。役職の兼任は役職ごとに別レコードにし、同じ内閣・役職・氏名の組み合わせを一意には制限しません。
官邸ページで数値が `ー` と記載されている場合、その年齢・日数は `NULL` として保存します。
`prime_ministers.tenure_start_date` / `tenure_end_date` は西暦の `DATE`、`tenure_start_date_era` / `tenure_end_date_era` は和暦表記です。在職期間の終了が「現在」の場合は、日本時間の実行日を終了日にします。既存DBの `tenure_period` 列は、次回スクレイパー実行時に新しい4列へ移行して削除します。

### `cabinet_wiki`（fetch_cabinet_wiki）

```sql
CREATE TABLE IF NOT EXISTS cabinet_wiki (
  prime_minister_number SMALLINT UNSIGNED NOT NULL,
  cabinet_name LONGTEXT NOT NULL,
  wiki_body LONGTEXT NOT NULL,
  PRIMARY KEY (prime_minister_number)
);
```

`cabinet_name` は同じ代に該当する内閣名を空白行で連結した文字列、`wiki_body` は各内閣ページの本文HTMLを空白行で連結した文字列です。CSS、ページヘッダー、表示用の `class`・`id`・`style`・`tabindex` 属性を除外します。

### `diet_bills`（fetch_diet_bills）

```sql
CREATE TABLE IF NOT EXISTS diet_bills (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  diet_number SMALLINT UNSIGNED NOT NULL,
  category VARCHAR(16) NOT NULL,
  submission_session SMALLINT UNSIGNED NOT NULL,
  bill_number VARCHAR(32) NOT NULL,
  bill_title VARCHAR(600) NULL,
  deliberation_status VARCHAR(255) NULL,
  date_gregorian DATE NULL,
  date_era VARCHAR(32) NULL,
  bill_body LONGTEXT NULL,
  reference_information LONGTEXT NULL,
  PRIMARY KEY (id),
  KEY idx_diet_bills_lookup (diet_number, category, submission_session, bill_number)
);
```

`id` はDB内部の行識別子で、CSVには含めません。`bill_title` または `deliberation_status` が元ページで空欄の場合は `NULL` として保存します。`bill_body` は本文情報ページの `#TopContents` 以降にあるHTML、`reference_information` は「照会できる情報の一覧」の各リンク先から抽出した本文HTMLを空白行で連結した文字列です。いずれもヘッダー・パンくず・フッター・スクリプト・スタイル・表示用の `id`・`class`・`style`・`tabindex` 属性を除外します。本文情報リンクまたは参照情報リンクがない場合、該当列は `NULL` です。元ページの番号が空欄の場合は `bill_number` に空文字を保存します。

### `cabinet_diet_bills`（map_cabinet_diet_bills）

```sql
CREATE TABLE IF NOT EXISTS cabinet_diet_bills (
  prime_minister_number SMALLINT UNSIGNED NOT NULL,
  diet_number SMALLINT UNSIGNED NOT NULL,
  category VARCHAR(16) NOT NULL,
  submission_session SMALLINT UNSIGNED NOT NULL,
  bill_number VARCHAR(32) NOT NULL,
  PRIMARY KEY (
    prime_minister_number,
    diet_number,
    category,
    submission_session,
    bill_number
  ),
  KEY idx_cabinet_diet_bills_diet_key (
    diet_number,
    category,
    submission_session,
    bill_number
  )
);
```

`cabinet_diet_bills` は、同じ `diet_number` の最新の `date_gregorian` が在職期間に含まれる内閣代と、その回次の全議案の `diet_bills` キーを保持します。期間の両端は含み、複数の内閣に該当する場合は新しい代にのみ紐づけます。

### `prime_minister_mart`（create_prime_minister_mart）

```sql
CREATE TABLE IF NOT EXISTS prime_minister_mart (
  prime_minister_number SMALLINT UNSIGNED NOT NULL,
  name VARCHAR(120) NOT NULL,
  name_kana VARCHAR(120) NOT NULL,
  name_romaji VARCHAR(240) NOT NULL,
  tenure_start_date DATE NOT NULL,
  tenure_end_date DATE NOT NULL,
  tenure_start_date_era VARCHAR(32) NOT NULL,
  tenure_end_date_era VARCHAR(32) NOT NULL,
  tenure_days INT UNSIGNED NULL,
  wiki_body LONGTEXT NOT NULL,
  diet JSON NOT NULL,
  PRIMARY KEY (prime_minister_number)
);
```

`diet` は `diet_bills` の全列（`id` を含む）を持つJSONオブジェクトの配列です。

`docker compose down` はコンテナを停止します。DBを含めて初期化する場合のみ `docker compose down -v` を実行してください。
