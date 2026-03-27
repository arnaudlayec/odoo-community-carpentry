# -*- coding: utf-8 -*-

import logging
_logger = logging.getLogger(__name__)

def migrate(cr, version):
    cr.execute("""
        ALTER TABLE carpentry_position  RENAME COLUMN external_db_guid TO external_id;
        ALTER TABLE carpentry_group_lot RENAME COLUMN external_db_guid TO external_id;
    """)
