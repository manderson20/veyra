# SPDX-License-Identifier: AGPL-3.0-or-later
"""Name the classes_of_service unique constraint after the models' naming
convention (0038 called it uq_classes_of_service_organization_id, so
``alembic check`` saw a drop and a re-create on every run).

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-18 08:55:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_classes_of_service_organization_id", "classes_of_service", type_="unique"
    )
    op.create_unique_constraint(
        op.f("uq_classes_of_service_organization_id_name"),
        "classes_of_service",
        ["organization_id", "name"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("uq_classes_of_service_organization_id_name"), "classes_of_service", type_="unique"
    )
    op.create_unique_constraint(
        "uq_classes_of_service_organization_id", "classes_of_service", ["organization_id", "name"]
    )
