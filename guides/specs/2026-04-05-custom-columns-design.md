# Custom Columns & Column Visibility

## Overview

User-defined columns with custom values on targets, sessions, and rigs, plus the ability to hide/show any column (built-in or custom) in the dashboard and session tables.

## Requirements

- Users can define custom columns with a name, type (boolean, text, dropdown), and scope (target, session, rig)
- Column definitions are shared across all users
- Column values are shared across all users
- Each user independently controls which columns (built-in + custom) are visible in each table
- Target Name and Date columns are always visible (not hideable)

## Data Model

### `custom_column` table

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `name` | String | Display name, e.g. "Processed" |
| `slug` | String | Unique, URL-safe key, auto-generated from name |
| `column_type` | Enum | `boolean`, `text`, `dropdown` |
| `applies_to` | Enum | `target`, `session`, `rig` |
| `dropdown_options` | ARRAY(String) | Only used when `column_type = dropdown`, nullable |
| `display_order` | Integer | Controls column ordering in tables |
| `created_by` | UUID FK | References user who created it |
| `created_at` | DateTime | |

### `custom_column_value` table

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | PK |
| `column_id` | UUID FK | References `custom_column` |
| `target_id` | UUID FK | References `target`, always set |
| `session_date` | Date | Null for target-level columns |
| `rig_label` | String | Null for target-level and session-level columns |
| `value` | String | Stores all types as string ("true"/"false", free text, or dropdown value) |
| `updated_by` | UUID FK | Last user who set the value |
| `updated_at` | DateTime | |

**Uniqueness:** Enforced via a unique index on `(column_id, target_id, COALESCE(session_date, '1970-01-01'), COALESCE(rig_label, ''))` to handle nullable columns correctly in PostgreSQL (where `NULL != NULL` in standard unique constraints).

Sessions are identified by `target_id + session_date` (no separate session table). Adding `rig_label` gives rig-level granularity.

## Column Visibility

Extends `UserSettings.display` JSONB with a new `column_visibility` key:

```json
{
  "column_visibility": {
    "dashboard": {
      "builtin": {
        "designation": true,
        "palette": true,
        "integration": true,
        "equipment": false,
        "last_session": true
      },
      "custom": {
        "<column-slug>": true,
        "<column-slug>": false
      }
    },
    "session_table": {
      "builtin": {
        "frames": true,
        "integration": true,
        "filters": true
      },
      "custom": {
        "<column-slug>": true
      }
    },
    "session_detail": {
      "custom": {
        "<column-slug>": true
      }
    }
  }
}
```

**Defaults:** All built-in columns visible. New custom columns default to visible until explicitly hidden.

The existing `DisplaySettings` metric group toggles (quality, guiding, ADU, etc.) remain unchanged -- this is additive.

## API Design

### Custom Column CRUD

- `GET /api/custom-columns` -- list all column definitions
- `POST /api/custom-columns` -- create a new column (any user)
- `PATCH /api/custom-columns/{id}` -- update name, dropdown options, display order
- `DELETE /api/custom-columns/{id}` -- delete column and all its values

### Custom Column Values

- `GET /api/targets/{target_id}/custom-values` -- all custom values for a target (includes session and rig level)
- `PUT /api/targets/{target_id}/custom-values` -- set one or more values:
  ```json
  {
    "column_id": "uuid",
    "session_date": null,
    "rig_label": null,
    "value": "true"
  }
  ```

### Integration with Existing Endpoints

- `GET /api/targets/aggregates` gains `include_custom=true` query param to include custom column values alongside each target, avoiding N+1 queries.
- `GET /api/targets/{target_id}/session/{date}` response gains a `custom_values` field with session-level and rig-level values.
- Column visibility managed through the existing `PATCH /api/settings` endpoint (lives in `UserSettings.display`).

## Frontend UX

### Column Picker

A "Columns" icon button in the table header area of the dashboard and session tables. Opens a popover with a checklist of all columns, grouped into "Built-in" and "Custom" sections. Toggling a checkbox immediately shows/hides the column and persists to settings.

### Custom Column Management

A new "Custom Columns" tab in the Settings page (alongside General, Display, Filters, Equipment). Provides:

- Create new columns (name, type, applies_to, dropdown options)
- Edit existing columns (rename, add/remove dropdown options)
- Reorder columns (drag or up/down arrows)
- Delete columns (with confirmation since it removes all values)

### Setting Values

- **Dashboard table:** Target-level custom columns as inline-editable cells -- booleans as checkboxes, text as click-to-edit, dropdowns as a select.
- **Session table:** Session-level custom columns as inline-editable cells in session summary rows.
- **Session detail (rig level):** Rig-level custom columns within each rig's section in SessionAccordionCard, editable inline.

### Sorting

Custom columns in the dashboard support client-side sorting:
- Boolean: false-first / true-first
- Text: alphabetical
- Dropdown: by option order
