# SPDX-License-Identifier: AGPL-3.0-or-later
"""Core schema: tenancy, identity, audit, modules, updates, HA, configuration, provisioning.

Revision ID: 0001
Revises: 
Create Date: 2026-10-12 16:08:58.892768
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('audit_log',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_type', sa.String(length=16), nullable=False),
    sa.Column('actor_user_id', sa.UUID(), nullable=True),
    sa.Column('actor_label', sa.String(length=320), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=True),
    sa.Column('action', sa.String(length=128), nullable=False),
    sa.Column('target_type', sa.String(length=64), nullable=True),
    sa.Column('target_id', sa.String(length=128), nullable=True),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    op.create_index('ix_audit_log_occurred_at', 'audit_log', ['occurred_at'], unique=False)
    op.create_index('ix_audit_log_org_occurred', 'audit_log', ['organization_id', 'occurred_at'], unique=False)
    op.create_table('available_updates',
    sa.Column('component', sa.String(length=32), nullable=False),
    sa.Column('target', sa.String(length=128), nullable=False),
    sa.Column('version', sa.String(length=64), nullable=False),
    sa.Column('current_version', sa.String(length=64), nullable=True),
    sa.Column('channel', sa.String(length=16), nullable=False),
    sa.Column('category', sa.String(length=16), nullable=False),
    sa.Column('release_notes', sa.Text(), nullable=True),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_available_updates')),
    sa.UniqueConstraint('component', 'target', 'version', name=op.f('uq_available_updates_component_target_version'))
    )
    op.create_table('cluster_nodes',
    sa.Column('node_name', sa.String(length=128), nullable=False),
    sa.Column('hostname', sa.String(length=255), nullable=False),
    sa.Column('address', sa.String(length=255), nullable=True),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('software_version', sa.String(length=64), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cluster_nodes')),
    sa.UniqueConstraint('node_name', name=op.f('uq_cluster_nodes_node_name'))
    )
    op.create_table('config_revisions',
    sa.Column('sequence', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('engine', sa.String(length=32), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('artifacts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('validation_errors', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('parent_id', sa.UUID(), nullable=True),
    sa.Column('created_by', sa.String(length=320), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deployed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['parent_id'], ['config_revisions.id'], name=op.f('fk_config_revisions_parent_id_config_revisions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_config_revisions')),
    sa.UniqueConstraint('sequence', name=op.f('uq_config_revisions_sequence'))
    )
    op.create_table('installation',
    sa.Column('instance_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('deployment_mode', sa.String(length=32), nullable=False),
    sa.Column('multi_tenancy_enabled', sa.Boolean(), nullable=False),
    sa.Column('central_management_enabled', sa.Boolean(), nullable=False),
    sa.Column('setup_completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_installation')),
    sa.UniqueConstraint('instance_id', name=op.f('uq_installation_instance_id'))
    )
    op.create_table('installed_modules',
    sa.Column('module_id', sa.String(length=128), nullable=False),
    sa.Column('version', sa.String(length=64), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('trust_level', sa.String(length=16), nullable=False),
    sa.Column('signature_verified', sa.Boolean(), nullable=False),
    sa.Column('source_path', sa.Text(), nullable=False),
    sa.Column('manifest', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('module_id', name=op.f('pk_installed_modules'))
    )
    op.create_table('organizations',
    sa.Column('slug', sa.String(length=63), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_organizations')),
    sa.UniqueConstraint('slug', name=op.f('uq_organizations_slug'))
    )
    op.create_table('permissions',
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=False),
    sa.Column('module_id', sa.String(length=128), nullable=False),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_permissions'))
    )
    op.create_table('system_settings',
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_system_settings'))
    )
    op.create_table('update_checks',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('message', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_update_checks'))
    )
    op.create_table('update_history',
    sa.Column('component', sa.String(length=32), nullable=False),
    sa.Column('target', sa.String(length=128), nullable=False),
    sa.Column('from_version', sa.String(length=64), nullable=True),
    sa.Column('to_version', sa.String(length=64), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('initiated_by', sa.String(length=320), nullable=False),
    sa.Column('node_id', sa.UUID(), nullable=True),
    sa.Column('backup_ref', sa.Text(), nullable=True),
    sa.Column('log', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_update_history'))
    )
    op.create_table('update_policies',
    sa.Column('component', sa.String(length=32), nullable=False),
    sa.Column('mode', sa.String(length=32), nullable=False),
    sa.Column('channel', sa.String(length=16), nullable=False),
    sa.Column('check_enabled', sa.Boolean(), nullable=False),
    sa.Column('check_interval_hours', sa.Integer(), nullable=False),
    sa.Column('auto_download', sa.Boolean(), nullable=False),
    sa.Column('auto_install_categories', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('require_approval', sa.Boolean(), nullable=False),
    sa.Column('notify_admins', sa.Boolean(), nullable=False),
    sa.Column('maintenance_window', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('component', name=op.f('pk_update_policies'))
    )
    op.create_table('cluster_events',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('node_id', sa.UUID(), nullable=True),
    sa.Column('actor_label', sa.String(length=320), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['node_id'], ['cluster_nodes.id'], name=op.f('fk_cluster_events_node_id_cluster_nodes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cluster_events'))
    )
    op.create_table('module_configs',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('module_id', sa.String(length=128), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=True),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_module_configs_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_module_configs')),
    sa.UniqueConstraint('module_id', 'organization_id', name=op.f('uq_module_configs_module_id_organization_id'))
    )
    op.create_table('provisioning_templates',
    sa.Column('template_key', sa.String(length=128), nullable=False),
    sa.Column('version', sa.String(length=64), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=True),
    sa.Column('manifest', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('files', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_provisioning_templates_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_provisioning_templates')),
    sa.UniqueConstraint('template_key', 'version', name=op.f('uq_provisioning_templates_template_key_version'))
    )
    op.create_table('roles',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=False),
    sa.Column('is_system', sa.Boolean(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_roles_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_roles')),
    sa.UniqueConstraint('organization_id', 'key', name=op.f('uq_roles_organization_id_key'))
    )
    op.create_table('sites',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('slug', sa.String(length=63), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=True),
    sa.Column('street', sa.String(length=200), nullable=True),
    sa.Column('city', sa.String(length=100), nullable=True),
    sa.Column('region', sa.String(length=100), nullable=True),
    sa.Column('postal_code', sa.String(length=20), nullable=True),
    sa.Column('country', sa.String(length=2), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_sites_organization_id_organizations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sites')),
    sa.UniqueConstraint('organization_id', 'slug', name=op.f('uq_sites_organization_id_slug'))
    )
    op.create_index(op.f('ix_sites_organization_id'), 'sites', ['organization_id'], unique=False)
    op.create_table('users',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('display_name', sa.String(length=200), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=True),
    sa.Column('auth_source', sa.String(length=32), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('is_recovery_admin', sa.Boolean(), nullable=False),
    sa.Column('home_organization_id', sa.UUID(), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failed_login_count', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['home_organization_id'], ['organizations.id'], name=op.f('fk_users_home_organization_id_organizations'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_table('buildings',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('site_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_buildings_organization_id_organizations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], name=op.f('fk_buildings_site_id_sites'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_buildings')),
    sa.UniqueConstraint('site_id', 'name', name=op.f('uq_buildings_site_id_name'))
    )
    op.create_index(op.f('ix_buildings_organization_id'), 'buildings', ['organization_id'], unique=False)
    op.create_table('departments',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('site_id', sa.UUID(), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_departments_organization_id_organizations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], name=op.f('fk_departments_site_id_sites'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_departments')),
    sa.UniqueConstraint('organization_id', 'name', name=op.f('uq_departments_organization_id_name'))
    )
    op.create_index(op.f('ix_departments_organization_id'), 'departments', ['organization_id'], unique=False)
    op.create_table('role_assignments',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('role_id', sa.UUID(), nullable=False),
    sa.Column('scope_type', sa.String(length=16), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=True),
    sa.Column('site_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(scope_type = 'platform' AND organization_id IS NULL AND site_id IS NULL) OR (scope_type = 'organization' AND organization_id IS NOT NULL AND site_id IS NULL) OR (scope_type = 'site' AND organization_id IS NOT NULL AND site_id IS NOT NULL)", name=op.f('ck_role_assignments_scope_consistent')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_role_assignments_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], name=op.f('fk_role_assignments_role_id_roles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], name=op.f('fk_role_assignments_site_id_sites'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_role_assignments_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_role_assignments')),
    sa.UniqueConstraint('user_id', 'role_id', 'scope_type', 'organization_id', 'site_id', name=op.f('uq_role_assignments_user_id_role_id_scope_type_organization_id_site_id'))
    )
    op.create_index(op.f('ix_role_assignments_user_id'), 'role_assignments', ['user_id'], unique=False)
    op.create_table('role_permissions',
    sa.Column('role_id', sa.UUID(), nullable=False),
    sa.Column('permission_key', sa.String(length=128), nullable=False),
    sa.ForeignKeyConstraint(['permission_key'], ['permissions.key'], name=op.f('fk_role_permissions_permission_key_permissions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], name=op.f('fk_role_permissions_role_id_roles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('role_id', 'permission_key', name=op.f('pk_role_permissions'))
    )
    op.create_table('sessions',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('csrf_token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=500), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_sessions_token_hash'))
    )
    op.create_index(op.f('ix_sessions_user_id'), 'sessions', ['user_id'], unique=False)
    op.create_table('extensions',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('site_id', sa.UUID(), nullable=True),
    sa.Column('department_id', sa.UUID(), nullable=True),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('number', sa.String(length=32), nullable=False),
    sa.Column('display_name', sa.String(length=200), nullable=False),
    sa.Column('endpoint_name', sa.String(length=80), nullable=False),
    sa.Column('sip_secret_ciphertext', sa.Text(), nullable=True),
    sa.Column('caller_id_name', sa.String(length=80), nullable=True),
    sa.Column('caller_id_number', sa.String(length=32), nullable=True),
    sa.Column('is_enabled', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_extensions_department_id_departments'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_extensions_organization_id_organizations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], name=op.f('fk_extensions_site_id_sites'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_extensions_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_extensions')),
    sa.UniqueConstraint('endpoint_name', name=op.f('uq_extensions_endpoint_name')),
    sa.UniqueConstraint('organization_id', 'number', name=op.f('uq_extensions_organization_id_number'))
    )
    op.create_index(op.f('ix_extensions_organization_id'), 'extensions', ['organization_id'], unique=False)
    op.create_table('devices',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('site_id', sa.UUID(), nullable=True),
    sa.Column('mac_address', sa.String(length=12), nullable=False),
    sa.Column('manufacturer', sa.String(length=64), nullable=False),
    sa.Column('model', sa.String(length=64), nullable=False),
    sa.Column('label', sa.String(length=200), nullable=True),
    sa.Column('template_key', sa.String(length=128), nullable=True),
    sa.Column('primary_extension_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_devices_organization_id_organizations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['primary_extension_id'], ['extensions.id'], name=op.f('fk_devices_primary_extension_id_extensions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], name=op.f('fk_devices_site_id_sites'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_devices')),
    sa.UniqueConstraint('mac_address', name=op.f('uq_devices_mac_address'))
    )
    op.create_index(op.f('ix_devices_organization_id'), 'devices', ['organization_id'], unique=False)

    # The audit log is append-only. UPDATE is always refused; DELETE is only
    # allowed inside a transaction that has explicitly set
    # veyra.audit_retention = 'on' (the audited retention job).
    op.execute("""
        CREATE FUNCTION veyra_audit_log_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE'
               AND coalesce(current_setting('veyra.audit_retention', true), '') = 'on' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'audit_log is append-only';
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION veyra_audit_log_guard();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS veyra_audit_log_guard()")
    op.drop_index(op.f('ix_devices_organization_id'), table_name='devices')
    op.drop_table('devices')
    op.drop_index(op.f('ix_extensions_organization_id'), table_name='extensions')
    op.drop_table('extensions')
    op.drop_index(op.f('ix_sessions_user_id'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_table('role_permissions')
    op.drop_index(op.f('ix_role_assignments_user_id'), table_name='role_assignments')
    op.drop_table('role_assignments')
    op.drop_index(op.f('ix_departments_organization_id'), table_name='departments')
    op.drop_table('departments')
    op.drop_index(op.f('ix_buildings_organization_id'), table_name='buildings')
    op.drop_table('buildings')
    op.drop_table('users')
    op.drop_index(op.f('ix_sites_organization_id'), table_name='sites')
    op.drop_table('sites')
    op.drop_table('roles')
    op.drop_table('provisioning_templates')
    op.drop_table('module_configs')
    op.drop_table('cluster_events')
    op.drop_table('update_policies')
    op.drop_table('update_history')
    op.drop_table('update_checks')
    op.drop_table('system_settings')
    op.drop_table('permissions')
    op.drop_table('organizations')
    op.drop_table('installed_modules')
    op.drop_table('installation')
    op.drop_table('config_revisions')
    op.drop_table('cluster_nodes')
    op.drop_table('available_updates')
    op.drop_index('ix_audit_log_org_occurred', table_name='audit_log')
    op.drop_index('ix_audit_log_occurred_at', table_name='audit_log')
    op.drop_table('audit_log')
