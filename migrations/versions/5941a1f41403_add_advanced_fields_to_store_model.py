"""Add advanced fields to Store model

Revision ID: 5941a1f41403
Revises: 88222e441266
Create Date: 2025-06-10 17:37:58.200303

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5941a1f41403'
down_revision = '88222e441266'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('store', schema=None) as batch_op:
        batch_op.add_column(sa.Column('logo_filename', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('status', sa.String(length=20), nullable=False))
        batch_op.add_column(sa.Column('business_hours', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('description', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('facebook_url', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('instagram_url', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('website_url', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('tax_id', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('notification_preferences', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('default_appointment_duration', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('default_appointment_buffer', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('payment_settings', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('is_archived', sa.Boolean(), nullable=False))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('store', schema=None) as batch_op:
        batch_op.drop_column('is_archived')
        batch_op.drop_column('payment_settings')
        batch_op.drop_column('default_appointment_buffer')
        batch_op.drop_column('default_appointment_duration')
        batch_op.drop_column('notification_preferences')
        batch_op.drop_column('tax_id')
        batch_op.drop_column('website_url')
        batch_op.drop_column('instagram_url')
        batch_op.drop_column('facebook_url')
        batch_op.drop_column('description')
        batch_op.drop_column('business_hours')
        batch_op.drop_column('status')
        batch_op.drop_column('logo_filename')

    # ### end Alembic commands ###
