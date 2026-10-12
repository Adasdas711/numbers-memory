"""Boundary cases, lifecycle, mode variants, and storage fault injection."""
from playwright.sync_api import expect
from test_app import BrowserTestCase


class EdgeCaseTests(BrowserTestCase):
    def test_audio_navigation_during_preparation_cancels_pending_start(self):
        self.nav('audio')
        self.count('au.count', 2)
        self.instrument_audio()
        self.page.evaluate('''() => {
          window.originalVoiceBuffers = voiceBuffers;
          voiceBuffers = async (...args) => {
            const buffers = await originalVoiceBuffers(...args);
            return new Promise(resolve => {
              window.finishPreparation = () => resolve(buffers);
            });
          };
        }''')
        self.page.locator('#auSetup .start').click()
        self.page.wait_for_function('typeof finishPreparation === "function"')
        expect(self.page.locator('#auSetup .start')).to_be_disabled()
        self.nav('theory')
        self.page.evaluate('''async () => {
          finishPreparation(); await new Promise(resolve => setTimeout(resolve, 0));
        }''')
        self.assertEqual(self.page.evaluate('audioSources.length'), 0)
        self.assertEqual(self.page.evaluate('liveIntervals.size'), 0)
        self.assertFalse(self.page.evaluate('auStarting'))
        self.page.evaluate('() => { voiceBuffers = originalVoiceBuffers; }')
        self.nav('audio')
        expect(self.page.locator('#auSetup .start')).to_be_enabled()
        self.page.locator('#auSetup .start').click()
        expect(self.page.locator('#auRun .stop')).to_be_visible()
        self.assertEqual(self.page.evaluate('audioSources.length'), 2)
        self.page.locator('#auRun .stop').click()

    def test_audio_resume_failure_allows_retry(self):
        self.nav('audio')
        self.count('au.count', 2)
        self.page.evaluate('''() => {
          const ctx = getCtx();
          window.originalResume = ctx.resume.bind(ctx);
          ctx.resume = () => Promise.reject(new Error('Audio unavailable'));
        }''')
        self.page.locator('#auSetup .start').click()
        expect(self.page.locator('#auVoiceInfo')).to_contain_text('Не получилось подготовить звук')
        expect(self.page.locator('#auSetup .start')).to_be_enabled()
        self.assertFalse(self.page.evaluate('auStarting'))
        self.page.evaluate('() => { getCtx().resume = originalResume; }')
        self.page.locator('#auSetup .start').click()
        expect(self.page.locator('#auRun .stop')).to_be_visible()
        self.page.locator('#auRun .stop').click()
        expect(self.page.locator('#auVoiceInfo')).not_to_contain_text('Не получилось')

    def test_statistics_preserve_valid_records_and_drop_corrupt_entries(self):
        self.reload_with_script('''localStorage.setItem('bck.stats.v1', JSON.stringify({
          '25': {n:2, ok:1, tT:1200, nT:1, tS:0, nS:0, last:123},
          '26': null,
          '27': {n:'broken'},
          '28': {n:2, ok:3, tT:0, nT:0, tS:0, nS:0},
          '29': {n:1, ok:1, tT:-1, nT:1, tS:0, nS:0}
        }));''')
        self.assertEqual(self.errors, [])
        expect(self.page.locator('#statsSummary')).to_contain_text('Данные есть по 1')
        self.page.locator('.cell[data-id="25"]').click()
        expect(self.page.locator('#cellDetail')).to_contain_text('верно 1 из 2')
        self.assertEqual(self.page.evaluate('Object.keys(Stats.d)'), ['25'])
        self.assertEqual(self.page.evaluate('Stats.d["25"].tT'), 1200)

    def test_duplicate_correct_answer_is_counted_once(self):
        root = self.learn('assoc')
        self.count('assoc.count', 1)
        self.seg('assoc.dir', 'toWord')
        self.page.clock.install()
        self.page.clock.pause_at(self.page.evaluate('Date.now()'))
        root.locator('.start').click()
        number = root.locator('.prompt .num').inner_text()
        root.locator('.ans').fill(self.page.locator(f'.cell[data-id="{number}"] .w').inner_text())
        self.page.evaluate('''() => {
          const button = document.querySelector('.lmode[data-mode="assoc"] .go');
          button.click(); button.click();
        }''')
        self.page.clock.run_for(700)
        expect(root.locator('.stats-box .v').first).to_have_text('1 / 1')
        self.assertEqual(self.page.evaluate('id => Stats.d[id].n', number), 1)

    def score(self, kind, digits, answers):
        return self.page.evaluate('''({kind,digits,answers}) =>
            scoreSequence(kind,digits,toUnits(kind,digits),answers)''',
            {'kind': kind, 'digits': digits, 'answers': answers})

    def test_scoring_short_odd_empty_and_error_positions(self):
        # Explicit expected values are independent of the scoring implementation.
        cases = [
            ('12345', ['12', '34', '5'], (5, 5, -1, 5, 3, 2)),
            ('12345', ['92', '34', '5'], (4, 0, 0, 3, 2, 2)),
            ('12345', ['12', '34', '9'], (4, 4, 4, 3, 2, 2)),
            ('12345', ['92', '34', '9'], (3, 0, 0, 0, 1, 2)),
            ('12345', ['', '', ''], (0, 0, 0, 0, 0, -1)),
            ('12345', ['12', '', '5'], (3, 2, 2, 0, 2, 2)),
            ('12345', ['12', '3', '5'], (4, 3, 3, 3, 2, 2)),
            ('7', ['7'], (1, 1, -1, 1, 1, 0)),
            ('7', [''], (0, 0, 0, 0, 0, -1)),
        ]
        for digits, answers, expected in cases:
            with self.subTest(digits=digits, answers=answers):
                result = self.score('dec', digits, answers)
                self.assertEqual(tuple(result[k] for k in (
                    'correctDigits', 'untilFirst', 'firstErr', 'rowPoints',
                    'unitsOk', 'lastAnswered')), expected)

    def test_scoring_full_and_partial_decimal_rows(self):
        cases = [
            ('01' * 20, ['01'] * 20, (40, 40, -1, 40)),
            ('01' * 20, ['11'] + ['01'] * 19, (39, 0, 0, 20)),
            ('01' * 20, ['10'] + ['01'] * 19, (38, 0, 0, 0)),
            ('01' * 20 + '234', ['01'] * 20 + ['23', '4'], (43, 43, -1, 43)),
            ('01' * 20 + '234', ['01'] * 20 + ['23', '9'], (42, 42, 42, 42)),
            ('01' * 20 + '234', ['01'] * 20 + ['', ''], (40, 40, 40, 40)),
            ('01' * 20 + '234', ['11'] + ['01'] * 19 + ['23', '4'], (42, 0, 0, 23)),
        ]
        for digits, answers, expected in cases:
            with self.subTest(length=len(digits), answers=answers):
                r = self.score('dec', digits, answers)
                self.assertEqual(tuple(r[k] for k in (
                    'correctDigits', 'untilFirst', 'firstErr', 'rowPoints')), expected)

    def test_scoring_full_and_partial_binary_rows(self):
        cases = [
            ('010101' * 5, ['010101'] * 5, (30, 30, -1, 30)),
            ('010101' * 5, ['110101'] + ['010101'] * 4, (29, 0, 0, 15)),
            ('010101' * 5, ['100101'] + ['010101'] * 4, (28, 0, 0, 0)),
            ('010101' * 5 + '010', ['010101'] * 5 + ['010'], (33, 33, -1, 33)),
            ('010101' * 5 + '010', ['010101'] * 5 + ['011'], (32, 32, 32, 32)),
            ('010101' * 5 + '010', ['010101'] * 5 + [''], (30, 30, 30, 30)),
        ]
        for digits, answers, expected in cases:
            with self.subTest(length=len(digits), answers=answers):
                r = self.score('bin', digits, answers)
                self.assertEqual(tuple(r[k] for k in (
                    'correctDigits', 'untilFirst', 'firstErr', 'rowPoints')), expected)

    def test_odd_decimal_length_in_browser(self):
        self.nav('digits')
        self.count('dg.len', 5)
        self.seg('dg.view', 'sheet')
        self.page.locator('#dgSetup .start').click()
        box = self.page.locator('#dgRun')
        answers = box.locator('.sheet .u').all_text_contents()
        self.assertEqual([len(a) for a in answers], [2, 2, 1])
        box.locator('.to-recall').click()
        for field, answer in zip(box.locator('input').all(), answers):
            field.fill(answer)
        box.locator('.check').click()
        expect(box.locator('.stats-box .v').first).to_have_text('5 / 5')
        expect(box.locator('.stats-box .v').nth(1)).to_have_text('5')
        expect(box.locator('.stats-box .v').nth(2)).to_have_text('5')

    def audit_intervals(self):
        self.page.evaluate('''() => {
          window.liveIntervals = new Set();
          const set = window.setInterval, clear = window.clearInterval;
          window.setInterval = (...args) => {
            const id=set(...args); liveIntervals.add(id); return id;
          };
          window.clearInterval = id => {liveIntervals.delete(id); clear(id);};
        }''')

    def test_sequence_cancel_releases_timer_and_keyboard(self):
        self.nav('digits')
        self.audit_intervals()
        self.page.locator('#dgSetup .start').click()
        self.assertEqual(self.page.evaluate('liveIntervals.size'), 1)
        self.page.locator('#dgRun .cancel').click()
        self.assertEqual(self.page.evaluate('liveIntervals.size'), 0)
        self.assertTrue(self.page.evaluate('activeKeyHandler === null && stopSeqRun.dec === null'))
        self.page.keyboard.press('Space')
        expect(self.page.locator('#dgSetup')).to_be_visible()

    def test_sequence_navigation_releases_timer(self):
        self.nav('digits')
        self.audit_intervals()
        self.page.locator('#dgSetup .start').click()
        self.nav('theory')
        self.assertEqual(self.page.evaluate('liveIntervals.size'), 0,
                         'The hidden decimal training must stop on leaving its tab')
        self.assertTrue(self.page.evaluate('stopSeqRun.dec === null'))

    def test_binary_navigation_releases_timer(self):
        self.nav('binary')
        self.audit_intervals()
        self.page.locator('#bnSetup .start').click()
        self.nav('theory')
        self.assertEqual(self.page.evaluate('liveIntervals.size'), 0,
                         'The hidden binary training must stop on leaving its tab')
        self.assertTrue(self.page.evaluate('stopSeqRun.bin === null'))

    def test_metronome_switch_mode_cancels_pending_tick(self):
        root = self.learn('metro')
        self.count('metro.count', 3)
        self.seg('metro.tempo', '1')
        self.page.clock.install()
        root.locator('.start').click()
        self.learn('check')
        self.page.clock.run_for(10000)
        expect(self.page.locator('#checkInput')).to_be_visible()
        self.assertTrue(self.page.evaluate('stopLearnRun === null && activeKeyHandler === null'))
        self.assertEqual(self.page.evaluate('Object.keys(Stats.d).length'), 0)
        root = self.learn('metro')
        expect(root.locator('.setup')).to_be_visible()
        expect(root.locator('.runbox')).to_be_hidden()

    def test_association_navigation_cancels_delayed_next_question(self):
        root = self.learn('assoc')
        self.count('assoc.count', 2)
        self.seg('assoc.dir', 'toWord')
        self.page.clock.install()
        root.locator('.start').click()
        number = root.locator('.prompt .num').inner_text()
        word = self.page.locator(f'.cell[data-id="{number}"] .w').inner_text()
        root.locator('.ans').fill(word)
        self.page.evaluate('''() => {
          document.querySelector('.lmode[data-mode="assoc"] .go').click();
          document.querySelector('[data-go="theory"]').click();
        }''')
        self.page.clock.run_for(2000)
        self.assertEqual(self.errors, [], 'A delayed answer callback must not access removed UI')
        self.assertFalse(self.page.evaluate('''() =>
          document.querySelector('.lmode[data-mode="assoc"] .progress-text')?.textContent === '2 / 2'
        '''), 'A hidden drill must not advance after navigating away')
        expect(self.page.locator('#tab-theory')).to_be_visible()

    def instrument_audio(self):
        self.page.evaluate('''() => {
          window.audioSources=[];
          const start=AudioBufferSourceNode.prototype.start;
          const stop=AudioBufferSourceNode.prototype.stop;
          AudioBufferSourceNode.prototype.start=function(...args) {
            audioSources.push({node:this,stopped:false}); return start.apply(this,args);
          };
          AudioBufferSourceNode.prototype.stop=function(...args) {
            const source=audioSources.find(s=>s.node===this);
            if(source) source.stopped=true;
            return stop.apply(this,args);
          };
        }''')
        self.audit_intervals()

    def test_audio_navigation_stops_sources_and_restarts_once(self):
        self.nav('audio')
        self.count('au.count', 2)
        self.instrument_audio()
        self.page.locator('#auSetup .start').click()
        expect(self.page.locator('#auRun .stop')).to_be_visible()
        self.assertEqual(self.page.evaluate('audioSources.length'), 2)
        self.nav('theory')
        self.assertTrue(self.page.evaluate('audioSources.every(s=>s.stopped)'))
        self.assertEqual(self.page.evaluate('liveIntervals.size'), 0)
        self.assertTrue(self.page.evaluate('auStop === null'))
        self.nav('audio')
        self.page.locator('#auSetup .start').click()
        expect(self.page.locator('#auRun .stop')).to_be_visible()
        self.assertEqual(self.page.evaluate('audioSources.filter(s=>!s.stopped).length'), 2)
        self.assertEqual(self.page.evaluate('liveIntervals.size'), 1)
        self.page.locator('#auRun .stop').click()
        self.assertEqual(self.page.evaluate('liveIntervals.size'), 0)

    def test_double_audio_start_does_not_duplicate_training(self):
        self.nav('audio')
        self.count('au.count', 2)
        self.instrument_audio()
        # Two real button events before asynchronous MP3 loading completes.
        self.page.evaluate('''() => {
          const button=document.querySelector('#auSetup .start');
          button.click(); button.click();
        }''')
        self.page.wait_for_function('audioSources.length >= 2')
        self.page.wait_for_timeout(250)
        self.assertEqual(self.page.evaluate('audioSources.filter(s=>!s.stopped).length'), 2)
        self.assertEqual(self.page.evaluate('liveIntervals.size'), 1)
        self.page.locator('#auRun .stop').click()

    def test_random_access_position_after_and_mixed_questions(self):
        root = self.learn('assoc')
        self.seg('assoc.kind', 'random')
        self.count('rnd.count', 4)
        for mode in ['pos', 'after', 'mix']:
            with self.subTest(mode=mode):
                self.seg('rnd.q', mode)
                root.locator('.start').click()
                sequence = root.locator('.rnd-cell b').all_text_contents()
                root.locator('.ready').click()
                for i in range(4):
                    prompt = root.locator('.prompt .sub').inner_text()
                    number = root.locator('.prompt .num').inner_text()
                    if prompt == 'На каком месте':
                        answer = str(sequence.index(number) + 1)
                    elif prompt == 'Что идёт после':
                        answer = sequence[sequence.index(number) + 1]
                    else:
                        answer = sequence[int(number) - 1]
                    root.locator('.ans').fill(answer)
                    root.locator('.go').click()
                    if i < 3:
                        expect(root.locator('.progress-text')).to_have_text(f'{i+2} / 4')
                expect(root.locator('.stats-box .v').first).to_have_text('4 / 4')
                root.locator('.back').click()

    def test_association_mixed_directions_correct_answers(self):
        root = self.learn('assoc')
        self.count('assoc.count', 4)
        self.seg('assoc.dir', 'mix')
        # Exercise both branches deterministically, retaining the real UI/drill.
        self.page.evaluate('''() => {
          const original=randInt; let direction=0;
          randInt=n => n===2 ? direction++%2 : original(n);
        }''')
        root.locator('.start').click()
        seen = set()
        for i in range(4):
            if root.locator('.prompt .num').count():
                seen.add('number')
                number = root.locator('.prompt .num').inner_text()
                answer = self.page.locator(f'.cell[data-id="{number}"] .w').inner_text()
            else:
                seen.add('word')
                word = root.locator('.prompt .word').inner_text()
                answer = next(c.get_attribute('data-id') for c in self.page.locator('.cell').all()
                              if c.locator('.w').inner_text() == word)
            root.locator('.ans').fill(answer)
            root.locator('.go').click()
            if i < 3:
                expect(root.locator('.progress-text')).to_have_text(f'{i+2} / 4')
        self.assertEqual(seen, {'number', 'word'})
        expect(root.locator('.stats-box .v').first).to_have_text('4 / 4')

    def test_flash_multiple_numbers_forces_numeric_answers(self):
        root = self.learn('speed')
        self.seg('speed.kind', 'flash')
        root.locator('[data-store="speed.pool"]').select_option('two')
        self.count('speed.count', 1)
        self.seg('flash.ans', 'word')
        self.page.clock.install()
        self.page.clock.pause_at(self.page.evaluate('Date.now()'))
        for per in ['2', '3']:
            with self.subTest(per=per):
                self.seg('flash.n', per)
                root.locator('.start').click()
                self.page.clock.run_for(500)
                displayed = root.locator('.flash-num').inner_text()
                self.assertRegex(displayed, r'^\d{2}( \d{2})+$')
                answer = displayed.replace(' ', '')
                self.assertEqual(len(answer), 2 * int(per))
                expect(root.locator('.ans')).to_have_attribute('inputmode', 'numeric')
                root.locator('.ans').fill(answer)
                root.locator('.go').click()
                self.page.clock.run_for(500)
                expect(root.locator('.stats-box .v').first).to_have_text('1 / 1')
                root.locator('.back').click()

    def test_flash_adapts_after_three_correct_and_one_wrong(self):
        root = self.learn('speed')
        self.seg('speed.kind', 'flash')
        root.locator('[data-store="speed.pool"]').select_option('two')
        self.seg('flash.ans', 'digits')
        self.seg('flash.ms', '800')
        self.count('speed.count', 4)
        self.page.clock.install()
        self.page.clock.pause_at(self.page.evaluate('Date.now()'))
        root.locator('[data-store="flash.adapt"]').check()
        root.locator('.start').click()
        for i in range(3):
            self.page.clock.run_for(500)
            answer = root.locator('.flash-num').inner_text()
            self.assertRegex(answer, r'^\d{2}$')
            root.locator('.ans').fill(answer)
            root.locator('.go').click()
            self.page.clock.run_for(500)
            expect(root.locator('.progress-text')).to_have_text(f'{i+2} / 4')
        self.page.clock.run_for(500)
        expect(root.locator('.flash-sub')).to_have_text('0,72 с')
        root.locator('.skip').click()
        root.locator('.go').click()
        expect(root.locator('.stats-box .v').first).to_have_text('3 / 4')
        expect(root.locator('.stats-box .v').last).to_have_text('0,79 с')

    def test_flash_word_answer_and_disabled_adaptation(self):
        root = self.learn('speed')
        self.seg('speed.kind', 'flash')
        root.locator('[data-store="speed.pool"]').select_option('two')
        self.seg('flash.ans', 'word')
        self.seg('flash.ms', '800')
        root.locator('[data-store="flash.adapt"]').uncheck()
        self.count('speed.count', 2)
        self.page.clock.install()
        self.page.clock.pause_at(self.page.evaluate('Date.now()'))
        root.locator('.start').click()
        self.page.clock.run_for(500)
        number = root.locator('.flash-num').inner_text()
        word = self.page.locator(f'.cell[data-id="{number}"] .w').inner_text()
        root.locator('.ans').fill(word)
        root.locator('.go').click()
        self.page.clock.run_for(500)
        expect(root.locator('.progress-text')).to_have_text('2 / 2')
        root.locator('.skip').click()
        root.locator('.go').click()
        expect(root.locator('.stats-box .v').first).to_have_text('1 / 2')
        expect(root.locator('.stats-box .v').last).to_have_text('0,80 с')

    def test_metronome_acceleration_and_minimum_tempo(self):
        root = self.learn('metro')
        self.count('metro.count', 70)
        self.seg('metro.tempo', '1')
        root.locator('[data-store="metro.accel"]').check()
        self.page.clock.install()
        root.locator('.start').click()
        expect(root.locator('.tempo')).to_have_text('Темп: 1,00 с на число')
        self.page.clock.run_for(10000)
        expect(root.locator('.tempo')).to_have_text('Темп: 0,90 с на число')
        self.page.clock.run_for(39000)
        expect(root.locator('.tempo')).to_have_text('Темп: 0,60 с на число')
        root.locator('.stop').click()
        expect(root.locator('.stats-box .v').nth(1)).to_have_text('0,60 с')

    def reload_with_script(self, script):
        self.page.add_init_script(script)
        self.page.reload()

    def assert_storage_fallback_workflow(self):
        # Report startup errors once rather than again in the fixture cleanup.
        startup_errors = self.errors[:]
        self.errors.clear()
        self.assertEqual(startup_errors, [],
                         'Storage failures must not break application initialization')
        expect(self.page.locator('#grid2 .cell')).to_have_count(100)
        self.nav('digits')
        self.count('dg.len', 5)
        self.page.locator('#dgSetup .start').click()
        self.page.locator('#dgRun .to-recall').click()
        self.page.locator('#dgRun .check').click()
        expect(self.page.locator('#dgRun .stats-box .v').first).to_have_text('0 / 5')
        self.assertEqual(self.errors, [])

    def test_localstorage_read_access_denied(self):
        self.reload_with_script('''Storage.prototype.getItem = () => {
          throw new DOMException('Denied','SecurityError');
        };''')
        self.assert_storage_fallback_workflow()

    def test_localstorage_write_quota_exceeded(self):
        self.reload_with_script('''Storage.prototype.setItem = () => {
          throw new DOMException('Full','QuotaExceededError');
        };''')
        self.assert_storage_fallback_workflow()

    def test_localstorage_malformed_json(self):
        self.reload_with_script('''for (const key of ['bck.settings.v1','bck.stats.v1','bck.tab'])
          localStorage.setItem(key,'{broken JSON');''')
        self.assert_storage_fallback_workflow()

    def test_localstorage_settings_valid_json_wrong_shape(self):
        self.reload_with_script("localStorage.setItem('bck.settings.v1','null');")
        self.assert_storage_fallback_workflow()

    def test_localstorage_statistics_valid_json_wrong_shape(self):
        self.reload_with_script("localStorage.setItem('bck.stats.v1','null');")
        self.assert_storage_fallback_workflow()

    def test_indexeddb_open_denied_keeps_app_usable(self):
        self.reload_with_script('''indexedDB.open = () => {
          throw new DOMException('Denied','SecurityError');
        };''')
        self.assert_storage_fallback_workflow()
        self.assertEqual(self.page.evaluate('async () => await VoiceDB.all()'), {})
        self.assertIsNone(self.page.evaluate('async () => await VoiceDB.put("0",{})'))

    def test_indexeddb_open_async_error_keeps_app_usable(self):
        self.reload_with_script('''indexedDB.open = () => {
          const request={}; setTimeout(()=>request.onerror?.(),0); return request;
        };''')
        self.assert_storage_fallback_workflow()
        self.assertEqual(self.page.evaluate('async () => await VoiceDB.all()'), {})

    def test_indexeddb_transaction_exception_returns_fallback(self):
        self.page.evaluate('''async () => {
          await VoiceDB.open(); VoiceDB.db.transaction=()=>{
            throw new DOMException('Invalid transaction','InvalidStateError');
          };
        }''')
        self.assertEqual(self.page.evaluate('async () => await VoiceDB.all()'), {})
        self.assertIsNone(self.page.evaluate('async () => await VoiceDB.clear()'))
        self.assert_storage_fallback_workflow()

    def test_indexeddb_transaction_abort_does_not_hang(self):
        self.page.evaluate('''async () => {
          await VoiceDB.open(); const original=VoiceDB.db.transaction.bind(VoiceDB.db);
          VoiceDB.db.transaction=(...args)=> {
            const tx=original(...args); queueMicrotask(()=>tx.abort()); return tx;
          };
        }''')
        result = self.page.evaluate('''async () => Promise.race([
          VoiceDB.clear().then(()=> 'settled'),
          new Promise(resolve=>setTimeout(()=>resolve('hung'),500))
        ])''')
        self.assertEqual(result, 'settled', 'An aborted transaction must settle its promise')
