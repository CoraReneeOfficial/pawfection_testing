"""
Add tax_enabled column to Store
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('store', sa.Column('tax_enabled', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.execute('UPDATE store SET tax_enabled = TRUE')

def downgrade():
    op.drop_column('store', 'tax_enabled')
