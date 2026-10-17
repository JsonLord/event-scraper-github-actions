#!/usr/bin/env python3
"""Offline browser smoke against a built site; uses an installed Chromium."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
from threading import Thread
from playwright.sync_api import sync_playwright


def main():
    p=argparse.ArgumentParser();p.add_argument('--site',default='/tmp/r1-site');p.add_argument('--output',default='/tmp/r1-smoke');a=p.parse_args()
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=a.site))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium'),headless=True,args=['--no-sandbox'])
            context=browser.new_context(timezone_id='Europe/Berlin',accept_downloads=True,viewport={'width':1280,'height':900})
            page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.add_init_script("""{const NativeDate=Date;const fixed=NativeDate.parse('2026-10-17T07:17:00Z');globalThis.Date=class extends NativeDate {constructor(...args){super(...(args.length?args:[fixed]));} static now(){return fixed;}};}""")
            page.goto(f'http://127.0.0.1:{server.server_port}/',wait_until='networkidle')
            page.wait_for_selector('tbody tr')
            visible=page.locator('tbody tr:has(input[type=checkbox])').count()
            assert visible>0
            page.screenshot(path=str(out/'desktop.png'),full_page=False)
            (out/'rendered.html').write_text(page.content())
            page.locator('tbody input[type=checkbox]').first.check()
            with page.expect_download() as dl: page.locator('#exportBtn').click()
            dl.value.save_as(str(out/'selected.ics'))
            calendar=(out/'selected.ics').read_text()
            assert 'BEGIN:VEVENT' in calendar and 'DTSTART' in calendar and 'END:VCALENDAR' in calendar
            page.locator('#showPast').check()
            all_rows=page.locator('tbody tr:has(input[type=checkbox])').count();assert all_rows>=visible
            page.locator('#search').fill('no-such-event-r1-smoke')
            assert page.locator('tbody tr:has(input[type=checkbox])').count()==0
            page.locator('#search').fill('')
            page.locator('#freeOnly').check()
            free_rows=page.locator('tbody tr:has(input[type=checkbox])').count()
            page.locator('#freeOnly').uncheck();page.locator('#showPast').uncheck()
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(out/'mobile.png'),full_page=False)
            assert not errors, errors
            report=dict(default_upcoming_rows=visible,including_past_rows=all_rows,fresh_verified_free_rows=free_rows,ics_export='passed',search='passed',responsive_render='passed',page_errors=errors)
            (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
            browser.close()
    finally:
        server.shutdown();server.server_close()

if __name__=='__main__': main()
