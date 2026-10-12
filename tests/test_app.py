"""Browser regressions: python -m unittest discover -s tests -v."""
import functools
import http.server
import os
import re
from pathlib import Path
import shutil
import threading
import unittest
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


class BrowserTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(
            ('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(ROOT)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/'
        cls.pw = sync_playwright().start()
        executable = os.environ.get('CHROMIUM_PATH') or shutil.which('chromium')
        cls.browser = cls.pw.chromium.launch(
            **({'executable_path': executable} if executable else {}),
            args=['--no-sandbox'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.set_default_timeout(5000)
        self.errors = []
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        self.addCleanup(self.context.close)
        self.addCleanup(lambda: self.assertEqual(self.errors, []))
        response = self.page.goto(self.url)
        self.assertEqual(response.status, 200)

    def nav(self, target):
        self.page.locator(f'[data-go="{target}"]').click()

    def seg(self, key, value):
        self.page.locator(f'[data-store="{key}"] [data-val="{value}"]').click()

    def count(self, key, n):
        self.seg(key, 'custom')
        field = self.page.locator(f'input[data-store="{key}.custom"]')
        field.fill(str(n))
        field.dispatch_event('change')

    def learn(self, mode):
        self.nav('learn:' + mode)
        return self.page.locator(f'.lmode[data-mode="{mode}"]')


class AppTests(BrowserTestCase):
    def test_theory_tables_details_and_heat(self):
        expect(self.page).to_have_title('Цифры')
        expect(self.page.locator('#grid2 .cell')).to_have_count(100)
        expect(self.page.locator('#grid1 .cell')).to_have_count(10)
        expect(self.page.locator('#codeGrid .code-cell')).to_have_count(10)
        expect(self.page.locator('#binTable > div')).to_have_count(8)
        cell = self.page.locator('#grid2 .cell[data-id="25"]')
        word = cell.locator('.w').inner_text()
        cell.click()
        expect(self.page.locator('#cellDetail .big')).to_contain_text(word)
        self.page.locator('#heatToggle').check()
        expect(self.page.locator('#heatLegend')).to_be_visible()
        self.page.locator('#heatToggle').uncheck()
        expect(self.page.locator('#heatLegend')).to_be_hidden()

    def test_all_navigation_and_settings_persist(self):
        for target in ['learn:assoc', 'learn:speed', 'learn:metro', 'learn:check',
                       'digits', 'binary', 'audio', 'theory']:
            self.nav(target)
            expect(self.page.locator('#tab-' + (target.split(':')[0]))).to_be_visible()
        self.nav('digits')
        self.count('dg.len', 17)
        self.seg('dg.view', 'sheet')
        self.page.reload()
        expect(self.page.locator('#tab-digits')).to_be_visible()
        expect(self.page.locator('input[data-store="dg.len.custom"]')).to_have_value('17')
        expect(self.page.locator('[data-store="dg.view"] [data-val="sheet"]')).to_have_class('active')

    def test_mobile_menu_escape_backdrop_and_navigation(self):
        self.page.set_viewport_size({'width': 390, 'height': 844})
        toggle = self.page.locator('#menuToggle')
        toggle.click()
        expect(toggle).to_have_attribute('aria-expanded', 'true')
        self.page.keyboard.press('Escape')
        expect(toggle).to_have_attribute('aria-expanded', 'false')
        toggle.click()
        self.page.locator('#menuBackdrop').click(position={'x': 380, 'y': 400})
        expect(toggle).to_have_attribute('aria-expanded', 'false')
        toggle.click()
        self.nav('binary')
        expect(self.page.locator('#tab-binary')).to_be_visible()
        expect(toggle).to_have_attribute('aria-expanded', 'false')

    def test_word_analysis_and_html_is_not_executed(self):
        self.learn('check')
        field = self.page.locator('#checkInput')
        field.fill('топор')
        expect(self.page.locator('#checkOut')).to_contain_text('25')
        field.fill('<img src=x onerror="window.injected=true">')
        self.assertIsNone(self.page.evaluate('window.injected'))
        expect(self.page.locator('#checkOut img')).to_have_count(0)
        field.fill('')
        expect(self.page.locator('#checkOut')).to_contain_text('Покажу')

    def test_association_correct_wrong_skip_retry_and_stats(self):
        root = self.learn('assoc')
        self.count('assoc.count', 2)
        self.seg('assoc.dir', 'toWord')
        root.locator('.start').click()
        box = root.locator('.runbox')
        number = box.locator('.prompt .num').inner_text()
        word = self.page.locator(f'#grid2 .cell[data-id="{number}"], #grid1 .cell[data-id="{number}"]').locator('.w').inner_text()
        box.locator('.ans').fill(word)
        box.locator('.ans').press('Enter')
        expect(box.locator('.progress-text')).to_have_text('2 / 2')
        box.locator('.ans').fill('заведомоневерно')
        box.locator('.go').click()
        expect(box.locator('.prompt')).to_have_class('prompt bad')
        box.locator('.go').click()
        expect(box.locator('.stats-box .v').first).to_have_text('1 / 2')
        box.locator('.retry-wrong').click()
        expect(box.locator('.progress-text')).to_have_text('1 / 1')
        box.locator('.skip').click()
        box.locator('.go').click()
        expect(box.locator('.stats-box .v').first).to_have_text('0 / 1')
        self.nav('theory')
        expect(self.page.locator('#statsSummary')).to_contain_text('Данные есть по 2')
        self.page.reload()
        expect(self.page.locator('#statsSummary')).to_contain_text('Данные есть по 2')
        self.page.once('dialog', lambda d: d.dismiss())
        self.page.locator('#resetStats').click()
        expect(self.page.locator('#statsSummary')).to_contain_text('Данные есть')
        self.page.once('dialog', lambda d: d.accept())
        self.page.locator('#resetStats').click()
        expect(self.page.locator('#statsSummary')).to_contain_text('Статистики пока нет')

    def test_association_word_to_number(self):
        root = self.learn('assoc')
        self.count('assoc.count', 1)
        self.seg('assoc.dir', 'toNum')
        root.locator('.start').click()
        word = root.locator('.prompt .word').inner_text()
        cells = self.page.locator('#grid2 .cell, #grid1 .cell')
        answer = next(cell.get_attribute('data-id') for cell in cells.all()
                      if cell.locator('.w').inner_text() == word)
        root.locator('.ans').fill(answer)
        root.locator('.go').click()
        expect(root.locator('.stats-box .v').first).to_have_text('1 / 1')

    def test_audio_decode_failure_is_reported(self):
        self.nav('audio')
        # Fault injection tests the UI error path, separate from real MP3 tests.
        self.page.evaluate("""() => {
          getCtx().decodeAudioData = () => Promise.reject(new Error('bad audio'));
        }""")
        self.page.locator('#auSetup .start').click()
        expect(self.page.locator('#auVoiceInfo')).to_contain_text('Не получилось подготовить звук')
        expect(self.page.locator('#auSetup')).to_be_visible()
        expect(self.page.locator('#auRun')).to_be_hidden()

    def test_association_self_grading_keyboard(self):
        root = self.learn('assoc')
        self.count('assoc.count', 2)
        self.seg('assoc.fmt', 'show')
        root.locator('.start').click()
        self.page.keyboard.press('Space')
        expect(root.locator('.grade')).to_be_visible()
        self.page.keyboard.press('ArrowRight')
        self.page.keyboard.press('Space')
        self.page.keyboard.press('ArrowLeft')
        expect(root.locator('.stats-box .v').first).to_have_text('1 / 2')

    def test_code_drill_all_directions(self):
        root = self.learn('assoc')
        code = {cell.locator('.d').inner_text(): cell.locator('.c').inner_text()
                for cell in self.page.locator('#codeGrid .code-cell').all()}
        letters = {letter.lower(): digit for digit, pair in code.items()
                   for letter in pair.split()}
        self.seg('assoc.kind', 'code')
        for kind in ['d2l', 'l2d', 'w2n']:
            with self.subTest(kind=kind):
                self.seg('code.kind', kind)
                root.locator('.start').click()
                box = root.locator('.runbox')
                expect(box.locator('.prompt')).to_be_visible()
                if kind == 'd2l':
                    answer = code[box.locator('.prompt .num').inner_text()]
                elif kind == 'l2d':
                    answer = letters[box.locator('.prompt .num').inner_text().lower()]
                else:
                    word = box.locator('.prompt .word').inner_text().lower()
                    answer = ''.join(letters[c] for c in word if c in letters)[:2]
                box.locator('.ans').fill(answer)
                box.locator('.go').click()
                expect(box.locator('.progress-text')).to_have_text('№ 2')
                box.locator('.skip').click()
                expect(box.locator('.feedback')).not_to_be_empty()
                box.locator('.stop').click()
                expect(box.locator('.stats-box .v').first).to_have_text('1 / 2')
                box.locator('.back').click()

    def test_random_access_remember_and_answer(self):
        root = self.learn('assoc')
        self.seg('assoc.kind', 'random')
        self.count('rnd.count', 2)
        self.seg('rnd.q', 'at')
        root.locator('.start').click()
        sequence = root.locator('.rnd-cell b').all_text_contents()
        root.locator('.ready').click()
        for i in range(2):
            position = int(root.locator('.prompt .num').inner_text())
            root.locator('.ans').fill(sequence[position - 1])
            root.locator('.go').click()
            if i == 0:
                expect(root.locator('.progress-text')).to_have_text('2 / 2')
        expect(root.locator('.stats-box .v').first).to_have_text('2 / 2')

    def test_speed_and_verification(self):
        root = self.learn('speed')
        self.count('speed.count', 3)
        root.locator('.start').click()
        for i in range(3):
            # Application deliberately ignores reactions faster than 120ms.
            self.page.wait_for_timeout(150)
            self.page.keyboard.press('Space')
        expect(root.locator('.ans')).to_be_visible()
        for i in range(3):
            root.locator('.skip').click()
            root.locator('.go').click()
        expect(root.locator('.stats-box')).to_be_visible()
        root.locator('.back').click()
        self.count('speed.count', 1)
        root.locator('[data-store="speed.verify"]').uncheck()
        root.locator('.start').click()
        self.page.wait_for_timeout(150)
        root.locator('.prompt').click()
        expect(root.locator('.stats-box')).to_be_visible()

    def test_flash_disappears_and_scores_correct_answer(self):
        root = self.learn('speed')
        self.seg('speed.kind', 'flash')
        root.locator('[data-store="speed.pool"]').select_option('two')
        self.count('speed.count', 1)
        self.seg('flash.ms', '300')
        self.seg('flash.ans', 'digits')
        root.locator('.start').click()
        number = root.locator('.flash-num')
        answer = self.page.wait_for_function(
            "() => { const s=document.querySelector('.flash-num').textContent; return /^\\d{2}$/.test(s) && s; }").json_value()
        expect(number).to_have_text('··')
        root.locator('.ans').fill(answer)
        root.locator('.go').click()
        expect(root.locator('.stats-box .v').first).to_have_text('1 / 1')

    def test_metronome_misses_and_retry(self):
        root = self.learn('metro')
        self.count('metro.count', 1)
        self.seg('metro.tempo', '1')
        root.locator('.start').click()
        root.locator('.miss').click()
        expect(root.locator('.stats-box .v').first).to_have_text('0 / 1')
        root.locator('.missed-only').click()
        expect(root.locator('.miss')).to_be_visible()
        root.locator('.stop').click()
        expect(root.locator('.stats-box')).to_be_visible()

    def sequence(self, kind, view, answers_correct=True):
        prefix = 'bn' if kind == 'binary' else 'dg'
        self.nav(kind)
        self.count(prefix + '.len', 10)
        self.seg(prefix + '.view', view)
        self.seg(prefix + '.memo', '0')
        self.seg(prefix + '.recall', '0')
        self.page.locator('#' + prefix + 'Setup .start').click()
        box = self.page.locator('#' + prefix + 'Run')
        # Read the displayed sequence, never the generator or scoring implementation.
        if view == 'sheet':
            chars = box.locator('.sheet-units .u').all_text_contents()
        else:
            chars = []
            while True:
                chars += box.locator('.unit .chars').all_text_contents()
                progress = box.locator('.progress-text').inner_text()
                end, total = re.search(r'–(\d+) из (\d+)', progress).groups()
                if end == total:
                    break
                box.locator('.next').click()
        digits = ''.join(''.join(c.split()) for c in chars)
        self.assertEqual(len(digits), 12 if prefix == 'bn' else 10)
        box.locator('.to-recall').click()
        fields = box.locator('.recall-grid input')
        offset = 0
        for field in fields.all():
            length = int(field.get_attribute('maxlength'))
            value = digits[offset:offset + length]
            if not answers_correct and offset == 0:
                value = ('1' if value[0] == '0' else '0') + value[1:]
            field.fill(value)
            offset += length
        box.locator('.check').click()
        expect(box.locator('.stats-box .v').first).to_have_text(
            f'{len(digits) if answers_correct else len(digits)-1} / {len(digits)}')
        expect(box.locator('.res-unit.bad')).to_have_count(0 if answers_correct else 1)
        box.locator('.again').click()
        expect(box.locator('.memo-area')).to_be_visible()
        box.locator('.cancel').click()
        expect(self.page.locator('#' + prefix + 'Setup')).to_be_visible()

    def test_decimal_groups(self):
        self.sequence('digits', 'groups')

    def test_decimal_sheet_wrong_answer(self):
        self.sequence('digits', 'sheet', False)

    def test_binary_groups_rounding(self):
        self.sequence('binary', 'groups')

    def test_binary_sheet(self):
        self.sequence('binary', 'sheet')

    def test_pool_filters_empty_weak_and_decade(self):
        root = self.learn('assoc')
        root.locator('[data-store="assoc.pool"]').select_option('weak')
        root.locator('.start').click()
        expect(root.locator('.pool-msg')).to_contain_text('Слабых чисел пока нет')
        expect(root.locator('.setup')).to_be_visible()
        root.locator('[data-store="assoc.pool"]').select_option('decade')
        root.locator('[data-store="assoc.decade"]').select_option('4')
        self.count('assoc.count', 1)
        self.seg('assoc.dir', 'toWord')
        root.locator('.start').click()
        expect(root.locator('.prompt .num')).to_have_text(re.compile(r'4[0-9]'))
        root.locator('.stop').click()
        expect(root.locator('.setup')).to_be_visible()

    def test_sequence_timers_auto_recall_and_finish(self):
        self.nav('digits')
        self.count('dg.len', 2)
        self.seg('dg.memo', '60')
        self.seg('dg.recall', '300')
        self.page.clock.install()
        self.page.locator('#dgSetup .start').click()
        self.page.clock.run_for(61000)
        expect(self.page.locator('#dgRun input')).to_have_count(1)
        self.page.clock.run_for(301000)
        expect(self.page.locator('#dgRun .stats-box .v').first).to_have_text('0 / 2')

    def test_recall_sanitization_focus_and_cancel(self):
        self.nav('binary')
        self.count('bn.len', 12)
        self.page.locator('#bnSetup .start').click()
        self.page.locator('#bnRun .to-recall').click()
        inputs = self.page.locator('#bnRun input')
        inputs.first.fill('0x12')
        expect(inputs.first).to_have_value('01')
        inputs.first.fill('010101')
        expect(inputs.nth(1)).to_be_focused()
        inputs.nth(1).press('Backspace')
        expect(inputs.first).to_be_focused()
        self.page.locator('#bnRun .cancel').click()
        expect(self.page.locator('#bnSetup')).to_be_visible()

    def test_record_voice_from_real_media_stream(self):
        self.nav('audio')
        self.page.locator('#auRecorder summary').click()
        # Supply an oscillator as microphone input; retain the real MediaRecorder,
        # codec decoding, normalization, IndexedDB and playback code paths.
        self.page.evaluate("""() => {
          navigator.mediaDevices.getUserMedia = async () => {
            const ctx = getCtx(); await ctx.resume();
            const stream = ctx.createMediaStreamDestination();
            const osc = ctx.createOscillator();
            osc.connect(stream); osc.start();
            window.testOsc = osc;
            return stream.stream;
          };
        }""")
        self.page.locator('#voiceGrid .voice-tile').first.locator('.rec').click()
        expect(self.page.locator('#voiceGrid .has')).to_have_count(1, timeout=10000)
        expect(self.page.locator('#voiceMsg')).to_contain_text('Записано 1 из 10')
        self.page.evaluate('testOsc.stop()')
        self.page.reload()
        expect(self.page.locator('#voiceGrid .has')).to_have_count(1)

    def audio_probe(self):
        self.page.evaluate('''() => {
          window.sources = []; window.tones = [];
          const start = AudioBufferSourceNode.prototype.start;
          AudioBufferSourceNode.prototype.start = function(...args) {
            sources.push({duration:this.buffer.duration, time:args[0],
              peak: Math.max(...this.buffer.getChannelData(0))});
            return start.apply(this,args);
          };
          const osc = OscillatorNode.prototype.start;
          OscillatorNode.prototype.start = function(...args) {
            tones.push(args[0]); return osc.apply(this,args);
          };
        }''')

    def test_english_all_mp3s_decode_non_silent_and_sound_button(self):
        self.nav('audio')
        buffers = self.page.evaluate('''async () => {
          const ctx = getCtx(); await ctx.resume();
          const buffers = await getEnBuffers(ctx);
          return Object.values(buffers).map(b => ({duration:b.duration,
            peak: Math.max(...b.getChannelData(0))}));
        }''')
        self.assertEqual(len(buffers), 10)
        for buffer in buffers:
            self.assertGreater(buffer['duration'], .1)
            self.assertGreater(buffer['peak'], .1)
        self.audio_probe()
        self.page.locator('#auTest').click()
        self.page.wait_for_function('sources.length === 3')
        self.assertEqual(self.page.evaluate('getCtx().state'), 'running')
        times = self.page.evaluate('sources.map(s=>s.time)')
        self.assertAlmostEqual(times[1] - times[0], .8)

    def test_audio_training_pause_resume_recall_score_and_stop(self):
        self.nav('audio')
        self.audio_probe()
        self.count('au.count', 2)
        self.page.locator('#auInterval').select_option('0.5')
        self.page.locator('#auSetup .start').click()
        box = self.page.locator('#auRun')
        expect(box.locator('.countdown')).to_be_visible()
        self.assertEqual(self.page.evaluate('sources.length'), 2)
        self.assertEqual(self.page.evaluate('tones.length'), 4)
        box.locator('.pause').click()
        self.page.wait_for_function('getCtx().state === "suspended"')
        expect(box.locator('.pause')).to_have_text('Продолжить')
        box.locator('.pause').click()
        self.page.wait_for_function('getCtx().state === "running"')
        expect(box.locator('.recall-grid input')).to_have_count(1, timeout=10000)
        box.locator('input').fill('')
        box.locator('.check').click()
        expect(box.locator('.stats-box .v').nth(1)).to_have_text('0 / 2')
        box.locator('.again').click()
        box.locator('.stop').click()
        expect(self.page.locator('#auSetup')).to_be_visible()
        self.assertTrue(self.page.evaluate('auStop === null'))

    def test_system_voice_and_competition_mode(self):
        self.nav('audio')
        # OS speech is unavailable headlessly: stub only the external speech service.
        self.page.evaluate('''() => { window.spoken=[];
          speechSynthesis.speak = u => spoken.push({text:u.text,lang:u.lang});
          speechSynthesis.cancel = () => {}; }''')
        self.seg('au.voice', 'system')
        self.page.locator('#auTest').click()
        self.page.wait_for_function('spoken.length === 3')
        self.assertEqual(self.page.evaluate('spoken.map(u=>u.text)'), ['1', '2', '3'])
        self.seg('au.mode', 'comp')
        self.count('au.count', 1)
        self.page.locator('#auInterval').select_option('0.5')
        self.page.locator('#auSetup .start').click()
        expect(self.page.locator('#auRun .pause')).to_have_count(0)
        expect(self.page.locator('#auRun input')).to_have_count(1, timeout=10000)
        self.assertGreaterEqual(self.page.evaluate('spoken.length'), 5)
        self.page.locator('#auRun .cancel').click()

    def test_own_voice_missing_recordings_and_microphone_denied(self):
        self.nav('audio')
        self.seg('au.voice', 'own')
        self.page.locator('#auSetup .start').click()
        expect(self.page.locator('#auVoiceInfo')).to_contain_text('нужны записи всех 10')
        expect(self.page.locator('#auRecorder')).to_have_attribute('open', '')
        self.page.evaluate('''() => {
          navigator.mediaDevices.getUserMedia = async () => {
            throw new DOMException('Denied','NotAllowedError');
          };
        }''')
        self.page.locator('#voiceGrid .voice-tile').first.locator('button').first.click()
        expect(self.page.locator('#voiceMsg')).to_contain_text('Нет доступа к микрофону')

    def test_own_voice_indexeddb_playback_and_delete(self):
        self.nav('audio')
        # Synthetic PCM fixture isolates storage/playback from microphone hardware.
        self.page.evaluate('''async () => {
          for(let d=0;d<10;d++) {
            const pcm=Float32Array.from({length:2205},(_,i)=>Math.sin(i*.1)*.3);
            await VoiceDB.put(String(d),{sr:22050,pcm});
          }
        }''')
        self.page.reload()
        expect(self.page.locator('#voiceGrid .has')).to_have_count(10)
        self.seg('au.voice', 'own')
        expect(self.page.locator('#auVoiceInfo')).to_contain_text('все 10')
        self.audio_probe()
        self.page.locator('#auTest').click()
        self.page.wait_for_function('sources.length === 3')
        self.page.locator('#auRecorder summary').click()
        self.page.once('dialog', lambda d: d.dismiss())
        self.page.locator('#voiceClear').click()
        expect(self.page.locator('#voiceGrid .has')).to_have_count(10)
        self.page.once('dialog', lambda d: d.accept())
        self.page.locator('#voiceClear').click()
        expect(self.page.locator('#voiceGrid .has')).to_have_count(0)
        self.page.reload()
        expect(self.page.locator('#voiceGrid .has')).to_have_count(0)


if __name__ == '__main__':
    unittest.main()
