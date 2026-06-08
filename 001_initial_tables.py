"""Initial tables

Revision ID: 001
Create Date: 2025-01-01
"""
from alembic import op
import sqlalchemy as sa

revision = '001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('users',
        sa.Column('id',           sa.Integer(),     primary_key=True),
        sa.Column('name',         sa.String(100),   nullable=True),
        sa.Column('email',        sa.String(150),   unique=True, index=True),
        sa.Column('resume_path',  sa.String(500),   nullable=True),
        sa.Column('current_role', sa.String(150),   nullable=True),
        sa.Column('years_exp',    sa.Float(),        default=0),
        sa.Column('created_at',   sa.DateTime(),    nullable=True),
    )
    op.create_table('skill_profiles',
        sa.Column('id',           sa.Integer(),  primary_key=True),
        sa.Column('user_id',      sa.Integer(),  sa.ForeignKey('users.id')),
        sa.Column('skill_name',   sa.String(200)),
        sa.Column('level',        sa.String(50)),
        sa.Column('score',        sa.Float(),    default=0.0),
        sa.Column('verified',     sa.Boolean(),  default=False),
        sa.Column('source',       sa.String(100)),
        sa.Column('extracted_at', sa.DateTime()),
    )
    op.create_table('risk_predictions',
        sa.Column('id',              sa.Integer(), primary_key=True),
        sa.Column('user_id',         sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('role',            sa.String(150)),
        sa.Column('risk_score',      sa.Float()),
        sa.Column('risk_category',   sa.String(50)),
        sa.Column('viability_index', sa.Float()),
        sa.Column('shap_values',     sa.JSON()),
        sa.Column('predicted_at',    sa.DateTime()),
    )
    op.create_table('job_trends',
        sa.Column('id',            sa.Integer(), primary_key=True),
        sa.Column('role',          sa.String(150), index=True),
        sa.Column('date',          sa.DateTime()),
        sa.Column('posting_count', sa.Integer(), default=0),
        sa.Column('median_salary', sa.Float(),   default=0.0),
        sa.Column('yoy_growth',    sa.Float(),   default=0.0),
        sa.Column('sector',        sa.String(100)),
        sa.Column('source',        sa.String(100)),
        sa.Column('fetched_at',    sa.DateTime()),
    )
    op.create_table('recommendations',
        sa.Column('id',             sa.Integer(), primary_key=True),
        sa.Column('user_id',        sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('type',           sa.String(50)),
        sa.Column('title',          sa.String(300)),
        sa.Column('provider',       sa.String(150)),
        sa.Column('resource_url',   sa.String(500)),
        sa.Column('skill_tags',     sa.JSON()),
        sa.Column('priority_score', sa.Float()),
        sa.Column('phase',          sa.Integer()),
        sa.Column('created_at',     sa.DateTime()),
    )
    op.create_table('courses',
        sa.Column('id',           sa.Integer(), primary_key=True),
        sa.Column('title',        sa.String(300)),
        sa.Column('platform',     sa.String(100)),
        sa.Column('url',          sa.String(500)),
        sa.Column('skill_tags',   sa.JSON()),
        sa.Column('avg_rating',   sa.Float(), default=0.0),
        sa.Column('duration_hr',  sa.Float(), default=0.0),
        sa.Column('salary_lift',  sa.Float(), default=0.0),
        sa.Column('difficulty',   sa.String(50)),
        sa.Column('source',       sa.String(100)),
        sa.Column('last_updated', sa.DateTime()),
    )

def downgrade():
    op.drop_table('courses')
    op.drop_table('recommendations')
    op.drop_table('job_trends')
    op.drop_table('risk_predictions')
    op.drop_table('skill_profiles')
    op.drop_table('users')
