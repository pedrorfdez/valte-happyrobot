-- store the pack's scenario block with each run so presentation
-- (title, hazard noun, historical benchmark) travels with the data
alter table runs add column if not exists scenario_doc jsonb;
