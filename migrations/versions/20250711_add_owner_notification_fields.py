"""Add owner notification fields

Revision ID: abcdef123456
Revises: 5941a1f41403
Create Date: 2025-07-11 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'abcdef123456'
down_revision = '5941a1f41403'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('owner', schema=None) as batch_op:
        batch_op.add_column(sa.Column('phone_carrier', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('text_notifications_enabled', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('email_notifications_enabled', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    with op.batch_alter_table('owner', schema=None) as batch_op:
        batch_op.drop_column('email_notifications_enabled')
        batch_op.drop_column('text_notifications_enabled')
        batch_op.drop_column('phone_carrier')
