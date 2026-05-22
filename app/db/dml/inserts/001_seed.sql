INSERT INTO nba_team (name, abbreviation) VALUES
  ('Los Angeles Lakers', 'LAL'),
  ('Golden State Warriors', 'GSW'),
  ('Boston Celtics', 'BOS')
ON DUPLICATE KEY UPDATE
  name = VALUES(name);
