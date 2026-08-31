CREATE TABLE department (
  id BIGINT PRIMARY KEY,
  name VARCHAR(120) NOT NULL UNIQUE
);

CREATE TABLE app_user (
  id BIGINT PRIMARY KEY,
  dept_id BIGINT NOT NULL,
  username VARCHAR(120) NOT NULL,
  CONSTRAINT fk_user_department FOREIGN KEY (dept_id) REFERENCES department(id)
);
