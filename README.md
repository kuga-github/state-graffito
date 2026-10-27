# State Graffito

A tool for editing and saving vector paths for characters and managing path statistics.

## Directory structure

```text
.
├── assets/
│   ├── generate_char_path/       # Next.js UI, API, database schema, and run.sh
│   ├── fetch_cabinet_info/       # Service for fetching prime minister and cabinet member data, and run.sh
│   ├── fetch_cabinet_wiki/       # Service for fetching Wikipedia articles about past cabinets, and run.sh
│   ├── fetch_diet_bills/         # Service for fetching Diet bill data, and run.sh
│   ├── map_cabinet_diet_bills/   # Service for mapping cabinets to Diet bills, and run.sh
│   └── create_prime_minister_mart/ # Service for creating the prime minister mart, and run.sh
├── services/
│   └── tag_pipeline/             # Cabinet analysis, scoring, character-path selection, and instruction image generation
├── docker-compose.yml            # Web app and shared MySQL
├── exports/                      # CSV output by database table
└── README.md
```

## Run the application

Docker Engine / Compose and Node.js / npm are required. Node.js / npm are used to install dependencies on the host; the application runs in a Node.js 22 container.

```sh
./assets/generate_char_path/run.sh
```

`generate_char_path/run.sh` installs the service's `node_modules` on the host, mounts that directory at `/app/node_modules` in the container, and starts MySQL and Next.js. After the database starts, CSV files for each table are exported to `exports/`. After the first startup, open <http://localhost:3000>. MySQL is available on the host at `localhost:3306`. Other containers can connect through the Docker network `state-graffito` using hostname `state-graffito-db` and port `3306`.

Each database table is exported to its own CSV file, such as `character_paths.csv`, `prime_ministers.csv`, and `cabinet_members.csv`. Files include a UTF-8 BOM for easier opening in Excel.

The default MySQL username and password are for development. For a shared environment, create `.env` and change `MYSQL_ROOT_PASSWORD`, `MYSQL_DATABASE`, `MYSQL_USER`, and `MYSQL_PASSWORD`. Data is stored in the `mysql-data` volume.

## Fetch information about past cabinets

`fetch_cabinet_info` fetches the specified range of cabinet terms from the Prime Minister's Office page for past cabinets and saves prime minister information and cabinet member rosters to MySQL. The script exports each table to `exports/` when MySQL starts and again after scraping is complete.

```sh
./assets/fetch_cabinet_info/run.sh --from-number 1 --to-number 104
```

`--from-number` defaults to `1`. Only terms available in the requested range are fetched. If a cabinet member holds multiple positions, a separate roster row is saved for each position.

## Fetch Wikipedia articles about past cabinets

`fetch_cabinet_wiki` dynamically retrieves cabinet pages and prime minister term numbers from Wikipedia's list of Japanese cabinets, then saves the HTML body of each cabinet page to the `cabinet_wiki` table. If multiple cabinet pages correspond to the same term, their `cabinet_name` and `wiki_body` values are joined with blank lines. CSS and page headers are excluded. The service fetches all terms through the latest one listed at the time it runs. The resulting table is exported to `exports/cabinet_wiki.csv`.

```sh
./assets/fetch_cabinet_wiki/run.sh
```

Use `--from-number` and `--to-number` to specify a range. If `--to-number` is omitted, the range ends at the latest term detected in the list.

## Fetch Diet bill information

`fetch_diet_bills` fetches government bills, treaties, budgets, and resolutions from the House of Representatives for the specified Diet sessions and saves each item to the MySQL `diet_bills` table as it is fetched. It records the latest date shown on each bill's progress page in both Gregorian and Japanese-era formats. For bills with detailed information, it saves the `body` of the linked HTML page as well as the `body` of each page linked in that detail page's "List of available information". After execution, it exports a headered CSV for each Diet session in the form `exports/diet_bills/diet_bills-1.csv`.

```sh
./assets/fetch_diet_bills/run.sh --from-number 140 --to-number 142
```

`--from-number` defaults to `1`. Both endpoints of the Diet session range are inclusive.

## Map cabinets to Diet bills

`map_cabinet_diet_bills` matches the tenure of each entry in `prime_ministers` against `diet_bills.date_gregorian` and saves the keys of bills dated within the tenure to the `cabinet_diet_bills` table. It recreates only the specified range of cabinet terms and exports the mapping to `exports/cabinet_diet_bills.csv`. Run it after fetching the source data.

```sh
./assets/map_cabinet_diet_bills/run.sh --from-number 1 --to-number 104
```

`--from-number` defaults to `1`. For each Diet session, the service finds the latest `date_gregorian` and assigns all bills from that session to the cabinet whose tenure includes that date (including the start and end dates). If multiple cabinets match, the latest term is selected. If the latest date is `NULL` (there are no bills with dates in that session) or no cabinet tenure contains the date, no mapping is created.

## Create the prime minister mart

`create_prime_minister_mart` rebuilds all rows in `prime_minister_mart` using `prime_ministers` as the base and joining `cabinet_wiki` and `diet_bills` through `cabinet_diet_bills`. Bills are stored in the `diet` JSON array, which contains all columns from `diet_bills`. Prime ministers without bills have an empty array. If no Wikipedia article is available, the body is an empty string. After creation, the service exports a UTF-8 BOM CSV for each prime minister term to `exports/mart/cabinet-<term>.csv` (for example, `cabinet-1.csv`).

```sh
./assets/create_prime_minister_mart/run.sh
```

## Prime minister tag-generation pipeline

Cabinet analysis, scoring, and character-path selection are performed by the single script `services/tag_pipeline/main.py`.
Specify a per-work `config.yaml`; the final result is saved to
`works/<work_name>/<work_version>/tag.json`. No intermediate JSON files are created,
and intermediate JSON files in the legacy format are removed on success.

```yaml
common:
  cabinet_number: 42
  name_romaji: Shinzo Abe
  gemini_model: gemini-2.5-flash
  random_seed: 42
```

`name_romaji` is required and is used to generate the Romanized name and tag in `tag.json`.
Instead of `cabinet_number`, you may specify `prime_minister_number`, which matches the database column name. If both are specified, they must be the same integer.
Enter `name_romaji` in "given name surname" order. The tag is formed by removing the vowels from the given name.
Generation numbers and Roman-numeral paths are not generated.
The Gemini model defaults to `gemini-2.5-flash`, and the random seed defaults to `42`.

```sh
bash services/tag_pipeline/run.sh works/<work_name>/<work_version>/config.yaml
```

For the Gemini Developer API, set `GEMINI_API_KEY`. For Vertex AI, set
`GOOGLE_GENAI_USE_VERTEXAI=true`, `GOOGLE_CLOUD_PROJECT`, and `GOOGLE_CLOUD_LOCATION`,
and make ADC available. `run.sh` mounts the standard gcloud ADC file
(`~/.config/gcloud/application_default_credentials.json`) into the container as read-only.
LLM responses for the same input, model, and prompt are reused from the work directory's `.cache/cabinet_llm/`.

`tag.json` combines cabinet information, Task 1 / Task 2 LLM responses, per-item `raw_sums` and `final_scores`,
and tag and character-path selection results. Raw bill and event scores are binary (`-1` or `1`).
For MILITARY, increased military activity is scored positively; for SECURITY, increased enforcement is scored positively.

Bill deliberation weights are `1.0` for enacted, `0.75` for enacted with amendments, `0.5` for continued review during recess, and `0.0` for unresolved, withdrawn, or rejected bills.
For bills classified as GOVERNANCE, the policy-direction score is multiplied by the deliberation weight. There is no enactment bonus.
GOVERNANCE adds `-0.5` for unresolved bills that are not carryovers, `-0.25` for withdrawn bills, and `-0.75` for rejected bills.
For no-confidence motions, the scores are `-1.0` for enacted, `-0.75` for enacted with amendments, `-0.25` for rejected, and `-0.5` for continued review during recess.
There is no penalty for unresolved or withdrawn no-confidence motions. Let the raw score total be `X` and the tenure in days be `D`; normalization is
`alpha = 3.0 × max(1.0, (D / 365) ** 0.35)` and `final_score = round(tanh(X / alpha), 2)`.

For each character in a tag, character paths are selected using the rank percentile (0–100) among candidates with the same initial.
The target score is `s = 25 + (final_score + 1) × 25` (25–75); candidates within `s ± 25` are retained,
clamped to the percentile range 0–100. Filters are applied in this order, using these metrics: MILITARY (`1 - curveRatio`),
SECURITY (`totalLength`), FINANCE (`boundingBox.width × boundingBox.height`), and BANKING (`centroid.y`).
If a filter leaves no candidates, that filter is skipped and the next filter is applied without reducing the candidate set.
Each character's `selection.filter_steps` records the candidate counts before and after each filter, and skipped conditions are recorded in
`selection.skipped_filters`. The selected path is reused for repeated tag characters.
GOVERNANCE score `g` is converted to the range 0–100 using `(g + 1) × 50` and stored in `governance_percent`.
If this value is less than 20, the decoration is `arrow`; less than 40, `double quotes`; less than 60, `null`;
less than 80, `underline`; otherwise, `halo`. The category is stored in `decoration_category`.
The output contains one character path for each character in the Romanized tag. It does not include generation numbers or Roman-numeral paths.
A white-background PNG with the selected characters arranged horizontally is saved as `debug/selected-string.png`.

In addition to the tag and selected character paths, the tag-generation pipeline automatically writes a reference-sheet-style `instruction.png`
to the work directory. The image combines basic CABINET information and counts, category scores and shape ranges,
the decoration category, and selected character paths. All tables have evenly sized columns and rows; label cells in the score and shape tables
span two rows each. The shape table headings are `linearity`, `length`, `area`, `centroid`, and `addon`.
Below the title, centered `source code: https://github.com/kuga-github/state-graffito` is shown in the same font size as table values.
There is a 40 px-equivalent gap between the subtitle and the CABINET heading.
The selected character-path table displays only character names, not categories. For the `capital` category,
the character in the top row is uppercase. Row heights and font sizes are consistent across tables, with spacing between the title and tables,
between tables, and between sections. Section spacing is equivalent to 20 px, spacing between tables is 0 px, and spacing between a title and table
is equivalent to 10 px. The page has equal margins on all sides. The GRAFFITO area contains only its border.
The image is A4 portrait at 300 dpi (2480 × 3508 px) and uses Courier Prime. Text color, line color, and line width can be changed through the
`INSTRUCTION_TEXT_COLOR`, `INSTRUCTION_MUTED_TEXT_COLOR`, `INSTRUCTION_LINE_COLOR`, and
`INSTRUCTION_LINE_WIDTH` constants in `services/tag_pipeline/main.py`.

## Percentile ranges

Percentile ranges used for character-path selection are aggregated from per-character records and output by category in
`tag.json.selection.filter_ranges`. Each character's `selection.filter_steps` records candidate counts before and after filter application,
and only the filters that were skipped.

## Character path specifications

- Each character is identified by the combination of category and name, and this combination is unique.
- Existing characters can be edited from the saved list and deleted after confirmation.
- A character can have multiple strokes. Each stroke consists of a start point, zero or more intermediate points, and an end point.
- A stroke without intermediate points is a straight line. A stroke with intermediate points is drawn as a smooth sequence of cubic Bezier curves passing through each point. Control points are calculated from tangents derived from adjacent points; the same curves are used for rendering and statistics.
- The total number of strokes is preserved, and strokes are classified as horizontal, vertical, diagonal, or curved. Counts and percentages are calculated for each category. Straight strokes without intermediate points are classified based on the relative positions of their endpoints; strokes with intermediate points are classified as curves. Straight strokes whose start and end points have the same coordinates are excluded from directional classification. The percentage denominator is the total count across the four categories. If that total is zero, all percentages are zero.
- The center of the 17 × 17 grid is `(0, 0)`, and coordinates are integers from `-8` to `8`. The Y-axis increases downward on screen, so the top edge is `-8` and the bottom edge is `8`. In the bounding box of a rendered curve, `minY` is the top edge and `maxY` is the bottom edge. The centroid is the rounded integer average of the coordinates of all stroke start, intermediate, and end points. The number of bottom points is the count of unique coordinates on the bottom edge of the input vector-point bounding box (the maximum Y coordinate). Intermediate points and non-intermediate points (start and end points) are also counted uniquely by coordinate within their respective groups. Even if a curve extends below the vector points, the bottom-point count is based on the vector points. Statistics are calculated by sampling the curves, and the fill ratio is "total path length / bounding-box area."
- Characters saved using the former `0–16` coordinate system are automatically migrated to centered coordinates when first loaded.
- When the curve algorithm is updated, the statistics for saved characters are recalculated when first loaded.

## Database schema

MySQL initialization DDL is in `assets/generate_char_path/db/init.sql`, `assets/fetch_cabinet_info/db/init.sql`, `assets/fetch_cabinet_wiki/db/init.sql`, `assets/fetch_diet_bills/db/init.sql`, `assets/map_cabinet_diet_bills/db/init.sql`, and `assets/create_prime_minister_mart/db/init.sql`. Each service also creates its own tables at runtime when using an existing database volume. The complete schema for all database tables is shown below.

For data protection, the `name_romaji` column and `prime_minister_tags` table, if already present in an existing database, are not automatically deleted, but they are no longer used. They are not created in new databases.

### `character_paths` (`generate_char_path`)

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

### `prime_ministers` (`fetch_cabinet_info`)

```sql
CREATE TABLE IF NOT EXISTS prime_ministers (
  prime_minister_number SMALLINT UNSIGNED NOT NULL,
  name VARCHAR(120) NOT NULL,
  name_kana VARCHAR(120) NOT NULL,
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

### `cabinet_members` (`fetch_cabinet_info`)

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

`cabinet_members` keeps the prime minister's term number as a foreign key. Multiple positions held by one cabinet member are stored as separate records; there is no uniqueness constraint on the combination of cabinet, position, and name.
If the Prime Minister's Office page shows a numeric value as `ー`, the corresponding age or number of days is stored as `NULL`.
`prime_ministers.tenure_start_date` / `tenure_end_date` are Gregorian `DATE` values, while `tenure_start_date_era` / `tenure_end_date_era` use Japanese-era notation. If a tenure ends with "present", the end date is set to the execution date in Japan Standard Time. The existing database's `tenure_period` column is migrated to the four new columns and removed on the next scraper run.

### `cabinet_wiki` (`fetch_cabinet_wiki`)

```sql
CREATE TABLE IF NOT EXISTS cabinet_wiki (
  prime_minister_number SMALLINT UNSIGNED NOT NULL,
  cabinet_name LONGTEXT NOT NULL,
  wiki_body LONGTEXT NOT NULL,
  PRIMARY KEY (prime_minister_number)
);
```

`cabinet_name` is a string containing the names of all cabinets for the same term, joined with blank lines. `wiki_body` contains the body HTML of each cabinet page, also joined with blank lines. CSS, page headers, and display-only `class`, `id`, `style`, and `tabindex` attributes are excluded.

### `diet_bills` (`fetch_diet_bills`)

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

`id` is an internal database row identifier and is not included in CSV files. If `bill_title` or `deliberation_status` is blank on the source page, it is stored as `NULL`. `bill_body` is the HTML from `#TopContents` onward on the detailed-information page. `reference_information` is a string containing the body HTML extracted from each link in the "List of available information", joined with blank lines. Both fields exclude headers, breadcrumbs, footers, scripts, styles, and display-only `id`, `class`, `style`, and `tabindex` attributes. If there is no detailed-information link or reference-information link, the corresponding column is `NULL`. If the source page has a blank bill number, an empty string is stored in `bill_number`.

### `cabinet_diet_bills` (`map_cabinet_diet_bills`)

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

`cabinet_diet_bills` stores the cabinet term whose tenure includes the latest `date_gregorian` in a given `diet_number`, together with the `diet_bills` keys of every bill in that session. The tenure's start and end dates are inclusive. If multiple terms match, the bill is associated only with the latest term.

### `prime_minister_mart` (`create_prime_minister_mart`)

```sql
CREATE TABLE IF NOT EXISTS prime_minister_mart (
  prime_minister_number SMALLINT UNSIGNED NOT NULL,
  name VARCHAR(120) NOT NULL,
  name_kana VARCHAR(120) NOT NULL,
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

`diet` is an array of JSON objects containing all columns from `diet_bills`, including `id`.

`docker compose down` stops the containers. Run `docker compose down -v` only when you also intend to delete and reinitialize the database.
