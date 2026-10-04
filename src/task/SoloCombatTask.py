from src.task.AutoCombatTask import AutoCombatTask


class SoloCombatTask(AutoCombatTask):
    """Background combat for a verified one-member party only."""

    use_original_multi_rotation = False
    solo_rotation_enabled = True
    combat_mode = 'solo'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '⚔️ Solo Auto Combat'
        self.description = 'Fight automatically only with a verified one-member party.'
        self.default_config['_enabled'] = False
        self.default_config.pop('Switch to Healer before and after Combat', None)
        self.config_description.pop('Switch to Healer before and after Combat', None)

    def _team_size_allowed(self, count):
        return count == 1

    def switch_healer(self):
        return None
