# Session Notes & Annotations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add free-text notes to targets and sessions, with auto-save and visual indicators for annotated sessions.

**Architecture:** New `session_notes` table + `notes` column on targets. PUT endpoints for saving. Frontend textareas with debounced auto-save on the Target Detail page.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), SolidJS (frontend)

---

### Task 1: Backend — SessionNote Model and Migration

**Files:**
- Create: `backend/app/models/session_note.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0016_add_notes.py`

- [ ] **Step 1: Create the SessionNote model**

Create `backend/app/models/session_note.py`:

```python
import uuid
from datetime import datetime, date

from sqlalchemy import String, Text, Date, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SessionNote(Base):
    __tablename__ = "session_notes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("targets.id"), nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("target_id", "session_date", name="uq_session_notes_target_date"),
    )
```

- [ ] **Step 2: Register the model**

In `backend/app/models/__init__.py`, add:

```python
from .session_note import SessionNote
```

Update `__all__` to include `"SessionNote"`.

- [ ] **Step 3: Create the Alembic migration**

Create `backend/alembic/versions/0016_add_notes.py`:

```python
"""Add session_notes table and target notes column."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    from sqlalchemy import inspect
    bind = op.get_bind()
    insp = inspect(bind)
    return column in [c["name"] for c in insp.get_columns(table)]


def upgrade() -> None:
    # Session notes table
    op.create_table(
        "session_notes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("target_id", UUID(as_uuid=True), sa.ForeignKey("targets.id"), nullable=False),
        sa.Column("session_date", sa.Date, nullable=False),
        sa.Column("notes", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("target_id", "session_date", name="uq_session_notes_target_date"),
        if_not_exists=True,
    )

    # Target notes column
    if not _column_exists("targets", "notes"):
        op.add_column("targets", sa.Column("notes", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("targets", "notes")
    op.drop_table("session_notes")
```

- [ ] **Step 4: Run the migration**

```bash
cd backend && alembic upgrade head
```

Expected: `Running upgrade 0015 -> 0016, Add session_notes table and target notes column.`

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/session_note.py backend/app/models/__init__.py backend/alembic/versions/0016_add_notes.py
git commit -m "feat: add session_notes table and target notes column"
```

---

### Task 2: Backend — Add Notes Column to Target Model

**Files:**
- Modify: `backend/app/models/target.py`

- [ ] **Step 1: Add the notes field to the Target model**

In `backend/app/models/target.py`, add after the `surface_brightness` field (around line 27):

```python
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Also add `Text` to the imports from sqlalchemy:

```python
from sqlalchemy import String, Float, Index, ForeignKey, DateTime, Text
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/models/target.py
git commit -m "feat: add notes field to Target model"
```

---

### Task 3: Backend — Notes API Endpoints

**Files:**
- Modify: `backend/app/api/targets.py`
- Modify: `backend/app/schemas/target.py`

- [ ] **Step 1: Add notes to schemas**

In `backend/app/schemas/target.py`, add a schema for notes requests:

```python
class NotesUpdate(BaseModel):
    notes: str | None = None
```

Add `notes` field to `TargetDetailResponse`:

```python
    notes: str | None = None
```

Add `notes` field to `SessionDetailResponse`:

```python
    notes: str | None = None
```

Add `notes` field to `SessionOverview` (so collapsed sessions show the indicator):

```python
    has_notes: bool = False
```

- [ ] **Step 2: Add target notes endpoint**

In `backend/app/api/targets.py`, add the import:

```python
from app.models.session_note import SessionNote
from app.schemas.target import NotesUpdate
```

Add the endpoint:

```python
@router.put("/{target_id}/notes")
async def update_target_notes(
    target_id: uuid.UUID,
    body: NotesUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    target = await session.get(Target, target_id)
    if not target:
        raise HTTPException(404, "Target not found")
    target.notes = body.notes if body.notes else None
    await session.commit()
    return {"status": "ok"}
```

- [ ] **Step 3: Add session notes endpoint**

```python
@router.put("/{target_id}/sessions/{date}/notes")
async def update_session_notes(
    target_id: str,
    date: str,
    body: NotesUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    from datetime import date as date_type
    session_date = date_type.fromisoformat(date)

    # Resolve target_id (may be UUID or obj:name)
    resolved_id = None
    try:
        resolved_id = uuid.UUID(target_id)
    except ValueError:
        if target_id.startswith("obj:"):
            name = target_id[4:]
            tq = select(Target.id).where(Target.primary_name == name)
            row = (await session.execute(tq)).scalar_one_or_none()
            if row:
                resolved_id = row
    if not resolved_id:
        raise HTTPException(404, "Target not found")

    # Upsert note
    if not body.notes:
        # Delete if empty
        q = select(SessionNote).where(
            SessionNote.target_id == resolved_id,
            SessionNote.session_date == session_date,
        )
        note = (await session.execute(q)).scalar_one_or_none()
        if note:
            await session.delete(note)
            await session.commit()
    else:
        q = select(SessionNote).where(
            SessionNote.target_id == resolved_id,
            SessionNote.session_date == session_date,
        )
        note = (await session.execute(q)).scalar_one_or_none()
        if note:
            note.notes = body.notes
        else:
            note = SessionNote(
                target_id=resolved_id,
                session_date=session_date,
                notes=body.notes,
            )
            session.add(note)
        await session.commit()

    return {"status": "ok"}
```

- [ ] **Step 4: Include notes in existing target detail response**

In the `get_target_detail` endpoint, where `TargetDetailResponse` is constructed, add the `notes` field from the target object:

```python
    notes=target.notes,
```

- [ ] **Step 5: Include has_notes flag in session overviews**

In the `get_target_detail` endpoint, after fetching images, query for session notes for this target:

```python
    note_dates_q = select(SessionNote.session_date).where(SessionNote.target_id == target.id)
    note_dates = {r[0] for r in (await session.execute(note_dates_q)).all()}
```

Then when building `SessionOverview` objects, add:

```python
    has_notes=date_type.fromisoformat(date_key) in note_dates if date_key != "unknown" else False,
```

- [ ] **Step 6: Include notes in session detail response**

In the `get_session_detail` endpoint, fetch the session note:

```python
    from datetime import date as date_type
    note_q = select(SessionNote.notes).where(
        SessionNote.target_id == resolved_id,
        SessionNote.session_date == date_type.fromisoformat(date),
    )
    session_note = (await session.execute(note_q)).scalar_one_or_none()
```

Add to the `SessionDetailResponse` construction:

```python
    notes=session_note,
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/targets.py backend/app/schemas/target.py
git commit -m "feat: add notes API endpoints for targets and sessions"
```

---

### Task 4: Frontend — Notes Types and API Methods

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Update TypeScript types**

In `frontend/src/types/index.ts`, add `notes` to `TargetDetailResponse`:

```typescript
  notes: string | null;
```

Add `notes` to `SessionDetail`:

```typescript
  notes: string | null;
```

Add `has_notes` to `SessionOverview`:

```typescript
  has_notes: boolean;
```

- [ ] **Step 2: Add API methods**

In `frontend/src/api/client.ts`, add to the `api` object:

```typescript
  updateTargetNotes: (targetId: string, notes: string | null) =>
    fetchJson<{ status: string }>(`/targets/${encodeURIComponent(targetId)}/notes`, {
      method: "PUT",
      body: JSON.stringify({ notes }),
    }),

  updateSessionNotes: (targetId: string, date: string, notes: string | null) =>
    fetchJson<{ status: string }>(`/targets/${encodeURIComponent(targetId)}/sessions/${date}/notes`, {
      method: "PUT",
      body: JSON.stringify({ notes }),
    }),
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts
git commit -m "feat: add notes API client methods and types"
```

---

### Task 5: Frontend — Target Notes UI

**Files:**
- Modify: `frontend/src/pages/TargetDetailPage.tsx`

- [ ] **Step 1: Add target notes section**

In `TargetDetailPage.tsx`, add state and save handler near the top of the component (after existing signals):

```typescript
  const [targetNotes, setTargetNotes] = createSignal<string>("");
  const [notesSaving, setNotesSaving] = createSignal(false);
  let notesTimer: ReturnType<typeof setTimeout> | undefined;

  // Initialize notes when data loads
  createEffect(() => {
    const detail = targetDetail();
    if (detail?.notes) setTargetNotes(detail.notes);
  });

  const saveTargetNotes = (text: string) => {
    clearTimeout(notesTimer);
    notesTimer = setTimeout(async () => {
      setNotesSaving(true);
      try {
        await api.updateTargetNotes(params.targetId, text || null);
      } finally {
        setNotesSaving(false);
      }
    }, 1000);
  };
```

Add the notes textarea in the JSX, after the hero stats section and before the metrics chart. Find the appropriate location (after the cumulative stats bars) and add:

```typescript
          {/* Target Notes */}
          <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
            <div class="flex items-center justify-between mb-2">
              <h3 class="text-sm font-medium text-theme-text-primary">Notes</h3>
              <Show when={notesSaving()}>
                <span class="text-xs text-theme-text-secondary">Saving...</span>
              </Show>
            </div>
            <textarea
              class="w-full bg-theme-elevated border border-theme-border rounded px-3 py-2 text-sm text-theme-text-primary placeholder-theme-text-secondary resize-y min-h-[60px]"
              placeholder="Add notes about this target..."
              value={targetNotes()}
              onInput={(e) => {
                const val = e.currentTarget.value;
                setTargetNotes(val);
                saveTargetNotes(val);
              }}
            />
          </div>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/TargetDetailPage.tsx
git commit -m "feat: add target notes textarea on detail page"
```

---

### Task 6: Frontend — Session Notes UI

**Files:**
- Modify: `frontend/src/components/SessionAccordionCard.tsx`

- [ ] **Step 1: Add session notes to the accordion card**

In `SessionAccordionCard.tsx`, add to the component props:

```typescript
  targetId?: string;
```

Add state for the session note inside the component:

```typescript
  const [sessionNote, setSessionNote] = createSignal(props.detail?.notes || "");
  const [noteSaving, setNoteSaving] = createSignal(false);
  let noteTimer: ReturnType<typeof setTimeout> | undefined;

  // Sync when detail loads
  createEffect(() => {
    if (props.detail?.notes !== undefined) {
      setSessionNote(props.detail.notes || "");
    }
  });

  const saveSessionNote = (text: string) => {
    if (!props.targetId) return;
    clearTimeout(noteTimer);
    noteTimer = setTimeout(async () => {
      setNoteSaving(true);
      try {
        await api.updateSessionNotes(props.targetId!, props.session.session_date, text || null);
      } finally {
        setNoteSaving(false);
      }
    }, 1000);
  };
```

Add a note indicator icon on the collapsed header row, next to the expand button. Add a small SVG icon that is filled when `props.session.has_notes` is true:

```typescript
  {/* Note indicator */}
  <span
    class={`inline-block w-4 h-4 ${props.session.has_notes ? "text-theme-accent" : "text-theme-text-secondary opacity-30"}`}
    title={props.session.has_notes ? "Has notes" : "No notes"}
  >
    <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
      <path d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" />
    </svg>
  </span>
```

Add the notes textarea in the expanded section, after the existing content but before the closing div:

```typescript
  {/* Session Notes */}
  <div class="mt-4 pt-4 border-t border-theme-border">
    <div class="flex items-center justify-between mb-2">
      <h4 class="text-xs font-medium text-theme-text-secondary uppercase tracking-wide">Session Notes</h4>
      <Show when={noteSaving()}>
        <span class="text-xs text-theme-text-secondary">Saving...</span>
      </Show>
    </div>
    <textarea
      class="w-full bg-theme-elevated border border-theme-border rounded px-3 py-2 text-sm text-theme-text-primary placeholder-theme-text-secondary resize-y min-h-[50px]"
      placeholder="Add notes for this session..."
      value={sessionNote()}
      onInput={(e) => {
        const val = e.currentTarget.value;
        setSessionNote(val);
        saveSessionNote(val);
      }}
    />
  </div>
```

- [ ] **Step 2: Pass targetId to SessionAccordionCard**

In `TargetDetailPage.tsx`, update the `<SessionAccordionCard>` call to pass `targetId`:

```typescript
  targetId={params.targetId}
```

- [ ] **Step 3: Verify in browser**

Navigate to a target detail page. Verify:
- Target notes textarea appears below the hero section
- Typing triggers auto-save after 1 second (shows "Saving...")
- Expanding a session shows the session notes textarea
- Sessions with notes show a filled icon on the collapsed row
- Notes persist after page refresh

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/SessionAccordionCard.tsx frontend/src/pages/TargetDetailPage.tsx
git commit -m "feat: add session notes UI with auto-save and indicators"
```
