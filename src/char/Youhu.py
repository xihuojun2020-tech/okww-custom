from src.char.BaseChar import BaseChar


class Youhu(BaseChar):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _liberation_choice_visible(self):
        # Youhu's antique selection hides the party HUD until W/A/S/D is chosen.
        keys = {box.name.strip().upper() for box in self.task.ocr(.52, .20, .87, .69)}
        return {'W', 'A', 'S', 'D'} <= keys

    def recheck_liberation_timeout(self):
        self.task.next_frame()
        if self._liberation_choice_visible():
            self.task.send_key('w', after_sleep=.1)
            self.task.wait_until(lambda: self.task.in_team()[0], time_out=3, raise_if_not_found=True)
        super().recheck_liberation_timeout()
