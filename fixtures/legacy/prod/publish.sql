-- dialect: postgres
-- Synthetic definition-only SQL; this does not prove that final.orders exists.
CREATE TABLE final.orders AS SELECT order_id, amount FROM staging.orders;
