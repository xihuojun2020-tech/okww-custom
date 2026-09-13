"""Complete the PostMessage drag endpoint and always release on interruption."""
import math


def drag(interaction, x1, y1, x2, y2, duration, settle_time, sleep):
    if not math.isfinite(duration) or duration < 0 or not math.isfinite(settle_time) or settle_time < 0:
        raise ValueError('drag duration must be finite and nonnegative')
    steps = max(1, math.ceil(duration / .02))
    interaction.move(x1, y1)
    sleep(.1)
    try:
        interaction.mouse_down(x1, y1)
        for step in range(1, steps + 1):
            interaction.move(round(x1 + (x2-x1)*step/steps),
                             round(y1 + (y2-y1)*step/steps), down_btn=1)
            sleep(duration / steps)
    finally:
        interaction.mouse_up()
    if settle_time:
        sleep(settle_time)
