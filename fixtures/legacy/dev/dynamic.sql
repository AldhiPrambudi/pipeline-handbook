-- dialect: postgres
DO $$ BEGIN EXECUTE 'SELECT * FROM ' || current_setting('demo.table'); END $$;
