# SPDX-License-Identifier: AGPL-3.0-or-later
"""Passkeys (issue #107): the pending WebAuthn challenge of a session, and
passkeys allowed in a stored two-factor policy written before they existed.

Revision ID: 0065
Revises: 0064
Create Date: 2026-10-21 01:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0065"
down_revision: str | None = "0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("webauthn_challenge", sa.Text(), nullable=True))
    # Until now the only method was the authenticator app: a stored policy
    # listing only it predates passkeys rather than refusing them.
    op.execute(
        """
        UPDATE system_settings
           SET value = jsonb_set(value, '{allowed_methods}', '["totp", "webauthn"]'::jsonb)
         WHERE key = 'security.mfa'
           AND value -> 'allowed_methods' = '["totp"]'::jsonb
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE system_settings
           SET value = jsonb_set(value, '{allowed_methods}', '["totp"]'::jsonb)
         WHERE key = 'security.mfa'
        """
    )
    op.drop_column("sessions", "webauthn_challenge")
