"""Paged diagnostic evidence browser. Disk and network operations stay off Qt."""
import json
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QPlainTextEdit, QLineEdit,
    QComboBox, QMessageBox, QFileDialog, QGridLayout, QHeaderView)
from src.gui.CodexTheme import SPACING, size_dialog
from src.gui.SectionPanel import SectionPanel
from src.gui.BackgroundOperation import BackgroundOperation
from src.runtime.diagnostic_status import (DiagnosticIndex, STATUS, retry_batches,
    bounded_verify, backfill_preview, enqueue_backfill)
from src.runtime.nas_location import DEFAULT_TARGET
from src.runtime.diagnostic_lifecycle import wake_uploader

CAPTURE_STATUS = {'incomplete':'截图不完整','complete':'采集完整','collecting':'采集中',
                  'interrupted':'采集已中断','sealed':'已封存'}


def stamp(value):
    if not value:return '无'
    return datetime.fromtimestamp(value).strftime('%m-%d %H:%M:%S') if isinstance(value,(float,int)) else str(value)


class DiagnosticDetails(QDialog):
    PAGE_SIZE=50
    def __init__(self,root,parent=None):
        super().__init__(parent)
        self.setWindowTitle('日志与截图上传明细')
        self.setObjectName('diagnosticDetails')
        size_dialog(self,1120,800)
        from src.runtime.diagnostic_policy import REPO
        self.root=Path(root);self.index=DiagnosticIndex(root, REPO);self.snapshot={};self.page=0;self.rows=[]
        layout=QVBoxLayout(self)
        layout.setContentsMargins(16,16,16,16)
        layout.setSpacing(SPACING['section'])
        title=QLabel('日志与截图上传明细',self);title.setProperty('role','pageTitle');layout.addWidget(title)
        self.overview=SectionPanel('传输概览',parent=self,collapsible=True)
        layout.addWidget(self.overview)
        self.summary=QLabel('读取本地状态…');self.summary.setWordWrap(True)
        self.summary.setProperty('role','description');self.overview.add_widget(self.summary)
        bar=QHBoxLayout();layout.addLayout(bar)
        self.filter=QComboBox();self.filter.addItems(['全部','待传/失败','已上传'])
        refresh=QPushButton('刷新');retry=QPushButton('重试选中批次');verify=QPushButton('核验选中远端')
        refresh.setProperty('role','primary')
        for w in (self.filter,refresh,retry,verify):bar.addWidget(w)
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        self.tables=[]
        for name in ('日志来源','错误事件','文件','批次'):
            table=QTableWidget();table.setSelectionBehavior(QTableWidget.SelectRows)
            table.setSelectionMode(QTableWidget.SingleSelection);table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.style_table(table)
            self.tables.append(table);self.tabs.addTab(table,name)
            table.itemSelectionChanged.connect(self.select)
        pager=QHBoxLayout();layout.addLayout(pager)
        prev=QPushButton('上一页');nxt=QPushButton('下一页');self.page_label=QLabel()
        pager.addWidget(prev);pager.addStretch();pager.addWidget(self.page_label);pager.addStretch();pager.addWidget(nxt)
        self.page_label.setProperty('role','description')
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);self.detail.setMaximumHeight(120)
        self.detail.setPlaceholderText('选择一项，查看上传结果、时间和缺失原因')
        layout.addWidget(self.detail)
        self.timeline=QTableWidget(0,6);self.timeline.setHorizontalHeaderLabels(['阶段','距错误秒数','实际采集时间','画面质量','上传状态','文件'])
        self.timeline.setMaximumHeight(120);self.timeline.setSelectionBehavior(QTableWidget.SelectRows)
        self.style_table(self.timeline)
        self.timeline.setSelectionMode(QTableWidget.SingleSelection);self.timeline.setEditTriggers(QTableWidget.NoEditTriggers)
        self.timeline.itemSelectionChanged.connect(self.select_frame);layout.addWidget(self.timeline)
        self.frame_file=None
        actions=QGridLayout();actions.setSpacing(SPACING['small']);layout.addLayout(actions)
        local=QPushButton('打开本地');remote=QPushButton('打开NAS目录');copy=QPushButton('复制路径')
        preview=QPushButton('预览选中图片');export=QPushButton('导出诊断索引');backfill=QPushButton('补传指定时间日志')
        for n,w in enumerate((local,remote,copy,preview,export,backfill)):actions.addWidget(w,n//3,n%3)
        self.message=QLabel('连接未检测；历史上传成功不代表当前在线。');self.message.setWordWrap(True);layout.addWidget(self.message)
        self.message.setProperty('role','description')
        self.operation=BackgroundOperation(self,(refresh,retry,verify,preview,export,backfill))
        self.tabs.currentChanged.connect(self.reset_page);self.filter.currentIndexChanged.connect(self.reset_page)
        refresh.clicked.connect(self.refresh);retry.clicked.connect(self.retry);verify.clicked.connect(self.verify)
        prev.clicked.connect(lambda:self.change_page(-1));nxt.clicked.connect(lambda:self.change_page(1))
        local.clicked.connect(self.open_local);remote.clicked.connect(self.open_remote);copy.clicked.connect(self.copy_path)
        preview.clicked.connect(self.preview);export.clicked.connect(self.export);backfill.clicked.connect(self.backfill)
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(5000);self.refresh()

    @staticmethod
    def style_table(table):
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(32)
        table.horizontalHeader().setHighlightSections(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.setWordWrap(False)

    def error(self,error):self.message.setText(str(error))
    def refresh(self):
        if self.isVisible() or not self.snapshot:self.operation.start(self.index.snapshot,self.loaded,self.error)
    def loaded(self,snapshot):
        self.snapshot=snapshot
        self.overview.set_summary(f'待传 {snapshot["pending_bytes"]:,} 字节 · {len(snapshot.get("batches",[]))} 批次 · {stamp(snapshot["updated_at"])}')
        self.summary.setText(f'NAS：{DEFAULT_TARGET}\n状态刷新：{stamp(snapshot["updated_at"])} | '
            f'待传 {snapshot["pending_bytes"]:,} 字节 | 批次：'+
            '，'.join(f'{STATUS.get(k,k)} {v}' for k,v in snapshot['counts'].items())+
            '\n采集与上传分别统计；上传器已校验表示当时成功，远端核验需点击按钮。'+
            ('\n'+'；'.join(snapshot['warnings'][:3]) if snapshot['warnings'] else ''))
        scheduler=snapshot.get('scheduler',{})
        self.summary.setText(self.summary.text()+f'\n退出后补传任务：{scheduler.get("status", "未记录")}；'
            f'系统验证：{"已验证" if scheduler.get("system_verified") else "未验证"}；'
            f'采集警告：{snapshot.get("collector",{}).get("error", "无")}')
        self.render()
    def reset_page(self,*args):self.page=0;self.render()
    def change_page(self,delta):
        self.page=max(0,min(self.page+delta,max(0,(len(self.rows)-1)//self.PAGE_SIZE)));self.render()
    def render(self):
        i=self.tabs.currentIndex();keys=('sources','incidents','files','batches')
        rows=self.snapshot.get(keys[i],[])
        f=self.filter.currentIndex()
        if i and f:
            rows=[r for r in rows if (r.get('upload_status',r.get('status')) in ('uploaded','logs_purged'))==(f==2)]
        self.rows=rows;self.page=min(self.page,max(0,(len(rows)-1)//self.PAGE_SIZE))
        headers=[['源文件','已采集位置','当前大小','待采集字节','最近采集','历史基线'],
                 ['发生时间','版本','错误摘要','采集状态','前/当时/后','上传状态'],
                 ['文件','类型','字节','上传状态','尝试','下次重试'],
                 ['批次','时间','类型','文件数/字节','状态','最近错误']][i]
        table=self.tables[i]
        old_item=table.item(table.currentRow(),0)
        selected_key=old_item.data(Qt.UserRole) if old_item else None
        table.blockSignals(True);table.clearSelection();table.setCurrentCell(-1,-1)
        self.detail.clear();self.frame_file=None;self.timeline.setRowCount(0);self.timeline.setVisible(i==1)
        table.setColumnCount(len(headers));table.setHorizontalHeaderLabels(headers)
        shown=rows[self.page*self.PAGE_SIZE:(self.page+1)*self.PAGE_SIZE];table.setRowCount(len(shown))
        for n,r in enumerate(shown):
            status=STATUS.get(r.get('upload_status',r.get('status')),r.get('status','未知'))
            if i==0:vals=[r['source'],r['offset'],r.get('live_size','未读取'),r['remaining'] if r['remaining'] is not None else '轮转/不可用',stamp(r['collected_at']),'首次启用前历史' if r['pre_policy'] else '增量采集']
            elif i==1:
                counts=[sum(x.get('phase')==phase for x in r.get('frames',[])) for phase in ('pre','at','post')]
                vals=[r.get('triggered_at'),r.get('version'),str((r.get('triggers') or [{}])[0].get('message',''))[:100],
                      CAPTURE_STATUS.get(r.get('state'),r.get('state')),'/'.join(map(str,counts)),status]
            elif i==2:vals=[r['path'],r['type'],r['size'],STATUS.get(r['file_status'],status),r['attempts'],stamp(r['next_retry'])]
            else:vals=[r['key'],stamp(r['created_at']),r['kind'],f'{r["count"]}/{r["size"]}',status,r['error']]
            for c,v in enumerate(vals):table.setItem(n,c,QTableWidgetItem(str(v)))
            identity=r.get('source') or r.get('incident_id') or (r.get('key','')+':'+r.get('path',''))
            table.item(n,0).setData(Qt.UserRole,identity)
            if identity==selected_key:table.selectRow(n)
        table.resizeColumnsToContents()
        for column in range(table.columnCount()):
            table.setColumnWidth(column,min(table.columnWidth(column),380))
        table.blockSignals(False)
        self.select()
        self.page_label.setText(f'第 {self.page+1} 页 / {max(1,(len(rows)+49)//50)} 页，共 {len(rows)} 项')
    def selected(self):
        n=self.tables[self.tabs.currentIndex()].currentRow()+self.page*self.PAGE_SIZE
        return self.rows[n] if self.tables[self.tabs.currentIndex()].currentRow()>=0 and n<len(self.rows) else None
    def select(self):
        r=self.selected()
        self.frame_file=None
        self.timeline.blockSignals(True);self.timeline.setRowCount(0)
        if r:
            reasons={'warmup':'启动时间不足，错误前画面未缓存齐', 'pre_frames_missing':'错误前截图缺失',
                     'post_frames_missing':'错误后截图缺失','stale_frame':'游戏画面未更新',
                     'frame_unavailable':'游戏画面不可用','interrupted':'采集被中断'}
            lines=[f'本地路径：{r.get("local", r.get("source", "无"))}',
                   f'上传状态：{STATUS.get(r.get("upload_status", r.get("file_status",r.get("status"))), "见关联批次")}',
                   f'最近错误：{r.get("upload_error",r.get("error")) or "无"}',
                   f'最后成功：{stamp(r.get("uploaded_at"))}']
            if 'frames' in r:
                lines += [f'采集状态：{CAPTURE_STATUS.get(r.get("state"), r.get("state", "未知"))}', '缺失原因：'+
                          ('；'.join(reasons.get(x,x) for x in r.get('incomplete_reasons',[])) or '未记录'),
                          f'未采集记录：{len(r.get("missing_frames",[]))} 项（导出索引可查看逐项原因）']
            for b in r.get('batches',[]):
                extent=b['range'];lines.append(f'来源范围 {extent.get("start","时间补传")} → {extent.get("end","")}：'
                    f'{STATUS.get(b["status"],b["status"])}；时间 {extent.get("start_time") or "未知"} → '
                    f'{extent.get("end_time") or "未知"}；批次 {b["key"]}')
            self.detail.setPlainText('\n'.join(lines))
            frames=r.get('frames',[]);self.timeline.setRowCount(len(frames))
            for n,f in enumerate(frames):
                for c,v in enumerate([f.get('phase'),f.get('relative_seconds'),f.get('observed_at'),f.get('freshness'),STATUS.get(f.get('upload_status'),'未知'),f.get('remote_path','未封存')]):
                    self.timeline.setItem(n,c,QTableWidgetItem(str(v)))
            self.timeline.resizeColumnsToContents()
        self.timeline.blockSignals(False)
    def select_frame(self):
        r=self.selected() or {};n=self.timeline.currentRow();frames=r.get('frames',[])
        self.frame_file=next((f for f in self.snapshot.get('files',[]) if 0<=n<len(frames) and
                              f['path']==frames[n].get('remote_path')),None)
    def batch(self):
        r=self.selected() or {};key=r.get('batch_key',r.get('key'))
        return next((b for b in self.snapshot.get('batches',[]) if b['key']==key),None)
    def retry(self):
        b=self.batch()
        if not b:return self.error('请选择事件、文件或批次')
        def work():
            count=retry_batches(self.root,[b['key']]);wake_uploader(self.root);return count
        self.operation.start(work,lambda n:self.message.setText(f'已重排 {n} 批次；上传中或被阻塞的项目不会强制重置'),self.error)
    def verify(self):
        b=self.batch()
        if b:self.operation.start(lambda:bounded_verify(b['local'],DEFAULT_TARGET),
            lambda r:self.message.setText(f'远端校验通过：{r["files"]} 文件，{stamp(r["verified_at"])}'+
                ('；旧日志已按保留策略清理，仅核验保留文件' if r.get('logs_purged') else '')),self.error)
    def open_local(self):
        r=self.selected() or {};p=r.get('local',str(self.root));QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(p).parent if Path(p).suffix else p)))
    def open_remote(self):
        b=self.batch()
        if b and b.get('remote'):
            QDesktopServices.openUrl(QUrl.fromLocalFile(b['remote']))
    def copy_path(self):
        from PySide6.QtWidgets import QApplication
        r=self.selected() or {};QApplication.clipboard().setText(r.get('local',r.get('source',str(self.root))))
    def preview(self):
        r=self.frame_file or self.selected() or {}
        if r.get('type')!='截图':return self.error('请在文件页签选择截图；事件详情列有图片真实相对秒数')
        path=r['local']
        def load():
            image=QImage(path)
            if image.isNull():raise ValueError('图片不存在或无法解码')
            return image.scaled(1000,650,Qt.KeepAspectRatio,Qt.SmoothTransformation)
        def show(image):
            dialog=QDialog(self);dialog.setWindowTitle('诊断图片（已有脱敏产物）');layout=QVBoxLayout(dialog)
            label=QLabel();label.setPixmap(QPixmap.fromImage(image));layout.addWidget(label);dialog.exec()
        self.operation.start(load,show,self.error)
    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'导出诊断索引','diagnostic-index.json','JSON (*.json)')
        if path:
            data=json.dumps(self.snapshot,ensure_ascii=False,indent=2)
            self.operation.start(lambda:Path(path).write_text(data,encoding='utf-8'),lambda _:self.message.setText('索引已导出'),self.error)
    def backfill(self):
        dialog=QDialog(self);dialog.setWindowTitle('补传时间范围（北京时间/本机时间）');layout=QVBoxLayout(dialog)
        start=QLineEdit((datetime.now()-timedelta(hours=1)).isoformat(timespec='seconds'));end=QLineEdit(datetime.now().isoformat(timespec='seconds'))
        layout.addWidget(QLabel('开始（包含）'));layout.addWidget(start);layout.addWidget(QLabel('结束（不包含）'));layout.addWidget(end)
        button=QPushButton('预览');layout.addWidget(button);button.clicked.connect(dialog.accept)
        if dialog.exec()!=QDialog.Accepted:return
        try:a,b=datetime.fromisoformat(start.text()),datetime.fromisoformat(end.text())
        except ValueError:return self.error('时间格式错误')
        from src.runtime.diagnostic_policy import REPO
        def ready(rows):
            text='\n'.join(f'{Path(r["path"]).name}: {r.get("bytes",0)} 字节 {r.get("error","")}' for r in rows)
            if QMessageBox.question(self,'确认补传',text or '无匹配日志')!=QMessageBox.Yes:return
            from config import version
            def enqueue():
                result=enqueue_backfill(self.root,rows,version);wake_uploader(self.root);return result
            self.operation.start(enqueue,lambda _:self.message.setText('补传已入队，未改变自动采集游标'),self.error)
        self.operation.start(lambda:backfill_preview(REPO,a,b),ready,self.error)
