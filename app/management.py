"""Management blueprint — category management, CA assignments, location management."""

from __future__ import annotations

import json
import logging
from collections import defaultdict

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.helpers import (
    current_user, is_valid_email, live_departments, page_context,
    role_required, route_for_role, safe_int, resolve_user_org,
    departments_match, normalize_dept_name,
)

log = logging.getLogger(__name__)

management_bp = Blueprint("management", __name__)


# ── CA Promotion & Assignment Helpers ──────────────────────────────

def check_and_promote_ca(demo_db, ca_id, target_dept, actor_id, org_id):
    ca_user = demo_db.get_user(ca_id)
    if ca_user:
        user_dept = (ca_user.get("department") or "").strip()
        user_dept_display = normalize_dept_name(user_dept, org_id) or user_dept
        target_dept_display = normalize_dept_name(target_dept, org_id) or target_dept
        if user_dept and not departments_match(user_dept, target_dept, org_id):
            raise ValueError(f"User '{ca_user['name']}' belongs to department '{user_dept_display}', which does not match target department '{target_dept_display}'. Cross-department Assignee assignment is not allowed.")

        if ca_user["role"] == "FACULTY":
            new_role = "CA"
            demo_db.update_user(ca_id, {
                "name": ca_user["name"],
                "email": ca_user["email"],
                "role": new_role,
                "department": ca_user["department"],
            })
            demo_db.log_audit_event(
                "CA_PROMOTED", actor_id, org_id,
                target_type="user", target_id=ca_id,
                details={"promoted_name": ca_user["name"], "department": target_dept},
            )
            flash(f"Promoted {ca_user['name']} to Assignee for {target_dept_display}.", "success")


def resolve_and_promote_ca(demo_db, live_db, assigned_ca_id_str, target_dept, actor_id, org_id):
    if not assigned_ca_id_str or str(assigned_ca_id_str).strip().lower() in ("none", "unassigned", "0", ""):
        return None
    if str(assigned_ca_id_str).startswith("ref:"):
        ref_email = assigned_ca_id_str.split(":", 1)[1]
        teacher = live_db.lookup_teacher_by_email(ref_email)
        if not teacher:
            raise ValueError("Selected authority not found in reference directory.")

        teacher_dept = (teacher.get("department_code") or teacher.get("department_name") or "").strip()
        teacher_dept_display = normalize_dept_name(teacher_dept, org_id) or teacher_dept
        target_dept_display = normalize_dept_name(target_dept, org_id) or target_dept
        if teacher_dept and not departments_match(teacher_dept, target_dept, org_id):
            raise ValueError(f"Reference user '{teacher.get('TEACHER_NAME', 'Teacher')}' belongs to department '{teacher_dept_display}', not '{target_dept_display}'.")

        sap_id = str(teacher.get("sap_id", "123")).strip()
        existing = demo_db.get_user_by_email(teacher["email"])
        if existing:
            check_and_promote_ca(demo_db, existing["id"], target_dept, actor_id, org_id)
            return existing["id"]

        new_user_id = demo_db.create_user({
            "name": teacher["name"],
            "email": teacher["email"],
            "password": sap_id,
            "role": "CA",
            "department": target_dept,
        })
        demo_db.log_audit_event(
            "CA_PROMOTED", actor_id, org_id,
            target_type="user", target_id=new_user_id,
            details={"promoted_name": teacher["name"], "department": target_dept},
        )
        flash(f"Promoted reference user {teacher['name']} to Assignee for {target_dept}.", "success")
        return new_user_id
    else:
        ca_id = safe_int(assigned_ca_id_str)
        if ca_id <= 0:
            return None
        check_and_promote_ca(demo_db, ca_id, target_dept, actor_id, org_id)
        return ca_id



# ── Category & CA Management (Unified Module) ──────────────────────

@management_bp.route("/management/category-assignments", methods=["GET", "POST"])
@role_required("HOD", "SUPER_ADMIN", "ADMIN", "CA")
def category_assignments():
    from app import get_demo_db, get_live_db
    demo_db = get_demo_db()
    live_db = get_live_db()
    user = current_user()
    read_only = user["role"] == "CA"

    # Forward legacy/redirect callers to GET
    if request.method == "POST" and read_only:
        flash("Concerned Authorities only have read-only view access.", "error")
        return redirect(url_for("management.category_assignments"))

    if request.method == "POST":
        action = request.form.get("action", "").strip()

        # Action 1: Create Category
        if action == "create_category":
            category_name = request.form.get("category_name", "").strip()
            department = user["department"] if user["role"] == "HOD" else request.form.get("department", "").strip()
            assigned_ca_id_str = request.form.get("assigned_ca_id", "").strip()
            block = request.form.get("block", "").strip()

            if not category_name or not department:
                flash("Category name and department are required.", "error")
                return redirect(url_for("management.category_assignments"))

            if demo_db.category_exists(category_name, department):
                cats = demo_db.list_categories(department=department)
                matching = [c for c in cats if c["category_name"].lower() == category_name.lower()]
                if matching and matching[0]["is_active"] == 0:
                    demo_db.toggle_category_status(matching[0]["id"], 1)
                    demo_db.log_audit_event("CATEGORY_TOGGLED", user["id"], user["org_id"],
                                            target_type="category", target_id=matching[0]["id"],
                                            details={"category_name": matching[0]["category_name"], "is_active": 1})
                    flash(f"Re-activated category '{matching[0]['category_name']}' for {department}.", "success")
                else:
                    flash(f"A category '{category_name}' already exists in {department}.", "error")
                return redirect(url_for("management.category_assignments"))

            ca_id = None
            if assigned_ca_id_str:
                try:
                    ca_id = resolve_and_promote_ca(demo_db, live_db, assigned_ca_id_str, department, user["id"], user["org_id"])
                except Exception as e:
                    flash(f"Failed to assign CA: {e}", "error")

            payload = {
                "category_name": category_name,
                "department": department,
                "assigned_ca_id": ca_id,
            }
            cat_id = demo_db.create_category(payload)

            blocks = request.form.getlist("blocks") or request.form.getlist("block")
            if not blocks:
                single_block = request.form.get("block", "").strip()
                if single_block:
                    blocks = [single_block]

            created_count = 0
            skipped_count = 0
            if blocks and ca_id:
                for b in blocks:
                    b_stripped = b.strip()
                    if not b_stripped or b_stripped == "all":
                        continue
                    try:
                        demo_db.create_ca_assignment(cat_id, ca_id, b_stripped)
                        demo_db.log_audit_event(
                            "CA_BLOCK_ASSIGNED", user["id"], user["org_id"],
                            target_type="ca_assignment", target_id=ca_id,
                            details={"category_id": cat_id, "block": b_stripped},
                        )
                        created_count += 1
                    except ValueError:
                        skipped_count += 1
                    except Exception as e:
                        flash(f"Location mapping failed for block {b_stripped}: {e}", "warning")

            demo_db.log_audit_event("CATEGORY_CREATED", user["id"], user["org_id"],
                                    target_type="category", target_id=cat_id,
                                    details={"category_name": category_name, "department": department, "assigned_ca_id": ca_id, "blocks": blocks})

            if created_count > 0 or skipped_count > 0:
                flash(f"Category '{category_name}' created successfully. Created {created_count} location block mapping(s) ({skipped_count} skipped because they already existed).", "success")
            else:
                flash(f"Category '{category_name}' created successfully.", "success")
            return redirect(url_for("management.category_assignments"))

        # Action 2: Update Category (Inline / Form edit)
        elif action == "update_category":
            category_id = safe_int(request.form.get("category_id"))
            existing_cat = demo_db.get_category(category_id)
            if not existing_cat:
                flash("Category not found.", "error")
                return redirect(url_for("management.category_assignments"))

            if user["role"] == "HOD" and existing_cat["department"] != user["department"]:
                flash("You can only modify categories in your own department.", "error")
                return redirect(url_for("management.category_assignments"))

            category_name = request.form.get("category_name", "").strip()
            department = user["department"] if user["role"] == "HOD" else request.form.get("department", "").strip()
            assigned_ca_id_str = request.form.get("assigned_ca_id", "").strip()

            if not category_name or not department:
                flash("Category name and department are required.", "error")
                return redirect(url_for("management.category_assignments"))

            if demo_db.category_exists(category_name, department, exclude_id=category_id):
                flash(f"A category '{category_name}' already exists in {department}.", "error")
                return redirect(url_for("management.category_assignments"))

            ca_id = existing_cat.get("assigned_ca_id")
            if assigned_ca_id_str != "":
                if assigned_ca_id_str == "none":
                    ca_id = None
                else:
                    try:
                        ca_id = resolve_and_promote_ca(demo_db, live_db, assigned_ca_id_str, department, user["id"], user["org_id"])
                    except Exception as e:
                        flash(f"Failed to assign CA: {e}", "error")

            payload = {
                "category_name": category_name,
                "department": department,
                "assigned_ca_id": ca_id,
            }

            # Audit Log for CA assignment change if changed
            prev_ca_id = existing_cat.get("assigned_ca_id")
            if prev_ca_id != ca_id:
                prev_ca_user = demo_db.get_user(prev_ca_id) if prev_ca_id else None
                new_ca_user = demo_db.get_user(ca_id) if ca_id else None
                demo_db.log_audit_event(
                    "CA_ASSIGNMENT_CHANGED", user["id"], user["org_id"],
                    target_type="category", target_id=category_id,
                    details={
                        "category_name": category_name,
                        "previous_assigned_ca": prev_ca_user["name"] if prev_ca_user else "Unassigned",
                        "new_assigned_ca": new_ca_user["name"] if new_ca_user else "Unassigned",
                        "actor": user["name"],
                    },
                )

            # Handle optional Location Block mappings specified in edit modal
            blocks = request.form.getlist("blocks") or request.form.getlist("block")
            if not blocks:
                single_block = request.form.get("block", "").strip()
                if single_block:
                    blocks = [single_block]

            created_count = 0
            skipped_count = 0
            if blocks and ca_id:
                for b in blocks:
                    b_stripped = b.strip()
                    if not b_stripped or b_stripped == "all":
                        continue
                    try:
                        demo_db.create_ca_assignment(category_id, ca_id, b_stripped)
                        demo_db.log_audit_event(
                            "CA_BLOCK_ASSIGNED", user["id"], user["org_id"],
                            target_type="ca_assignment", target_id=ca_id,
                            details={"category_id": category_id, "block": b_stripped},
                        )
                        created_count += 1
                    except ValueError:
                        skipped_count += 1
                    except Exception as e:
                        pass

            demo_db.update_category(category_id, payload)
            demo_db.log_audit_event("CATEGORY_UPDATED", user["id"], user["org_id"],
                                    target_type="category", target_id=category_id,
                                    details={"category_name": category_name, "department": department, "blocks": blocks})

            if created_count > 0 or skipped_count > 0:
                flash(f"Category updated successfully. Created {created_count} location block mapping(s) ({skipped_count} skipped because they already existed).", "success")
            else:
                flash("Category updated successfully.", "success")
            return redirect(url_for("management.category_assignments"))

        # Action 3: Assign CA & Block Mappings
        elif action == "assign_ca":
            faculty_id_str = request.form.get("faculty_id", "").strip()
            category_ids = [safe_int(cid) for cid in request.form.getlist("categories") if safe_int(cid) > 0]
            if not category_ids:
                single_cat = safe_int(request.form.get("category_id", "0"))
                if single_cat > 0:
                    category_ids = [single_cat]

            blocks = request.form.getlist("blocks") or request.form.getlist("block")
            if not blocks:
                single_block = request.form.get("block", "").strip()
                if single_block:
                    blocks = [single_block]

            if not faculty_id_str or not category_ids:
                flash("Faculty and Category selection are required.", "error")
                return redirect(url_for("management.category_assignments"))

            try:
                dept_to_categories = {}
                for cat_id in category_ids:
                    cat = demo_db.get_category(cat_id)
                    if cat:
                        dept = cat["department"]
                        if dept not in dept_to_categories:
                            dept_to_categories[dept] = []
                        dept_to_categories[dept].append(cat_id)

                created_count = 0
                skipped_count = 0
                for dept, cat_ids in dept_to_categories.items():
                    ca_id = resolve_and_promote_ca(demo_db, live_db, faculty_id_str, dept, user["id"], user["org_id"])
                    for cat_id in cat_ids:
                        cat = demo_db.get_category(cat_id)
                        prev_ca_id = cat.get("assigned_ca_id") if cat else None
                        
                        # Set default CA for category if not assigned or blocks empty
                        if not blocks:
                            demo_db.update_category(cat_id, {
                                "category_name": cat["category_name"],
                                "department": cat["department"],
                                "assigned_ca_id": ca_id,
                            })
                            ca_user = demo_db.get_user(ca_id)
                            prev_user = demo_db.get_user(prev_ca_id) if prev_ca_id else None
                            demo_db.log_audit_event(
                                "CA_ASSIGNMENT_CHANGED", user["id"], user["org_id"],
                                target_type="category", target_id=cat_id,
                                details={
                                    "category_name": cat["category_name"],
                                    "previous_assigned_ca": prev_user["name"] if prev_user else "Unassigned",
                                    "new_assigned_ca": ca_user["name"] if ca_user else "Unknown",
                                },
                            )
                            created_count += 1
                        else:
                            # Create block-level mapping
                            for b in blocks:
                                b_stripped = b.strip()
                                if not b_stripped or b_stripped == "all":
                                    continue
                                try:
                                    demo_db.create_ca_assignment(cat_id, ca_id, b_stripped)
                                    demo_db.log_audit_event(
                                        "CA_BLOCK_ASSIGNED", user["id"], user["org_id"],
                                        target_type="ca_assignment", target_id=ca_id,
                                        details={"category_id": cat_id, "block": b_stripped},
                                    )
                                    created_count += 1
                                except ValueError:
                                    skipped_count += 1

                flash(f"CA assigned successfully. Created {created_count} location block mapping(s) ({skipped_count} skipped because they already existed).", "success")
            except Exception as e:
                flash(f"Assignment failed: {e}", "error")
            return redirect(url_for("management.category_assignments"))

        # Action 4: Bulk Operations (Bulk Assign CA, Bulk Enable/Disable, Bulk Unassign)
        elif action == "bulk_action":
            bulk_op = request.form.get("bulk_op", "").strip()
            selected_cat_ids = [safe_int(cid) for cid in request.form.getlist("selected_categories") if safe_int(cid) > 0]
            
            if not selected_cat_ids:
                flash("Please select at least one category for bulk operation.", "warning")
                return redirect(url_for("management.category_assignments"))

            if bulk_op == "bulk_assign":
                bulk_ca_id_str = request.form.get("bulk_ca_id", "").strip()
                if not bulk_ca_id_str:
                    flash("Please select a CA for bulk assignment.", "error")
                    return redirect(url_for("management.category_assignments"))
                
                # Resolve CA for first department
                first_cat = demo_db.get_category(selected_cat_ids[0])
                target_dept = first_cat["department"] if first_cat else (user["department"] if user["role"] == "HOD" else "CSE")
                ca_id = resolve_and_promote_ca(demo_db, live_db, bulk_ca_id_str, target_dept, user["id"], user["org_id"])
                
                count = demo_db.bulk_assign_ca(selected_cat_ids, ca_id)
                ca_user = demo_db.get_user(ca_id)
                demo_db.log_audit_event(
                    "BULK_CA_ASSIGNED", user["id"], user["org_id"],
                    target_type="category",
                    details={"count": count, "new_assigned_ca": ca_user["name"] if ca_user else str(ca_id), "category_ids": selected_cat_ids},
                )
                flash(f"Bulk assigned {ca_user['name'] if ca_user else 'CA'} to {count} category(ies).", "success")

            elif bulk_op == "bulk_enable":
                count = demo_db.bulk_toggle_categories(selected_cat_ids, True)
                demo_db.log_audit_event("BULK_CATEGORY_ENABLED", user["id"], user["org_id"],
                                        target_type="category", details={"count": count, "category_ids": selected_cat_ids})
                flash(f"Bulk enabled {count} category(ies).", "success")

            elif bulk_op == "bulk_disable":
                count = demo_db.bulk_toggle_categories(selected_cat_ids, False)
                demo_db.log_audit_event("BULK_CATEGORY_DISABLED", user["id"], user["org_id"],
                                        target_type="category", details={"count": count, "category_ids": selected_cat_ids})
                flash(f"Bulk disabled {count} category(ies).", "success")

            elif bulk_op == "bulk_unassign":
                count = demo_db.bulk_remove_ca(selected_cat_ids)
                demo_db.log_audit_event("BULK_CA_UNASSIGNED", user["id"], user["org_id"],
                                        target_type="category", details={"count": count, "category_ids": selected_cat_ids})
                flash(f"Bulk removed CA assignment from {count} category(ies).", "success")

            else:
                flash("Invalid bulk operation.", "error")
            return redirect(url_for("management.category_assignments"))

        # Action 5: Single Category Delete via Modal Form
        elif action == "delete_category":
            category_id = safe_int(request.form.get("category_id", "0"))
            if not category_id:
                flash("Category ID is required for deletion.", "error")
                return redirect(url_for("management.category_assignments"))
            return delete_category(category_id)

        # Action 7: Assign CA to single category with blocks (Multi-CA support)
        elif action == "assign_ca_to_category":
            category_id = safe_int(request.form.get("category_id", "0"))
            faculty_id_str = request.form.get("faculty_id", "").strip()
            cat = demo_db.get_category(category_id)
            if not cat or not faculty_id_str:
                flash("Category and Assignee selection are required.", "error")
                return redirect(url_for("management.category_assignments"))

            if user["role"] == "HOD" and cat["department"] != user["department"]:
                flash("You can only modify categories in your department.", "error")
                return redirect(url_for("management.category_assignments"))

            blocks = request.form.getlist("blocks") or request.form.getlist("block")
            try:
                ca_id = resolve_and_promote_ca(demo_db, live_db, faculty_id_str, cat["department"], user["id"], user["org_id"])
                res = demo_db.assign_ca_to_category_blocks(category_id, ca_id, blocks)
                ca_user = demo_db.get_user(ca_id)
                ca_name = ca_user["name"] if ca_user else "Assignee"
                demo_db.log_audit_event(
                    "CA_ASSIGNED_TO_CATEGORY", user["id"], user["org_id"],
                    target_type="category", target_id=category_id,
                    details={"ca_id": ca_id, "ca_name": ca_name, "blocks": blocks},
                )
                block_desc = ", ".join(blocks) if blocks else "All Blocks"
                flash(f"Successfully assigned {ca_name} to category '{cat['category_name']}' for {block_desc}.", "success")
            except Exception as e:
                flash(f"Failed to assign Assignee: {e}", "error")
            return redirect(url_for("management.category_assignments"))

        # Action 8: Remove Assignee from category
        elif action == "remove_category_assignee":
            category_id = safe_int(request.form.get("category_id", "0"))
            ca_id = safe_int(request.form.get("ca_id", "0"))
            if not category_id or not ca_id:
                flash("Category ID and Assignee ID are required.", "error")
                return redirect(url_for("management.category_assignments"))

            cat = demo_db.get_category(category_id)
            if user["role"] == "HOD" and cat and cat["department"] != user["department"]:
                flash("You can only modify categories in your department.", "error")
                return redirect(url_for("management.category_assignments"))

            demo_db.remove_ca_from_category(category_id, ca_id)
            demo_db.log_audit_event(
                "CA_REMOVED_FROM_CATEGORY", user["id"], user["org_id"],
                target_type="category", target_id=category_id,
                details={"removed_ca_id": ca_id},
            )
            flash("Assignee removed from category successfully.", "success")
            return redirect(url_for("management.category_assignments"))

        # Action 9: Delete individual block mapping
        elif action == "delete_mapping":
            mapping_id = safe_int(request.form.get("mapping_id", "0"))
            if mapping_id > 0:
                demo_db.delete_ca_assignment(mapping_id)
                demo_db.log_audit_event(
                    "CA_MAPPING_DELETED", user["id"], user["org_id"],
                    target_type="ca_assignment", target_id=mapping_id,
                )
                flash("Block mapping removed.", "success")
            return redirect(url_for("management.category_assignments"))

    # ── GET: Category & CA Management View ──────────────────────────────
    dept_filter = None
    if user["role"] == "HOD":
        dept_filter = user["department"]
    elif request.args.get("department", "").strip():
        dept_filter = request.args.get("department", "").strip()

    search = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    ca_filter = safe_int(request.args.get("ca_id", "0")) or None

    active_only = status_filter == "active"
    
    # If CA user, filter categories where assigned_ca_id == user["id"] or has block mapping
    filter_ca_id = user["id"] if user["role"] == "CA" else ca_filter

    categories = demo_db.list_categories(
        department=dept_filter,
        search=search,
        ca_id=filter_ca_id,
        org_id=user["org_id"],
        active_only=active_only,
    )

    if status_filter == "inactive":
        categories = [c for c in categories if c.get("is_active") == 0]

    # Enrich categories with ticket counts, block mappings & structured assignees
    for cat in categories:
        cat["ticket_count"] = demo_db.count_tickets_by_category(cat["id"]) if hasattr(demo_db, 'count_tickets_by_category') else 0
        cat["block_mappings"] = demo_db.get_category_block_mappings(cat["id"]) if hasattr(demo_db, 'get_category_block_mappings') else []
        cat["assignees"] = demo_db.get_category_assignees(cat["id"]) if hasattr(demo_db, 'get_category_assignees') else []

    # Fetch Assignees strictly for the target department (only active CA/ASSIGNEE users)
    if dept_filter:
        candidate_users = demo_db.list_users(role=["CA", "ASSIGNEE"], department=dept_filter, org_id=user["org_id"])
    else:
        candidate_users = demo_db.list_users(role=["CA", "ASSIGNEE"], org_id=user["org_id"])

    promoteable_users = []
    seen_emails = set()

    depts = live_departments(user["org_id"])
    dept_map = {}
    for d in depts:
        code = (d.get("code") or "").strip()
        name = (d.get("name") or "").strip()
        if d.get("id"):
            dept_map[str(d["id"])] = code or name
        if code:
            dept_map[code] = code
            dept_map[code.upper()] = code
            dept_map[code.lower()] = code
        if name:
            dept_map[name] = code or name
            dept_map[name.upper()] = code or name
            dept_map[name.lower()] = code or name

    for u in candidate_users:
        if u.get("is_active", 1) == 0:
            continue
        email_lower = (u.get("email") or "").lower().strip()
        if not email_lower or email_lower in seen_emails:
            continue
        u_dept = (u.get("department") or "").strip()
        if dept_filter and u_dept.lower() != dept_filter.lower():
            continue
        seen_emails.add(email_lower)

        raw_dept = (u.get("department") or "General").strip()
        dept_name = dept_map.get(raw_dept) or dept_map.get(raw_dept.upper()) or raw_dept
        promoteable_users.append({
            "id": u["id"],
            "name": u["name"],
            "email": u["email"],
            "role": u["role"],
            "department": dept_name or "General",
        })

    # Sort promoteable users by department and name for clean optgroup categorization
    promoteable_users.sort(key=lambda x: (x["department"].upper(), x["name"].upper()))



    locations = live_db.fetch_locations()
    blocks = sorted(list(set(loc["block"] for loc in locations if loc.get("block"))))

    # Calculate summary statistics
    all_cats = demo_db.list_categories(department=dept_filter, org_id=user["org_id"])
    total_count = len(all_cats)
    active_count = sum(1 for c in all_cats if c.get("is_active") == 1)
    assigned_cas_count = len(set(c["assigned_ca_id"] for c in all_cats if c.get("assigned_ca_id")))
    unassigned_count = sum(1 for c in all_cats if not c.get("assigned_ca_id"))

    stats = {
        "total": total_count,
        "active": active_count,
        "assigned_cas": assigned_cas_count,
        "unassigned": unassigned_count,
    }

    filters = {
        "q": search,
        "department": dept_filter or "",
        "status": status_filter or "",
        "ca_id": ca_filter or "",
    }

    # Prepare clean, JSON-safe datasets for instant smart search
    categories_json_safe = []
    for c in categories:
        categories_json_safe.append({
            "id": c.get("id"),
            "category_name": c.get("category_name", ""),
            "department": c.get("department", ""),
            "assigned_ca_id": c.get("assigned_ca_id"),
            "assigned_ca_name": c.get("assigned_ca_name", ""),
            "assigned_ca_email": c.get("assigned_ca_email", ""),
            "is_active": c.get("is_active", 1),
            "active_tickets": c.get("ticket_count", 0),
            "mapped_blocks": c.get("block_mappings", []),
        })

    users_json_safe = []
    for u in promoteable_users:
        users_json_safe.append({
            "id": u.get("id"),
            "name": u.get("name", ""),
            "email": u.get("email", ""),
            "role": u.get("role", ""),
            "department": u.get("department", ""),
        })

    return render_template(
        "category_ca_management.html",
        categories=categories,
        users=promoteable_users,
        categories_json_str=json.dumps(categories_json_safe),
        users_json_str=json.dumps(users_json_safe),
        departments=live_departments(user["org_id"]),
        blocks=blocks,
        filters=filters,
        stats=stats,
        read_only=read_only,
        **page_context("Category & CA Management"),
    )


# Backward Compatibility / Redirect Routes
@management_bp.route("/management/category-management", methods=["GET", "POST"])
@role_required("HOD", "SUPER_ADMIN", "ADMIN")
def management_category():
    if request.method == "POST" and not request.form.get("action"):
        mutable_form = request.form.copy()
        mutable_form["action"] = "create_category"
        request.form = mutable_form
    return category_assignments()


@management_bp.route("/hod/ca-assignments", methods=["GET", "POST"])
@role_required("HOD", "SUPER_ADMIN", "ADMIN")
def ca_assignments():
    if request.method == "POST" and not request.form.get("action"):
        # Synthesize assign_ca action if omitted in legacy form posts
        mutable_form = request.form.copy()
        mutable_form["action"] = "assign_ca"
        request.form = mutable_form
    return category_assignments()


@management_bp.route("/api/locations")
@role_required("FACULTY", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
def api_locations():
    from app import get_live_db
    from flask import jsonify
    live_db = get_live_db()
    locations = live_db.fetch_locations()
    grouped = {}
    for loc in locations:
        block = loc.get("block", "Unknown")
        floor = loc.get("floor", "Unknown")
        if block not in grouped:
            grouped[block] = {}
        if floor not in grouped[block]:
            grouped[block][floor] = []
        grouped[block][floor].append({
            "id": loc["id"],
            "room_no": loc.get("room_no", ""),
            "name": loc.get("name", ""),
        })
    return jsonify(grouped)


@management_bp.route("/management/category-management/<int:category_id>/update", methods=["POST"])
@role_required("HOD", "SUPER_ADMIN")
def update_category(category_id):
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    existing_cat = demo_db.get_category(category_id)
    if not existing_cat:
        flash("Category not found.", "error")
        return redirect(url_for("management.category_assignments"))

    category_name = request.form.get("category_name", "").strip()
    department = user["department"] if user["role"] == "HOD" else request.form.get("department", "").strip()
    if not category_name or not department:
        flash("Category name and department are required.", "error")
        return redirect(url_for("management.category_assignments"))

    demo_db.update_category(category_id, {
        "category_name": category_name,
        "department": department,
        "assigned_ca_id": existing_cat.get("assigned_ca_id"),
    })
    demo_db.log_audit_event("CATEGORY_UPDATED", user["id"], user["org_id"],
                            target_type="category", target_id=category_id,
                            details={"category_name": category_name, "department": department})
    flash("Category updated successfully.", "success")
    return redirect(url_for("management.category_assignments"))


@management_bp.route("/management/category-management/<int:category_id>/delete", methods=["POST"])
@role_required("HOD", "SUPER_ADMIN", "ADMIN", "CA")
def delete_category(category_id):
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    if user["role"] == "CA":
        flash("You cannot make this change as it is against allowed workflow.", "error")
        return redirect(url_for("management.category_assignments"))

    cat = demo_db.get_category(category_id)
    if not cat:
        flash("Category not found.", "error")
        return redirect(url_for("management.category_assignments"))

    if user["role"] == "HOD" and cat["department"] != user["department"]:
        flash("You cannot make this change as it is against allowed workflow.", "error")
        return redirect(url_for("management.category_assignments"))

    # Check if category has existing tickets
    ticket_count = 0
    if hasattr(demo_db, 'count_tickets_by_category'):
        ticket_count = demo_db.count_tickets_by_category(category_id)
    else:
        try:
            with demo_db.connection() as conn, conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS cnt FROM helpdesk_tickets WHERE category_id = %s", (category_id,))
                res = cursor.fetchone()
                ticket_count = res["cnt"] if res else 0
        except Exception:
            ticket_count = 0

    if ticket_count > 0:
        flash(f"You cannot make this change as it is against allowed workflow. Category '{cat['category_name']}' has {ticket_count} existing ticket(s) associated with it. Disable the category instead.", "error")
        return redirect(url_for("management.category_assignments"))

    try:
        demo_db.delete_category(category_id)
        demo_db.log_audit_event("CATEGORY_DELETED", user["id"], user["org_id"],
                                target_type="category", target_id=category_id,
                                details={"category_name": cat["category_name"]})
        flash(f"Category '{cat['category_name']}' deleted successfully.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    except Exception as e:
        flash(f"Failed to delete category: {e}", "error")
    return redirect(url_for("management.category_assignments"))


@management_bp.route("/management/category-management/<int:category_id>/toggle", methods=["POST"])
@role_required("HOD", "SUPER_ADMIN", "ADMIN", "CA")
def toggle_category(category_id):
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    if user["role"] == "CA":
        flash("You cannot make this change as it is against allowed workflow.", "error")
        return redirect(url_for("management.category_assignments"))

    existing_cat = demo_db.get_category(category_id)
    if existing_cat:
        if user["role"] == "HOD" and existing_cat["department"] != user["department"]:
            flash("You cannot make this change as it is against allowed workflow.", "error")
            return redirect(url_for("management.category_assignments"))

        new_state = 0 if existing_cat.get("is_active", 1) == 1 else 1
        demo_db.toggle_category_status(category_id, new_state)
        demo_db.log_audit_event("CATEGORY_TOGGLED", user["id"], user["org_id"],
                                target_type="category", target_id=category_id,
                                details={"category_name": existing_cat["category_name"], "is_active": new_state})
        status_str = "activated" if new_state else "deactivated"
        flash(f"Category '{existing_cat['category_name']}' has been {status_str}.", "success")
    return redirect(url_for("management.category_assignments"))


@management_bp.route("/hod/ca-assignments/<int:assignment_id>/delete", methods=["POST"])
@role_required("HOD", "SUPER_ADMIN", "ADMIN", "CA")
def delete_ca_assignment(assignment_id):
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    if user["role"] == "CA":
        flash("You cannot make this change as it is against allowed workflow.", "error")
        return redirect(url_for("management.category_assignments"))

    try:
        demo_db.delete_ca_assignment(assignment_id)
        demo_db.log_audit_event("CA_ASSIGNMENT_REMOVED", user["id"], user["org_id"],
                                target_type="ca_assignment", target_id=assignment_id)
        flash("CA block assignment removed successfully.", "success")
    except Exception as e:
        flash(f"Failed to delete assignment: {e}", "error")
    return redirect(url_for("management.category_assignments"))





# ── Location Management ─────────────────────────────────────────────

@management_bp.route("/super-admin/locations", methods=["GET", "POST"])
@role_required("SUPER_ADMIN")
def location_management():
    from app import get_demo_db, get_live_db
    demo_db = get_demo_db()
    live_db = get_live_db()
    user = current_user()

    if request.method == "POST":
        block = request.form.get("block", "").strip()
        floor = request.form.get("floor", "").strip()
        room_no = request.form.get("room_no", "").strip()
        name = request.form.get("name", "").strip()
        if not all([block, floor, room_no]):
            flash("Block, Floor, and Room Number are required.", "error")
            return redirect(url_for("management.location_management"))
        try:
            demo_db.create_location(user["org_id"], block, floor, room_no, name)
            demo_db.log_audit_event("LOCATION_CREATED", user["id"], user["org_id"],
                                    target_type="location", details={"block": block, "floor": floor, "room_no": room_no})
            flash(f"Location {block} - {floor} - {room_no} created successfully.", "success")
        except Exception as e:
            flash(f"Failed to create location: {e}", "error")
        return redirect(url_for("management.location_management"))

    search = request.args.get("q", "").strip()
    locations = live_db.fetch_locations()
    filtered_locations = [loc for loc in locations if str(loc.get("ORG_ID", "2000")) == str(user["org_id"])]
    if search:
        search_lower = search.lower()
        filtered_locations = [loc for loc in filtered_locations
                              if search_lower in (loc.get("block") or "").lower()
                              or search_lower in (loc.get("floor") or "").lower()
                              or search_lower in (loc.get("room_no") or "").lower()
                              or search_lower in (loc.get("name") or "").lower()]
    return render_template("location_management.html", locations=filtered_locations, search=search,
                           **page_context("Location Management"))


@management_bp.route("/super-admin/locations/<int:location_id>/update", methods=["POST"])
@role_required("SUPER_ADMIN")
def update_location(location_id):
    from app import get_demo_db, get_live_db
    demo_db = get_demo_db()
    live_db = get_live_db()
    user = current_user()
    block = request.form.get("block", "").strip()
    floor = request.form.get("floor", "").strip()
    room_no = request.form.get("room_no", "").strip()
    name = request.form.get("name", "").strip()
    if not all([block, floor, room_no]):
        flash("Block, Floor, and Room Number are required.", "error")
        return redirect(url_for("management.location_management"))
    try:
        live_db.update_location(location_id, block, floor, room_no, name)
        demo_db.log_audit_event("LOCATION_UPDATED", user["id"], user["org_id"],
                                target_type="location", target_id=location_id,
                                details={"block": block, "floor": floor, "room_no": room_no})
        flash("Location updated successfully.", "success")
    except Exception as e:
        flash(f"Failed to update location: {e}", "error")
    return redirect(url_for("management.location_management"))


@management_bp.route("/super-admin/locations/<int:location_id>/delete", methods=["POST"])
@role_required("SUPER_ADMIN")
def delete_location(location_id):
    from app import get_demo_db, get_live_db
    demo_db = get_demo_db()
    live_db = get_live_db()
    user = current_user()
    try:
        loc = live_db.get_location(location_id)
        live_db.delete_location(location_id)
        demo_db.log_audit_event("LOCATION_DELETED", user["id"], user["org_id"],
                                target_type="location", target_id=location_id,
                                details={"block": loc.get("block") if loc else "", "room_no": loc.get("room_no") if loc else ""})
        flash("Location deleted successfully.", "success")
    except ValueError as e:
        flash(str(e), "error")
    except Exception as e:
        flash(f"Failed to delete location: {e}", "error")
    return redirect(url_for("management.location_management"))


# ── User Management Routes ──────────────────────────────────────────

@management_bp.route("/user-management", methods=["GET", "POST"])
@role_required("SUPER_ADMIN", "ADMIN", "HOD")
def user_management():
    from app import get_demo_db, get_live_db
    from db_services import ROLE_MAP
    demo_db = get_demo_db()
    live_db = get_live_db()
    user = current_user()
    if request.method == "POST":
        role = request.form.get("role", "").strip().upper()
        if user["role"] == "HOD":
            if role not in ("CA", "FACULTY"):
                flash("Access denied: HOD can only create CA or FACULTY users.", "error")
                return redirect(url_for("management.user_management"))
            if role == "CA":
                selected_depts = [d.strip() for d in request.form.getlist("department") if d.strip()]
                if user["department"] not in selected_depts:
                    selected_depts.append(user["department"])
                department = ",".join(selected_depts)
            else:
                department = user["department"]
        else:
            if user["role"] != "SUPER_ADMIN" and role == "SUPER_ADMIN":
                flash("Access denied: Only SUPER_ADMIN can create SUPER_ADMIN users.", "error")
                return redirect(url_for("management.user_management"))
            if role == "CA":
                department = ",".join([d.strip() for d in request.form.getlist("department") if d.strip()])
            else:
                department = request.form.get("department", "").strip()

        payload = {
            "name": request.form.get("name", "").strip(),
            "email": request.form.get("email", "").strip().lower(),
            "password": request.form.get("password", "").strip() or "123",
            "role": role,
            "department": department,
        }
        if not all([payload["name"], payload["email"], payload["role"], payload["department"]]):
            flash("All user fields are required.", "error")
            return redirect(url_for("management.user_management"))
        if len(payload["name"]) > 120:
            flash("Name cannot exceed 120 characters.", "error")
            return redirect(url_for("management.user_management"))
        if len(payload["email"]) > 190:
            flash("Email cannot exceed 190 characters.", "error")
            return redirect(url_for("management.user_management"))
        if not is_valid_email(payload["email"]):
            flash("Please enter a valid email address.", "error")
            return redirect(url_for("management.user_management"))

        target_org = resolve_user_org(payload["email"], payload["department"])
        if target_org != user["org_id"]:
            flash(f"Access denied: User details do not resolve to your organization ({user['org_id']}).", "error")
            return redirect(url_for("management.user_management"))

        existing = demo_db.list_users(search=payload["email"])
        if any(u["email"].lower() == payload["email"] for u in existing):
            flash(f"A user with email '{payload['email']}' already exists.", "error")
            return redirect(url_for("management.user_management"))
        demo_db.create_user(payload)
        demo_db.log_audit_event(
            "USER_CREATED", user["id"], user["org_id"],
            target_type="user", target_id=None,
            details={"email": payload["email"], "role": payload["role"], "department": payload["department"]},
        )
        flash("Demo user created successfully.", "success")
        return redirect(url_for("management.user_management"))

    search = request.args.get("q", "").strip()
    roles_filter = [r.upper() for r in request.args.getlist("role") if r.strip()]
    department = request.args.get("department", "").strip() or None

    if user["role"] == "HOD":
        department = user["department"]
        roles_list = ["CA", "FACULTY"]
    else:
        roles_list = list(ROLE_MAP.keys()) if user["role"] == "SUPER_ADMIN" else [r for r in ROLE_MAP.keys() if r != "SUPER_ADMIN"]

    role_arg = roles_filter if len(roles_filter) > 1 else (roles_filter[0] if roles_filter else None)
    users = demo_db.list_users(role=role_arg, department=department, search=search, org_id=user["org_id"])
    if user["role"] == "HOD":
        users = [u for u in users if u["role"] in ("CA", "FACULTY")]
    
    # Server-side pagination to prevent browser freezing on large user directories
    page = safe_int(request.args.get("page", "1")) or 1
    per_page = 50
    total_users = len(users)
    total_pages = max(1, (total_users + per_page - 1) // per_page)
    page = min(max(1, page), total_pages)
    start_idx = (page - 1) * per_page
    paginated_users = users[start_idx:start_idx + per_page]

    departments = live_departments(user["org_id"])
    return render_template(
        "user_management.html",
        users=paginated_users,
        total_users=total_users,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
        departments=departments,
        filters={"q": search, "role": roles_filter[0] if len(roles_filter) == 1 else "", "roles": roles_filter, "department": department or ""},
        roles=roles_list,
        **page_context("User Management"),
    )


@management_bp.route("/user-management/<int:user_id>/update", methods=["POST"])
@role_required("SUPER_ADMIN", "ADMIN", "HOD")
def update_user(user_id):
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    target_user = demo_db.get_user(user_id)
    if not target_user:
        flash("User not found.", "error")
        return redirect(url_for("management.user_management"))

    target_org = resolve_user_org(target_user["email"], target_user["department"])
    if target_org != user["org_id"]:
        flash("Access denied: User belongs to a different organization.", "error")
        return redirect(url_for("management.user_management"))

    if user["role"] == "HOD":
        target_depts = [d.strip() for d in target_user["department"].split(",")]
        if user["department"] not in target_depts:
            flash("Access denied: You can only modify users in your own department.", "error")
            return redirect(url_for("management.user_management"))
        if target_user["role"] not in ("CA", "FACULTY"):
            flash("Access denied: You can only modify CA or FACULTY users.", "error")
            return redirect(url_for("management.user_management"))

        role = request.form.get("role", "").strip().upper()
        if role not in ("CA", "FACULTY"):
            flash("Access denied: You can only assign CA or FACULTY role.", "error")
            return redirect(url_for("management.user_management"))

        if role == "CA":
            selected_depts = [d.strip() for d in request.form.getlist("department") if d.strip()]
            if user["department"] not in selected_depts:
                selected_depts.append(user["department"])
            department = ",".join(selected_depts)
        else:
            department = user["department"]
    else:
        role = request.form.get("role", "").strip().upper()
        if user["role"] != "SUPER_ADMIN":
            if target_user["role"] == "SUPER_ADMIN":
                flash("Access denied: Cannot modify SUPER_ADMIN users.", "error")
                return redirect(url_for("management.user_management"))
            if role == "SUPER_ADMIN":
                flash("Access denied: Cannot assign SUPER_ADMIN role.", "error")
                return redirect(url_for("management.user_management"))

        if role == "CA":
            department = ",".join([d.strip() for d in request.form.getlist("department") if d.strip()])
        else:
            department = request.form.get("department", "").strip()

    password = request.form.get("password", "").strip()
    payload = {
        "name": request.form.get("name", "").strip() or target_user["name"],
        "email": request.form.get("email", "").strip().lower() or target_user["email"],
        "role": role or target_user["role"],
        "department": department or target_user["department"],
    }
    if password:
        payload["password"] = password
    if not all([payload["name"], payload["email"], payload["role"], payload["department"]]):
        flash("All user fields are required.", "error")
        return redirect(url_for("management.user_management"))
    if len(payload["name"]) > 120:
        flash("Name cannot exceed 120 characters.", "error")
        return redirect(url_for("management.user_management"))
    if len(payload["email"]) > 190:
        flash("Email cannot exceed 190 characters.", "error")
        return redirect(url_for("management.user_management"))
    if not is_valid_email(payload["email"]):
        flash("Please enter a valid email address.", "error")
        return redirect(url_for("management.user_management"))

    new_org = resolve_user_org(payload["email"], payload["department"])
    if new_org != user["org_id"]:
        flash(f"Access denied: Updated details do not resolve to your organization ({user['org_id']}).", "error")
        return redirect(url_for("management.user_management"))

    demo_db.update_user(user_id, payload)
    flash("Demo user updated.", "success")
    return redirect(url_for("management.user_management"))


@management_bp.route("/user-management/<int:user_id>/delete", methods=["POST"])
@role_required("SUPER_ADMIN", "ADMIN", "HOD")
def delete_user(user_id):
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    target_user = demo_db.get_user(user_id)
    if not target_user:
        flash("User not found.", "error")
        return redirect(url_for("management.user_management"))

    target_org = resolve_user_org(target_user["email"], target_user["department"])
    if target_org != user["org_id"]:
        flash("Access denied: User belongs to a different organization.", "error")
        return redirect(url_for("management.user_management"))

    if user["role"] == "HOD":
        target_depts = [d.strip() for d in target_user["department"].split(",")]
        if user["department"] not in target_depts:
            flash("Access denied: You can only delete users in your own department.", "error")
            return redirect(url_for("management.user_management"))
        if target_user["role"] not in ("CA", "FACULTY"):
            flash("Access denied: You can only delete CA or FACULTY users.", "error")
            return redirect(url_for("management.user_management"))
    else:
        if user["role"] != "SUPER_ADMIN" and target_user["role"] == "SUPER_ADMIN":
            flash("Access denied: Cannot delete SUPER_ADMIN users.", "error")
            return redirect(url_for("management.user_management"))

    try:
        demo_db.delete_user(user_id)
        flash("Demo user deleted.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("management.user_management"))


# ── HOD Ticket Management: Selective Ticket Reassignment ─────────────────
@management_bp.route("/hod/ticket-management", methods=["GET", "POST"])
@role_required("HOD", "SUPER_ADMIN", "ADMIN")
def hod_ticket_management():
    from app import get_demo_db, get_live_db
    demo_db = get_demo_db()
    live_db = get_live_db()
    user = current_user()

    # Determine target department
    if user["role"] == "HOD":
        dept_filter = user["department"]
    else:
        dept_filter = request.args.get("department", "").strip() or request.form.get("department", "").strip() or None

    if request.method == "POST":
        action = request.form.get("action", "").strip()
        if action == "reassign_tickets":
            source_ca_id = safe_int(request.form.get("source_ca_id", "0"))
            target_ca_id = safe_int(request.form.get("target_ca_id", "0"))
            ticket_ids = [safe_int(tid) for tid in request.form.getlist("selected_tickets") if safe_int(tid) > 0]
            if not ticket_ids:
                single_tid = safe_int(request.form.get("ticket_id", "0"))
                if single_tid > 0:
                    ticket_ids = [single_tid]
            remarks = request.form.get("remarks", "").strip()

            try:
                result = demo_db.reassign_tickets(
                    ticket_ids=ticket_ids,
                    source_ca_id=source_ca_id,
                    target_ca_id=target_ca_id,
                    actor=user,
                    remarks=remarks
                )
                flash(
                    f"Successfully transferred {result['reassigned_count']} ticket(s) from {result['source_ca_name']} to {result['target_ca_name']}.",
                    "success"
                )
            except Exception as e:
                flash(f"Reassignment failed: {e}", "error")

            return redirect(url_for("management.hod_ticket_management", ca_id=source_ca_id, department=dept_filter or ""))

    # GET Request
    selected_ca_id = safe_int(request.args.get("ca_id", "0")) or None

    # Fetch all active CAs / Assignees in the department for source and replacement selection
    if dept_filter:
        cas_in_dept = demo_db.list_users(role=["CA", "ASSIGNEE"], department=dept_filter, org_id=user["org_id"])
    else:
        cas_in_dept = demo_db.list_users(role=["CA", "ASSIGNEE"], org_id=user["org_id"])

    # Only include active users
    cas_in_dept = [ca for ca in cas_in_dept if ca.get("is_active", 1) != 0]

    # Enrich CAs with active ticket counts
    for ca in cas_in_dept:
        ca_tickets = demo_db.get_ca_open_tickets(ca["id"], department=dept_filter, org_id=user["org_id"])
        ca["open_ticket_count"] = len(ca_tickets)

    # Sort CAs by name
    cas_in_dept.sort(key=lambda x: (x.get("name") or "").upper())

    # If selected_ca_id is not provided but CAs exist, default to first CA with open tickets or first CA
    if not selected_ca_id and cas_in_dept:
        with_tickets = [ca for ca in cas_in_dept if ca.get("open_ticket_count", 0) > 0]
        selected_ca_id = with_tickets[0]["id"] if with_tickets else cas_in_dept[0]["id"]

    # Fetch tickets assigned to the selected CA
    ca_tickets = []
    selected_ca = None
    if selected_ca_id:
        selected_ca = demo_db.get_user(selected_ca_id)
        ca_tickets = demo_db.get_ca_open_tickets(selected_ca_id, department=dept_filter, org_id=user["org_id"])

    # Filter replacement candidates: strictly active CAs in the same department (excluding selected_ca_id)
    eligible_replacements = [
        u for u in cas_in_dept
        if u.get("id") != selected_ca_id
    ]
    eligible_replacements.sort(key=lambda x: (x.get("name") or "").upper())

    # Department list for Super Admin / Admin
    departments = live_departments(user["org_id"]) if user["role"] in ["SUPER_ADMIN", "ADMIN"] else []

    # Categories for filter tags
    categories = demo_db.list_categories(department=dept_filter, org_id=user["org_id"])

    ctx = page_context("Ticket Management")
    ctx.update({
        "current_page": "ticket_management",
        "dept_filter": dept_filter,
        "departments": departments,
        "cas": cas_in_dept,
        "selected_ca": selected_ca,
        "selected_ca_id": selected_ca_id,
        "tickets": ca_tickets,
        "eligible_replacements": eligible_replacements,
        "categories": categories,
    })
    return render_template("hod_ticket_management.html", **ctx)



