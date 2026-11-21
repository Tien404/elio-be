-- MySQL 8.4 / UTC. Apply with python -m scripts.migrate.
-- Group work: the professor marks an assignment as group work (assignments.is_group_work)
-- and sets the largest group size. Groups are made by the professor or by students.

ALTER TABLE assignments
    ADD COLUMN max_group_size INT NULL;

ALTER TABLE assignments
    ADD CONSTRAINT CK_assignments_group_size CHECK (
        (is_group_work = 0 AND max_group_size IS NULL)
        OR (is_group_work = 1 AND max_group_size BETWEEN 1 AND 20));
