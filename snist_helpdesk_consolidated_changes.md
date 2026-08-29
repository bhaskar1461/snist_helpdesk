# SNIST Help Desk --- Consolidated Change Request

## Objective

Implement the following changes to the SNIST Help Desk system.

Do not make assumptions about existing behavior. Inspect the current
frontend, backend, database models, APIs, and authorization logic before
making changes.

The implementation must preserve existing functionality while applying
the requirements below.

------------------------------------------------------------------------

# 1. Ticket Creation --- Any Department With Active Categories

## Current Problem

Users are currently restricted to creating tickets for their own
department.

## Required Behavior

Any authenticated user, regardless of their own department, must be able
to create a ticket for any department that has at least one **active
category**.

### Department field

On the **Create Ticket** page:

-   Show departments based on whether they have at least one active
    category.
-   Do NOT restrict the department list to the logged-in user's
    department.
-   A user's own department must not determine which ticket departments
    they can select.

### Category filtering

After the user selects a department:

-   Show only active categories belonging to the selected department.
-   Do not show inactive categories.
-   Do not show categories belonging to other departments.
-   Changing the department must refresh the category list.
-   If the previously selected category no longer belongs to the
    selected department, clear the category selection.

### Assignment

After selecting a valid department and category:

-   Use the existing category-to-Assignee configuration to determine the
    ticket's Assignee.
-   Preserve the existing automatic assignment workflow.

### Backend security

Do not trust the frontend.

The backend must verify:

1.  The selected department exists and is eligible for ticket creation.
2.  The selected department has an active category.
3.  The selected category is active.
4.  The selected category belongs to the selected department.
5.  The authenticated user is allowed to create tickets.

Reject manipulated or invalid requests.

------------------------------------------------------------------------

# 2. Create Ticket UI Cleanup

## Heading

Change:

`Create a new complaint`

to:

`Create a new ticket`

Use **Ticket** consistently throughout the Create Ticket flow where
appropriate.

Avoid using "Complaint" when referring to the ticket entity unless it is
genuinely required by the business logic.

## Remove unnecessary informational text

Remove unnecessary helper/information text from the Create Ticket page,
including:

-   Text explaining that category selection automatically assigns the
    mapped Assignee.
-   Informational department counts such as:
    `2 department(s) with active categories`
-   Any other redundant explanatory text that does not help the user
    complete the form.

Do not remove actual validation messages, errors, required-field
indicators, or information necessary to complete the form.

## Alignment and layout

Fix the Create Ticket form layout.

Ensure:

-   Labels align correctly with their fields.
-   Department and Category fields have consistent widths.
-   Block, Floor, and Room/Lab fields align properly.
-   Description and other fields follow the same spacing system.
-   Buttons are positioned consistently.
-   No elements overlap.
-   No unnecessary horizontal scrolling occurs.
-   The layout works correctly on desktop, tablet, and smaller screens.
-   The form has consistent margins, padding, typography, and spacing.

Do not redesign the entire application. Make the UI cleaner and more
consistent with the existing design system.

------------------------------------------------------------------------

# 3. Category & Assignee Management --- Department-Based Assignee Filtering

## Current Problem

The **Assigned To** selector currently displays users from multiple/all
departments even when a specific department has been selected.

## Required Behavior

The selected department must be the strict source of truth for the
**Assigned To** list.

### Example

If:

`Department = HR - Human Resource`

Then the Assigned To selector must contain:

-   Active HR users only.

It must NOT contain:

-   CSE users
-   Administration users
-   Mechanical users
-   ECE users
-   Users from any other department

## Filtering rules

When a department is selected:

-   Query/filter users using that exact department.
-   Show only active users.
-   Exclude inactive users.
-   Exclude suspended/deleted users where applicable.
-   Do not display users from other departments.

### Department change

When the administrator changes the selected department:

1.  Clear the current Assigned To selection if it belongs to the
    previous department.
2.  Reload the Assignee list.
3.  Display only active users from the newly selected department.
4.  Prevent the old department's users from remaining selectable.

------------------------------------------------------------------------

# 4. Backend/API Enforcement for Assignee Filtering

Frontend filtering alone is NOT sufficient.

The backend must enforce the same department relationship.

When creating or updating a category assignment, validate:

``` text
selected_department == assigned_user.department
```

If the departments do not match:

-   Reject the request.
-   Do not create/update the assignment.
-   Return a clear validation error.

The backend must never allow an administrator or manipulated API request
to assign a user from Department A to a category belonging to Department
B.

## API requirements

Inspect the existing API/query used by the Assigned To selector.

Ensure the API itself returns only:

-   Active users
-   Belonging to the selected department

Do not fetch all users and rely only on frontend filtering if the
backend can filter the query.

Prefer server-side filtering for correctness, security, and performance.

------------------------------------------------------------------------

# 5. Assignee Terminology

Use **Assignee** as the role/entity terminology instead of "Concerned
Authority (CA)".

Use:

  Current                        New
  ------------------------------ ---------------------
  Concerned Authority            Assignee
  CA                             Assignee
  Assigned Concerned Authority   Assigned To
  CA Dashboard                   Assignee Dashboard
  CA Management                  Assignee Management
  CA Tickets                     Assigned Tickets
  Assign CA                      Assign User
  Active CAs                     Active Assignees
  CA Mapping                     Assignee Mapping
  CA Assignment                  Assignee Assignment

Apply this consistently across relevant:

-   UI labels
-   Navigation
-   Forms
-   Tables
-   Buttons
-   Messages
-   API naming where appropriate
-   Backend variables where appropriate
-   Documentation

Preserve backward compatibility where changing an existing API/database
field would break deployed functionality.

------------------------------------------------------------------------

# 6. Validation & Regression Requirements

After implementing the changes, verify all of the following.

## Ticket creation

-   Any user can select an eligible department.
-   Only departments with active categories appear.
-   Only active categories for the selected department appear.
-   A category from another department cannot be submitted.
-   An inactive category cannot be submitted.
-   Automatic Assignee mapping still works.

## Category management

-   Selecting a department shows only active users from that department.
-   Users from other departments never appear.
-   Changing departments refreshes the list.
-   Previous invalid Assignee selections are cleared.
-   Backend rejects cross-department assignments.
-   Existing valid assignments continue to work.

## UI

-   Create Ticket heading says "Create a new ticket".
-   Unnecessary informational text is removed.
-   Form alignment is corrected.
-   Responsive behavior remains intact.
-   Existing functionality is not visually or functionally broken.

## Security

Test API requests manually or through automated tests to ensure a user
cannot bypass the UI and:

-   Assign a category to a user from another department.
-   Submit an inactive category.
-   Submit a category belonging to another department.
-   Create a ticket for a department/category combination that is not
    eligible.

------------------------------------------------------------------------

# 7. Implementation Rules

Before changing code:

1.  Inspect the existing architecture.
2.  Identify the relevant frontend components.
3.  Identify the relevant backend routes/services.
4.  Identify the database relationships.
5.  Identify existing authorization rules.
6.  Reuse existing patterns where possible.
7.  Avoid unnecessary architectural changes.

After implementation:

1.  Run the application.
2.  Test the affected pages.
3.  Test the relevant APIs.
4.  Test invalid/malicious requests.
5.  Check for regressions.
6.  Fix every issue discovered.
7.  Re-test after every fix.

Do not declare the task complete merely because the code compiles.

The final implementation must be verified through actual application
behavior.

------------------------------------------------------------------------

# Definition of Done

The changes are complete only when:

-   Any user can create a ticket for any department with active
    categories.
-   Category selection is correctly restricted to the selected
    department.
-   Create Ticket UI is clean and properly aligned.
-   "Create a new complaint" has been changed to "Create a new ticket".
-   Unnecessary informational text has been removed.
-   Assigned To shows only active users from the selected department.
-   Cross-department Assignee assignments are impossible through both UI
    and API.
-   Assignee terminology is used consistently.
-   Existing ticket creation, category management, and automatic
    assignment functionality still works.
-   No data is lost.
-   No security bypass exists.
-   No regression is introduced.
