-- Migration: 0007_staff_roles_enum.sql
-- Description: Expand helpdesk_staff_roles.role ENUM to support all application roles.

ALTER TABLE helpdesk_staff_roles 
MODIFY COLUMN role ENUM('SUPER_ADMIN', 'ADMIN', 'HOD', 'ASSIGNEE', 'CA', 'FACULTY') NOT NULL DEFAULT 'ASSIGNEE';
