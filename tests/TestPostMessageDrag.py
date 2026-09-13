import unittest
from types import SimpleNamespace
from unittest.mock import patch
from src.runtime.post_message_drag import drag


class TestPostMessageDrag(unittest.TestCase):
    def test_endpoint_settle_and_release(self):
        moves, buttons, sleeps = [], [], []
        interaction = SimpleNamespace(move=lambda x,y,**kw:moves.append((x,y,kw)),
            mouse_down=lambda *_:buttons.append('down'), mouse_up=lambda:buttons.append('up'))
        drag(interaction, 1774, 676, 1774, 345, .5, .3, sleeps.append)
        self.assertEqual(moves[-1], (1774,345,{'down_btn':1}))
        self.assertEqual(buttons,['down','up'])
        self.assertAlmostEqual(sum(sleeps), .9)

    def test_releases_on_interruption_and_zero_duration_reaches_end(self):
        buttons=[]
        interaction=SimpleNamespace(move=lambda *_args,**_kw:None,
            mouse_down=lambda *_:buttons.append('down'), mouse_up=lambda:buttons.append('up'))
        def sleep(value):
            if value != .1: raise InterruptedError()
        with self.assertRaises(InterruptedError):drag(interaction,1,2,3,4,.5,.3,sleep)
        self.assertEqual(buttons,['down','up'])
        drag(interaction,1,2,3,4,0,0,lambda _:None)

    def test_reproduce_old_backend_stopping_before_endpoint(self):
        from ok.device.interaction_methods.post_message import PostMessageInteraction
        moves=[]
        fake=SimpleNamespace(move=lambda x,y,**kw:moves.append((x,y)),mouse_down=lambda *_:None,mouse_up=lambda:None)
        with patch('ok.device.interaction_methods.post_message.time.sleep'):
            PostMessageInteraction.swipe(fake,100,676,100,345,500,settle_time=.3)
        self.assertNotEqual(moves[-1],(100,345))
        self.assertEqual(moves[-1],(100,412))
