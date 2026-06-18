# -*- coding: utf-8 -*-

from odoo import api, SUPERUSER_ID
import logging
_logger = logging.getLogger(__name__)

def migrate(cr, version):
    """Sets all new `milestone.is_done` as per former `launch.is_done`"""

    env = api.Environment(cr, SUPERUSER_ID, {})
    _logger.info("Migrate `launch.is_done` to `launch.milestone(:last).is_done`")
    
    cr.execute("""
        SELECT id, is_done
        FROM carpentry_group_launch
    """)
    mapped_done = {row[0]: row[1] for row in cr.fetchall()}

    launchs = env["carpentry.group.launch"].search([])
    for launch in launchs:
        launch.milestone_ids.is_done = mapped_done.get(launch.id)
