"""Manual-entry, single-player controller for 群声共振模拟域."""
import math
import time

import win32gui

from src.activity_catalog import ACTIVITIES
from src.runtime.game_runtime_errors import GameProcessLost
from src.task.BaseWWTask import BaseWWTask
from src.task.resonance_simulation import (
    DEFAULT_RULES, Tracker, blood_bars, choose, compact, markers, movement,
    resized, rules_from_text, scene_visible, text_targets,
)


class ResonanceSimulationTask(BaseWWTask):
    navigation_section = 'activities'
    activity_category = '限时活动'

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.name=ACTIVITIES['resonance_simulation']
        self.description='手动进入群声共振模拟域后启动：按文字和指引移动、普攻破障及单人通用战斗；活动结束请停止。'
        self.group_name='限时活动'
        self.supported_languages=['zh_CN']
        self.support_schedule_task=False
        self.default_config.update({
            'Target Text': DEFAULT_RULES,
            'Exact Text Match': False,
            'Combat Keys': 'e,q',
            'Skill Interval': 2.0,
            'Attack While Moving': True,
            'Player Feet X': .51,
            'Player Feet Y': .58,
            'Move Pulse': .18,
            'No Progress Timeout': 8,
        })
        self.config_type['Target Text']={'type':'text_edit'}
        self.config_description.update({
            'Target Text':'每行 阶段|关键词，按顺序优先。阶段：奖励、下一关、通用；不写阶段视为通用。奖励在下一关阶段仍可领取。',
            'Exact Text Match':'关闭时包含匹配，例如共鸣因子可匹配任意角色；开启时须完整相同。',
            'Combat Keys':'通用战斗技能键，英文逗号分隔，按活动实际键位填写；默认 e,q，留空仅普攻。',
            'Skill Interval':'技能键轮流尝试的间隔秒数；不判断角色专属连招。',
            'Attack While Moving':'向目标移动时穿插普攻，用于击碎可破坏岩石。',
            'Player Feet X':'角色脚下横坐标/画面宽度，默认0.51。',
            'Player Feet Y':'角色脚下纵坐标/画面高度，默认0.58；不是屏幕中心。',
            'Move Pulse':'单次方向键保持秒数（0.05至0.25），之后用新截图重新判断。',
            'No Progress Timeout':'无接近进展时先原地破障再侧移，仍无进展停止；每阶段等待秒数（3至30）。',
        })
        self._held_keys=set()
        self._held_mouse=set()

    def _settings(self):
        self._rules=rules_from_text(self.config['Target Text'])
        self._feet=(float(self.config['Player Feet X']),float(self.config['Player Feet Y']))
        self._duration=float(self.config['Move Pulse'])
        self._stall=float(self.config['No Progress Timeout'])
        self._skill_interval=float(self.config['Skill Interval'])
        if not all(math.isfinite(v) for v in (*self._feet,self._duration,self._stall,self._skill_interval)):
            raise ValueError('活动参数必须是有限数值')
        if not (.3 <= self._feet[0] <= .7 and .4 <= self._feet[1] <= .75
                and .05 <= self._duration <= .25 and 3 <= self._stall <= 30 and .5 <= self._skill_interval <= 10):
            raise ValueError('足点、步长或超时参数超出范围，请查看配置说明')
        self._skills=[s.strip().lower() for s in self.config['Combat Keys'].split(',') if s.strip()]
        if len(self._skills)>6 or any(k not in ('e','q','r','t') for k in self._skills):
            raise ValueError('通用技能仅接受 e,q,r,t，最多6项；不允许方向键、切人键或确认键')

    def _foreground(self):
        window=self.hwnd
        if window is None or not window.exists:
            raise GameProcessLost('游戏窗口已断开，停止群声共振任务')
        return win32gui.GetForegroundWindow() in (window.hwnd,getattr(window,'top_hwnd',None))

    def _input_ready(self):
        executor=self.executor
        executor.check_enabled(check_pause=False)
        self._guard_account_input()
        return not executor.paused and not executor.exit_event.is_set() and self._foreground()

    def _release(self):
        # Bypass pause guards for cleanup; attempt every held input even if one fails.
        errors=[]
        for key in tuple(self._held_keys):
            try:
                self.executor.interaction.send_key_up(key)
                self._held_keys.discard(key)
            except Exception as error:
                errors.append(error)
        for key in tuple(self._held_mouse):
            try:
                self.executor.interaction.mouse_up(key=key)
                self._held_mouse.discard(key)
            except Exception as error:
                errors.append(error)
        if errors:
            raise RuntimeError('群声共振输入释放失败，停止任务') from errors[0]

    def _pulse(self,keys=(),attack=False,skill=None):
        if not self._input_ready():
            return
        if time.monotonic()-getattr(self,'_observed_at',time.monotonic()) > 1.5:
            return
        interaction=self.executor.interaction
        try:
            for key in (*keys,*((skill,) if skill else ())):
                if not self._input_ready():
                    return
                self._held_keys.add(key)
                interaction.send_key_down(key,activate=False)
            if attack and self._input_ready():
                self._held_mouse.add('left')
                interaction.mouse_down(key='left')
            deadline=time.monotonic()+self._duration
            while time.monotonic()<deadline and self._input_ready():
                # No executor.sleep while keys are held: it can block on pause.
                time.sleep(min(.025,max(0,deadline-time.monotonic())))
        finally:
            self._release()

    def _phase(self,frame):
        text=''.join(compact(b.name) for b in self.ocr(.0,.22,.26,.33,frame=frame))
        if '击败敌人' in text:
            return '战斗'
        if '收集奖励' in text:
            return '奖励'
        if '前往下一个区域' in text:
            return '下一关'
        if '前往目标地点' in text:
            return '前往'
        return ''

    def _objects(self,frame,phase,previous,full):
        if full:
            boxes=self.ocr(.01,.09,1,.80,frame=frame)
        elif previous and previous.kind=='object' and previous.label:
            x1,y1,x2,y2=previous.label
            boxes=self.ocr(max(0,x1-.06),max(.09,y1-.08),min(1,x2+.06),min(.80,y2+.08),frame=frame)
        else:
            return []
        return text_targets(frame,boxes,self._rules,phase,self.config['Exact Text Match'])

    def _progress(self,target,now):
        distance=math.dist(target.point,self._feet)
        identity=(target.kind,target.name)
        damage=(target.kind=='enemy' and 0 < target.health_width < getattr(self,'_health_width',0)-2)
        if identity != self._progress_id or distance < self._best_distance-.015 or damage:
            self._progress_id=identity
            self._best_distance=distance
            self._progress_at=now
            self._recoveries=0
            self._health_width=target.health_width
        if target.health_width > getattr(self,'_health_width',0)+3:
            self._health_width=target.health_width
        if now-self._progress_at < self._stall:
            return None
        self._progress_at=now
        self._recoveries+=1
        if self._recoveries==1:
            return 'break'
        if self._recoveries==2:
            return 'sidestep'
        raise RuntimeError('目标长时间无法接近：已尝试破障和侧移，请手动确认地形或交互要求')

    def run(self):
        self._settings()
        tracker=Tracker()
        phase=''
        next_ocr=0
        next_skill=0
        skill_index=0
        last_seen=time.monotonic()
        last_loop=last_seen
        self._progress_id=None
        self._best_distance=10
        self._progress_at=last_seen
        self._recoveries=0
        self.info_set('活动状态','等待活动场景；请手动进入群声共振模拟域')
        try:
            while True:
                self.executor.check_enabled()
                now=time.monotonic()
                if now-last_loop>2:
                    tracker=Tracker();phase='';next_ocr=0
                    last_seen=now;self._progress_at=now
                last_loop=now
                if not self._input_ready():
                    tracker=Tracker();phase='';next_ocr=0
                    last_seen=now;self._progress_at=now
                    self.info_set('活动状态','等待游戏回到前台')
                    self.sleep(.2)
                    continue
                self.next_frame()
                frame=self.require_game_frame()
                h,w=frame.shape[:2]
                if abs(w/h-16/9)>.03:
                    raise RuntimeError('群声共振任务需要16:9画面')
                now=time.monotonic()
                self._observed_at=now
                token=getattr(self.executor,'_last_frame_time',None) or id(frame)
                image=resized(frame)
                if not scene_visible(image):
                    tracker.update(None,token);phase='';next_ocr=0
                    self.info_set('活动状态','页面切换或活动画面未确认，等待；不会自动确认弹窗')
                    if now-last_seen>30:
                        raise RuntimeError('30秒未确认活动目标；请检查结算、交互或教学页面')
                    self.sleep(.15)
                    continue
                full=now>=next_ocr
                if full:
                    phase=self._phase(image)
                    next_ocr=now+.7
                previous=tracker.target
                enemies=blood_bars(image,previous)
                if enemies and phase in ('战斗','奖励','下一关','前往'):
                    target=choose(enemies,previous,self._feet)
                elif phase in ('奖励','下一关','前往'):
                    objects=self._objects(image,phase,previous,full)
                    target=choose(objects,previous,self._feet)
                    if target is None:
                        # On lost named objects wait for a fresh full scan before following a marker.
                        if previous and previous.kind=='object':
                            next_ocr=0
                        else:
                            target=choose(markers(image),previous,self._feet)
                else:
                    target=None
                confirmed=tracker.update(target,token)
                if confirmed:
                    last_seen=now
                    keys=movement(confirmed.point,self._feet)
                    combat=confirmed.kind=='enemy'
                    recovery=self._progress(confirmed,now)
                    if recovery=='break':
                        keys=()
                    elif recovery=='sidestep':
                        keys=('a',) if confirmed.point[0]>=self._feet[0] else ('d',)
                    skill=None
                    if combat and self._skills and now>=next_skill:
                        skill=self._skills[skill_index%len(self._skills)]
                        skill_index+=1;next_skill=now+self._skill_interval
                    self.info_set('活动状态',f'{phase}：{confirmed.name}'+('｜破障' if recovery else ''))
                    self._pulse(keys,attack=combat or self.config['Attack While Moving'],skill=skill)
                else:
                    self.info_set('活动状态','目标变化或暂不可见，重新确认')
                    if now-last_seen>30:
                        raise RuntimeError('30秒没有可确认目标，停止；目标消失不代表活动完成')
                self.sleep(.1)
        finally:
            self._release()
