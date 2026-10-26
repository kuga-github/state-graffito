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
