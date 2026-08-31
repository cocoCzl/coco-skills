CREATE TABLE report_job(id BIGINT PRIMARY KEY,user_id BIGINT);
CREATE VIEW report_job_view AS SELECT id,user_id FROM report_job;
CREATE FUNCTION count_jobs() RETURNS INT BEGIN SELECT count(*) FROM report_job; END;
