# SPDX-License-Identifier: AGPL-3.0-or-later
"""Multi-factor authentication: methods, recovery codes, policy columns,
pre-authentication sessions.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-12 20:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('mfa_methods',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('type', sa.String(length=16), nullable=False),
    sa.Column('label', sa.String(length=100), nullable=False),
    sa.Column('secret_ciphertext', sa.Text(), nullable=True),
    sa.Column('credential', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('last_used_step', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_mfa_methods_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mfa_methods'))
    )
    op.create_index(op.f('ix_mfa_methods_user_id'), 'mfa_methods', ['user_id'], unique=False)
    op.create_table('mfa_recovery_codes',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('code_hash', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_mfa_recovery_codes_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mfa_recovery_codes'))
    )
    op.create_index(op.f('ix_mfa_recovery_codes_user_id'), 'mfa_recovery_codes', ['user_id'], unique=False)
    op.add_column('users', sa.Column('mfa_required_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('mfa_grace_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column('sessions', sa.Column('mfa_verified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('sessions', sa.Column('mfa_failures', sa.Integer(), server_default='0', nullable=False))
    op.alter_column('sessions', 'mfa_failures', server_default=None)
    # Sessions that exist today were created before MFA existed and must stay
    # usable: a NULL mfa_verified_at means "pre-authentication" from now on.
    op.execute("UPDATE sessions SET mfa_verified_at = created_at WHERE mfa_verified_at IS NULL")


def downgrade() -> None:
    op.drop_column('sessions', 'mfa_failures')
    op.drop_column('sessions', 'mfa_verified_at')
    op.drop_column('users', 'mfa_grace_until')
    op.drop_column('users', 'mfa_required_at')
    op.drop_index(op.f('ix_mfa_recovery_codes_user_id'), table_name='mfa_recovery_codes')
    op.drop_table('mfa_recovery_codes')
    op.drop_index(op.f('ix_mfa_methods_user_id'), table_name='mfa_methods')
    op.drop_table('mfa_methods')
