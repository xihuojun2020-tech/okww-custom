"""A diagnostic package, not a claim of support for a second game."""

from gameframe.vision import load_image, match_template


class VisionProbe:
    def run(self, task_id, context):
        frame = context.frame()
        match = match_template(frame.image, load_image(context.config['template']),
                               context.config['threshold'])
        if match is None:
            return {'status': 'blocked', 'reason': 'Template not visible',
                    'frame_sequence': frame.sequence}
        context.act('click', x=match.x + match.width // 2, y=match.y + match.height // 2)
        return {'frame_sequence': frame.sequence, 'confidence': match.confidence,
                'position': [match.x, match.y]}


def create_package():
    return VisionProbe()
