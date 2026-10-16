-- text of the warnings of a finished collection, empty when there were none
ALTER TABLE Task ADD COLUMN warning TEXT;
-- short hash of the cities the buyer price was averaged over, empty means Moscow only
ALTER TABLE WbPrice ADD COLUMN site_dests_key TEXT
