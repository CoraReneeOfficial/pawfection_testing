"""
Migration script to add the Receipt table for finalized receipts
"""
from alembic import op
import sqlalchemy as sa
import datetime

# revision identifiers, used by Alembic.
revision = '20250704_add_receipt_table'
down_revision = None  # Set this to the previous migration's revision ID if not initial
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'receipt',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('appointment_id', sa.Integer(), sa.ForeignKey('appointment.id'), nullable=False),
        sa.Column('store_id', sa.Integer(), sa.ForeignKey('store.id'), nullable=False),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('owner.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), default=datetime.datetime.utcnow, nullable=False),
        sa.Column('receipt_json', sa.Text(), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=True)
    )

def downgrade():
    op.drop_table('receipt')
