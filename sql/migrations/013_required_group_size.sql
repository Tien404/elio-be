-- Repair group assignments created before group-size configuration was required.
-- Use the editor's default of four, preserving the size of any larger existing group.
UPDATE assignments AS a
LEFT JOIN (
    SELECT assignment_id, MAX(member_count) AS largest_group
    FROM (
        SELECT assignment_id, group_id, COUNT(*) AS member_count
        FROM group_members
        GROUP BY assignment_id, group_id
    ) AS sizes
    GROUP BY assignment_id
) AS existing ON existing.assignment_id = a.activity_id
SET a.max_group_size = GREATEST(4, COALESCE(existing.largest_group, 0))
WHERE a.is_group_work = 1 AND a.max_group_size IS NULL;

-- MySQL accepts UNKNOWN in a CHECK, so BETWEEN alone does not reject NULL.
ALTER TABLE assignments
    DROP CHECK CK_assignments_group_size,
    ADD CONSTRAINT CK_assignments_group_size CHECK (
        (is_group_work = 0 AND max_group_size IS NULL)
        OR (is_group_work = 1 AND max_group_size IS NOT NULL
            AND max_group_size BETWEEN 1 AND 20));
