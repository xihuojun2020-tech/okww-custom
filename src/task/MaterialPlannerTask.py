"""Conservative cultivation planner, executed inside the verified daily account."""
import hashlib
import json
import re
import time
from dataclasses import asdict
from datetime import datetime
from uuid import UUID, uuid4

import cv2
import numpy as np

from src.task.BaseWWTask import BaseWWTask
from src.materials.catalog import Catalog
from src.materials.model import (Settlement, calculate_gap, equivalent, is_satisfied,
                                 count_reward_units, aggregate_settlements, week_id)
from src.materials.repository import MaterialRepository
from src.materials.vision import (normalize, parse_reward_frame, parse_inventory_frame,
                                  parse_target_frame, stitch_reward_pages, target_totals,
                                  forgery_rows)

MATERIAL_PLANNER = 'Material Planner Enabled'


class MaterialPlannerTask(BaseWWTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '养成材料规划'
        self.description = '读取培养目标、校准仓库并永久保存凝素收益；由账号每日任务调用。'
        self.supported_languages = ['zh_CN']
        self.visible = False
        self.default_config = {}
        self.catalog = Catalog()
        self.repository = MaterialRepository()
        self.report = None

    def _report(self, key, value):
        self.info_set(key,value)
        if self.report:
            self.report(key,value)

    def run(self):
        raise RuntimeError('请从已验证账号的每日任务启用养成材料规划')

    def _ocr_image(self, image):
        return self.ocr(frame=image)

    def _capture(self, record, sequence):
        self.next_frame()
        frame = self.require_game_frame().copy()
        self._save_frame(record, sequence, frame)
        return frame

    def _save_frame(self, record, sequence, frame):
        from src.runtime.vision_metrics import measure
        with measure('material_png'):
            ok, data = cv2.imencode('.png', frame)
        if not ok:
            raise RuntimeError('材料证据截图编码失败')
        with measure('material_save'):
            self.repository.save_frame(record, sequence, data.tobytes())

    @staticmethod
    def _same_view(a, b, region):
        x,y,w,h = region
        left = cv2.resize(normalize(a)[y:h,x:w], (160,80))
        right = cv2.resize(normalize(b)[y:h,x:w], (160,80))
        return float(np.mean(cv2.absdiff(left, right))) < 1.5

    def _pages(self, parser, record, region, scroll_at, *, stop_at_echo=False):
        """Save useful full pages; keep calibration observations without repeated PNGs."""
        seq = 0
        saved_hashes = {}
        observations = []
        def capture():
            self.next_frame()
            return self.require_game_frame().copy()
        def save(frame, sequence, stage):
            sha = hashlib.sha256(memoryview(frame)).hexdigest()
            # Exact full pixels, scoped to this scan/claim only. ROI equality
            # must never stand in for full evidence equality.
            if sha not in saved_hashes:
                self._save_frame(record, sequence, frame)
                saved_hashes[sha] = sequence
            observations.append(dict(sequence=sequence, frame_seq=saved_hashes[sha],
                                     stage=stage, observed_at=time.time()))
            return saved_hashes[sha]
        previous = capture()
        previous_view = normalize(previous)
        stable = 0
        for _ in range(16):
            self.scroll_relative(*scroll_at, 8)
            self.sleep(.5)
            seq += 1
            current = capture()
            current_view = normalize(current)
            stable = stable + 1 if self._same_view(previous_view,current_view,region) else 0
            previous = current
            previous_view = current_view
            if stable >= 2: break
        else:
            save(previous, seq, 'top_unconfirmed')
            raise RuntimeError('材料列表未确认顶部，停止扫描')
        pages = []
        stable = 0
        for _ in range(60):
            frame_seq = save(previous, seq, 'page')
            page = parser(previous_view, self._ocr_image, self.catalog)
            if page['scene'] == 'unknown':
                raise RuntimeError('材料页面身份未确认')
            page['frame_seq'] = frame_seq
            page['observations'] = observations
            observations = []
            page['at_top'] = not pages
            pages.append(page)
            if stop_at_echo and page.get('has_echo_boundary'):
                page['at_bottom'] = True
                return pages
            while stable < 2:
                self.scroll_relative(*scroll_at, -2)
                self.sleep(.5)
                seq += 1
                current = capture()
                current_view = normalize(current)
                if not self._same_view(previous_view,current_view,region):
                    stable = 0
                    break
                save(current, seq, 'bottom_probe')
                stable += 1
            if stable >= 2:
                page['observations'].extend(observations)
                page['at_bottom'] = True
                return pages
            previous = current
            previous_view = current_view
        raise RuntimeError('材料列表超过扫描上限，原图已保留')

    @staticmethod
    def _json_pages(pages):
        return [{**p, 'cells': [{k:v for k,v in c.items() if k != 'signature'}
                                for c in p['cells']]} for p in pages]

    def scan_target(self):
        self.guard()
        self.openF2Book('gray_book_boss')
        button = self.wait_ocr(.1,.12,.34,.23, match=re.compile('培养目标'), time_out=5)
        if not button:
            raise RuntimeError('未找到培养目标入口')
        self.click(button[0], after_sleep=1)
        record = str(uuid4())
        pages = self._pages(parse_target_frame, record, (780,230,1970,1000), (.88,.65), stop_at_echo=True)
        groups, errors = target_totals(pages)
        if not any(p.get('has_echo_boundary') for p in pages):
            errors.append('echo_boundary_not_confirmed')
        payload = dict(pages=self._json_pages(pages), groups={k:{n:asdict(v) for n,v in g.items()}
                                                           for k,g in groups.items()}, errors=errors)
        inventory = self.repository.latest_complete_snapshot(self.profile_id,'inventory')
        if inventory:
            known = inventory['payload']['stock']
            differences = {f'{g}_{tier}':dict(warehouse=known[f'{g}_{tier}'],current=count)
                           for g,values in groups.items() for tier,count in asdict(values['stock']).items()
                           if f'{g}_{tier}' in known and known[f'{g}_{tier}']!=count}
            payload['inventory_changes'] = differences
            if differences:
                self._report('库存校正',differences)
        self.repository.save_snapshot(self.profile_id,'target',payload,complete=not errors,snapshot_id=record)
        for page in pages:
            for row in page.get('records', []):
                if '技能升级材料' in row['label'] or '共鸣者突破材料' in row['label']:
                    self._report(row['label'], [(c['amount'],c['need']) for c in row['cells']])
        if errors:
            raise RuntimeError('培养材料未完整识别，停止消费：' + ', '.join(sorted(set(errors))))
        revision = dict(identity=pages[0]['target_identity'],needs={g:asdict(v['need']) for g,v in groups.items()})
        self.target_revision = hashlib.sha256(json.dumps(revision,sort_keys=True).encode()).hexdigest()
        self.ensure_main()
        return groups

    def scan_inventory(self):
        self.guard()
        self.ensure_main()
        self.send_key('b', after_sleep=2)
        self.click_relative(.04,.55, after_sleep=1)
        record = str(uuid4())
        pages = self._pages(parse_inventory_frame, record, (180,140,1290,968), (.50,.65))
        stock = {}; conflicts = []
        for page in pages:
            for c in page['cells']:
                if c['group_id'] not in self.catalog.groups or c['amount'] is None: continue
                if c['item_id'] in stock and stock[c['item_id']] != c['amount']:
                    conflicts.append(c['item_id'])
                stock[c['item_id']] = c['amount']
        coverage = stitch_reward_pages(pages)
        expected = pages[0]['anchors'].get('declared_count')
        complete = (not conflicts and coverage['complete'] and expected is not None
                    and expected == len(coverage['drops']))
        self.repository.save_snapshot(self.profile_id, 'inventory',
            dict(pages=self._json_pages(pages), stock=stock, week=week_id(), conflicts=conflicts,
                 unknown_means_zero=False, coverage_errors=coverage['errors'],
                 observed_slots=len(coverage['drops']),expected_slots=expected), complete=complete, snapshot_id=record)
        self.ensure_main()
        if not complete:
            raise RuntimeError('仓库数量尚未全部确认，已保留截图，停止本轮材料规划')
        self._report('仓库校准', f'{week_id()}；已识别 {len(stock)} 种材料，未知材料保留原图')

    def begin_claim(self):
        self.guard()
        self.claim_id = self.repository.begin_claim(self.profile_id,self.target_revision,self.group_id)
        return self.claim_id

    def collect_claim(self, used):
        if not used:
            self.repository.record_event(self.claim_id,'not_claimed')
            return
        self.repository.record_event(self.claim_id,'consumed',dict(stamina=used))
        pages = self._pages(parse_reward_frame,self.claim_id,(310,430,1735,826),(.77,.58))
        result = stitch_reward_pages(pages)
        units = count_reward_units(result['drops'],self.group_id)
        complete = result['complete'] and units is not None
        errors = tuple(result['errors']) + (() if units else ('missing_target_green',))
        settlement = Settlement(self.claim_id,self.profile_id,self.target_revision,self.group_id,used,
                                complete,result['drops'],units if complete else None,errors)
        self.repository.append_settlement(settlement, parser_version='material-v1',
            evidence=dict(pages=self._json_pages(pages),frame_links=result['frame_links']))
        self.total_used += used
        stats = aggregate_settlements(self.repository.list_settlements(self.profile_id,self.group_id))
        self._report('材料累计收益', f"{self.group_id}：{stats['reward_units']} 份，绿等价 {stats['equivalent']}，每份 {stats['per_unit']}")
        if not complete:
            raise RuntimeError('收益未完整识别，原图及异常记录永久保留，停止再次挑战')

    def capture_failure(self):
        evidence_id = str(uuid4())
        self.repository.record_event(self.claim_id,'capture_failed',dict(evidence_id=evidence_id))
        # A separate evidence ID avoids ever overwriting already saved claim frames.
        self._capture(evidence_id,0)

    def enter_forgery(self, domain):
        domain.open_boss_book('ningsu')
        weapon = next(v['weapon_type'] for v in self.catalog.items.values() if v['group_id']==self.group_id)
        # Search visible preview icons and the weapon type on the same row, never dungeon names.
        for _ in range(3):
            domain.scroll_relative(.88,.60,10)
            domain.sleep(.3)
        for _ in range(30):
            domain.next_frame()
            frame = normalize(domain.require_game_frame())
            for row in forgery_rows(frame,self._ocr_image,self.catalog):
                if row['group_id']!=self.group_id: continue
                top,bottom=row['top'],row['bottom']
                buttons = domain.ocr(.83,top/1152,.96,bottom/1152,match=re.compile('直接挑战|前往'))
                if len(buttons)!=1: continue
                domain.click(buttons[0],after_sleep=1)
                feature = domain.wait_feature(['fast_travel_custom','gray_teleport','team_close'],time_out=10)
                if feature.name != 'team_close': domain.click_traval_button()
                domain.click_team_challenge()
                domain.wait_in_team_and_world(time_out=domain.teleport_timeout)
                return
            domain.scroll_relative(.88,.60,-2)
            domain.sleep(.5)
        raise RuntimeError(f'未确认 {weapon} / {self.group_id} 的材料预览，停止进入副本')

    def run_for_profile(self, profile_id, config, guard, activity_ready=False, report=None):
        from src.task.ForgeryTask import ForgeryTask
        from src.task.TacetTask import TacetTask
        if self.game_lang != 'zh_CN' or abs(self.width/self.height-16/9)>.02:
            raise RuntimeError('材料规划首版需要简体中文、16:9 游戏画面')
        self.profile_id = str(UUID(profile_id))
        self.guard = guard
        self.report = report
        self.total_used = 0
        guard()
        if self.repository.pending_claims(self.profile_id):
            self._report('待复核收益', len(self.repository.pending_claims(self.profile_id)))
        snapshot = self.repository.latest_complete_snapshot(self.profile_id,'inventory')
        if not snapshot or week_id(datetime.fromisoformat(snapshot['captured_at'])) != week_id():
            self.scan_inventory()
        budget = self.daily_stamina_budget(activity_ready,40)
        domain = self.get_task_by_class(ForgeryTask)
        try:
            while True:
                groups = self.scan_target()  # Refresh actual counts after every claim, including the last.
                missing = [(g,calculate_gap(v['stock'],v['need'])) for g,v in groups.items()]
                self._report('养成缺口', {g:asdict(gap.missing) for g,gap in missing})
                missing = [(g,gap) for g,gap in missing if not is_satisfied(gap)]
                remaining = max(0,budget-self.total_used) if budget else 0
                if budget and remaining<40: return
                if not missing:
                    self.scan_inventory()
                    final_groups = self.scan_target()
                    if any(not is_satisfied(calculate_gap(v['stock'],v['need'])) for v in final_groups.values()):
                        continue
                    self._report('养成进度','凝素材料已满足，进入声骸培养')
                    self.get_task_by_class(TacetTask).farm_tacet(daily=True,config=config,
                        activity_ready=activity_ready,stamina_budget=remaining if budget else None)
                    return
                self.group_id,gap = missing[0]
                self.max_claims = 1 if equivalent(gap.missing)<120 or (budget and remaining<80) else 2
                domain.material_planner = self
                before = self.total_used
                domain.farm_domain_with_recovery_loop(remaining,lambda:self.enter_forgery(domain),
                    activity_ready=activity_ready,stamina_budget=remaining)
                if self.total_used==before: return
        finally:
            domain.material_planner = None
