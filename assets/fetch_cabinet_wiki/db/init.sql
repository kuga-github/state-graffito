CREATE TABLE IF NOT EXISTS cabinet_wiki (
  prime_minister_number SMALLINT UNSIGNED NOT NULL,
  cabinet_name LONGTEXT NOT NULL,
  wiki_body LONGTEXT NOT NULL,
  PRIMARY KEY (prime_minister_number)
);
