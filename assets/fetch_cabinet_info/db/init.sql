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
