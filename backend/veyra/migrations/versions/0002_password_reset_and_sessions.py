# SPDX-License-Identifier: AGPL-3.0-or-later
"""Password reset tokens, forced password change, password change timestamp.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12 18:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('password_reset_tokens',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('issued_by', sa.String(length=320), nullable=False),
    sa.Column('issued_from_ip', sa.String(length=64), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_password_reset_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_password_reset_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_password_reset_tokens_token_hash'))
    )
    op.create_index(op.f('ix_password_reset_tokens_user_id'), 'password_reset_tokens', ['user_id'], unique=False)
    op.add_column('users', sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('must_change_password', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.alter_column('users', 'must_change_password', server_default=None)


def downgrade() -> None:
    op.drop_column('users', 'must_change_password')
    op.drop_column('users', 'password_changed_at')
    op.drop_index(op.f('ix_password_reset_tokens_user_id'), table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')
