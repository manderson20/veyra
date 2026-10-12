"""Create the notes table.

Revision ID: notes_0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "notes_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mod_example_notes_note",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_mod_example_notes_note_organization_id", "mod_example_notes_note", ["organization_id"]
    )


def downgrade() -> None:
    op.drop_table("mod_example_notes_note")
