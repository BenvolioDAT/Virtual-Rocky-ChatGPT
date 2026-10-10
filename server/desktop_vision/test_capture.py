"""Manual Windows integration: visible managed helper; no disk images or uploads."""
import base64
import io
import sys
import time
import argparse
from brain.screen import ScreenClient, ScreenVisionManager


def main():
    parser=argparse.ArgumentParser(description='In-memory Windows Screen Vision diagnostic; no provider uploads')
    parser.add_argument('--watch-seconds',type=float,default=0,help='Also observe locally for 0 to 60 seconds and report performance')
    args=parser.parse_args()
    if not 0 <= args.watch_seconds <= 60: parser.error('--watch-seconds must be 0 to 60')
    from PIL import Image
    client = ScreenClient()
    manager = ScreenVisionManager(client)
    failures = []
    def capture(selection, **options):
        try:
            result = client.request('/capture', dict(monitor=selection,**options))
            desktop_frame = base64.b64decode(result['jpeg'], validate=True)
            with Image.open(io.BytesIO(desktop_frame)) as image:
                image.verify()
                dimensions = image.size
            print(f'Capture {selection}: PASS {dimensions[0]}x{dimensions[1]} {len(desktop_frame)} bytes')
            return True
        except Exception as exc:
            failures.append(str(exc))
            print(f'Capture {selection}: FAIL {exc}')
            return False
    try:
        if manager.enable() != 'Connected':
            raise RuntimeError('Managed helper did not connect. Check diagnostics above.')
        monitors = client.request('/monitors')
        if not monitors:
            raise RuntimeError('No monitors detected.')
        print('Monitor enumeration: PASS', monitors)
        capture('primary'); capture('primary')
        for monitor in monitors:
            capture(monitor['id'])
        capture('primary'); capture('all')
        capture('active')
        first=monitors[0]
        capture(first['id'],region=dict(x=0,y=0,width=min(300,first['width']),height=min(200,first['height'])),tier='detail')
        passed = sum(capture('primary') for _ in range(20))
        print(f'Repeated captures: {passed}/20 PASS')
        if args.watch_seconds:
            manager.watch(interval=2)
            time.sleep(args.watch_seconds)
            status=client.request('/status')['watch']
            print('Local Watch:',status)
            if status['automatic_cloud_uploads'] != 0 or status['frames'] > status['max_frames'] or client.model_image_count:
                raise RuntimeError('Local Watch exceeded its limits.')
            manager.watch(enabled=False)
            if client.request('/status')['watch']['frames'] != 0:
                raise RuntimeError('Stop did not clear visual memory.')
            print('Local Watch / no provider traffic / RAM cleanup: PASS')
        manager.pause(True)
        try:
            client.request('/capture', {'monitor':'primary'})
            failures.append('Paused capture was allowed.')
        except ValueError as exc:
            if 'paused' not in str(exc).lower(): raise
            print('Pause denies capture: PASS')
        manager.pause(False); capture('primary')
        token, url = client.token, client.url
        client.disconnect()
        client.token, client.url = token, url
        client.state = 'Connected'
        if client.status() != 'Connected':
            raise RuntimeError('Reconnect failed.')
        capture('primary')
        print('Same-session reconnect: PASS')
    except Exception as exc:
        failures.append(str(exc))
        print('Integration: FAIL', exc)
    finally:
        process = manager.process
        manager.disable()
        if client.token is not None or (process and process.poll() is None):
            failures.append('Shutdown did not revoke the session.')
        print('Cleanup:', 'PASS' if client.token is None and (not process or process.poll() is not None) else 'FAIL')
        client.local.requested = True
        text, desktop_frame = client.look({'monitor':'primary'})
        if desktop_frame is not None or 'disabled' not in text.lower():
            failures.append('Disabled capture was not denied.')
        print('Disabled capture denied:', 'PASS' if desktop_frame is None else 'FAIL')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
