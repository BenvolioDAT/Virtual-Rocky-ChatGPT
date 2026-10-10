"""Capture backend boundary. Imported only by the helper, never by Rocky."""
import io
import sys


def select_monitor(monitors, selection):
    if not monitors:
        raise ValueError('No displays detected.')
    if selection == 'all':
        left = min(m['x'] for m in monitors)
        top = min(m['y'] for m in monitors)
        return dict(x=left, y=top,
                    width=max(m['x'] + m['width'] for m in monitors) - left,
                    height=max(m['y'] + m['height'] for m in monitors) - top)
    if selection == 'primary':
        return next(m for m in monitors if m['primary'])
    if type(selection) is int:
        for monitor in monitors:
            if monitor['id'] == selection:
                return monitor
    raise ValueError('Requested monitor does not exist. Query the monitor list.')


class WindowsCapture:
    def monitors(self):
        if sys.platform != 'win32':
            raise ValueError('This capture backend requires Windows.')
        import mss
        with mss.mss() as capture:
            return [dict(id=i, primary=m['left'] == 0 and m['top'] == 0,
                         x=m['left'], y=m['top'], width=m['width'], height=m['height'])
                    for i, m in enumerate(capture.monitors[1:], 1)]

    def image(self, selection, region=None):
        import mss
        from PIL import Image
        from .windows import foreground_window
        monitors = self.monitors()
        foreground = foreground_window(monitors)
        window = foreground if selection == 'active' else None
        if selection == 'active':
            chosen = dict(window) if window else dict(select_monitor(monitors,'primary'))
            desktop = select_monitor(monitors,'all')
            # Clip to visible desktop pixels. No PrintWindow hooks, game injection or focus changes.
            left,top = max(chosen['x'],desktop['x']),max(chosen['y'],desktop['y'])
            right = min(chosen['x']+chosen['width'],desktop['x']+desktop['width'])
            bottom = min(chosen['y']+chosen['height'],desktop['y']+desktop['height'])
            if right <= left or bottom <= top:
                chosen = dict(select_monitor(monitors,'primary')); window = None
            else: chosen.update(x=left,y=top,width=right-left,height=bottom-top)
        else: chosen = dict(select_monitor(monitors,selection))
        if region is not None:
            if not isinstance(region,dict) or set(region) != {'x','y','width','height'} or any(type(v) is not int for v in region.values()):
                raise ValueError('Region needs integer x,y,width,height relative to the selected monitor/window.')
            x,y,w,h = (region[k] for k in ('x','y','width','height'))
            if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > chosen['width'] or y+h > chosen['height']:
                raise ValueError('Region is outside the selected monitor/window.')
            chosen.update(x=chosen['x']+x,y=chosen['y']+y,width=w,height=h)
        with mss.mss() as capture:
            shot = capture.grab(dict(left=chosen['x'],top=chosen['y'],width=chosen['width'],height=chosen['height']))
            image = Image.frombytes('RGB',shot.size,shot.rgb)
        metadata = dict(monitors=monitors,selected=chosen,selection=dict(monitor=selection,region=region),_foreground=foreground)
        if not window and foreground and (selection == 'all' or foreground['monitor'] == chosen.get('id')):
            window = foreground
        if window: metadata['window'] = window
        if selection == 'active' and not window: metadata['active_fallback'] = 'primary'
        return image,metadata

    def observe(self, selection):
        from . import settings
        image,metadata = self.image(selection)
        image.thumbnail(settings.SCREEN_HISTORY_SIZE)
        return image,metadata

    def capture(self, selection, region=None, tier='overview'):
        from . import settings
        if tier not in ('overview','detail'): raise ValueError('Unknown image tier.')
        image,metadata = self.image(selection,region)
        with image:
            image.thumbnail(settings.SCREEN_DETAIL_SIZE if tier == 'detail' else settings.SCREEN_OVERVIEW_SIZE)
            with io.BytesIO() as buffer:
                image.save(buffer,format='JPEG',quality=settings.SCREEN_DETAIL_QUALITY if tier == 'detail' else settings.SCREEN_OVERVIEW_QUALITY)
                return buffer.getvalue(),dict(metadata,image_width=image.width,image_height=image.height,tier=tier)
