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
