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
