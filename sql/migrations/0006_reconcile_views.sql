-- =============================================================================
-- Migration: 0006_reconcile_views.sql
-- Description: Reconcile SQL SECURITY DEFINER views for institutional authority isolation.
-- Non-transactional DDL Note: Implicit commit on execution.
-- =============================================================================

-- 1. Virtual User Identity View over staff roles & institutional faculty
CREATE OR REPLACE VIEW helpdesk_users AS
SELECT 
  s.id AS id,
  s.name AS name,
  s.email AS email,
  s.password_hash AS password,
  s.role AS role,
  s.department AS department,
  s.phone AS phone,
  s.is_active AS is_active,
  s.created_at AS created_at
FROM helpdesk_staff_roles s
UNION ALL
SELECT 
  t.TEACHER_ID AS id,
  t.TEACHER_NAME AS name,
  t.EMAIL_ID AS email,
  '' AS password,
  CASE 
    WHEN b.HOD_ID = t.TEACHER_ID OR t.DESIGNATION LIKE '%Head%' THEN 'HOD' 
    ELSE 'FACULTY' 
  END AS role,
  COALESCE(b.BRANCH_CODE, 'General') AS department,
  t.MOBILE_PHONE AS phone,
  1 AS is_active,
  '2026-01-01 00:00:00' AS created_at
FROM teacher_info t
LEFT JOIN branch_detail b ON b.BRANCH_ID = t.BRANCH_ID
WHERE t.EMAIL_ID IS NOT NULL AND t.EMAIL_ID != ''
  AND NOT EXISTS (
    SELECT 1 FROM helpdesk_staff_roles s2 WHERE s2.id = t.TEACHER_ID
  );

-- 2. Upstream Read-Only Institutional Views
CREATE OR REPLACE VIEW teacher_info AS
SELECT 
  TEACHER_ID,
  TEACHER_NAME,
  CASE WHEN CAST(DATE_OF_BIRTH AS CHAR) REGEXP '^[12][0-9]{3}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$' THEN DATE_OF_BIRTH ELSE NULL END AS DATE_OF_BIRTH,
  GENDER,
  DESIGNATION,
  EMP_TYPE,
  CASE WHEN CAST(FROM_DATE AS CHAR) REGEXP '^[12][0-9]{3}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$' THEN FROM_DATE ELSE NULL END AS FROM_DATE,
  CASE WHEN CAST(TO_DATE AS CHAR) REGEXP '^[12][0-9]{3}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$' THEN TO_DATE ELSE NULL END AS TO_DATE,
  QUALIFICATION,
  COLLEGE,
  EMAIL_ID,
  ADDRESS,
  PIN_CODE,
  OFFICE_PHN,
  RES_PHONE,
  MOBILE_PHONE,
  ACTIVE,
  SALUTATION,
  TYPE_OF_JOB,
  SAP_ID,
  TEACHER_CODE,
  BRANCH_ID,
  MARITAL_STATUS,
  caste,
  sal_scale,
  CASE WHEN CAST(SAL_INC_DATE AS CHAR) REGEXP '^[12][0-9]{3}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$' THEN SAL_INC_DATE ELSE NULL END AS SAL_INC_DATE,
  CASE WHEN CAST(TOTODATE AS CHAR) REGEXP '^[12][0-9]{3}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$' THEN TOTODATE ELSE NULL END AS TOTODATE,
  RM_NAME,
  RM_MAILID,
  RM_ID,
  CASE WHEN CAST(PDATE AS CHAR) REGEXP '^[12][0-9]{3}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$' THEN PDATE ELSE NULL END AS PDATE,
  CASE WHEN CAST(RDATE AS CHAR) REGEXP '^[12][0-9]{3}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$' THEN RDATE ELSE NULL END AS RDATE,
  CASE WHEN CAST(RELDATE AS CHAR) REGEXP '^[12][0-9]{3}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$' THEN RELDATE ELSE NULL END AS RELDATE,
  CASE WHEN CAST(PRETODATE AS CHAR) REGEXP '^[12][0-9]{3}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$' THEN PRETODATE ELSE NULL END AS PRETODATE,
  '2000' AS ORG_ID
FROM sreenidhi.teacher_info;

CREATE OR REPLACE VIEW branch_detail AS
SELECT 
  BRANCH_ID,
  BRANCH_NAME,
  BRANCH_CODE,
  LEVEL,
  HOD_ID,
  course,
  HR_Level,
  SAP_BRANCH_ID,
  '2000' AS ORG_ID
FROM sreenidhi.branch_detail;

CREATE OR REPLACE VIEW location AS
SELECT 
  id,
  COALESCE(ORG_ID, 2000) AS ORG_ID,
  block,
  floor,
  room_no,
  name,
  created_at,
  updated_at
FROM sreenidhi.location;

-- DOWN
-- DROP VIEW IF EXISTS helpdesk_users;
-- DROP VIEW IF EXISTS teacher_info;
-- DROP VIEW IF EXISTS branch_detail;
-- DROP VIEW IF EXISTS location;
