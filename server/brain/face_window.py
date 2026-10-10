"""OLED face; painting and state updates stay on the Qt thread."""
import math
import random
import time
import os
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPointF, QRectF
from .ui_preferences import PRESETS, visible_position
from . import config
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath, QFont, QFontDatabase
from PySide6.QtWidgets import QWidget, QMenu, QInputDialog, QPushButton, QMessageBox

class Bridge(QObject):
    event = Signal(dict)

class FaceWindow(QWidget):
    def __init__(self, bridge, control=None, always_on_top=False, preferences=None):
        super().__init__()
        # Load the Windows font explicitly; offscreen Qt may enumerate fonts
        # without opening them through the platform font engine.
        font_path = os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts', 'segoeui.ttf')
        if os.name == 'nt' and os.path.isfile(font_path):
            QFontDatabase.addApplicationFont(font_path)
        self.control = control or (lambda line: None)
        self.preferences = preferences
        self.size_preset = 'Normal'
        self.variant = 0
        self.animation = 'idle'
        self.activity = None
        self.activity_until = 0
        self.double_blink_at = 0
        self.wink_until = self.glance_until = 0
        self.glance = 0
        self.resize_drag = None
        self.emotion = 'neutral'
        self.asleep = self.talking = self.listening = False
        self.mouth = 0.0
        self.gaze = (0.0, 0.0)
        self.status = 'Starting…'
        self.screen_status = 'Disabled'
        self.auth_info = None
        self.signin = QPushButton('Continue with ChatGPT', self)
        self.signin.setGeometry(15, 8, 230, 27)
        self.signin.setStyleSheet('QPushButton { background: #102522; color: #b4f9ee; border: 1px solid #618680; border-radius: 6px; font: 9pt "Segoe UI"; }')
        self.signin.hide()
        self.signin.clicked.connect(lambda: self.control('chatgpt cancel' if self.auth_info and self.auth_info.get('busy') else 'chatgpt login'))
        self.drag = None
        self.blink_until = 0
        self.next_blink = time.monotonic() + 3
        self.setWindowTitle('Virtual Rocky')
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, always_on_top)
        self.setMinimumSize(160, 100)
        self.setMouseTracking(True)
        self.resize(320, 200)
        if preferences:
            data = preferences.load()
            w,h = data.get('width',320),data.get('height',200)
            if type(w) is int and type(h) is int and 160 <= w <= 2048 and 100 <= h <= 1280:
                self.resize(w,h)
            self.size_preset = data.get('preset','Normal') if data.get('preset') in PRESETS else 'Custom'
            if type(data.get('always_on_top')) is bool:
                self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, always_on_top or data['always_on_top'])
            x,y = data.get('x',0),data.get('y',0)
            if type(x) is int and type(y) is int:
                displays = [(d.availableGeometry().x(),d.availableGeometry().y(),d.availableGeometry().width(),d.availableGeometry().height()) for d in __import__('PySide6.QtGui',fromlist=['QGuiApplication']).QGuiApplication.screens()]
                self.move(*visible_position(x,y,self.width(),self.height(),displays))
        bridge.event.connect(self.on_event)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)
    def on_event(self, e):
        kind = e.get('type')
        if kind == 'emotion':
            self.emotion = e.get('name') if e.get('name') in config.EMOTIONS else 'neutral'
            self.variant = random.randrange(3)
        elif kind == 'asleep':
            self.asleep = e.get('on', False)
            if not self.asleep:
                self.activity = 'wake_up'; self.activity_until = time.monotonic() + .5
        elif kind == 'activity':
            if e.get('name') in ('thinking','camera_looking','wake_up'):
                self.activity = e['name'] if e.get('on',True) else None
                self.activity_until = time.monotonic()+e.get('duration',60) if self.activity else 0
        elif kind == 'talking': self.talking = e.get('on', False)
        elif kind == 'listening': self.listening = e.get('on', False)
        elif kind == 'mouth': self.mouth = e.get('level', 0)
        elif kind == 'gaze': self.gaze = (e['x'], e['y'])
        elif kind == 'blink': self.blink_until = time.monotonic() + .15
        elif kind == 'status':
            self.status = e['text']
            self.setToolTip(self.status)
        elif kind == 'screen': self.screen_status = e['text']
        elif kind == 'screen_info': QMessageBox.information(self, 'Screen Vision', e['text'])
        elif kind == 'auth':
            self.auth_info = e
            self.signin.setVisible(e.get('mode') == 'chatgpt' and (not e.get('signed_in') or e.get('busy',False)))
            self.signin.setText('Cancel sign-in' if e.get('busy') else 'Continue with ChatGPT')
        elif kind == 'auth_error':
            QMessageBox.information(self, 'ChatGPT sign-in', e['text'])
        elif kind == 'pan': self.gaze = (max(-1, min(1, e['deg']/60)), self.gaze[1])
        elif kind == 'tilt': self.gaze = (self.gaze[0], max(-1, min(1, -e['deg']/60)))
        self.update_animation()
        self.update()
    def update_animation(self):
        activity = self.activity if time.monotonic() < self.activity_until else None
        self.animation = ('dozing' if self.asleep else 'talking' if self.talking else activity if activity else 'thinking' if self.emotion == 'thinking' else 'watching_screen' if self.screen_status == 'Watching' else 'listening' if self.listening else 'idle')
    def tick(self):
        now = time.monotonic()
        if self.double_blink_at and now >= self.double_blink_at:
            self.blink_until = now + .12
            self.double_blink_at = 0
        if now > self.next_blink:
            self.blink_until = now + .14
            self.next_blink = now + random.uniform(2.5, 6)
            if random.random() < .15: self.double_blink_at = now + .23
            if self.emotion == 'happy' and self.variant == 1: self.wink_until = now + .25
            if not self.talking and not self.listening:
                self.glance = random.choice((-.4,0,.4))
                self.glance_until = now + .6
        self.update_animation()
        self.update()
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor('#050a0c'))
        scale = min(self.width()/260, self.height()/180)
        p.translate((self.width()-260*scale)/2, (self.height()-180*scale)/2)
        p.scale(scale, scale)
        color = QColor('#b4f9ee')
        p.setPen(QPen(color, 3)); p.setBrush(color)
        closed = self.asleep or time.monotonic() < self.blink_until
        for i, x in enumerate((78, 182)):
            y = 70
            if closed or (i == 0 and time.monotonic() < self.wink_until):
                p.drawLine(x-21, y, x+21, y); continue
            h = 38 if self.emotion in ('surprised','excited') else 17 if self.emotion in ('happy','angry','sleepy') else 28
            if self.animation == 'wake_up': h = 38
            elif self.animation == 'listening': h = max(h,30)
            if self.emotion == 'skeptical' and i == 0: h = 12
            if self.emotion == 'confused' and i == self.variant % 2: h = 20
            p.drawRoundedRect(QRectF(x-25, y-h/2, 50, h), 10, 10)
            p.setBrush(QColor('#050a0c'))
            gx, gy = self.gaze
            if time.monotonic() < self.glance_until and self.gaze == (0.0,0.0): gx = self.glance
            if self.animation == 'watching_screen': gy = .25
            if self.emotion == 'curious': gx,gy = .3,-.25
            if self.emotion == 'excited': gy = math.sin(time.monotonic()*5)*.15
            if self.animation == 'thinking' or self.emotion == 'thinking': gx = math.sin(time.monotonic())*.65; gy = -.5
            if self.animation == 'camera_looking': gy = -.15
            pupil = 5 if self.emotion == 'worried' else 8
            p.drawEllipse(QPointF(x+gx*13, y+gy*6), pupil, pupil+1)
            p.setBrush(color)
            if self.emotion in ('angry', 'sad','worried','confused','skeptical','curious'):
                d = (1 if i == 0 else -1) * (1 if self.emotion == 'angry' else -1)
                p.drawLine(x-23, y-27-d*7, x+23, y-27+d*7)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self.talking: p.drawEllipse(QRectF(110, 117-self.mouth*10, 40, 4+self.mouth*25))
        elif self.emotion == 'surprised': p.drawEllipse(QRectF(122, 112, 16, 20))
        else:
            path = QPainterPath(QPointF(109, 120))
            path.quadTo(130, 137 if self.emotion == 'happy' else 103 if self.emotion == 'sad' else 123, 151, 120)
            p.drawPath(path)
        p.setFont(QFont('Segoe UI', max(9,round(6/scale))))
        p.setPen(QColor('#618680'))
        if self.auth_info and self.auth_info.get('signed_in') and not self.auth_info.get('busy'):
            p.drawText(QRectF(8, 8, 244, 26), Qt.AlignmentFlag.AlignCenter, 'Using ChatGPT plan')
        p.drawText(QRectF(8, 136, 244, 16), Qt.AlignmentFlag.AlignCenter, ('Vision: ' if self.width() < 240 else 'Desktop Vision: ') + self.screen_status)
        p.drawText(QRectF(8, 151, 244, 22), Qt.AlignmentFlag.AlignCenter,
                   'Speaking' if self.talking else 'Listening' if self.listening else self.status)
        p.resetTransform()
        p.drawLine(self.width()-10,self.height()-3,self.width()-3,self.height()-10)
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if e.position().x() > self.width()-14 and e.position().y() > self.height()-14:
                self.resize_drag = (e.globalPosition().toPoint(),self.width(),self.height())
                return
            self.drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
    def mouseMoveEvent(self, e):
        if self.resize_drag is None and self.drag is None:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor if e.position().x() > self.width()-14 and e.position().y() > self.height()-14 else Qt.CursorShape.ArrowCursor)
        if self.resize_drag and e.buttons() & Qt.MouseButton.LeftButton:
            start,w,h = self.resize_drag
            delta = e.globalPosition().toPoint()-start
            width = max(160,min(2048,w+delta.x()))
            self.resize(width,max(100,round(width/1.6)))
            self.size_preset = 'Custom'
            return
        if self.drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self.drag)
    def mouseReleaseEvent(self, e):
        self.drag = self.resize_drag = None
    def resizeEvent(self, e):
        scale = min(self.width()/260,self.height()/180)
        self.signin.setGeometry(round((self.width()-260*scale)/2+15*scale),round(8*scale),round(230*scale),max(18,round(27*scale)))
        self.signin.setStyleSheet('QPushButton { background: #102522; color: #b4f9ee; border: 1px solid #618680; border-radius: 6px; font: '+str(max(6,9*scale))+'pt "Segoe UI"; }')
        super().resizeEvent(e)
    def set_preset(self, name):
        self.size_preset = name
        self.resize(*PRESETS[name])
    def closeEvent(self,e):
        if self.preferences:
            try:
                self.preferences.save(dict(x=self.x(),y=self.y(),width=self.width(),height=self.height(),preset=self.size_preset,always_on_top=bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)))
            except OSError: pass
        super().closeEvent(e)
    def contextMenuEvent(self, e):
        menu = QMenu(self)
        sizes = menu.addMenu('Face Size')
        for name,size in PRESETS.items():
            sizes.addAction(name,lambda checked=False,n=name: self.set_preset(n))
        if self.auth_info and self.auth_info.get('mode') == 'chatgpt':
            menu.addAction('Continue with ChatGPT', lambda: self.control('chatgpt login'))
            accounts = menu.addMenu('ChatGPT accounts')
            for account in self.auth_info.get('accounts',[]):
                action = accounts.addAction(account['label'])
                action.setCheckable(True); action.setChecked(account['selected'])
                action.triggered.connect(lambda checked=False,k=account['key']: self.control('chatgpt account '+k))
            accounts.addAction('Add another ChatGPT account…', lambda: self.control('chatgpt login new'))
            models = menu.addMenu('ChatGPT model')
            for model in self.auth_info.get('models',[]):
                action = models.addAction(model['display_name'])
                action.setCheckable(True); action.setChecked(model['slug']==self.auth_info.get('model'))
                action.triggered.connect(lambda checked=False,m=model['slug']: self.control('chatgpt model '+m))
            models.addAction('Refresh model choices', lambda: self.control('chatgpt models'))
            menu.addAction('Manage ChatGPT usage', lambda: __import__('webbrowser').open('https://chatgpt.com/#settings/Usage'))
            menu.addAction('Sign out of ChatGPT', lambda: self.control('chatgpt logout'))
            menu.addSeparator()
        self.add_screen_menu(menu)
        top = menu.addAction('Always on top'); top.setCheckable(True)
        top.setChecked(bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))
        ask = menu.addAction('Type a question…')
        listen = menu.addAction('Toggle microphone')
        track = menu.addAction('Toggle face tracking')
        emotions = menu.addMenu('Expression')
        for name in config.EMOTIONS:
            emotions.addAction(name, lambda n=name: self.on_event({'type':'emotion','name':n}))
        quit_action = menu.addAction('Quit')
        action = menu.exec(e.globalPos())
        if action == top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, top.isChecked()); self.show()
        elif action == ask:
            text, ok = QInputDialog.getText(self, 'Ask Rocky', 'Question:')
            if ok and text.strip(): self.control('ask ' + text.strip())
        elif action == listen: self.control('listen')
        elif action == track: self.control('track toggle')
        elif action == quit_action: self.close()

    def add_screen_menu(self, menu):
        screen_menu = menu.addMenu('Screen Vision: ' + self.screen_status)
        active = self.screen_status in ('Connected', 'Watching', 'Paused')
        enable = screen_menu.addAction('Enable Screen Vision', lambda: self.control('screen enable'))
        enable.setEnabled(self.screen_status in ('Disabled', 'Offline', 'Error'))
        disable = screen_menu.addAction('Disable Screen Vision', lambda: self.control('screen disable'))
        disable.setEnabled(self.screen_status != 'Disabled')
        paused = self.screen_status == 'Paused'
        pause = screen_menu.addAction('Resume Screen Access' if paused else 'Pause Screen Access',
            lambda: self.control('screen resume' if paused else 'screen pause'))
        pause.setEnabled(active)
        monitors = screen_menu.addAction('Monitor List', lambda: self.control('screen monitors'))
        monitors.setEnabled(active)
        screen_menu.addAction('Status', lambda: self.control('screen status'))
        test = screen_menu.addAction('Test Screen Vision', lambda: self.control('screen test'))
        test.setEnabled(self.screen_status in ('Connected','Watching'))
        watch = screen_menu.addAction('Watch Screen (local only)',lambda:self.control('screen watch primary'))
        watch.setEnabled(self.screen_status in ('Connected','Watching'))
        watch_monitor = screen_menu.addAction('Watch Monitor...', self.watch_monitor)
        watch_monitor.setEnabled(self.screen_status in ('Connected','Watching'))
        active_watch = screen_menu.addAction('Watch Active Window',lambda:self.control('screen watch active'))
        active_watch.setEnabled(self.screen_status in ('Connected','Watching'))
        stop = screen_menu.addAction('Stop Watching / Clear Memory',lambda:self.control('screen stopwatch'))
        stop.setEnabled(self.screen_status == 'Watching')
        return screen_menu

    def watch_monitor(self):
        number,ok = QInputDialog.getInt(self,'Watch Monitor','Monitor number:',1,1,32)
        if ok: self.control('screen watch '+str(number))
