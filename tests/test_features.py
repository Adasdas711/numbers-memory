"""Personal images, portable backups, adaptive training, analysis and offline app."""
import functools
import http.server
import json
from pathlib import Path
import threading
from playwright.sync_api import expect
from test_app import BrowserTestCase, QuietHandler, ROOT


class FeatureTests(BrowserTestCase):
    def open_tools(self):
        self.nav('theory')
        self.page.locator('#personalTools summary').click()

    def test_personal_word_description_picture_persistence_reset_and_matching(self):
        self.open_tools()
        self.page.locator('#personalId').select_option('25')
        self.page.locator('#personalWord').fill('Моя ракета')
        self.page.locator('#personalDescription').fill('Летит над домом')
        self.page.locator('#personalPicture').set_input_files(str(ROOT/'icons/icon-192.png'))
        self.page.locator('#personalForm button[type=submit]').click()
        expect(self.page.locator('#dataStatus')).to_have_text('Образ сохранён.')
        expect(self.page.locator('.cell[data-id="25"] .w')).to_have_text('Моя ракета')
        expect(self.page.locator('#cellDetail img')).to_be_visible()
        self.assertTrue(self.page.evaluate('matchWord("25", "моя ракета")'))
        self.assertFalse(self.page.evaluate('matchWord("25", "топор")'))
        self.page.reload()
        expect(self.page.locator('.cell[data-id="25"] .w')).to_have_text('Моя ракета')
        self.open_tools()
        self.page.locator('#personalId').select_option('25')
        self.page.locator('#personalReset').click()
        expect(self.page.locator('.cell[data-id="25"] .w')).to_have_text('топор')
        self.page.reload()
        self.assertFalse(self.page.evaluate('Object.hasOwn(personalImages,"25")'))

    def test_invalid_picture_does_not_replace_existing_image(self):
        self.open_tools()
        self.page.locator('#personalWord').fill('Замена')
        self.page.locator('#personalPicture').set_input_files({'name':'bad.svg','mimeType':'image/svg+xml','buffer':b'<svg/>'})
        self.page.locator('#personalForm button[type=submit]').click()
        expect(self.page.locator('#dataStatus')).to_contain_text('PNG, JPEG или WebP')
        self.assertEqual(self.page.evaluate('personalImages'), {})

    def test_personal_description_is_escaped(self):
        self.open_tools()
        self.page.locator('#personalDescription').fill('<img src=x onerror="window.injected=true">')
        self.page.locator('#personalForm button[type=submit]').click()
        expect(self.page.locator('#dataStatus')).to_have_text('Образ сохранён.')
        self.assertIsNone(self.page.evaluate('window.injected'))
        expect(self.page.locator('#cellDetail .img img')).to_have_count(0)

    def seed_data(self):
        self.page.evaluate('''async () => {
          Settings.set('dg.len.custom','17');
          Stats.rec('25',{ok:true,tType:123});
          personalImages={'25':{word:'Ракета',description:'Мой образ',picture:''}};
          persistRecord(PERSONAL_KEY,personalImages);applyPersonalImages();
          adaptiveRuns={dec:{length:20,attempts:[1,.95]}};
          persistRecord(ADAPTIVE_KEY,adaptiveRuns);
          await VoiceDB.put('0',{sr:22050,pcm:Float32Array.from({length:2205},(_,i)=>Math.sin(i*.1)*.3)});
        }''')

    def test_backup_roundtrip_restores_settings_stats_images_adaptation_and_voice(self):
        self.seed_data()
        data=self.page.evaluate('async () => await createBackup()')
        self.assertEqual(len(data['voices']['0']['pcm']),2205)
        self.page.evaluate('''async () => {
          await VoiceDB.clear(); Stats.reset(); personalImages={};adaptiveRuns={};Settings.set('dg.len.custom','2');
        }''')
        self.page.evaluate('async data => await restoreBackup(data)',data)
        self.page.reload()
        expect(self.page.locator('.cell[data-id="25"] .w')).to_have_text('Ракета')
        self.assertEqual(self.page.evaluate('Settings.get("dg.len.custom")'),'17')
        self.assertEqual(self.page.evaluate('Stats.d["25"].ok'),1)
        self.assertEqual(self.page.evaluate('adaptiveRuns.dec.length'),20)
        expect(self.page.locator('#voiceGrid .has')).to_have_count(1)
        self.assertEqual(self.page.evaluate('ownRecs["0"].pcm.length'),2205)

    def test_export_download_is_valid_backup(self):
        self.seed_data();self.open_tools()
        with self.page.expect_download() as capture:
            self.page.locator('#exportData').click()
        data=json.loads(Path(capture.value.path()).read_text())
        self.assertEqual(data['app'],'numbers-memory')
        self.assertEqual(data['personal']['25']['word'],'Ракета')
        self.assertIn('0',data['voices'])
        self.page.evaluate('data => validateBackup(data)',data)

    def test_import_requires_confirmation_and_applies_file(self):
        self.seed_data()
        data=self.page.evaluate('async () => await createBackup()')
        data['personal']['25']['word']='Новый образ'
        self.open_tools()
        self.page.locator('#importFile').set_input_files({'name':'backup.json','mimeType':'application/json','buffer':json.dumps(data).encode()})
        self.page.locator('#importData').click()
        expect(self.page.locator('#dataStatus')).to_contain_text('подтверди замену')
        self.page.locator('#importConfirm').check()
        self.page.locator('#importData').click()
        expect(self.page.locator('.cell[data-id="25"] .w')).to_have_text('Новый образ')

    def test_invalid_backup_does_not_mutate_storage(self):
        self.seed_data()
        data=self.page.evaluate('async () => await createBackup()')
        before=self.page.evaluate('async () => JSON.stringify(await createBackup())')
        for change in ['version','voice','image','settings','adaptive']:
            with self.subTest(change=change):
                modified=json.loads(json.dumps(data))
                if change=='version':modified['version']=999
                elif change=='voice':modified['voices']['0']['pcm'][0]=4
                elif change=='image':modified['personal']['25']['picture']='javascript:alert(1)'
                elif change=='settings':modified['settings']['unknown']='bad'
                else:modified['adaptive']['dec']['attempts']=[2]
                result=self.page.evaluate('''async data => {
                  try { await restoreBackup(data); return 'unexpected success'; }catch(e){return e.message;}
                }''',modified)
                self.assertNotEqual(result,'unexpected success')
                current=self.page.evaluate('async () => await createBackup()')
                original=json.loads(before)
                current.pop('exportedAt');original.pop('exportedAt')
                self.assertEqual(current,original)

    def test_failed_voice_import_rolls_back_local_settings_and_preserves_database(self):
        self.seed_data()
        data=self.page.evaluate('async () => await createBackup()');data['settings']['dg.len.custom']='99'
        self.page.evaluate('''async () => {
          const db=await VoiceDB.open(); window.realTransaction=db.transaction.bind(db);
          db.transaction=(...args)=> {const tx=realTransaction(...args);
            if(args[1]==='readwrite')queueMicrotask(()=>tx.abort());return tx;};
        }''')
        result=self.page.evaluate('''async data => {
          try{await restoreBackup(data);return 'success';}catch(e){return e.message;}
        }''',data)
        self.assertIn('Исходные данные сохранены',result)
        self.page.reload()
        self.assertEqual(self.page.evaluate('Settings.get("dg.len.custom")'),'17')
        expect(self.page.locator('#voiceGrid .has')).to_have_count(1)

    def test_adaptation_disabled_preserves_manual_settings(self):
        self.nav('digits');self.count('dg.len',17)
        self.assertEqual(self.page.evaluate('readSeqSetup("dec").len'),17)
        self.assertEqual(self.page.evaluate('Adaptive.record("dec",17,17)'), '')
        self.assertEqual(self.page.evaluate('adaptiveRuns'),{})

    def test_three_good_results_increase_next_length_and_three_bad_decrease_it(self):
        self.nav('digits');self.count('dg.len',10)
        self.page.locator('[data-adaptive="dec"]').check()
        for _ in range(2):self.page.evaluate('Adaptive.record("dec",10,10)')
        self.assertEqual(self.page.evaluate('readSeqSetup("dec").len'),10)
        self.page.evaluate('Adaptive.record("dec",10,10)')
        self.assertEqual(self.page.evaluate('readSeqSetup("dec").len'),12)
        for _ in range(3):self.page.evaluate('Adaptive.record("dec",12,0)')
        self.assertEqual(self.page.evaluate('readSeqSetup("dec").len'),10)
        self.page.reload();self.assertEqual(self.page.evaluate('readSeqSetup("dec").len'),10)

    def test_adaptive_audio_tempo_binary_rounding_and_caps(self):
        self.page.evaluate('''() => {
          Settings.set('adaptive.audio',true);Settings.set('adaptive.bin',true);
          for(let i=0;i<3;i++){Adaptive.record('audio',10,10,.8);Adaptive.record('bin',12,12);}
        }''')
        self.assertEqual(self.page.evaluate('adaptiveRuns.audio.tempo'),.5)
        self.assertEqual(self.page.evaluate('adaptiveRuns.bin.length'),15)
        self.page.evaluate('''() => {for(let i=0;i<3;i++)Adaptive.record('bin',1200,1200);}''')
        self.assertEqual(self.page.evaluate('adaptiveRuns.bin.length'),1200)

    def test_completed_training_shows_error_analysis_and_records_adaptive_result(self):
        self.nav('digits');self.count('dg.len',5)
        self.page.locator('[data-adaptive="dec"]').check()
        self.page.locator('#dgSetup .start').click();self.page.locator('#dgRun .to-recall').click()
        self.page.locator('#dgRun .check').click()
        expect(self.page.locator('#dgRun .recall-analysis')).to_contain_text('Пропущен образ')
        expect(self.page.locator('#dgRun .adaptive-feedback')).to_contain_text('Следующая тренировка')
        self.assertEqual(self.page.evaluate('adaptiveRuns.dec.attempts'),[0])

    def test_analysis_detects_swapped_units_digits_incomplete_and_missing(self):
        rows=self.page.evaluate('''() => analyzeRecall('dec','12345678',toUnits('dec','12345678'),['34','12','65',''])''')
        self.assertEqual([r['reason'] for r in rows],['Переставлены соседние образы']*2+['Переставлены цифры внутри образа','Пропущен образ'])
        self.assertEqual(self.page.evaluate('analyzeRecall("dec","123",toUnits("dec","123"),["1","3"])[0].reason'),'Неполный ответ')
        self.assertEqual(self.page.evaluate('analyzeRecall("bin","010111",toUnits("bin","010111"),["010111"])'),[])

    def test_manifest_and_icons(self):
        manifest=self.page.evaluate('async () => await (await fetch("manifest.webmanifest")).json()')
        self.assertEqual(manifest['display'],'standalone')
        self.assertEqual(manifest['scope'],'./')
        for icon in manifest['icons']:
            self.assertEqual(self.page.request.get(self.url+icon['src'].removeprefix('./')).status,200)

    def test_pwa_under_github_pages_project_path_works_offline(self):
        class MountedHandler(QuietHandler):
            def translate_path(handler,path):
                return super().translate_path(path.removeprefix('/numbers-memory'))
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(MountedHandler,directory=str(ROOT)))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(thread.join);self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        self.page.goto(f'http://127.0.0.1:{server.server_port}/numbers-memory/')
        scope=self.page.evaluate('async () => (await navigator.serviceWorker.ready).scope')
        self.assertTrue(scope.endswith('/numbers-memory/'))
        self.page.wait_for_function('navigator.serviceWorker.controller !== null')
        self.context.set_offline(True);self.page.reload()
        expect(self.page.locator('#grid2 .cell')).to_have_count(100)
        expect(self.page.locator('#personalTools')).to_be_attached()

    def test_import_quota_failure_rolls_back_existing_data(self):
        self.seed_data();data=self.page.evaluate('async () => await createBackup()')
        data['settings']['dg.len.custom']='99'
        self.page.evaluate('''() => {
          const original=Storage.prototype.setItem;let calls=0;
          Storage.prototype.setItem=function(...args){
            if(++calls===2)throw new DOMException('Quota','QuotaExceededError');
            return original.apply(this,args);
          };
        }''')
        result=self.page.evaluate('''async data=>{
          try{await restoreBackup(data);return 'success';}catch(e){return e.message;}
        }''',data)
        self.assertIn('Исходные данные сохранены',result)
        self.assertEqual(self.page.evaluate('JSON.parse(localStorage.getItem(SETTINGS_KEY))["dg.len.custom"]'),'17')
        self.assertEqual(self.page.evaluate('async()=>Object.keys(await VoiceDB.all())'),['0'])

    def test_nonadjacent_permutation_is_explained(self):
        result=self.page.evaluate('''()=>analyzeRecall('dec','12345678',toUnits('dec','12345678'),['56','78','12','34'])''')
        self.assertEqual([r['reason'] for r in result],['Нарушен порядок образов']*4)

    def test_offline_reload_keeps_application_and_english_audio_functional(self):
        self.page.evaluate('async () => await navigator.serviceWorker.ready')
        self.page.wait_for_function('navigator.serviceWorker.controller !== null')
        self.context.set_offline(True)
        self.page.reload()
        expect(self.page.locator('#grid2 .cell')).to_have_count(100)
        self.nav('digits');self.page.locator('#dgSetup .start').click()
        expect(self.page.locator('#dgRun .memo-area')).to_be_visible()
        self.nav('audio');self.page.locator('#auTest').click()
        self.page.wait_for_function('enBufs !== null')
        self.assertEqual(self.page.evaluate('Object.keys(enBufs).length'),10)
        self.assertEqual(self.errors,[])

    def test_update_waits_for_user_then_reloads_and_removes_old_cache(self):
        original=(ROOT/'sw.js').read_text()
        class UpdateHandler(QuietHandler):
            def do_GET(handler):
                if handler.path.split('?')[0]=='/sw.js':
                    content=original
                    if handler.server.updated:
                        import re
                        content=re.sub(r"const CACHE = '[^']+';","const CACHE = 'numbers-memory-test-update';",content)
                    payload=content.encode();handler.send_response(200)
                    handler.send_header('Content-Type','application/javascript')
                    handler.send_header('Cache-Control','no-store');handler.end_headers();handler.wfile.write(payload)
                else:super().do_GET()
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(UpdateHandler,directory=str(ROOT)))
        server.updated=False
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(thread.join);self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        self.page.goto(f'http://127.0.0.1:{server.server_port}/')
        self.page.evaluate('async () => await navigator.serviceWorker.ready')
        self.page.wait_for_function('navigator.serviceWorker.controller !== null')
        server.updated=True
        self.page.evaluate('async () => {const reg=await navigator.serviceWorker.getRegistration(); await reg.update();}')
        self.page.locator('#personalTools summary').click()
        expect(self.page.locator('#updateApp')).to_be_visible(timeout=10000)
        self.assertTrue(self.page.evaluate('''async () => {
          const reg=await navigator.serviceWorker.getRegistration();
          return reg.waiting !== null && reg.active !== reg.waiting;
        }'''))
        self.page.evaluate('window.reloadMarker=true')
        self.page.locator('#updateApp').click()
        self.page.wait_for_function('window.reloadMarker === undefined')
        self.assertEqual(self.page.evaluate('async () => await caches.keys()'),['numbers-memory-test-update'])
