CREATE TABLE department(id BIGINT PRIMARY KEY,name VARCHAR(80));
CREATE TABLE app_user(id BIGINT PRIMARY KEY,department_id BIGINT NOT NULL,CONSTRAINT fk_user_department FOREIGN KEY(department_id) REFERENCES department(id));
