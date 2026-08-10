"""Complete SQLAlchemy metadata registry used by Alembic and schema checks."""

import sqlalchemy as sa

from astraquant_api import capture_repository, data_repository
from astraquant_api.paper_repository import metadata as paper_metadata
from astraquant_api.repository import metadata as core_data_metadata

if data_repository.data_snapshots.metadata is not core_data_metadata:
    raise RuntimeError("data repository tables must use core metadata")

metadata = sa.MetaData()
for source in (core_data_metadata, paper_metadata, capture_repository.metadata):
    for table in source.sorted_tables:
        table.to_metadata(metadata)
